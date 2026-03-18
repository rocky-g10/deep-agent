# Codex Implementation Tasks — Deep Agent Phase 1 Completion

> **Generated:** 2026-03-17
> **Source:** DESIGN_HANDOFF_SPEC.md, MULTI_SKILL_SPEC.md, full-project-audit.md, COMPLETION_PLAN_SPEC.md
> **Scope:** All remaining Phase 1 work, broken into PR-sized tasks for Codex

---

## Current State Summary

**Done:** Core orchestrator, skill engine + parser, models, subprocess sandbox, LangGraph adapter, LLM router, MCP config + manager, WebSocket API (basic), config loader, session manager, demo scripts, unit tests for most modules.

**Remaining:** Multi-skill composition, inputs/quality parsing gaps, integration test gaps, E2E coverage, minor cleanups.

---

## Task Dependency Graph

```
T1 (min_score filter) ──────────┐
                                 ├──► T3 (orchestrator multi-skill) ──► T5 (system prompt)
T2 (skill model quality) ───────┘                                        │
                                                                         ▼
T4 (merge function) ─────────────────────────────────────────────────► T6 (integration test)
                                                                         │
T7 (db-query scripts/) ── independent                                    ▼
T8 (config test coverage) ── independent                              T9 (E2E multi-skill test)
T10 (cleanup) ── independent
```

---

## T1: Add `min_score` parameter to `SkillEngine.match()`

**Priority:** High — prerequisite for multi-skill composition
**Files to modify:**
- `src/deep_agent/skills/engine.py`
- `tests/unit/test_skill_engine.py`

### Changes

**`engine.py` — `match()` signature (line 64):**

Change from:
```python
def match(self, query: str, bindings: AgentSkillBindings, top_k: int = 5) -> list[SkillSummary]:
```
To:
```python
def match(
    self, query: str, bindings: AgentSkillBindings,
    top_k: int = 5, min_score: float = 0.0,
) -> list[SkillSummary]:
```

**After the existing `top = scored[:top_k]` slice (line 72), add:**
```python
if min_score > 0.0:
    top = [(s, sk) for s, sk in top if s >= min_score]
```

**Backward compat:** Default `min_score=0.0` means all existing callers are unaffected.

### Tests to add (`test_skill_engine.py`)

1. **`test_min_score_filters_low_scoring`** — Create 3 skills, query matches 1 well (score ~0.67), set `min_score=0.4` → only 1 result returned.
2. **`test_min_score_zero_returns_all`** — Default `min_score=0.0` returns all results (backward compat with existing tests).
3. **`test_min_score_filters_all_when_none_match`** — Query with no tag overlap + `min_score=0.01` → empty list.

### Dependencies
None — standalone change.

---

## T2: Ensure `SkillContent` model exposes `quality` and `inputs` fields

**Priority:** High — needed by T3 for timeout merge
**Files to modify:**
- `src/deep_agent/models/skills.py`
- `src/deep_agent/skills/parser.py`
- `tests/unit/test_skill_parser.py`

### Current State

The models already define `SkillInput` (line 11-17), `SkillQuality` (line 20-27), and `SkillContent` includes `inputs` and `quality` fields. The parser (`parser.py`) already extracts these from frontmatter.

### Verify

Read the parser and confirm:
- `SkillContent.quality.timeout` is populated from `quality.timeout` in SKILL.md frontmatter
- `SkillContent.inputs` is populated from `inputs` in SKILL.md frontmatter
- Default values work when frontmatter omits these fields

If any of these are missing, add the parsing logic.

### Tests to verify (`test_skill_parser.py`)

1. **`test_quality_timeout_parsed`** — SKILL.md with `quality: { timeout: 90 }` → `skill.quality.timeout == 90`.
2. **`test_quality_defaults_when_omitted`** — SKILL.md without `quality` → `skill.quality.timeout == 60` (default).
3. **`test_inputs_parsed`** — SKILL.md with `inputs` list → `len(skill.inputs) > 0`, names match.

### Dependencies
None — standalone verification/fix.

---

## T3: Multi-skill match loop in `AgentOrchestrator.handle_message()`

**Priority:** High — core multi-skill composition change
**Files to modify:**
- `src/deep_agent/orchestrator/agent_orchestrator.py`
- `tests/unit/test_orchestrator.py`

### Changes

**Module-level constant (add near top of file):**
```python
_DEFAULT_MULTI_SKILL_MIN_SCORE = 0.01
```

No `top_k` override — the engine's default (5) is sufficient given that the bound skills list is already scoped by the agent YAML. All bound skills scoring above `min_score` are activated. The `min_score` threshold is the sole relevance filter.

**Match call (line 68) — change from:**
```python
matched_skills = self._skill_engine.match(message, skill_bindings, top_k=1)
```
**To:**
```python
matched_skills = self._skill_engine.match(
    message, skill_bindings,
    min_score=_DEFAULT_MULTI_SKILL_MIN_SCORE,
)
```

**Skill loading loop (lines 73-81) — replace single-skill block with:**
```python
active_skills: list[SkillContent] = []
for match in matched_skills:
    yield SkillMatchEvent(skill_id=match.skill_id, confidence=match.score)
    try:
        content = self._skill_engine.load(match.skill_id, skill_bindings)
        active_skills.append(content)
    except Exception as exc:
        logger.warning("Failed to load matched skill '%s': %s", match.skill_id, exc)
```

**Field extraction (lines 82-101) — replace with call to `_merge_skill_contents()`:**
```python
merged = _merge_skill_contents(active_skills)
allowed_tools = merged["allowed_tools"]
scripts_dirs = merged["scripts_dirs"]
skill_timeout = merged["skill_timeout"]
mcp_servers = merged["mcp_servers"]
mcp_tool_bindings = merged["mcp_tool_bindings"]
```

The `_merge_skill_contents()` function is defined in T4.

**Update downstream code** to use `active_skills` list instead of single `skill_content`:
- Pass `active_skills` to `_build_system_prompt()` (changed in T5)
- The `allowed_tools`, `scripts_dirs`, `skill_timeout` variables are already consumed downstream — just ensure they come from the merge dict.

### Tests to add/update (`test_orchestrator.py`)

**Update `_mock_skill_engine` helper (line 24)** — the mock must set:
```python
skill_content.quality.timeout = 60
skill_content.mcp_servers = []
skill_content.mcp_tool_bindings = []
```

For multi-skill tests, change `engine.load.return_value` to `engine.load.side_effect` keyed by `skill_id`.

1. **`test_multi_match_yields_multiple_skill_match_events`** — engine returns 2 skills → 2 `skill_match` events before any `agent_chunk`.
2. **`test_single_skill_backward_compat`** — engine returns 1 skill → behavior identical to current (singular prompt heading, single event).
3. **`test_no_match_backward_compat`** — engine returns 0 skills → `allowed_tools` is `None`, no filtering.
4. **`test_skill_load_failure_skips_gracefully`** — engine returns 2 skills, `load()` raises for second → first skill proceeds normally.

### Dependencies
- T1 (min_score parameter)
- T2 (quality fields on SkillContent)

---

## T4: Implement `_merge_skill_contents()` private function

**Priority:** High — merge logic for multi-skill composition
**Files to modify:**
- `src/deep_agent/orchestrator/agent_orchestrator.py`
- `tests/unit/test_orchestrator.py`

### Function signature

```python
def _merge_skill_contents(active_skills: list[SkillContent]) -> dict[str, Any]:
    """Merge multiple skill contents into a single context dict.

    Returns:
        Dict with keys:
        - allowed_tools: list[str] | None
        - scripts_dirs: list[str] | None
        - skill_timeout: int | None
        - mcp_servers: list[SkillMCPServer]
        - mcp_tool_bindings: list[MCPToolBinding]
    """
```

### Merge strategies

| Field | Strategy | Implementation |
|-------|----------|----------------|
| `allowed_tools` | Union (sorted) | `sorted(set(chain(*(s.allowed_tools for s in active_skills))))`. Return `None` if `active_skills` is empty (preserves no-filtering behavior). |
| `scripts_dirs` | Collect non-empty `scripts_path` | `[s.scripts_path for s in active_skills if s.scripts_path]`. Return `None` if empty. Order: highest-scored first (input list order). |
| `skill_timeout` | `max()` across skills | Only set if any skill's `quality.timeout` exceeds 60 (the default). Return `None` otherwise. |
| `mcp_servers` | Concatenate, dedupe by name | First-seen (highest-scored) wins on name collision. |
| `mcp_tool_bindings` | Concatenate, dedupe by `tool_name` | First-seen wins. Debug log for dropped duplicates. |

### Script filename collision check

Inside the merge function, iterate each skill's `scripts_path` directory, collect `.py` filenames. If a name appears in multiple skills, log a warning:
```python
logger.warning(
    "Script filename '%s' exists in multiple skills: %s — "
    "higher-scored skill's version will take precedence on PYTHONPATH",
    filename, [s.skill_id for s in colliding_skills],
)
```

### Critical invariant

When `active_skills` is empty (no match), `allowed_tools` must return `None` so that `_filter_tools` is never called (existing no-match behavior).

### Tests to add (`test_orchestrator.py`)

1. **`test_allowed_tools_unioned`** — skill A: `[execute_code]`, skill B: `[execute_code, get_data]` → result: `[execute_code, get_data]`.
2. **`test_scripts_dirs_merged`** — 2 skills with different `scripts_path` → both paths in result list.
3. **`test_highest_timeout_wins`** — skill A: timeout 60, skill B: timeout 120 → `skill_timeout == 120`.
4. **`test_default_timeout_returns_none`** — all skills timeout 60 → `skill_timeout is None`.
5. **`test_mcp_binding_conflict_first_wins`** — skill A binds `get_data→server-X`, skill B binds `get_data→server-Y` → only `server-X` binding kept.
6. **`test_mcp_server_name_dedup`** — two skills declare server with same name → first-seen URL preserved.
7. **`test_empty_active_skills_returns_none`** — empty list → `allowed_tools is None`.
8. **`test_script_filename_collision_warning`** — two skills both have `utils.py` → warning logged (use `caplog` fixture).

### Dependencies
- T3 (calls this function)

---

## T5: Update `_build_system_prompt()` for multi-skill

**Priority:** High — system prompt must show all active skills
**Files to modify:**
- `src/deep_agent/orchestrator/agent_orchestrator.py`
- `tests/unit/test_orchestrator.py`

### Changes

**Signature change (line 194) — from:**
```python
def _build_system_prompt(self, context, skill_content: SkillContent | None, all_skills):
```
**To:**
```python
def _build_system_prompt(self, context, active_skills: list[SkillContent], all_skills):
```

### Prompt body logic

```python
if len(active_skills) == 0:
    # No active skills section (unchanged)
    pass
elif len(active_skills) == 1:
    skill = active_skills[0]
    # Unchanged format: "## Active Skill: {name}" + body
    prompt_parts.append(f"## Active Skill: {skill.name}\n\n{skill.body}")
else:
    # Multi-skill format
    prompt_parts.append("## Active Skills\n")
    prompt_parts.append(
        "You may combine functionality from multiple active skills in a single "
        "`execute_code` call. Each skill's `scripts/` directory is on PYTHONPATH.\n"
    )
    for skill in active_skills:
        prompt_parts.append(f"### Skill: {skill.name}\n\n{skill.body}")
```

### Tests to add (`test_orchestrator.py`)

1. **`test_system_prompt_single_skill_singular_heading`** — 1 active skill → prompt contains `## Active Skill:` (singular), no composition instruction.
2. **`test_system_prompt_multi_skill_plural_heading`** — 2 active skills → prompt contains `## Active Skills` (plural), composition instruction, `### Skill:` for each.
3. **`test_system_prompt_no_skills_no_section`** — 0 active skills → prompt does not contain "Active Skill".
4. **`test_system_prompt_multi_skill_contains_both_bodies`** — Both skills' body text appears in the prompt.

### Dependencies
- T3 (changes the calling code)

---

## T6: Integration test — multi-skill sandbox execution

**Priority:** High — validates the full composition works end-to-end
**Files to create:**
- `tests/integration/test_multi_skill_sandbox.py`

### Test design

Create two temporary `scripts/` directories, each with a unique `.py` module. Execute code that imports from both. Verify `exit_code == 0`.

```python
import pytest
import tempfile
from pathlib import Path
from deep_agent.sandbox.subprocess_sandbox import PythonSubprocessSandbox


@pytest.fixture
def two_skill_scripts():
    """Create two temp script dirs with unique modules."""
    dir_a = tempfile.mkdtemp(prefix="skill_a_")
    dir_b = tempfile.mkdtemp(prefix="skill_b_")

    (Path(dir_a) / "alpha_mod.py").write_text(
        "def greet(): return 'hello from alpha'"
    )
    (Path(dir_b) / "beta_mod.py").write_text(
        "def greet(): return 'hello from beta'"
    )
    return dir_a, dir_b


@pytest.mark.asyncio
async def test_two_skills_importable_in_one_execution(two_skill_scripts):
    dir_a, dir_b = two_skill_scripts
    sandbox = PythonSubprocessSandbox()

    code = (
        "from alpha_mod import greet as a_greet\n"
        "from beta_mod import greet as b_greet\n"
        "print(a_greet())\n"
        "print(b_greet())\n"
    )

    import os
    env = {"PYTHONPATH": os.pathsep.join([dir_a, dir_b])}
    result = await sandbox.execute(code=code, env=env, timeout=15)

    assert result.exit_code == 0, f"stderr: {result.stderr}"
    assert "hello from alpha" in result.stdout
    assert "hello from beta" in result.stdout


@pytest.mark.asyncio
async def test_higher_scored_skill_shadows_on_collision(two_skill_scripts):
    """When both dirs have same filename, first on PYTHONPATH wins."""
    dir_a, dir_b = two_skill_scripts

    # Both dirs get a `shared.py` with different content
    (Path(dir_a) / "shared.py").write_text("WHO = 'skill_a'")
    (Path(dir_b) / "shared.py").write_text("WHO = 'skill_b'")

    sandbox = PythonSubprocessSandbox()
    code = "from shared import WHO\nprint(WHO)"

    import os
    env = {"PYTHONPATH": os.pathsep.join([dir_a, dir_b])}
    result = await sandbox.execute(code=code, env=env, timeout=15)

    assert result.exit_code == 0
    assert "skill_a" in result.stdout  # First on PYTHONPATH wins
```

### Dependencies
- T1, T4 (design informs the test, but test can be written independently)

---

## T7: Add `scripts/requirements.txt` to `db-query` skill

**Priority:** Medium — skill execution fails without DB driver
**Files to create:**
- `skills/common/db-query/scripts/requirements.txt`

### Content

```
clickhouse-connect>=0.7
```

### Verify

Check if `skills/common/db-query/scripts/` directory exists. If not, create it. Only the `requirements.txt` file is needed — the skill relies on inline code generation, not bundled scripts.

### Tests

No new tests needed — existing skill parser tests already validate directory structure. Verify the skill loads without error:

```python
def test_db_query_skill_has_scripts_dir():
    from deep_agent.skills.parser import parse_skill_file
    skill = parse_skill_file(Path("skills/common/db-query/SKILL.md"))
    # scripts_path should be non-empty now
    assert skill.scripts_path
```

### Dependencies
None — standalone fix.

---

## T8: Add config module test coverage

**Priority:** Medium — zero test coverage for `config.py`
**Files to modify:**
- `tests/unit/test_config.py` (create or extend)

### Tests to add

1. **`test_app_settings_defaults`** — Instantiate `AppSettings` with only required fields → verify defaults for `openai_model`, `openai_temperature`, `skills_root`, etc.
2. **`test_app_settings_env_override`** — Set env vars (`OPENAI_API_KEY`, `OPENAI_MODEL`) → verify `AppSettings` picks them up.
3. **`test_app_settings_missing_api_key_raises`** — No `OPENAI_API_KEY` set → `ValidationError`.
4. **`test_get_settings_returns_same_instance`** — Call `get_settings()` twice → same object (caching).

### Dependencies
None — standalone.

---

## T9: E2E test — multi-skill pipeline

**Priority:** Medium — validates the full composition pipeline
**Files to create:**
- `tests/e2e/test_multi_skill_e2e.py`

### Test design

This test uses the same pattern as the demo scripts (`demo_risk_agent.py`): mock runtime, real orchestrator + sandbox, FakeWebSocket.

```python
"""E2E test: multi-skill composition through the full pipeline.

Uses a mock runtime with two skills (portfolio-var + zscore-monitor)
to verify that the orchestrator activates both skills and the sandbox
can import from both scripts/ directories.
"""
import pytest
import json
import tempfile
from pathlib import Path


@pytest.fixture
def multi_skill_app(tmp_path):
    """Build app with two skills' scripts dirs on PYTHONPATH."""
    # Create skill script dirs (same pattern as demo_multi_skill.py)
    # Wire up orchestrator with mock runtime
    # Return app, tenant, bindings, skill_dirs
    ...


@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_multi_skill_full_pipeline(multi_skill_app):
    """Full pipeline: match 2 skills → merge → execute → both imports work."""
    # Send question spanning both skills
    # Verify: 2 skill_match events, 1 tool_call, 1 tool_result with output from both
    ...
```

### Dependencies
- T3, T4, T5 (the multi-skill orchestrator changes must be in place)

---

## T10: Minor cleanups from audit

**Priority:** Low — code quality, no behavioral change
**Files to modify:**
- `src/deep_agent/mcp/config.py` — Remove unnecessary `f` prefix on string without placeholders (line 54)
- `src/deep_agent/models/context.py` — Move `TenantContext.stub()` to `examples/` or rename to `TenantContext.default()` if not already done

### Verify

1. Check if `TenantContext.stub()` still exists and is ClickHouse-specific. If so, either remove it or replace with a generic `default()` factory.
2. Check `mcp/config.py:54` for the f-string issue.
3. Check for duplicate `firm_stats.py` in `examples/skills/` vs `skills/equities/zscore-monitor/scripts/` — remove the example copy if it's a duplicate.

### Tests

Run existing test suite — no new tests needed, just verify nothing breaks.

### Dependencies
None — standalone cleanup.

---

## Implementation Order (Recommended)

| Phase | Tasks | Can parallelize? |
|-------|-------|-----------------|
| 1 | T1 (min_score), T2 (quality fields), T7 (db-query scripts), T8 (config tests) | Yes — all independent |
| 2 | T3 (match loop), T4 (merge function) | T4 can start in parallel with T3 |
| 3 | T5 (system prompt) | Depends on T3 |
| 4 | T6 (integration test), T9 (E2E test) | T6 is independent; T9 depends on T3-T5 |
| 5 | T10 (cleanup) | Independent, any time |

---

## Appendix: Key File Paths Quick Reference

| Component | Path |
|-----------|------|
| Orchestrator | `src/deep_agent/orchestrator/agent_orchestrator.py` |
| Skill Engine | `src/deep_agent/skills/engine.py` |
| Skill Parser | `src/deep_agent/skills/parser.py` |
| Execute Code Tool | `src/deep_agent/tools/execute_code.py` |
| Events (SkillMatchEvent) | `src/deep_agent/models/events.py` |
| Skill Models | `src/deep_agent/models/skills.py` |
| Subprocess Sandbox | `src/deep_agent/sandbox/subprocess_sandbox.py` |
| App Factory | `src/deep_agent/api/app.py` |
| WebSocket Handler | `src/deep_agent/api/ws_chat.py` |
| Config Loader | `src/deep_agent/api/config_loader.py` |
| Session Manager | `src/deep_agent/api/session.py` |
| App Settings | `src/deep_agent/config.py` |
| Orchestrator Tests | `tests/unit/test_orchestrator.py` |
| Skill Engine Tests | `tests/unit/test_skill_engine.py` |
| Tools Tests | `tests/unit/test_tools.py` |
| Parser Tests | `tests/unit/test_skill_parser.py` |

---

## Appendix: Key Function Signatures

### SkillEngine.match() — current (engine.py:64)
```python
def match(self, query: str, bindings: AgentSkillBindings, top_k: int = 5) -> list[SkillSummary]:
```

### SkillEngine.match() — after T1
```python
def match(self, query: str, bindings: AgentSkillBindings, top_k: int = 5, min_score: float = 0.0) -> list[SkillSummary]:
```

### AgentOrchestrator.handle_message() — current (agent_orchestrator.py:51)
```python
async def handle_message(self, message: str, context: TenantContext, skill_bindings: AgentSkillBindings, ...) -> AsyncGenerator[AgentEvent, None]:
```

### _merge_skill_contents() — new (T4)
```python
def _merge_skill_contents(active_skills: list[SkillContent]) -> dict[str, Any]:
```

### _build_system_prompt() — current (agent_orchestrator.py:194)
```python
def _build_system_prompt(self, context, skill_content: SkillContent | None, all_skills):
```

### _build_system_prompt() — after T5
```python
def _build_system_prompt(self, context, active_skills: list[SkillContent], all_skills):
```

### create_execute_code_tool() — unchanged (execute_code.py:17)
```python
def create_execute_code_tool(sandbox: SandboxManager, tenant: TenantContext, scripts_dirs: list[str] | None = None, max_timeout: int = 60) -> BaseTool:
```

### SkillMatchEvent — unchanged (events.py:34)
```python
class SkillMatchEvent(BaseModel):
    type: Literal["skill_match"] = "skill_match"
    skill_id: str
    confidence: float
```

---

*End of document.*
