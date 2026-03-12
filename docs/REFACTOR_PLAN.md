# Codebase Refactoring Plan

> Generated from audit of all files under `src/deep_agent/` against the updated `docs/PRD.md`.
> **Plan only — no code changes.**

---

## 1. Summary Table

| File | Action | Reason |
|------|--------|--------|
| `src/deep_agent/__init__.py` | KEEP | Version re-export only, aligned |
| `src/deep_agent/config.py` | MODIFY | Remove 5 `clickhouse_*` fields from `AppSettings`; add `resource_env_prefixes` config |
| `src/deep_agent/models/__init__.py` | MODIFY | Remove database model re-exports |
| `src/deep_agent/models/context.py` | MODIFY | Replace `db_aliases` with `resource_env`; remove `skills_dirs` (replaced by agent skill bindings) |
| `src/deep_agent/models/skills.py` | MODIFY | Remove `tenant: str` from `SkillMetadata`; add `AgentSkillBindings` dataclass |
| `src/deep_agent/models/database.py` | MOVE | Move to `examples/skills/data-query/db-query/scripts/` — example code only |
| `src/deep_agent/models/events.py` | KEEP | Aligned with PRD |
| `src/deep_agent/models/llm.py` | KEEP | Aligned with PRD |
| `src/deep_agent/models/sandbox.py` | KEEP | Aligned with PRD |
| `src/deep_agent/skills/parser.py` | MODIFY | Remove `"tenant"` from `REQUIRED_SKILL_FIELDS`; stop passing `tenant=` to SkillContent |
| `src/deep_agent/skills/engine.py` | MODIFY | Replace tenant-based visibility with agent skill bindings; rewrite `discover()`/`match()`/`load()` signatures |
| `src/deep_agent/runtime/llm_router.py` | KEEP | Aligned with PRD |
| `src/deep_agent/runtime/protocol.py` | KEEP | Aligned with PRD |
| `src/deep_agent/runtime/langgraph_adapter.py` | KEEP | Aligned with PRD |
| `src/deep_agent/sandbox/protocol.py` | KEEP | Aligned with PRD |
| `src/deep_agent/sandbox/subprocess_sandbox.py` | MODIFY | Remove `stubs_path` parameter; add `"RESOURCE_"` to `_ALLOWED_ENV_PREFIXES` |
| `src/deep_agent/database/__init__.py` | MOVE | Move entire package to `examples/database/` |
| `src/deep_agent/database/registry.py` | MOVE | Move to `examples/database/registry.py` |
| `src/deep_agent/tools/execute_code.py` | MODIFY | Remove hard dependency on `DatabaseRegistry`/`AppSettings`; use generic resource env injection from `TenantContext.resource_env` |
| `src/deep_agent/tools/query_database.py` | MOVE | Move to `examples/tools/query_database.py` — example tool |
| `src/deep_agent/orchestrator/agent_orchestrator.py` | MODIFY | Make `db_registry` optional; add `skill_bindings` parameter; use agent-scoped discovery |
| `src/deep_agent/mcp/config.py` | KEEP | Aligned with PRD |
| `src/deep_agent/mcp/manager.py` | KEEP | Aligned with PRD |
| `stubs/firm/__init__.py` | MOVE | Move to `examples/skills/equities/zscore-monitor/scripts/` |
| `stubs/firm/stats.py` | MOVE | Move to `examples/skills/equities/zscore-monitor/scripts/firm_stats.py` |
| `requirements.txt` | MODIFY | Remove `clickhouse-connect>=0.7` from core deps |

---

## 2. Detailed Changes Per File

### 2.1 `src/deep_agent/config.py` — MODIFY

**Current state:** `AppSettings` contains 5 ClickHouse-specific fields (lines 34-38):
```python
clickhouse_host: str = "localhost"
clickhouse_port: int = 9000
clickhouse_db: str = "deep_agent"
clickhouse_user: str = "default"
clickhouse_password: str = ""
```

**Changes:**
1. Remove all 5 `clickhouse_*` fields
2. Add optional `resource_env_prefixes: list[str] = ["DB_", "RESOURCE_", "KDB_", "REDIS_", "MONGO_"]` for configurable env var allowlisting (or move this to a constant)
3. No other changes needed — `llm_provider`, `llm_model`, `sandbox_*` fields are all core

### 2.2 `src/deep_agent/models/__init__.py` — MODIFY

**Current state:** Re-exports all model types including `DatabaseAlias`, `TableMeta`, `DatabaseMetadata`, `ConnectionConfig`.

**Changes:**
1. Remove `DatabaseAlias`, `TableMeta`, `DatabaseMetadata`, `ConnectionConfig` from `__all__` and imports
2. Keep all other re-exports (they're core)

### 2.3 `src/deep_agent/models/context.py` — MODIFY

**Current state:** `TenantContext` has:
- `skills_dirs: tuple[str, ...]` — replaced by agent skill bindings
- `db_aliases: tuple[str, ...]` — ClickHouse-specific concept

**Changes:**
1. Remove `db_aliases: tuple[str, ...]`
2. Add `resource_env: dict[str, dict[str, str]] = {}` — maps resource alias name → env var key-value pairs
3. Keep `skills_dirs` but repurpose as optional override for skill discovery paths (or remove if bindings fully replace it). Recommend keeping for backward compat during migration, marking deprecated.
4. Keep `tenant_id`, `mcp_config_path` — both are core

### 2.4 `src/deep_agent/models/skills.py` — MODIFY

**Current state:** `SkillMetadata` has `tenant: str` field (line 25). No `AgentSkillBindings` type exists.

**Changes:**
1. Remove `tenant: str` from `SkillMetadata`
2. Add new dataclass:
```python
@dataclass(frozen=True)
class AgentSkillBindings:
    agent_id: str
    bound_skill_ids: tuple[str, ...]
```
3. Remove `tenant` from `SkillSummary` if present in the summary projection used by engine

### 2.5 `src/deep_agent/models/database.py` — MOVE

**Destination:** `examples/database/models.py`

**Reason:** `DatabaseAlias`, `TableMeta`, `DatabaseMetadata`, `ConnectionConfig` are all example/convenience types for the DB-query example skill. The core framework is resource-agnostic and has no database model concept.

### 2.6 `src/deep_agent/skills/parser.py` — MODIFY

**Current state:**
- Line 19: `REQUIRED_SKILL_FIELDS` includes `"tenant"`
- Line 69: Passes `tenant=meta.get("tenant", "")` to `SkillContent`

**Changes:**
1. Remove `"tenant"` from `REQUIRED_SKILL_FIELDS`
2. Remove `tenant=` kwarg from `SkillContent` constructor call
3. If `tenant` appears in YAML frontmatter, silently ignore it (don't error) for backward compat

### 2.7 `src/deep_agent/skills/engine.py` — MODIFY (major)

**Current state:**
- `_is_visible_to_tenant()` (line 140-141) checks `skill.tenant == "common" or skill.tenant == tenant.tenant_id`
- `discover()` and `match()` take `TenantContext`, filter by tenant visibility
- `load()` checks tenant visibility before returning skill

**Changes:**
1. Remove `_is_visible_to_tenant()` entirely
2. Add `_is_bound_to_agent(skill_id: str, bindings: AgentSkillBindings) -> bool` — checks if `skill_id in bindings.bound_skill_ids`
3. Rewrite `discover(tenant: TenantContext, ...)` → `discover(bindings: AgentSkillBindings, ...)` — returns only skills in `bindings.bound_skill_ids`
4. Rewrite `match(query, tenant, ...)` → `match(query, bindings: AgentSkillBindings, ...)` — matches against bound skills only
5. Rewrite `load(skill_id, tenant, ...)` → `load(skill_id, bindings: AgentSkillBindings, ...)` — validates skill is bound before loading
6. Keep `index_skills()` as global registry (indexes ALL skills regardless of agent)

### 2.8 `src/deep_agent/sandbox/subprocess_sandbox.py` — MODIFY

**Current state:**
- Line 35: `_ALLOWED_ENV_PREFIXES = ("DB_", "CLICKHOUSE_", "REDIS_", "MONGO_", "MYSQL_", "API_")`
- Line 41: Constructor has `stubs_path: Path | None = None`
- Lines 143-149: `self._stubs_path` usage to add stubs to `PYTHONPATH`

**Changes:**
1. Add `"RESOURCE_"` to `_ALLOWED_ENV_PREFIXES`
2. Remove `stubs_path` parameter from constructor
3. Remove `self._stubs_path` attribute and all stubs-related PYTHONPATH logic (lines 143-149)
4. Skills provide their own scripts via `files_in` parameter (already supported)

### 2.9 `src/deep_agent/database/` — MOVE (entire package)

**Destination:** `examples/database/`

**Files:**
- `src/deep_agent/database/__init__.py` → `examples/database/__init__.py`
- `src/deep_agent/database/registry.py` → `examples/database/registry.py`

**Reason:** `DatabaseRegistry` is example code. It hardcodes a ClickHouse alias, references `AppSettings.clickhouse_*` fields. The core framework provides generic resource env var injection; specific DB connectors are skill/example concerns.

### 2.10 `src/deep_agent/tools/execute_code.py` — MODIFY (major)

**Current state:**
- Imports `DatabaseRegistry` and `AppSettings`
- `_build_db_env()` constructs ClickHouse-specific env vars using `DatabaseRegistry` + `AppSettings`
- These env vars are passed to the sandbox

**Changes:**
1. Remove `DatabaseRegistry` and `AppSettings` imports
2. Remove `_build_db_env()` method
3. Replace with generic resource env injection:
   - Read `resource_env` from `TenantContext` (a `dict[str, dict[str, str]]`)
   - Flatten all resource env vars into the sandbox environment
   - Filter through `_ALLOWED_ENV_PREFIXES` (already in subprocess_sandbox.py)
4. The function signature should accept `TenantContext` (or just the resource_env dict) instead of `DatabaseRegistry`

### 2.11 `src/deep_agent/tools/query_database.py` — MOVE

**Destination:** `examples/tools/query_database.py`

**Reason:** `query_database` is an example tool that depends on `DatabaseRegistry`. The core framework ships `execute_code` only. Example skills can bundle `query_database` if needed.

### 2.12 `src/deep_agent/orchestrator/agent_orchestrator.py` — MODIFY (major)

**Current state:**
- Line 39: Constructor requires `DatabaseRegistry`
- Line 107: Accesses `self._db_registry._settings` (tight coupling)
- Uses tenant-based `discover()`/`match()`/`load()` calls
- Registers `query_database` tool unconditionally

**Changes:**
1. Make `db_registry` parameter optional (`db_registry: DatabaseRegistry | None = None`)
2. Add `skill_bindings: AgentSkillBindings | None = None` parameter
3. Pass `skill_bindings` (not `TenantContext`) to `discover()`/`match()`/`load()`
4. Conditionally register `query_database` tool only if `db_registry` is provided
5. Remove direct access to `self._db_registry._settings`; use `TenantContext.resource_env` for env var injection

### 2.13 `stubs/firm/` — MOVE

**Files:**
- `stubs/firm/__init__.py` → DELETE (or move as `__init__.py` to example scripts dir if needed)
- `stubs/firm/stats.py` → `examples/skills/equities/zscore-monitor/scripts/firm_stats.py`

**Reason:** Per Anthropic AgentSkills spec, skills bundle their own scripts. `firm.stats` becomes `firm_stats` module inside the zscore-monitor skill's `scripts/` directory. Imported as `from firm_stats import zscore`.

### 2.14 `requirements.txt` — MODIFY

**Remove:** `clickhouse-connect>=0.7` (line 9) — this is a skill-specific dependency, not a core framework requirement.

**Keep everything else** — `pydantic`, `langgraph`, `websockets`, `httpx`, `pyyaml`, etc. are all core.

---

## 3. New Files to Create

| File | Purpose |
|------|---------|
| `examples/database/__init__.py` | Package init for moved DatabaseRegistry |
| `examples/database/registry.py` | Moved from `src/deep_agent/database/registry.py` |
| `examples/database/models.py` | Moved from `src/deep_agent/models/database.py` |
| `examples/tools/query_database.py` | Moved from `src/deep_agent/tools/query_database.py` |
| `examples/skills/equities/zscore-monitor/SKILL.md` | Example skill definition (already described in PRD) |
| `examples/skills/equities/zscore-monitor/scripts/firm_stats.py` | Moved from `stubs/firm/stats.py`, renamed |
| `examples/skills/equities/zscore-monitor/scripts/requirements.txt` | Skill-specific deps (clickhouse-connect, pandas, numpy) |
| `examples/skills/data-query/db-query/SKILL.md` | Example skill definition |
| `examples/skills/data-query/db-query/scripts/requirements.txt` | Skill-specific deps |
| `examples/docker-compose.yaml` | Moved from project root (if exists) — ClickHouse + Redis for examples |
| `examples/README.md` | Brief guide to running example skills |
| `config/agents/` directory | Agent skill binding configs (YAML files) |

**No new core framework files needed** — the changes are subtractive (removing DB-specific code) and restructuring (moving example code out).

---

## 4. Test Impact

### 4.1 Tests That Must Change

| Test File | Impact | Changes Needed |
|-----------|--------|----------------|
| `tests/unit/test_config.py` | MODIFY | Remove assertions for `clickhouse_*` fields; add assertions for any new `resource_env_prefixes` field |
| `tests/unit/models/test_context.py` | MODIFY | Replace `db_aliases` assertions with `resource_env`; update `TenantContext` construction |
| `tests/unit/models/test_skills.py` | MODIFY | Remove `tenant` field assertions from `SkillMetadata` tests; add `AgentSkillBindings` tests |
| `tests/unit/models/test_database.py` | MOVE | Move to `tests/examples/test_database_models.py` or `examples/tests/` |
| `tests/unit/skills/test_parser.py` | MODIFY | Remove test for `tenant` as required field; update assertions on parsed skill objects |
| `tests/unit/skills/test_engine.py` | MODIFY (major) | Replace all `_is_visible_to_tenant` tests with `_is_bound_to_agent` tests; update `discover()`/`match()`/`load()` test signatures to use `AgentSkillBindings` instead of `TenantContext` |
| `tests/unit/sandbox/test_subprocess_sandbox.py` | MODIFY | Remove `stubs_path` tests; add `"RESOURCE_"` prefix test; remove stubs PYTHONPATH assertions |
| `tests/unit/database/test_registry.py` | MOVE | Move to `tests/examples/test_database_registry.py` |
| `tests/unit/tools/test_execute_code.py` | MODIFY (major) | Remove `DatabaseRegistry`/`AppSettings` mocking; test generic resource env injection via `TenantContext.resource_env` |
| `tests/unit/tools/test_query_database.py` | MOVE | Move to `tests/examples/test_query_database.py` |
| `tests/unit/orchestrator/test_agent_orchestrator.py` | MODIFY (major) | Make `db_registry` optional in setup; add `skill_bindings` to test fixtures; update `discover()`/`match()`/`load()` mock signatures |
| `tests/unit/test_firm_stats.py` (if exists) | MOVE | Move to `tests/examples/test_firm_stats.py`; update import from `firm.stats` → `firm_stats` |
| `tests/conftest.py` | MODIFY | Update shared fixtures: remove `stubs_path`, add `resource_env` to `TenantContext` fixtures, add `AgentSkillBindings` fixture |

### 4.2 Tests That Stay Unchanged

| Test File | Reason |
|-----------|--------|
| `tests/unit/models/test_events.py` | Events model is aligned |
| `tests/unit/models/test_llm.py` | LLM model is aligned |
| `tests/unit/models/test_sandbox.py` | Sandbox model is aligned |
| `tests/unit/runtime/test_llm_router.py` | LLM router is aligned |
| `tests/unit/runtime/test_protocol.py` | Protocol is aligned |
| `tests/unit/runtime/test_langgraph_adapter.py` | Adapter is aligned |
| `tests/unit/mcp/test_config.py` | MCP config is aligned |
| `tests/unit/mcp/test_manager.py` | MCP manager is aligned |

---

## 5. `examples/` Directory Structure

```
examples/
├── README.md                                    # How to run example skills
├── docker-compose.yaml                          # ClickHouse + Redis for examples
├── database/
│   ├── __init__.py
│   ├── models.py                                # DatabaseAlias, TableMeta, etc.
│   └── registry.py                              # DatabaseRegistry (ClickHouse convenience wrapper)
├── tools/
│   └── query_database.py                        # query_database tool implementation
├── skills/
│   ├── equities/
│   │   └── zscore-monitor/
│   │       ├── SKILL.md                         # Full AgentSkills-spec skill definition
│   │       ├── scripts/
│   │       │   ├── requirements.txt             # clickhouse-connect, pandas, numpy
│   │       │   └── firm_stats.py                # Moved from stubs/firm/stats.py
│   │       ├── references/                      # Extended docs (optional)
│   │       └── assets/                          # Static data (optional)
│   └── data-query/
│       └── db-query/
│           ├── SKILL.md
│           ├── scripts/
│           │   └── requirements.txt
│           ├── references/
│           └── assets/
├── config/
│   ├── agents/
│   │   └── equities-desk-agent.yaml             # Example agent skill bindings
│   └── tenants/
│       └── equities/
│           ├── resources.yaml                   # Example resource aliases (ClickHouse env vars)
│           └── mcp.json                         # Example MCP config
└── tests/
    ├── test_database_models.py
    ├── test_database_registry.py
    ├── test_query_database.py
    └── test_firm_stats.py
```

---

## 6. Dependency Changes

### 6.1 Remove from `requirements.txt`

| Package | Reason |
|---------|--------|
| `clickhouse-connect>=0.7` | Example skill dependency, not core framework |

### 6.2 Add to `requirements.txt`

Nothing — all core dependencies are already present.

### 6.3 Add to Example Skill Deps

| File | Packages |
|------|----------|
| `examples/skills/equities/zscore-monitor/scripts/requirements.txt` | `clickhouse-connect>=0.7`, `pandas>=2.2`, `numpy>=1.26` |
| `examples/skills/data-query/db-query/scripts/requirements.txt` | `clickhouse-connect>=0.7` |

### 6.4 Sandbox Base Image Changes

| Current | New |
|---------|-----|
| Python 3.12 + pre-installed analytics libs + `clickhouse-connect` | Python 3.12-slim + pip only |

Skills declare their own deps in `scripts/requirements.txt`; the sandbox installs them at execution time (with per-skill caching).

---

## 7. Execution Order

Ordered by dependency — each phase can be done in parallel within itself, but phases are sequential.

### Phase 1: Models & Config (no downstream deps)
**Can be done in parallel:**
1. **Remove `tenant` from `SkillMetadata`** (`models/skills.py`) — add `AgentSkillBindings` dataclass
2. **Update `TenantContext`** (`models/context.py`) — replace `db_aliases` with `resource_env`
3. **Remove `clickhouse_*` from `AppSettings`** (`config.py`)
4. **Update `models/__init__.py`** — remove database model re-exports

**Tests to update immediately:** `test_skills.py`, `test_context.py`, `test_config.py`

### Phase 2: Skills Layer (depends on Phase 1 models)
**Sequential:**
5. **Update `skills/parser.py`** — remove `tenant` from required fields and constructor
6. **Rewrite `skills/engine.py`** — replace tenant visibility with agent skill bindings

**Tests to update:** `test_parser.py`, `test_engine.py`

### Phase 3: Sandbox (independent of Phase 2)
**Can run in parallel with Phase 2:**
7. **Update `sandbox/subprocess_sandbox.py`** — remove `stubs_path`, add `"RESOURCE_"` prefix

**Tests to update:** `test_subprocess_sandbox.py`

### Phase 4: Tools & Orchestrator (depends on Phases 1-3)
**Sequential:**
8. **Refactor `tools/execute_code.py`** — remove DatabaseRegistry dependency, use `TenantContext.resource_env`
9. **Refactor `orchestrator/agent_orchestrator.py`** — optional `db_registry`, add `skill_bindings`, scoped discovery

**Tests to update:** `test_execute_code.py`, `test_agent_orchestrator.py`

### Phase 5: Move Example Code (depends on Phase 4)
**Can be done in parallel:**
10. **Create `examples/` directory structure**
11. **Move `src/deep_agent/database/`** → `examples/database/`
12. **Move `src/deep_agent/tools/query_database.py`** → `examples/tools/`
13. **Move `src/deep_agent/models/database.py`** → `examples/database/models.py`
14. **Move `stubs/firm/`** → `examples/skills/equities/zscore-monitor/scripts/`
15. **Update imports** in moved files to reference examples paths
16. **Move related tests** to `examples/tests/`

### Phase 6: Cleanup & Dependencies
17. **Remove `clickhouse-connect` from `requirements.txt`**
18. **Delete empty `src/deep_agent/database/` package** (after move)
19. **Delete empty `stubs/` directory** (after move)
20. **Create example skill `scripts/requirements.txt` files** with moved deps
21. **Write `examples/README.md`**

### Phase 7: Verification
22. **Run full test suite** — all core tests must pass
23. **Run grep checks** — zero references to removed concepts in core:
    - `grep -ri "DatabaseRegistry" src/` → 0 (only in examples/)
    - `grep -ri "clickhouse" src/` → 0
    - `grep -ri "stubs_path\|stubs/" src/` → 0
    - `grep -ri "tenant:.*common\|_is_visible_to_tenant" src/` → 0
    - `grep -ri "firm\.stats\|from firm import" src/` → 0
24. **Validate example skills** — confirm SKILL.md frontmatter, scripts/ structure, requirements.txt

---

## Appendix: Files Audited

All 24 source files under `src/deep_agent/` plus `stubs/` and `requirements.txt`:

| # | File | Lines | Verdict |
|---|------|-------|---------|
| 1 | `src/deep_agent/__init__.py` | 3 | KEEP |
| 2 | `src/deep_agent/config.py` | ~50 | MODIFY |
| 3 | `src/deep_agent/models/__init__.py` | ~20 | MODIFY |
| 4 | `src/deep_agent/models/context.py` | ~25 | MODIFY |
| 5 | `src/deep_agent/models/skills.py` | ~35 | MODIFY |
| 6 | `src/deep_agent/models/database.py` | ~60 | MOVE → examples/ |
| 7 | `src/deep_agent/models/events.py` | ~55 | KEEP |
| 8 | `src/deep_agent/models/llm.py` | ~20 | KEEP |
| 9 | `src/deep_agent/models/sandbox.py` | ~30 | KEEP |
| 10 | `src/deep_agent/skills/parser.py` | ~80 | MODIFY |
| 11 | `src/deep_agent/skills/engine.py` | ~160 | MODIFY |
| 12 | `src/deep_agent/runtime/llm_router.py` | ~90 | KEEP |
| 13 | `src/deep_agent/runtime/protocol.py` | ~25 | KEEP |
| 14 | `src/deep_agent/runtime/langgraph_adapter.py` | ~140 | KEEP |
| 15 | `src/deep_agent/sandbox/protocol.py` | ~25 | KEEP |
| 16 | `src/deep_agent/sandbox/subprocess_sandbox.py` | ~170 | MODIFY |
| 17 | `src/deep_agent/database/__init__.py` | ~5 | MOVE → examples/ |
| 18 | `src/deep_agent/database/registry.py` | ~110 | MOVE → examples/ |
| 19 | `src/deep_agent/tools/execute_code.py` | ~100 | MODIFY |
| 20 | `src/deep_agent/tools/query_database.py` | ~80 | MOVE → examples/ |
| 21 | `src/deep_agent/orchestrator/agent_orchestrator.py` | ~130 | MODIFY |
| 22 | `src/deep_agent/mcp/config.py` | ~40 | KEEP |
| 23 | `src/deep_agent/mcp/manager.py` | ~100 | KEEP |
| 24 | `stubs/firm/__init__.py` | ~3 | MOVE → examples/ |
| 25 | `stubs/firm/stats.py` | ~30 | MOVE → examples/ |
| 26 | `requirements.txt` | ~15 | MODIFY |

**Totals:** 8 KEEP, 10 MODIFY, 7 MOVE, 0 DELETE, 12 new files to create.
