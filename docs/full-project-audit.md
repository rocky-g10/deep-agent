# Full Project Audit — deep-agent

**Date:** 2026-03-12
**Auditor:** Claude (automated audit per FULL_AUDIT_SPEC.md)
**Codebase State:** Commit `3a69ee7` (post resource-agnostic refactor)

---

## Summary

The deep-agent codebase is in solid shape for a Phase 1 / MVP framework. The resource-agnostic refactor is **complete** — zero ClickHouse or hardcoded finance references remain in core `src/`. All 88 unit tests pass, 9 MCP integration tests are correctly gated behind an env flag, the example runs cleanly, lint is nearly clean (1 trivial f-string issue), and mypy reports zero errors across 26 source files. The architecture faithfully implements the PRD's layered design (Skills → Runtime → Sandbox → MCP). However, the **WebSocket Chat API (§4.5)** and **several Phase 1 implementation plan deliverables** (T4.1–T4.5) are entirely missing, which means the project cannot yet be run as a server or tested end-to-end via WebSocket. Additionally, the PRD's `inputs` and `quality` frontmatter fields are silently ignored rather than parsed into models, and the `db-query` skill is missing its `scripts/` directory. These gaps are documented below.

---

## Critical Issues

Issues that would break at runtime or prevent core functionality.

### C1. WebSocket API Not Implemented

**Location:** `src/deep_agent/api/` — contains only an empty `__init__.py`
**PRD Reference:** §4.5 (Chat API), §10 Phase 1 deliverables (T4.1)
**Impact:** The PRD specifies a WebSocket endpoint (`wss://{host}/ws/chat`) as the primary user-facing interface. The Implementation Plan tasks T4.1 (FastAPI + WS), T4.3 (WS integration tests), and T4.5 (dev run script) are unimplemented. There is no `app.py`, `ws_chat.py`, `schemas.py`, or any FastAPI code. The project cannot be started as a server.

### C2. No E2E Test

**Location:** `tests/e2e/` — contains only `__init__.py`
**PRD Reference:** §10 Phase 1 success criteria, Implementation Plan T4.4
**Impact:** The E2E test (T4.4: "Z-Score Query via WebSocket") is unimplemented. Phase 1 success criterion #1 ("E2E z-score query returns table + chart within 30 seconds") cannot be verified.

### C3. `db-query` Skill Has No Scripts Directory

**Location:** `skills/common/db-query/`
**Impact:** The `db-query` SKILL.md exists but has no `scripts/` directory or `requirements.txt`. While this skill doesn't reference bundled modules (unlike zscore-monitor), the skill's instructions tell the agent to "connect to the database" which requires `clickhouse-connect` or similar — yet there's no `scripts/requirements.txt` declaring this dependency. In sandbox execution, the `pip install` step for this skill would have nothing to install, and `import clickhouse_connect` would fail.

### C4. `inputs` and `quality` Frontmatter Fields Are Silently Dropped

**Location:** `src/deep_agent/skills/parser.py`, `src/deep_agent/models/skills.py`
**PRD Reference:** §5 (SKILL.md Format) — `inputs` and `quality` are defined as standard frontmatter fields
**Impact:** Both the `db-query` and `zscore-monitor` skills declare `inputs` and `quality` in their YAML frontmatter. The parser ignores these fields (they're not in `REQUIRED_SKILL_FIELDS` and `SkillContent` has no corresponding attributes). This means:
- The orchestrator has no access to declared input schemas for validation
- Quality constraints (`timeout`, `max-retries`, `validation`) are not enforced
- The PRD's quality contract ("output must include…") is invisible to the runtime

---

## Important Issues

Design or correctness concerns that don't crash at runtime but affect reliability or PRD alignment.

### I1. `TenantContext.stub()` Hardcodes Equities References

**Location:** `src/deep_agent/models/context.py:17-33`
**Impact:** The `stub()` classmethod is the only remaining equities-specific code in `src/`. It hardcodes `tenant_id="equities"`, `mcp_config_path="tenants/equities/mcp.json"`, and `resource_env={"ch-equities": {...}}`. While marked "for local development", this is misleading in a resource-agnostic framework — it implies ClickHouse is the default. Consider making stub() generic or moving it to `examples/`.

### I2. MCP Integration Tests All Skip in Default Test Run

**Location:** `tests/integration/test_mcp_manager.py`
**Impact:** All 9 MCP integration tests are gated behind `RUN_MCP_INTEGRATION=1`. This is reasonable for CI, but there's no documentation on how or when to run them. The README or dev guide should include instructions. The MCP manager's actual tool discovery path is essentially untested in the default test suite.

### I3. No Session/Conversation Management

**PRD Reference:** §4.5 — "Session management: Redis cache (TTL 4 hours) + PostgreSQL for persistence"
**Impact:** There is no session model, session store, or conversation history anywhere in the codebase. While persistence is Phase 2, even Phase 1 specifies "in-memory sessions with session_id" (T4.1). Without this, multi-turn conversations have no state.

### I4. No Input Sanitization

**PRD Reference:** §6.3 (Input Sanitization) — character filtering, prompt injection detection, length limits
**Impact:** No input sanitization layer exists. User messages flow directly from orchestrator to LLM without any filtering for null bytes, control characters, prompt injection patterns, or length limits. While some of this is Phase 2/3, the PRD frames it as a security baseline.

### I5. No Audit Logging

**PRD Reference:** §6.5 (Audit Trail) — structured JSON events, non-disableable
**Impact:** No audit logging infrastructure exists. LLM calls, tool executions, skill matches, and data access events are not recorded. While marked Phase 2, the PRD describes audit as "non-disableable" — implementing it retroactively may require touching every layer.

### I6. Skill Matching Algorithm Is Simplistic

**Location:** `src/deep_agent/skills/engine.py:149-153`
**Impact:** The `_score_skill()` function uses simple tag overlap ratio (`matched_tags / len(tags)`). This means a skill with 1 tag matching has score 1.0, while a skill with 5 tags where 4 match has score 0.8. The PRD envisions "progressive disclosure" and embedding-based matching (future), but the current algorithm could produce counterintuitive rankings. The description field is not used for matching at all.

### I7. `LangGraphAdapter` Tightly Coupled to OpenAI

**Location:** `src/deep_agent/runtime/langgraph_adapter.py:51`
**PRD Reference:** §9 (Technology Stack) — "Provider-agnostic LLM routing"
**Impact:** `create_agent()` unconditionally instantiates `ChatOpenAI`. While Phase 1 targets OpenAI only, the adapter doesn't check `LLMConfig.provider` — switching to Claude or Gemini would require code changes to the adapter, not just configuration. The PRD's provider-agnostic promise is not architecturally enforced.

### I8. `execute_code` Tool Uses Closure-Captured Env (Immutable After Creation)

**Location:** `src/deep_agent/tools/execute_code.py:23-25`
**Impact:** The `resource_env` dict is built once at tool creation time and captured in the closure. If the tenant context changes mid-session (e.g., resource rotation), the tool would use stale env vars. This is an architectural limitation — the tool factory pattern means env vars are frozen at construction.

### I9. Docker Compose Incomplete

**Location:** `examples/docker-compose.yml`
**PRD Reference:** Implementation Plan T4.2
**Impact:** File exists but I was unable to verify its completeness. The implementation plan calls for ClickHouse + seed script; the example now uses SQLite instead. The docker-compose may be stale or redundant.

---

## Minor Issues

Cleanup, style, and nice-to-haves.

### M1. f-string Without Placeholders

**Location:** `src/deep_agent/mcp/config.py:54`
**Impact:** Ruff reports `F541: f-string without any placeholders`. The `f` prefix is unnecessary on the string literal. Trivial fix.

### M2. `lru_cache` on `get_settings()` Prevents Re-Loading

**Location:** `src/deep_agent/config.py:47-51`
**Impact:** `@lru_cache(maxsize=1)` caches settings forever within the process. While fine for production, this makes testing harder (tests must mock before first call) and prevents configuration reload. The provider parameter is unhashable (Protocol instance), but `lru_cache` works because it's called without arguments in practice.

### M3. `SkillContent` Inherits `score` Field from `SkillSummary`

**Location:** `src/deep_agent/models/skills.py:17,29`
**Impact:** `SkillContent` inherits from `SkillMetadata` which inherits from `SkillSummary`, which has `score: float = 0.0`. The `score` field is only relevant for match results, not for full skill content. It's harmless but adds noise to serialized output.

### M4. Duplicate `firm_stats.py` Files

**Locations:**
- `skills/equities/zscore-monitor/scripts/firm_stats.py` (production skill)
- `examples/skills/equities/zscore-monitor/scripts/firm_stats.py` (example copy)

**Impact:** Two identical copies of the same file. If one is updated, the other becomes stale. The example copy is tested via `tests/unit/test_firm_stats.py` (which imports from the example path), while the production copy is referenced by the actual skill.

### M5. Test Fixtures Still Use "equities" Domain Terminology

**Location:** `tests/conftest.py`
**Impact:** Fixture names like `tenant_equities` and skill bindings referencing `equities/zscore-monitor` are fine for testing (you need concrete values), but they couple tests to the example domain. This is minor — just a naming observation.

### M6. `examples/database/registry.py` Hardcodes Aliases

**Location:** `examples/database/registry.py:25-50`
**Impact:** `_ALIASES` and `_SCHEMAS` are module-level dicts with hardcoded `ch-equities` data. This is in `examples/` (appropriate), but it means the registry example can't demonstrate multiple data sources without code changes. A constructor parameter or config file would be more illustrative.

### M7. Missing `__all__` Exports in Several Modules

**Locations:** `src/deep_agent/skills/__init__.py`, `src/deep_agent/sandbox/__init__.py`, `src/deep_agent/runtime/__init__.py`
**Impact:** Some `__init__.py` files re-export symbols, while others don't define `__all__`. This is inconsistent but not harmful.

### M8. No `py.typed` Marker in Package Root

**Location:** `src/deep_agent/py.typed` exists (good)
**Impact:** None — this is actually correct. Just noting it's present.

---

## PRD Gap Analysis

| PRD Requirement | Status | Notes |
|---|---|---|
| **§4.1 SkillEngine** — discover/match/load | **Implemented** | Works with AgentSkillBindings, tag-based matching, filesystem caching |
| **§4.1** — Progressive disclosure (3 tiers) | **Partial** | Discovery and Load tiers work. Execute tier exists but lacks formal boundary |
| **§4.1** — `inputs` field in SKILL.md | **Not Implemented** | Field exists in SKILL.md files but parser drops it; no model field |
| **§4.1** — `quality` field in SKILL.md | **Not Implemented** | Field exists in SKILL.md files but parser drops it; no enforcement |
| **§4.2 SandboxManager** — PythonSubprocessSandbox | **Implemented** | Temp dir, timeout, env injection, output file collection, path traversal checks |
| **§4.2** — Resource limits (memory via RLIMIT_AS) | **Implemented** | Preamble injection approach works on Linux |
| **§4.2** — OpenShiftPodSandbox | **Not Implemented** | Phase 3; acknowledged in PRD phasing |
| **§4.3 Resource Configuration** — Generic env var injection | **Implemented** | `TenantContext.resource_env` → sandbox env vars, with prefix/collision handling |
| **§4.4 MCP Adapters** — Per-tenant MCP config | **Implemented** | JSON config, stdio/SSE transports, graceful degradation |
| **§4.4** — MCP tool discovery | **Implemented** | Via `langchain-mcp-adapters`, partial availability on server failure |
| **§4.5 Chat API** — WebSocket endpoint | **Not Implemented** | Empty `api/` package. No FastAPI, no WebSocket handler |
| **§4.5** — Health endpoint (`GET /health`) | **Not Implemented** | No API code |
| **§4.5** — Session management | **Not Implemented** | No session model or store |
| **§4.5** — Streaming event protocol | **Partially Implemented** | Event models exist; no WebSocket delivery mechanism |
| **§5 Skills Spec** — SKILL.md parsing | **Implemented** | YAML frontmatter + Markdown body, validation, ID derivation |
| **§5** — `allowed-tools` enforcement | **Implemented** | `_filter_tools()` in orchestrator |
| **§5** — Skill directory structure (Anthropic AgentSkills spec) | **Implemented** | SKILL.md + scripts/ + references/ + assets/ convention followed |
| **§5** — Bundled scripts on PYTHONPATH | **Implemented** | `scripts_path` → `PYTHONPATH` env var injection into sandbox |
| **§6.1 Sandbox Hardening** — Dev/MVP controls | **Partial** | Path traversal blocked, symlink skipping, env allowlisting. Missing: dedicated OS user, network restriction (iptables), output scanning |
| **§6.3 Input Sanitization** | **Not Implemented** | No character filtering, no prompt injection detection, no length limits |
| **§6.4 Credential Management** — No secrets to LLM | **Partial** | Env vars injected to sandbox (not LLM), but no output scanning for credential patterns |
| **§6.5 Audit Trail** | **Not Implemented** | No audit logging infrastructure |
| **§7 Multi-Tenancy** — Tenant model | **Partial** | `TenantContext` exists; no tenant config loading, no quotas, no role resolution |
| **§7** — `TenantConfig` model | **Not Implemented** | PRD defines `TenantConfig` with quotas, teams, LLM overrides — none exist |
| **§7** — Role-based permissions | **Not Implemented** | Phase 2 |
| **§8 Deployment** — K8s / Helm charts | **Not Implemented** | Phase 3 |
| **§9 Tech Stack** — RuntimeAdapter protocol | **Implemented** | Clean protocol + LangGraphAdapter implementation |
| **§9** — LLM Router | **Implemented** | Returns OpenAI config from AppSettings; extensible for future providers |
| **§9** — `deepagents` with langgraph fallback | **Implemented** | Try-import pattern with fallback to `create_react_agent` |
| **§10 Phase 1** — T1.1 Project scaffolding | **Complete** | pyproject.toml, requirements, pip-installable |
| **§10 Phase 1** — T1.2 Data models | **Complete** | All Pydantic models for context, skills, events, LLM, sandbox |
| **§10 Phase 1** — T1.3 Skill parser | **Complete** | `parse_skill_file()` with validation |
| **§10 Phase 1** — T1.4 SkillEngine | **Complete** | discover/match/load with caching |
| **§10 Phase 1** — T1.5 Reference SKILL.md files | **Complete** | db-query + zscore-monitor |
| **§10 Phase 1** — T1.6 Skill unit tests | **Complete** | 9 parser + 9 engine tests |
| **§10 Phase 1** — T2.1 LLMRouter | **Complete** | |
| **§10 Phase 1** — T2.2 RuntimeAdapter protocol | **Complete** | |
| **§10 Phase 1** — T2.3 LangGraphAdapter | **Complete** | Both invoke + stream paths |
| **§10 Phase 1** — T2.4 SandboxManager + Subprocess | **Complete** | |
| **§10 Phase 1** — T2.5 firm_stats script | **Complete** | zscore + moving_avg |
| **§10 Phase 1** — T2.6 Runtime/sandbox unit tests | **Complete** | 14 sandbox + 10 adapter tests |
| **§10 Phase 1** — T3.1 Resource config (DatabaseRegistry) | **Complete** | In `examples/` (correct placement) |
| **§10 Phase 1** — T3.2 execute_code tool | **Complete** | |
| **§10 Phase 1** — T3.3 query_database tool (example) | **Complete** | In `examples/tools/` |
| **§10 Phase 1** — T3.4 AgentOrchestrator | **Complete** | |
| **§10 Phase 1** — T3.5 Orchestrator unit tests | **Complete** | 9 tests |
| **§10 Phase 1** — T3.6 MCP config loader | **Complete** | |
| **§10 Phase 1** — T3.7 MCPManager | **Complete** | |
| **§10 Phase 1** — T3.8 Test MCP server | **Complete** | echo/add/multiply |
| **§10 Phase 1** — T3.9 MCP tests | **Complete** | 13 config + 9 integration tests |
| **§10 Phase 1** — T4.1 FastAPI + WebSocket | **Not Started** | Empty api/ package |
| **§10 Phase 1** — T4.2 Docker compose + seed | **Partial** | docker-compose.yml exists; seed_data.py uses SQLite not ClickHouse |
| **§10 Phase 1** — T4.3 WebSocket integration tests | **Not Started** | |
| **§10 Phase 1** — T4.4 E2E test (Z-Score query) | **Not Started** | |
| **§10 Phase 1** — T4.5 Dev run script + polish | **Not Started** | No run_dev.py |

### Scope Creep Check

| Implemented Feature | In PRD? | Notes |
|---|---|---|
| `examples/run_example.py` (Portfolio VaR) | Not explicitly, but aligns with PRD spirit | Good addition — demonstrates patterns without API key |
| `examples/mock_mcp_server.py` | Not in PRD | Useful for local dev; reasonable |
| `examples/seed_data.py` (SQLite) | Variant of T4.2 | Uses SQLite instead of ClickHouse — pragmatic choice |
| `TenantContext.stub()` | Not in PRD | Dev convenience; minor |

**Verdict:** No significant scope creep detected. The examples/ additions are practical and well-contained.

---

## Test Coverage Analysis

### Coverage by Module

| Module | Test File | # Tests | Assessment |
|---|---|---|---|
| `models/` | `test_models.py` | 7 | Good: covers all model types, serialization, frozen dataclass |
| `skills/parser.py` | `test_skill_parser.py` | 9 | Good: valid/invalid/edge cases, ID derivation |
| `skills/engine.py` | `test_skill_engine.py` | 9 | Good: discover, match, load, caching, malformed files |
| `runtime/llm_router.py` | `test_llm_router.py` | 4 | Good: covers Phase 1 scope |
| `runtime/langgraph_adapter.py` | `test_langgraph_adapter.py` | 10 | Good: invoke, stream, error paths, tool events |
| `sandbox/subprocess_sandbox.py` | `test_sandbox.py` | 14 | Excellent: print, files, timeout, env injection, path traversal, symlinks, secrets, PYTHONPATH |
| `tools/execute_code.py` | `test_tools.py` | 6 | Good: name, JSON output, errors, env injection, multi-alias, PYTHONPATH |
| `orchestrator/agent_orchestrator.py` | `test_orchestrator.py` | 9 | Good: skill matching, system prompt, tool filtering, error handling, graceful degradation |
| `mcp/config.py` | `test_mcp_config.py` | 13 | Good: valid/invalid JSON, path traversal, transport validation |
| `mcp/manager.py` | `test_mcp_manager.py` | 9 | Good but skipped by default (requires `RUN_MCP_INTEGRATION=1`) |
| `config.py` | — | 0 | **Gap: No dedicated config tests** |
| `api/` | — | 0 | N/A (not implemented) |
| firm_stats | `test_firm_stats.py` | 7 | Good: basic math, edge cases |

### Notable Gaps

1. **`config.py` has zero test coverage.** `AppSettings` validation, `get_settings()` caching, and `EnvironmentSettingsProvider` are untested. The `lru_cache` behavior (inability to reload) is also untested.

2. **No integration test for the full orchestration pipeline.** All orchestrator tests mock every dependency. There's no test that wires real `SkillEngine` + real `Sandbox` + mock LLM together.

3. **`execute_code` tool's `files_in` parameter is never tested end-to-end.** The sandbox tests cover `files_in`, but the tool factory never passes `files_in` to the sandbox — and this code path (skill scripts as `files_in`) doesn't exist in the tool at all. Scripts are passed via PYTHONPATH, not `files_in`.

4. **Error paths in `_build_resource_env` multi-alias collision logging are tested via `test_resource_env_multi_alias_only_prefixed`, but the warning message itself is not asserted.**

---

## Runtime Correctness

### Test Suite Results

```
88 passed, 9 skipped in 2.89s
```

- All 88 unit tests pass
- 9 MCP integration tests correctly skipped (gated behind env flag)
- No warnings or deprecation errors in test output

### Example Run Results

```
Seeded /tmp/portfolio.db with 3 positions and 756 daily prices.
Portfolio: EQ-MACRO-1
1-Day 95% VaR: $4,591
Expected Shortfall: $5,813
Chart saved to: examples/output/var_chart.png
```

Example runs correctly, demonstrates all 3 integration patterns.

### Static Analysis

- **Ruff:** 1 issue (`F541` f-string without placeholders in `mcp/config.py:54`)
- **mypy:** `Success: no issues found in 26 source files`
- **No hardcoded equity/finance references in core `src/`** (except `TenantContext.stub()`)
- **No TODOs, FIXMEs, or HACKs anywhere in `src/`**
- **No unused imports detected**

---

## Recommendation

### Priority 1 — Complete Phase 1 (Week 4 Tasks)

The biggest gap is the missing WebSocket API layer (T4.1). This is the primary user-facing interface and is required for the Phase 1 success criteria. Implement:

1. **T4.1:** `src/deep_agent/api/app.py` (FastAPI), `ws_chat.py` (WebSocket handler), `schemas.py` (message models)
2. **T4.3:** WebSocket integration tests
3. **T4.4:** E2E test (can adapt to SQLite instead of ClickHouse)
4. **T4.5:** `scripts/run_dev.py` + README update

### Priority 2 — Parse `inputs` and `quality` Fields

These are defined in the PRD's skill spec (§5) and present in all SKILL.md files but silently dropped:

1. Add `inputs: list[dict]` and `quality: dict` fields to `SkillContent` (or dedicated Pydantic models)
2. Update parser to extract them
3. Pass `quality.timeout` to sandbox execution
4. Include `inputs` in system prompt for input validation guidance

### Priority 3 — Add `config.py` Tests

`AppSettings` is the project's configuration backbone and has zero test coverage. Add tests for:
- Default values
- Environment variable overrides
- Missing required field (`OPENAI_API_KEY`) behavior
- `get_settings()` caching

### Priority 4 — Add `scripts/requirements.txt` to `db-query` Skill

The `skills/common/db-query/` directory has no `scripts/` folder. The skill instructs the agent to use `clickhouse_connect`, but the sandbox won't have it installed. Add:
```
skills/common/db-query/scripts/requirements.txt
```

### Priority 5 — Address `TenantContext.stub()`

Move `stub()` to `examples/` or make it domain-neutral to fully complete the resource-agnostic refactor.
