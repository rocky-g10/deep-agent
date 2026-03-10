# Deep Agent — Phase 1 Implementation Plan

> **Phase:** 1 — Foundation (Weeks 1–4)
> **PRD Reference:** Section 10.1
> **Last Updated:** 2026-03-10
> **Status:** Draft

---

## Table of Contents

1. [Phase 1 Goal](#phase-1-goal)
2. [Key Tech Decisions](#key-tech-decisions)
3. [Package Structure](#package-structure)
4. [Dependency Graph](#dependency-graph)
5. [Week 1: Project Scaffolding, Data Models, and SkillEngine](#week-1-project-scaffolding-data-models-and-skillengine)
6. [Week 2: LLM Router, RuntimeAdapter, and Sandbox](#week-2-llm-router-runtimeadapter-and-sandbox)
7. [Week 3: Database, Tools, and Orchestrator](#week-3-database-tools-and-orchestrator)
8. [Week 4: WebSocket API, Seed Data, and E2E Test](#week-4-websocket-api-seed-data-and-e2e-test)
9. [Summary Table](#summary-table)
10. [Parallelization Opportunities](#parallelization-opportunities)
11. [Risks and Mitigations](#risks-and-mitigations)

---

## Phase 1 Goal

End-to-end agent loop — a single user on a single tenant can ask a natural-language question, the agent matches a skill, queries ClickHouse, executes Python in a sandbox, and streams the answer back over WebSocket.

**Deliverables:**

| Deliverable | Details |
|---|---|
| `RuntimeAdapter` protocol | Interface definition + `LangGraphAdapter` using `deepagents` (fallback: `langgraph`) |
| `LLMRouter` | OpenAI GPT-5 integration; single-provider, no fallback |
| `SkillEngine` | Discover, match (tag-based), load; hot reload from filesystem |
| WebSocket API | FastAPI with streaming events (`user_message` → `agent_chunk` / `tool_call` / `tool_result` / `agent_complete`) |
| `SandboxManager` | `PythonSubprocessSandbox` backend with resource limits |
| `DatabaseRegistry` | ClickHouse connector; single alias (`ch-equities`) |
| MCP Integration | `langchain-mcp-adapters` wired into orchestrator; config loader; test MCP server; tool merging with skill `allowed_tools` |
| Reference skills | `common/db-query`, `equities/zscore-monitor` |
| End-to-end test | "Show me z-scores for AAPL volume" → table + chart |

**NOT in Phase 1:** Auth, multi-tenancy, persistence, audit logging, standalone visualization skill.

---

## Key Tech Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Agent framework | `deepagents` (primary), `langgraph` (fallback) | PRD specifies `deepagents`; fall back to `langgraph.prebuilt.create_react_agent` if API doesn't support clean tool override |
| Package manager | `pip + venv` | Enterprise standard; maximum compatibility across CI and dev environments |
| Dependency spec | `pyproject.toml` + `requirements.txt` | `pyproject.toml` for project metadata and build config; `requirements.txt` (pinned) for reproducible installs |
| Local services | `docker-compose.yml` | ClickHouse for local dev and E2E testing |
| LLM provider | OpenAI GPT-5 via `langchain-openai` | Single provider, no fallback in Phase 1 |
| TenantContext | Hardcoded stub (`equities`) | No auth/multi-tenancy in Phase 1 |
| `firm.stats` | Stub implementation with real math | Installable stub so sandbox code can `import firm.stats` |
| MCP integration | `langchain-mcp-adapters` | PRD §4.4; connects LangChain tools to MCP servers; single-tenant config in Phase 1 |

---

## Package Structure

```
deep-agent/
├── pyproject.toml                          # Project metadata, build config
├── requirements.txt                        # Pinned runtime dependencies
├── requirements-dev.txt                    # Dev/test dependencies
├── .gitignore
├── .env.example                            # Template for local env vars
├── docker-compose.yml                      # ClickHouse for local dev
├── README.md
├── docs/
│   ├── PRD.md
│   └── IMPLEMENTATION_PLAN.md              # This file
│
├── src/
│   └── deep_agent/
│       ├── __init__.py                     # Package root, version
│       ├── py.typed                        # PEP 561 marker
│       ├── config.py                       # Pydantic Settings for app config
│       │
│       ├── models/                         # Shared data types
│       │   ├── __init__.py
│       │   ├── events.py                   # AgentEvent union (agent_chunk, tool_call, etc.)
│       │   ├── skills.py                   # SkillSummary, SkillMetadata, SkillContent
│       │   ├── sandbox.py                  # ResourceLimits, ExecuteResult
│       │   ├── database.py                 # DatabaseAlias, DatabaseMetadata, ConnectionConfig
│       │   ├── llm.py                      # LLMConfig
│       │   └── context.py                  # TenantContext (stub for Phase 1)
│       │
│       ├── skills/                         # SkillEngine
│       │   ├── __init__.py
│       │   ├── engine.py                   # SkillEngine class
│       │   └── parser.py                   # YAML frontmatter + Markdown parser
│       │
│       ├── runtime/                        # RuntimeAdapter + LLM routing
│       │   ├── __init__.py
│       │   ├── protocol.py                 # RuntimeAdapter Protocol
│       │   ├── langgraph_adapter.py        # LangGraphAdapter (deepagents/langgraph)
│       │   └── llm_router.py              # LLMRouter
│       │
│       ├── sandbox/                        # SandboxManager
│       │   ├── __init__.py
│       │   ├── protocol.py                 # SandboxManager Protocol
│       │   └── subprocess_sandbox.py       # PythonSubprocessSandbox
│       │
│       ├── database/                       # DatabaseRegistry
│       │   ├── __init__.py
│       │   └── registry.py                # DatabaseRegistry + ClickHouse config
│       │
│       ├── tools/                          # LangChain tool definitions
│       │   ├── __init__.py
│       │   ├── execute_code.py             # execute_code tool (wraps SandboxManager)
│       │   └── query_database.py           # query_database tool (wraps DatabaseRegistry)
│       │
│       ├── mcp/                            # MCP adapter integration
│       │   ├── __init__.py
│       │   ├── config.py                   # MCP JSON config loader
│       │   └── manager.py                  # MCPManager: connect, discover tools, lifecycle
│       │
│       ├── orchestrator/                   # Ties everything together
│       │   ├── __init__.py
│       │   └── agent_orchestrator.py       # Build prompt, match skills, run agent
│       │
│       └── api/                            # FastAPI application
│           ├── __init__.py
│           ├── app.py                      # FastAPI app factory
│           ├── ws_chat.py                  # WebSocket /ws/chat endpoint
│           └── schemas.py                  # Pydantic models for WS messages
│
├── skills/                                 # Skill files (Markdown)
│   ├── common/
│   │   └── db-query/
│   │       └── SKILL.md
│   └── equities/
│       └── zscore-monitor/
│           └── SKILL.md
│
├── config/                                 # Tenant configuration files
│   └── tenants/
│       └── equities/
│           └── mcp.json                    # MCP server config for equities tenant
│
├── tests_mcp/                              # Test MCP server (echo/calculator)
│   ├── __init__.py
│   └── echo_server.py                      # Simple MCP server for integration testing
│
├── stubs/                                  # Stub libraries for Phase 1
│   └── firm/
│       ├── __init__.py
│       └── stats.py                        # zscore(), moving_avg()
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                         # Shared fixtures
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── test_skill_parser.py
│   │   ├── test_skill_engine.py
│   │   ├── test_llm_router.py
│   │   ├── test_sandbox.py
│   │   ├── test_database_registry.py
│   │   ├── test_mcp_config.py
│   │   └── test_orchestrator.py
│   ├── integration/
│   │   ├── __init__.py
│   │   ├── test_ws_chat.py
│   │   ├── test_langgraph_adapter.py
│   │   └── test_mcp_manager.py
│   └── e2e/
│       ├── __init__.py
│       └── test_zscore_e2e.py
│
└── scripts/
    ├── run_dev.py                          # Launch dev server
    └── seed_clickhouse.py                  # Seed ch-equities with sample data
```

**Design rationale:**

- **`src/` layout** follows PEP 621; prevents accidental imports of the source tree root.
- **`models/`** has zero internal dependencies — every other module imports from it without circular references.
- **`protocol.py`** files in `runtime/` and `sandbox/` contain only the Protocol (abstract interface), keeping protocol separate from implementation.
- **`tools/`** bridges LangChain tool layer (consumed by `deepagents` / LangGraph) with internal services (sandbox, database). Each tool is a thin wrapper.
- **`mcp/`** encapsulates all MCP integration behind `MCPManager`. The orchestrator depends only on `MCPManager.get_tools()` — never on `langchain-mcp-adapters` directly. This isolates MCP adapter API changes.
- **`orchestrator/`** is the glue layer the API calls. It owns the "build prompt → match skill → discover MCP tools → merge tools → create agent → stream" workflow.
- **`stubs/firm/`** provides a real importable `firm.stats` module with actual math (not mocks), installed into the sandbox PYTHONPATH.

---

## Dependency Graph

```
Week 1: Foundation
  T1.1 Project scaffolding (pyproject.toml, requirements, etc.) ──┐
  T1.2 Shared data models (models/*)                              ├── no deps
  T1.3 Skill parser (skills/parser.py)                            │
                                                                   ▼
  T1.4 SkillEngine (skills/engine.py)         ← depends on T1.2, T1.3
  T1.5 Reference SKILL.md files               ← depends on T1.3 (validation)
  T1.6 Unit tests for skills                  ← depends on T1.4, T1.5

Week 2: Core Services
  T2.1 LLMRouter                              ← depends on T1.2
  T2.2 RuntimeAdapter protocol                ← depends on T1.2
  T2.3 LangGraphAdapter (deepagents)          ← depends on T2.1, T2.2
  T2.4 SandboxManager protocol + subprocess   ← depends on T1.2
  T2.5 firm.stats stubs                       ← no deps
  T2.6 Unit tests for runtime + sandbox       ← depends on T2.3, T2.4

Week 3: Integration Layer + MCP
  T3.1 DatabaseRegistry (ClickHouse)          ← depends on T1.2
  T3.2 execute_code tool                      ← depends on T2.4
  T3.3 query_database tool                    ← depends on T3.1
  T3.6 MCP config loader                      ← depends on T1.2
  T3.7 MCPManager (adapter service)           ← depends on T3.6
  T3.8 Test MCP server (echo/calculator)      ← no deps
  T3.4 AgentOrchestrator                      ← depends on T1.4, T2.3, T3.2, T3.3, T3.7
  T3.5 Unit tests for tools + orchestrator    ← depends on T3.4
  T3.9 MCP unit + integration tests           ← depends on T3.7, T3.8

Week 4: API + E2E
  T4.1 FastAPI app + WebSocket endpoint       ← depends on T3.4
  T4.2 docker-compose + ClickHouse seed       ← depends on T3.1
  T4.3 Integration tests (WS)                 ← depends on T4.1
  T4.4 E2E test: z-score query                ← depends on T4.1, T4.2, T2.5
  T4.5 Dev run script + polish                ← depends on all
```

---

## Week 1: Project Scaffolding, Data Models, and SkillEngine

### T1.1 — Project Scaffolding

**Description:** Set up the Python project with `pyproject.toml` (build metadata), `requirements.txt` / `requirements-dev.txt` (pinned deps for `pip`), `.gitignore`, `.env.example`, and the full directory skeleton with `__init__.py` files. Configure linting (ruff), type checking (mypy), and testing (pytest).

**Files to create:**
- `pyproject.toml`
- `requirements.txt`
- `requirements-dev.txt`
- `.gitignore`
- `.env.example`
- `src/deep_agent/__init__.py`
- `src/deep_agent/py.typed`
- `src/deep_agent/config.py`
- All `__init__.py` files for subpackages: `models`, `skills`, `runtime`, `sandbox`, `database`, `tools`, `mcp`, `orchestrator`, `api`
- `tests/__init__.py`, `tests/conftest.py`
- `tests/unit/__init__.py`, `tests/integration/__init__.py`, `tests/e2e/__init__.py`

**Dependencies:** None (first task).

**Effort:** M

**Acceptance criteria:**
1. `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt -r requirements-dev.txt` succeeds.
2. `pip install -e .` installs the `deep_agent` package in editable mode.
3. `python -c "import deep_agent"` succeeds.
4. `ruff check src/ tests/` passes with zero errors.
5. `mypy src/` passes with zero errors.
6. `pytest` discovers the test skeleton and passes (zero tests collected is OK at this stage).

**Key contents of `requirements.txt`:**
```
fastapi>=0.115
uvicorn[standard]>=0.30
websockets>=12.0
deepagents
langgraph>=0.2
langchain-openai>=0.2
langchain-core>=0.3
openai>=1.50
clickhouse-connect>=0.7
langchain-mcp-adapters>=0.1
mcp>=1.0
pydantic>=2.0
pydantic-settings>=2.0
python-frontmatter>=1.0
matplotlib>=3.9
plotly>=5.22
pandas>=2.2
numpy>=1.26
```

**Key contents of `requirements-dev.txt`:**
```
-r requirements.txt
pytest>=8.0
pytest-asyncio>=0.23
pytest-timeout>=2.2
httpx>=0.27
ruff>=0.5
mypy>=1.10
```

**`config.py`** uses `pydantic-settings` to load from environment: `OPENAI_API_KEY`, `OPENAI_MODEL` (default `gpt-5`), `CLICKHOUSE_HOST`, `CLICKHOUSE_PORT`, `SKILLS_ROOT` (default `skills/`), etc.

---

### T1.2 — Shared Data Models

**Description:** Define all shared data types used across the system as Pydantic models (for serialization/validation) and dataclasses. These live in `src/deep_agent/models/` and have zero internal dependencies.

**Files to create:**
- `src/deep_agent/models/__init__.py` (re-exports)
- `src/deep_agent/models/context.py` — `TenantContext`
- `src/deep_agent/models/skills.py` — `SkillSummary`, `SkillMetadata`, `SkillContent`
- `src/deep_agent/models/sandbox.py` — `ResourceLimits`, `ExecuteResult`
- `src/deep_agent/models/database.py` — `DatabaseAlias`, `DatabaseMetadata`, `TableMeta`, `ConnectionConfig`
- `src/deep_agent/models/llm.py` — `LLMConfig`
- `src/deep_agent/models/events.py` — `AgentEvent` union, `AgentChunkEvent`, `ToolCallEvent`, `ToolResultEvent`, `SkillMatchEvent`, `AgentCompleteEvent`, `ErrorEvent`

**Dependencies:** T1.1

**Effort:** M

**Acceptance criteria:**
1. All models can be instantiated with valid data.
2. All Pydantic models serialize to/from JSON (`.model_dump()` / `.model_validate()`).
3. `TenantContext` has a class method `stub()` returning a hardcoded equities context:
   ```python
   @dataclass
   class TenantContext:
       tenant_id: str
       user_id: str
       skills_dirs: list[str]
       db_aliases: list[str]

       @classmethod
       def stub(cls) -> "TenantContext":
           return cls(
               tenant_id="equities",
               user_id="dev-user",
               skills_dirs=["skills/common", "skills/equities"],
               db_aliases=["ch-equities"],
           )
   ```
4. `AgentEvent` is a discriminated union using Pydantic's `Discriminator` on the `type` field, matching the WebSocket protocol from PRD §4.5.
5. `mypy` passes on all model files.

---

### T1.3 — Skill File Parser

**Description:** Implement a parser that reads a `SKILL.md` file, extracts YAML frontmatter (via `python-frontmatter`), validates required fields, and returns a `SkillContent` object. Pure function with no side effects.

**Files to create:**
- `src/deep_agent/skills/__init__.py`
- `src/deep_agent/skills/parser.py`

**Dependencies:** T1.1, T1.2

**Effort:** S

**Acceptance criteria:**
1. `parse_skill_file(path: Path) -> SkillContent` correctly extracts all frontmatter fields from the reference SKILL.md examples in the PRD.
2. Missing required fields (`name`, `description`, `version`, `tags`, `tenant`, `allowed-tools`) raise `SkillParseError` with a clear message.
3. The `skill_id` is derived from the relative path: `skills/equities/zscore-monitor/SKILL.md` → `skill_id="equities/zscore-monitor"`.
4. The `body` field contains the full Markdown content (everything after frontmatter).
5. Parser handles edge cases: empty body, missing frontmatter delimiters, extra frontmatter fields (ignored gracefully).

---

### T1.4 — SkillEngine

**Description:** Implement the `SkillEngine` class with `discover()`, `match()`, and `load()` methods. Discovery scans the filesystem for `SKILL.md` files. Matching uses tag-based keyword overlap (MVP per PRD). Supports hot reload via cache TTL.

**Files to create:**
- `src/deep_agent/skills/engine.py`

**Dependencies:** T1.2, T1.3

**Effort:** M

**Acceptance criteria:**
1. `SkillEngine(skills_root=Path("skills/"), cache_ttl=300)` scans and indexes all `SKILL.md` files on first call.
2. `discover(tenant)` returns `SkillSummary` objects for skills in `common/` and the tenant's directory. Skills from other tenants are excluded.
3. `match(query, tenant, top_k=5)` returns skills ranked by tag overlap with query tokens. For "z-scores for AAPL volume", the zscore-monitor skill ranks first.
4. `load(skill_id, tenant)` returns full `SkillContent` including body. Raises `SkillNotFoundError` if skill does not exist or tenant lacks access.
5. Cache invalidation: after `cache_ttl` seconds, the next call re-scans the filesystem (hot reload).
6. Thread-safe: cache is guarded by a lock for concurrent access.

**Match algorithm (tag-based):**
```
score(skill, query) = |skill.tags ∩ query_tokens| / |skill.tags|
```
Where `query_tokens` = set of lowercase words from the query. Sufficient for Phase 1's small skill set.

---

### T1.5 — Reference SKILL.md Files

**Description:** Create the two reference skill files from the PRD (§5.3.1 and §5.4). Verbatim from PRD with minor formatting cleanup.

**Files to create:**
- `skills/common/db-query/SKILL.md`
- `skills/equities/zscore-monitor/SKILL.md`

**Dependencies:** T1.3 (to validate parsing)

**Effort:** S

**Acceptance criteria:**
1. Both files parse successfully with the skill parser from T1.3.
2. `db-query` has `tenant: common` and `skill_id: common/db-query`.
3. `zscore-monitor` has `tenant: equities` and `skill_id: equities/zscore-monitor`.
4. Frontmatter matches PRD spec (tags, allowed-tools, inputs, quality).

---

### T1.6 — Unit Tests for Skills Layer

**Description:** Write unit tests covering the parser, engine discovery, matching, and loading.

**Files to create:**
- `tests/unit/__init__.py`
- `tests/unit/test_skill_parser.py`
- `tests/unit/test_skill_engine.py`

**Dependencies:** T1.4, T1.5

**Effort:** M

**Acceptance criteria:**
1. Parser tests: valid file, missing fields, malformed frontmatter, empty body.
2. Engine discover tests: correct filtering by tenant, includes common skills.
3. Engine match tests: "z-scores for AAPL volume" ranks zscore-monitor first; "query database" ranks db-query first.
4. Engine load tests: valid load, access denied for wrong tenant, skill not found.
5. Cache tests: verify hot reload after TTL expiry (mock time or use short TTL).
6. All pass with `pytest tests/unit/`.

---

## Week 2: LLM Router, RuntimeAdapter, and Sandbox

### T2.1 — LLMRouter

**Description:** Implement the `LLMRouter` class. Phase 1 is single-provider (OpenAI GPT-5 only). The router resolves an `LLMConfig` from tenant context and optional task hint. Configuration from `config.py`.

**Files to create:**
- `src/deep_agent/runtime/__init__.py`
- `src/deep_agent/runtime/llm_router.py`

**Dependencies:** T1.2

**Effort:** S

**Acceptance criteria:**
1. `LLMRouter(config).resolve(tenant, task_hint=None)` returns `LLMConfig` with `model="gpt-5"`, `provider="openai"`.
2. Model name and provider are configurable via `config.py` / environment variables.
3. `task_hint` parameter is accepted but ignored in Phase 1 (placeholder for future routing).
4. Returns consistent `LLMConfig` with `model`, `temperature`, `max_tokens`, `provider` fields.

---

### T2.2 — RuntimeAdapter Protocol

**Description:** Define the `RuntimeAdapter` protocol exactly as specified in the PRD. Also define the `Agent` and `AgentResponse` types it depends on.

**Files to create:**
- `src/deep_agent/runtime/protocol.py`

**Dependencies:** T1.2

**Effort:** S

**Acceptance criteria:**
1. `RuntimeAdapter` is a `typing.Protocol` with `create_agent`, `invoke`, and `stream` methods matching PRD signatures.
2. `Agent` is defined as a type alias (wraps the compiled graph in Phase 1).
3. `AgentResponse` carries `content: str`, `tool_calls: list`, `tokens_used: int`.
4. Protocol passes `mypy` strict checking.

---

### T2.3 — LangGraphAdapter (deepagents + langgraph)

**Description:** Implement `LangGraphAdapter` conforming to `RuntimeAdapter`. Primary approach: use `deepagents.create_deep_agent()` to build the agent graph. Fallback: use `langgraph.prebuilt.create_react_agent` if `deepagents` doesn't support clean tool override. The `stream()` method yields `AgentEvent` objects from the graph's async stream.

**Files to create:**
- `src/deep_agent/runtime/langgraph_adapter.py`

**Dependencies:** T2.1, T2.2, T1.2

**Effort:** L

**Acceptance criteria:**
1. `create_agent(model, tools, system_prompt)` attempts `deepagents.create_deep_agent()` first with the specified model (via `langchain-openai`'s `ChatOpenAI`) and tools. If `deepagents` raises or doesn't support tool override, falls back to `langgraph.prebuilt.create_react_agent`.
2. `invoke(agent, message, context)` runs the graph synchronously and returns `AgentResponse`.
3. `stream(agent, message, context)` is an `AsyncIterator[AgentEvent]` that yields:
   - `AgentChunkEvent` for each LLM token.
   - `ToolCallEvent` when a tool call is initiated.
   - `ToolResultEvent` when a tool returns.
   - `AgentCompleteEvent` when the graph reaches the end.
4. Errors during execution are caught and yielded as `ErrorEvent`.
5. The adapter is stateless — all state lives in the graph instance.
6. A module-level `USING_DEEPAGENTS: bool` flag indicates which backend is active, logged on startup.

**Implementation strategy:**
```python
try:
    from deepagents import create_deep_agent
    USING_DEEPAGENTS = True
except ImportError:
    USING_DEEPAGENTS = False

from langgraph.prebuilt import create_react_agent  # always available as fallback
from langchain_openai import ChatOpenAI

class LangGraphAdapter:
    def create_agent(self, model, tools, system_prompt, **kwargs):
        llm = ChatOpenAI(model=model, temperature=kwargs.get("temperature", 0.1))
        if USING_DEEPAGENTS:
            try:
                return create_deep_agent(model=llm, tools=tools, system_prompt=system_prompt)
            except Exception:
                pass  # fall through to langgraph
        return create_react_agent(llm, tools, prompt=system_prompt)
```

**Key risk:** Streaming event mapping. LangGraph's stream modes (`messages`, `custom`, `updates`) may not map 1:1 to the PRD's event types. The adapter's `stream()` is responsible for this translation — plan to spend time experimenting with LangGraph stream modes.

---

### T2.4 — SandboxManager Protocol + PythonSubprocessSandbox

**Description:** Define the `SandboxManager` protocol and implement `PythonSubprocessSandbox`. Spawns a Python subprocess in a temp directory, applies resource limits via the `resource` module, captures stdout/stderr, and collects output files from `/output/`.

**Files to create:**
- `src/deep_agent/sandbox/__init__.py`
- `src/deep_agent/sandbox/protocol.py`
- `src/deep_agent/sandbox/subprocess_sandbox.py`

**Dependencies:** T1.2

**Effort:** L

**Acceptance criteria:**
1. `SandboxManager` protocol has `execute()` and `cleanup()` per PRD §4.2.
2. `PythonSubprocessSandbox.execute(code, timeout, resource_limits, env, files_in)`:
   - Creates a temp directory with `code.py` and `output/` subdirectory.
   - If `files_in` provided, writes those files into the temp directory.
   - Spawns `python3 code.py` as a subprocess with `env` vars injected.
   - Applies timeout via `asyncio.wait_for`.
   - Applies memory limit via `resource.RLIMIT_AS` in a `preexec_fn` (Linux only).
   - Captures stdout and stderr (truncated to `max_output_bytes`).
   - Reads all files from `output/` into `ExecuteResult.output_files`.
   - Returns `ExecuteResult` with `execution_id` (UUID), `exit_code`, `duration_ms`.
3. `cleanup(execution_id)` removes the temp directory.
4. Timeout produces `exit_code != 0` and stderr containing timeout info.
5. Code that exceeds memory limit is killed with appropriate error.
6. Code that writes to `/output/chart.png` has that file in `output_files`.
7. The `stubs/` directory is added to `PYTHONPATH` in the subprocess environment so sandbox code can `import firm.stats`.

---

### T2.5 — firm.stats Stubs

**Description:** Create a stub implementation of the `firm.stats` library with real math using pandas/numpy. Sandbox code can `import firm.stats` and get working results.

**Files to create:**
- `stubs/firm/__init__.py`
- `stubs/firm/stats.py`

**Dependencies:** None

**Effort:** S

**Acceptance criteria:**
1. `from firm.stats import zscore, moving_avg` works.
2. `moving_avg(series, window)` computes rolling mean via `pandas.Series.rolling().mean()`.
3. `zscore(series, window)` computes `(x - rolling_mean) / rolling_std` per point.
4. Both accept `pandas.Series` and return `pandas.Series`.
5. Edge cases: window larger than series length returns NaN for early values.
6. The module is usable by adding `stubs/` to `PYTHONPATH`.

---

### T2.6 — Unit Tests for Runtime and Sandbox

**Description:** Write unit tests for LLMRouter, RuntimeAdapter protocol conformance, and PythonSubprocessSandbox.

**Files to create:**
- `tests/unit/test_llm_router.py`
- `tests/unit/test_sandbox.py`

**Dependencies:** T2.1, T2.3, T2.4

**Effort:** M

**Acceptance criteria:**
1. LLMRouter tests: resolve returns correct model, config override works.
2. Sandbox tests:
   - Simple code execution (`print("hello")`) returns stdout `"hello\n"`.
   - Code that writes a file to `/output/` has that file in `output_files`.
   - Timeout: code with `time.sleep(100)` is killed within timeout.
   - Error: code with syntax error returns `exit_code != 0` with stderr.
   - Env var injection: code reading `os.environ["TEST_VAR"]` gets the injected value.
3. LangGraphAdapter tests: mock the LLM, verify `invoke` and `stream` produce correct event types (no real OpenAI calls).
4. All pass with `pytest tests/unit/`.

---

## Week 3: Database, Tools, MCP, and Orchestrator

### T3.1 — DatabaseRegistry (ClickHouse)

**Description:** Implement `DatabaseRegistry` with a single ClickHouse alias (`ch-equities`). Configuration from `config.py` / environment variables. Provides schema metadata and connection config.

**Files to create:**
- `src/deep_agent/database/__init__.py`
- `src/deep_agent/database/registry.py`

**Dependencies:** T1.2

**Effort:** M

**Acceptance criteria:**
1. `list_aliases(tenant)` returns `[DatabaseAlias(alias="ch-equities", engine="clickhouse", description="Equities fundamentals — daily OHLCV, splits, dividends")]` for the equities tenant.
2. `get_metadata("ch-equities", tenant)` returns `DatabaseMetadata` with table `fundamentals_daily` and columns: `date Date, symbol String, open Float64, high Float64, low Float64, close Float64, volume UInt64, pe_ratio Nullable(Float64)`. Schema metadata is hardcoded in Phase 1.
3. `get_connection("ch-equities", tenant)` returns `ConnectionConfig` with host/port/database from environment variables. `credentials_ref` points to env var names.
4. Raises `AliasNotFoundError` for unknown aliases.
5. Tenant scoping: only aliases registered for the given tenant are accessible.

---

### T3.2 — execute_code Tool

**Description:** LangChain-compatible tool wrapping `SandboxManager.execute()`. Handles env var injection for database credentials and returns formatted results including base64-encoded output files.

**Files to create:**
- `src/deep_agent/tools/__init__.py`
- `src/deep_agent/tools/execute_code.py`

**Dependencies:** T2.4

**Effort:** M

**Acceptance criteria:**
1. Tool defined using `@tool` decorator from `langchain_core.tools` with proper name, description, and input schema.
2. Tool name: `execute_code`; input schema: `code: str`, optional `timeout: int`.
3. When invoked, calls `sandbox.execute(code, timeout, env=db_env_vars)` where `db_env_vars` are injected from `DatabaseRegistry` connection config.
4. Return value includes stdout, stderr, exit_code, and base64-encoded output files.
5. Errors (timeout, crash) returned as tool output (not raised as exceptions) so the agent can react.

---

### T3.3 — query_database Tool

**Description:** LangChain-compatible tool providing database schema information. The agent uses this to understand tables/columns before writing code. Metadata only — no query execution.

**Files to create:**
- `src/deep_agent/tools/query_database.py`

**Dependencies:** T3.1

**Effort:** S

**Acceptance criteria:**
1. Tool name: `query_database`; input schema: `alias: str`, `action: Literal["list_aliases", "get_schema"]`.
2. `action="list_aliases"` returns available database aliases with descriptions.
3. `action="get_schema"` returns table names, column names, and types as formatted text.
4. Does NOT execute queries — that is done via `execute_code`.
5. Unknown alias returns a clear error message.

---

### T3.4 — AgentOrchestrator

**Description:** Central coordinator tying SkillEngine, LLMRouter, RuntimeAdapter, MCP, and tools together. Given a user message and tenant context: (1) discovers skills, (2) matches relevant skills, (3) discovers MCP tools, (4) merges tool sets filtered by skill `allowed_tools`, (5) builds system prompt, (6) creates agent with merged tools, (7) streams response.

**Files to create:**
- `src/deep_agent/orchestrator/__init__.py`
- `src/deep_agent/orchestrator/agent_orchestrator.py`

**Dependencies:** T1.4, T2.3, T3.2, T3.3, T3.7

**Effort:** L

**Acceptance criteria:**
1. Constructor takes `SkillEngine`, `LLMRouter`, `RuntimeAdapter`, `SandboxManager`, `DatabaseRegistry`, `MCPManager` (optional).
2. `async def handle_message(message, context) -> AsyncIterator[AgentEvent]`:
   - Calls `skill_engine.discover(context)` for available skills.
   - Calls `skill_engine.match(message, context)` for relevant skills.
   - Yields `SkillMatchEvent` for the top match.
   - Loads matched skill body via `skill_engine.load()`.
   - If `MCPManager` is provided, calls `mcp_manager.get_tools()` to discover MCP-provided tools.
   - Merges built-in tools (`execute_code`, `query_database`) with MCP-discovered tools.
   - Filters merged tool set by matched skill's `allowed_tools` list — a tool is available only if the skill permits it.
   - Builds system prompt with: base instructions, skill summaries, matched skill body, database metadata.
   - Creates agent via `runtime.create_agent(model, merged_tools, system_prompt)`.
   - Streams via `runtime.stream()` and yields each event.
3. System prompt follows PRD's progressive disclosure: all skill summaries + full body of matched skills.
4. MCP tools are included in the system prompt's tool descriptions so the LLM knows they exist.
5. If `MCPManager` is `None` or no MCP servers configured, orchestrator works with built-in tools only (graceful degradation).
6. If no skills match, agent runs with base instructions and all tools (built-in + MCP).

**System prompt template:**
```
You are Deep Agent, an AI assistant for the {tenant} desk.

## Available Skills
{for each summary: "- {name}: {description}"}

## Active Skill: {matched_skill.name}
{matched_skill.body}

## Available Databases
{for each alias: "- {alias} ({engine}): {description}"}
{schema details for relevant aliases}

## Tool Usage
- Use `query_database` to discover schema before writing queries.
- Use `execute_code` to run Python code in a sandboxed environment.
- Database credentials are available as env vars: DB_HOST, DB_PORT, DB_USER, DB_PASS.
- Save output files (charts, CSVs) to /output/ in your code.
```

---

### T3.5 — Unit Tests for Tools and Orchestrator

**Description:** Unit tests for tool wrappers and orchestrator's prompt building and skill matching logic.

**Files to create:**
- `tests/unit/test_database_registry.py`
- `tests/unit/test_orchestrator.py`

**Dependencies:** T3.4

**Effort:** M

**Acceptance criteria:**
1. DatabaseRegistry tests: list aliases, get metadata, get connection, alias not found, tenant scoping.
2. Orchestrator tests (with mocked dependencies):
   - System prompt contains skill summaries and matched skill body.
   - Tools are filtered by matched skill's `allowed_tools`.
   - `SkillMatchEvent` yielded before agent events.
   - Error handling when no skills match.
3. All pass with mocked RuntimeAdapter (no real LLM calls).

---

### T3.6 — MCP Config Loader

**Description:** Implement a loader that reads per-tenant MCP configuration from a JSON file at `config/tenants/{tenant_id}/mcp.json`. The config specifies MCP servers with their transport type (`stdio` or `sse`), connection details, and environment variables. Phase 1 supports a single tenant (`equities`) with a single config file.

**Files to create:**
- `src/deep_agent/mcp/__init__.py`
- `src/deep_agent/mcp/config.py`
- `config/tenants/equities/mcp.json` (example config for testing)

**Dependencies:** T1.2

**Effort:** S

**Acceptance criteria:**
1. `MCPServerConfig` Pydantic model with fields: `name: str`, `transport: Literal["stdio", "sse"]`, `command: list[str] | None` (for stdio), `url: str | None` (for SSE), `env: dict[str, str]` (optional env vars).
2. `MCPConfig` model with `servers: list[MCPServerConfig]`.
3. `load_mcp_config(tenant: TenantContext) -> MCPConfig` reads from `config/tenants/{tenant_id}/mcp.json`.
4. Returns an empty `MCPConfig(servers=[])` if the config file does not exist (graceful degradation).
5. Validates the JSON structure — raises `MCPConfigError` with a clear message on malformed input.
6. Example `config/tenants/equities/mcp.json`:
   ```json
   {
     "servers": [
       {
         "name": "echo-test",
         "transport": "stdio",
         "command": ["python", "-m", "tests_mcp.echo_server"]
       }
     ]
   }
   ```

---

### T3.7 — MCPManager (Adapter Service)

**Description:** Implement `MCPManager` which uses `langchain-mcp-adapters` to connect to MCP servers, discover their tools, and expose them as LangChain-compatible tools. Manages the lifecycle of MCP server connections (connect on session start, disconnect on session end).

**Files to create:**
- `src/deep_agent/mcp/manager.py`

**Dependencies:** T3.6

**Effort:** M

**Acceptance criteria:**
1. `MCPManager.__init__(config: MCPConfig)` stores the server config.
2. `async def connect()` establishes connections to all configured MCP servers using `langchain-mcp-adapters`:
   - For `stdio` transport: launches the server process and connects via stdin/stdout.
   - For `sse` transport: connects to the SSE URL.
3. `async def get_tools() -> list[Tool]` returns all LangChain `BaseTool` instances discovered from connected MCP servers. Tools are cached after first discovery within a session.
4. `async def disconnect()` cleanly shuts down all MCP server connections and processes.
5. If a server fails to connect, logs a warning and continues with remaining servers (partial availability).
6. If `langchain-mcp-adapters` is not installed, `MCPManager` logs a warning and `get_tools()` returns an empty list (graceful degradation).

**Implementation approach:**
```python
from langchain_mcp_adapters.client import MultiServerMCPClient

class MCPManager:
    async def connect(self):
        server_params = {}
        for server in self.config.servers:
            if server.transport == "stdio":
                server_params[server.name] = {
                    "command": server.command[0],
                    "args": server.command[1:],
                    "transport": "stdio",
                    "env": server.env or {},
                }
            elif server.transport == "sse":
                server_params[server.name] = {
                    "url": server.url,
                    "transport": "sse",
                }
        self._client = MultiServerMCPClient(server_params)
        await self._client.__aenter__()
        self._tools = self._client.get_tools()

    async def get_tools(self) -> list:
        return self._tools if self._tools else []

    async def disconnect(self):
        if self._client:
            await self._client.__aexit__(None, None, None)
```

---

### T3.8 — Test MCP Server (Echo/Calculator)

**Description:** Create a simple MCP server for integration testing. The server exposes 2-3 trivial tools (e.g., `echo`, `add`, `multiply`) via the MCP protocol using the `mcp` Python SDK. This server is used only in tests — it validates that the MCPManager correctly discovers and invokes MCP-provided tools.

**Files to create:**
- `tests_mcp/__init__.py`
- `tests_mcp/echo_server.py`

**Dependencies:** None

**Effort:** S

**Acceptance criteria:**
1. `echo_server.py` is a valid MCP server runnable via `python -m tests_mcp.echo_server`.
2. Exposes tools:
   - `echo(message: str) -> str` — returns the input message.
   - `add(a: float, b: float) -> float` — returns `a + b`.
   - `multiply(a: float, b: float) -> float` — returns `a * b`.
3. Uses `stdio` transport (reads from stdin, writes to stdout).
4. Built using the `mcp` Python SDK (`from mcp.server import Server`).
5. Server starts, serves tool discovery and invocation requests, and exits cleanly on disconnect.

---

### T3.9 — MCP Unit and Integration Tests

**Description:** Write tests covering MCP config loading, MCPManager lifecycle, tool discovery, and tool invocation via the test MCP server.

**Files to create:**
- `tests/unit/test_mcp_config.py`
- `tests/integration/test_mcp_manager.py`

**Dependencies:** T3.7, T3.8

**Effort:** M

**Acceptance criteria:**
1. Config loader tests:
   - Valid JSON parses to `MCPConfig` with correct server entries.
   - Missing file returns empty config (no error).
   - Malformed JSON raises `MCPConfigError`.
   - Validates required fields per transport type (`command` for stdio, `url` for SSE).
2. MCPManager integration tests (using the test echo server):
   - `connect()` successfully starts the echo server process and discovers 3 tools.
   - `get_tools()` returns LangChain `BaseTool` instances with correct names (`echo`, `add`, `multiply`).
   - Invoking the `add` tool with `(2, 3)` returns `5`.
   - `disconnect()` cleanly shuts down the server process.
   - Graceful degradation: config with a non-existent server command logs a warning and returns partial tools.
3. All unit tests pass with `pytest tests/unit/test_mcp_config.py`.
4. Integration tests pass with `pytest tests/integration/test_mcp_manager.py`.

---

## Week 4: WebSocket API, Seed Data, and E2E Test

### T4.1 — FastAPI Application + WebSocket Chat Endpoint

**Description:** FastAPI application with WebSocket endpoint at `/ws/chat`. Receives `user_message` events, passes to `AgentOrchestrator`, streams back agent events. No auth in Phase 1 — connections accepted with stub tenant context.

**Files to create:**
- `src/deep_agent/api/__init__.py`
- `src/deep_agent/api/app.py`
- `src/deep_agent/api/ws_chat.py`
- `src/deep_agent/api/schemas.py`

**Dependencies:** T3.4

**Effort:** L

**Acceptance criteria:**
1. `app.py` creates a FastAPI application with:
   - Health check `GET /health` → `{"status": "ok"}`.
   - WebSocket endpoint at `/ws/chat`.
   - Startup event initializing all components.
2. `ws_chat.py` handles WebSocket lifecycle:
   - On connect: accept, create stub `TenantContext`.
   - On `user_message`: pass to orchestrator, stream events back as JSON.
   - On disconnect: cleanup.
   - On error: send `error` event (do not close for recoverable errors).
3. `schemas.py` defines Pydantic models for all WS message types per PRD §4.5:
   - Client → server: `UserMessage` (type, content, session_id).
   - Server → client: `AgentChunk`, `ToolCall`, `ToolResult`, `SkillMatch`, `AgentComplete`, `Error`.
4. In-memory session management: each connection gets a session_id, conversation history in a dict.
5. Multiple concurrent WebSocket connections supported.
6. Starts with `uvicorn deep_agent.api.app:create_app --factory`.

---

### T4.2 — Docker Compose + ClickHouse Seed Script

**Description:** Create `docker-compose.yml` for local ClickHouse and a seed script that populates sample `fundamentals_daily` data for `ch-equities`.

**Files to create:**
- `docker-compose.yml`
- `scripts/seed_clickhouse.py`

**Dependencies:** T3.1

**Effort:** M

**Acceptance criteria:**
1. `docker-compose.yml` defines a ClickHouse service on port 8123 (HTTP) / 9000 (native), with a volume for data persistence.
2. `docker compose up -d` starts ClickHouse and it accepts connections.
3. Seed script connects via env vars (`CLICKHOUSE_HOST`, etc.).
4. Creates `fundamentals_daily` table if not exists with schema: `date Date, symbol String, open Float64, high Float64, low Float64, close Float64, volume UInt64, pe_ratio Nullable(Float64)`.
5. Inserts 180 days of synthetic OHLCV data for AAPL (and optionally MSFT, GOOG) using seeded random walks for reproducibility.
6. Volume data includes deliberate outliers (z-score > 2) so zscore-monitor can find them.
7. Script is idempotent (safe to re-run).
8. Runs with `python scripts/seed_clickhouse.py`.

---

### T4.3 — Integration Tests (WebSocket)

**Description:** Integration tests that start FastAPI, connect via WebSocket, send a `user_message`, and verify the event stream. Uses a mocked LLM.

**Files to create:**
- `tests/integration/__init__.py`
- `tests/integration/test_ws_chat.py`
- `tests/integration/test_langgraph_adapter.py`

**Dependencies:** T4.1

**Effort:** M

**Acceptance criteria:**
1. WebSocket test uses `httpx` / FastAPI `TestClient` with WebSocket support.
2. Sends `{"type": "user_message", "content": "hello", "session_id": "test-1"}` and receives at least one `agent_chunk` and one `agent_complete`.
3. Verifies event sequence: optional `skill_match` → one or more `agent_chunk` → `agent_complete`.
4. Invalid JSON produces an `error` event.
5. LangGraph adapter integration test: real agent graph with mock tool, verify tool_call and tool_result events stream correctly.
6. All pass with `pytest tests/integration/`.

---

### T4.4 — End-to-End Test: Z-Score Query

**Description:** Capstone deliverable proving the full pipeline. User asks "Show me z-scores for AAPL volume" via WebSocket → agent matches zscore-monitor skill → queries ClickHouse → executes Python with `firm.stats` in sandbox → returns table + chart.

**Files to create:**
- `tests/e2e/__init__.py`
- `tests/e2e/test_zscore_e2e.py`

**Dependencies:** T4.1, T4.2, T2.5

**Effort:** L

**Acceptance criteria:**
1. Requires a real OpenAI API key and running ClickHouse with seeded data. Marked `@pytest.mark.e2e` (skippable in CI without credentials).
2. Test flow:
   1. Start FastAPI app.
   2. Connect via WebSocket.
   3. Send `{"type": "user_message", "content": "Show me z-scores for AAPL volume", "session_id": "e2e-1"}`.
   4. Collect all events until `agent_complete`.
3. Assertions:
   - At least one `skill_match` event with `skill_id` containing `zscore-monitor`.
   - At least one `tool_call` event with `tool="execute_code"`.
   - At least one `tool_result` event with stdout containing z-score values.
   - At least one `tool_result` event with `chart.png` in files (base64-encoded).
   - An `agent_complete` event.
4. Total time from send to `agent_complete` under 60 seconds.
5. No `error` events in the stream.

---

### T4.5 — Dev Run Script and Polish

**Description:** Development run script, finalize README with setup instructions, ensure all components wire together cleanly.

**Files to create/modify:**
- `scripts/run_dev.py`
- `README.md` (update)

**Dependencies:** All previous tasks.

**Effort:** M

**Acceptance criteria:**
1. `scripts/run_dev.py`:
   - Validates required env vars are set (or loads `.env`).
   - Starts uvicorn with hot reload.
   - Prints connection info (`ws://localhost:8000/ws/chat`).
2. `README.md` includes:
   - Prerequisites (Python 3.12, Docker, ClickHouse).
   - Setup steps (`python -m venv .venv`, `pip install`, env vars, seed script).
   - How to run the dev server.
   - How to run tests (unit, integration, e2e).
   - Architecture overview referencing the PRD.
3. All imports clean — no circular dependencies.
4. `ruff check src/ tests/` passes.
5. `mypy src/` passes.

---

## Summary Table

| Week | Task | Description | Effort | Dependencies |
|------|------|-------------|--------|--------------|
| 1 | T1.1 | Project scaffolding (pyproject.toml, requirements, skeleton) | M | None |
| 1 | T1.2 | Shared data models (models/*) | M | T1.1 |
| 1 | T1.3 | Skill file parser | S | T1.1, T1.2 |
| 1 | T1.4 | SkillEngine (discover, match, load) | M | T1.2, T1.3 |
| 1 | T1.5 | Reference SKILL.md files | S | T1.3 |
| 1 | T1.6 | Unit tests — skills layer | M | T1.4, T1.5 |
| 2 | T2.1 | LLMRouter (GPT-5 only) | S | T1.2 |
| 2 | T2.2 | RuntimeAdapter protocol | S | T1.2 |
| 2 | T2.3 | LangGraphAdapter (deepagents + langgraph fallback) | L | T2.1, T2.2 |
| 2 | T2.4 | SandboxManager protocol + PythonSubprocessSandbox | L | T1.2 |
| 2 | T2.5 | firm.stats stubs | S | None |
| 2 | T2.6 | Unit tests — runtime + sandbox | M | T2.3, T2.4 |
| 3 | T3.1 | DatabaseRegistry (ClickHouse) | M | T1.2 |
| 3 | T3.2 | execute_code tool | M | T2.4 |
| 3 | T3.3 | query_database tool | S | T3.1 |
| 3 | T3.6 | MCP config loader | S | T1.2 |
| 3 | T3.7 | MCPManager (adapter service) | M | T3.6 |
| 3 | T3.8 | Test MCP server (echo/calculator) | S | None |
| 3 | T3.4 | AgentOrchestrator (with MCP tool merging) | L | T1.4, T2.3, T3.2, T3.3, T3.7 |
| 3 | T3.5 | Unit tests — tools + orchestrator | M | T3.4 |
| 3 | T3.9 | MCP unit + integration tests | M | T3.7, T3.8 |
| 4 | T4.1 | FastAPI app + WebSocket endpoint | L | T3.4 |
| 4 | T4.2 | docker-compose + ClickHouse seed script | M | T3.1 |
| 4 | T4.3 | Integration tests (WebSocket) | M | T4.1 |
| 4 | T4.4 | E2E test — z-score query | L | T4.1, T4.2, T2.5 |
| 4 | T4.5 | Dev run script + polish | M | All |

**Effort breakdown:** 7S + 12M + 5L = ~156 engineer-hours (~3.9 FTE-weeks for one engineer, comfortable for 2 engineers over 4 weeks with parallelization).

---

## Parallelization Opportunities

Within each week, tasks can be split across two engineers:

- **Week 1:** T1.1 first. Then T1.2 + T1.3 in parallel. Then T1.4 + T1.5 in parallel. T1.6 after both land.
- **Week 2:** T2.1 + T2.2 + T2.4 + T2.5 all in parallel (share only T1.2 as dep). T2.3 waits for T2.1 + T2.2.
- **Week 3:** T3.1 + T3.6 + T3.8 start immediately in parallel. T3.2 + T3.3 + T3.7 in second wave. T3.4 waits for T3.2, T3.3, T3.7. T3.5 + T3.9 can run in parallel after their deps land.
- **Week 4:** T4.1 + T4.2 in parallel. T4.3 + T4.4 wait for T4.1.

---

## Risks and Mitigations

| # | Risk | Impact | Mitigation |
|---|------|--------|------------|
| 1 | **`deepagents` API instability or limited tool override** | Blocks agent creation with custom tools | `RuntimeAdapter` insulates us. Fallback to `langgraph.prebuilt.create_react_agent` is built into T2.3. Both produce a compiled graph with `.astream()`. |
| 2 | **Streaming event mapping** | LangGraph stream modes may not map 1:1 to PRD event types | `LangGraphAdapter.stream()` owns the translation. Budget time in T2.3 to experiment with `stream_mode` options. |
| 3 | **Subprocess sandbox `resource` module Linux-only** | `RLIMIT_AS` behaves differently on macOS | Target Linux (deployment platform). Document macOS limitations in README. CI runs on Linux. |
| 4 | **ClickHouse availability for E2E** | E2E test requires running ClickHouse | `docker-compose.yml` in T4.2. E2E tests marked `@pytest.mark.e2e` and skippable. |
| 5 | **LLM non-determinism in E2E** | Agent may generate different code each run | Assert on structural properties (events contain tool calls, output files exist) not exact content. |
| 6 | **`langchain-mcp-adapters` API changes** | MCP integration is relatively new; API may shift | `MCPManager` encapsulates all adapter calls. If the API changes, only `manager.py` needs updating. Test MCP server validates the integration independently. |
| 7 | **MCP server process management** | stdio-transport servers are child processes; leaked processes on crash | `MCPManager.disconnect()` in a `finally` block. Integration tests verify clean shutdown. Subprocess timeout as safety net. |

---

*End of Phase 1 Implementation Plan.*
