# Example Rewrite Specification

## Overview

This spec defines the complete rewrite of the `examples/` directory. The previous
example (`run_example.py`) directly called `calculate_var()`, bypassing the entire
deep-agent framework. The new example exercises the full pipeline end-to-end:

**WebSocket API -> Session Management -> Agent Resolution -> Skill Orchestration -> Sandbox Execution**

All without requiring an LLM API key.

---

## Requirements

The example MUST demonstrate:

1. **WebSocket API** — Connect via the FastAPI WebSocket endpoint
2. **Agent resolution** — Load `risk-desk-agent` from agent config YAML
3. **Tenant context** — Tenant-based config loading with resource env vars
4. **Skill orchestration** — Orchestrator selects skill by tag-based matching
5. **Multi-turn sessions** — Conversation history persists across turns
6. **Sandbox execution** — Code runs in a subprocess with env var injection
7. **PYTHONPATH injection** — Skill scripts dir available to sandbox code
8. **Mock LLM** — `ScriptedRuntime` replays code blocks (CI-safe, no API key)

---

## File Structure

```
examples/
├── __init__.py                        # Package marker (unchanged)
├── __main__.py                        # python -m examples entry point
├── README.md                          # Documentation
├── run.py                             # Main demo: server + WebSocket client
├── scripted_runtime.py                # Mock RuntimeAdapter (no LLM needed)
├── display.py                         # ANSI-colored event pretty-printer
├── seed_data.py                       # Seeds SQLite (unchanged)
├── agents/
│   └── risk-desk-agent.yaml           # Agent -> skill bindings
├── tenants/
│   └── risk/
│       └── resources.yaml             # DB_PATH env var mapping
└── skills/
    └── risk/
        └── portfolio-var/
            ├── SKILL.md               # Skill definition
            └── scripts/
                ├── risk_calc.py       # VaR calculation module
                └── requirements.txt   # Script dependencies
```

### Deleted Files

All of these were removed in the rewrite:

- `examples/run_example.py` — old standalone script that bypassed the framework
- `examples/mock_runtime.py` — replaced by `scripted_runtime.py`
- `examples/mock_mcp_server.py` — MCP not needed for demo
- `examples/docker-compose.yml` — not needed
- `examples/database/` — ORM layer not used
- `examples/tools/` — tools created by framework, not manually
- `examples/output/` — generated artifacts
- `examples/tests/` — empty
- `examples/tenants/risk/mcp.json` — MCP not needed
- `examples/skills/data-query/` — db-query skill not in demo
- `examples/skills/equities/` — zscore skill not in demo
- `examples/skills/risk/portfolio-var/assets/` — empty
- `examples/skills/risk/portfolio-var/references/` — empty

---

## Design Decisions

### 1. Real Server (not TestClient)

The demo starts a real uvicorn server in a daemon thread on `127.0.0.1` with a
random port. This is more impressive than `httpx.AsyncClient` — it shows actual
network usage and exercises the full ASGI lifecycle.

### 2. WebSocket Client

Uses the `websockets` library (already a project dependency). The client connects
to `/ws/chat?tenant_id=risk&agent_id=risk-desk-agent` and sends/receives JSON
messages over the same connection for both turns.

### 3. ScriptedRuntime (Mock LLM)

`ScriptedRuntime` maps turn numbers to predetermined Python code blocks. It
implements the `RuntimeAdapter` protocol identically to `LangGraphAdapter`, but
instead of calling an LLM, it replays the next script in its list.

Pattern follows `DeterministicRuntime` from `tests/e2e/test_pipeline_e2e.py`.

On each `stream()` call:
1. Selects `self._scripts[self._turn]`
2. Finds `execute_code` tool from `agent["tools"]`
3. Yields `ToolCallEvent(tool="execute_code", input={"code": code})`
4. Calls `await tool.ainvoke({"code": code})` — runs in the real sandbox
5. Parses JSON result, yields `ToolResultEvent` with stdout
6. Yields `AgentChunkEvent` with summary text
7. Yields `AgentCompleteEvent`
8. Increments turn counter

### 4. Multi-Turn

Turn 1 computes 95% VaR; Turn 2 computes 99% VaR. Both use the same WebSocket
connection. The session manager keeps message history, proving multi-turn works.

### 5. No MCP

MCP is skipped — it adds complexity without showcasing the core pipeline. The
skill instructions say to generate synthetic returns instead.

### 6. Self-Contained Config

The `examples/` directory serves as both `config_root` (for agents/ and tenants/)
and `SKILLS_ROOT` (for skills/). This makes the example completely self-contained,
independent of the project-root `config/` and `skills/` directories.

---

## Pipeline Flow

```
python -m examples.run
  -> seed SQLite (/tmp/portfolio.db)
  -> create_app(settings, config_root=examples/, runtime=ScriptedRuntime)
  -> start uvicorn on 127.0.0.1:{random_port}
  -> websockets.connect("ws://127.0.0.1:{port}/ws/chat?tenant_id=risk&agent_id=risk-desk-agent")

  Server-side on connect:
    -> build_tenant_context("risk", config_root=examples/)
       -> TenantContext(resource_env={"mock-portfolio-db": {"DB_PATH": "/tmp/portfolio.db", ...}})
    -> load_agent_bindings("risk-desk-agent", config_root=examples/)
       -> AgentSkillBindings(bound_skill_ids=("risk/portfolio-var",))
    -> session_manager.create() -> Session(session_id=...)
    -> send SessionStartedMessage

  Turn 1: "Calculate the 1-day 95% VaR for portfolio EQ-MACRO-1"
    -> orchestrator.handle_message():
      -> skill_engine.discover() -> [SkillSummary(risk/portfolio-var)]
      -> skill_engine.match(message) -> match on tags: var, portfolio, risk
      -> yield SkillMatchEvent
      -> skill_engine.load("risk/portfolio-var") -> SkillContent with scripts_path
      -> create_execute_code_tool(sandbox, tenant, scripts_dirs=[scripts_path])
      -> ScriptedRuntime.stream() -> executes turn 1 code in real sandbox
      -> yield ToolCallEvent, ToolResultEvent, AgentChunkEvent, AgentCompleteEvent
    -> session.messages updated (HumanMessage + AIMessage)

  Turn 2: "What about at 99% confidence?"
    -> Same flow, ScriptedRuntime uses turn 2 code (confidence=0.99)
    -> history parameter includes turn 1 messages (multi-turn proof)
```

---

## Key Code Explained

### Sandbox Env Var Flow

The `DB_PATH` env var flows through these layers:

1. `tenants/risk/resources.yaml` defines `DB_PATH: "/tmp/portfolio.db"` under alias `mock-portfolio-db`
2. `build_tenant_context()` loads this into `TenantContext.resource_env`
3. `create_execute_code_tool()` calls `_build_resource_env(tenant)` which flattens aliases
4. Since there's one alias, both prefixed (`MOCK_PORTFOLIO_DB_DB_PATH`) and unprefixed (`DB_PATH`) keys are emitted
5. `PythonSubprocessSandbox._build_process_env()` allows `DB_PATH` because it starts with `DB_` prefix

### PYTHONPATH Flow

1. `skill_engine.load("risk/portfolio-var")` returns `SkillContent` with `scripts_path` pointing to `examples/skills/risk/portfolio-var/scripts/`
2. `orchestrator._build_builtin_tools()` passes `scripts_dirs` to `create_execute_code_tool()`
3. `create_execute_code_tool()` sets `resource_env["PYTHONPATH"]` to the scripts dir
4. `PythonSubprocessSandbox._build_process_env()` allows `PYTHONPATH` via `_SANDBOX_ENV_OVERRIDE_EXACT`
5. Sandbox code can `from risk_calc import calculate_var`

### Scripted Code Blocks

Both turns follow the same pattern:
1. Connect to SQLite via `DB_PATH` env var
2. Read positions for portfolio `EQ-MACRO-1`
3. Generate synthetic returns with seeded RNG (`np.random.default_rng(42)`)
4. Call `calculate_var()` from the bundled `risk_calc` module
5. Print formatted results

Turn 1 uses `confidence=0.95`, Turn 2 uses `confidence=0.99`.

---

## Reused Framework Code

| Component | Source | Purpose |
|-----------|--------|---------|
| `create_app()` | `src/deep_agent/api/app.py` | App factory with runtime injection |
| `AppSettings` | `src/deep_agent/config.py` | Settings with `OPENAI_API_KEY="sk-fake"` |
| `DeterministicRuntime` pattern | `tests/e2e/test_pipeline_e2e.py` | ScriptedRuntime extends this idea |
| `seed()` | `examples/seed_data.py` | Seeds SQLite (unchanged) |
| `calculate_var()` | `examples/skills/.../risk_calc.py` | VaR calculation (unchanged) |
| Event models | `src/deep_agent/models/events.py` | ToolCallEvent, ToolResultEvent, etc. |
| Orchestrator | `src/deep_agent/orchestrator/` | Full pipeline coordination |
| Sandbox | `src/deep_agent/sandbox/` | Subprocess code execution |
| SkillEngine | `src/deep_agent/skills/engine.py` | Skill discovery and matching |
| SessionManager | `src/deep_agent/api/session.py` | In-memory session store |
| WebSocket handler | `src/deep_agent/api/ws_chat.py` | WebSocket endpoint |

---

## Verification

1. Run `python -m examples.run` from project root
2. Expect:
   - Server starts, health check passes
   - WebSocket connects, `session_started` received
   - Turn 1: `skill_match` -> `tool_call` -> `tool_result` (contains VaR at 95%) -> `agent_complete`
   - Turn 2: `skill_match` -> `tool_call` -> `tool_result` (contains VaR at 99%) -> `agent_complete`
   - No error events
   - Clean shutdown
3. Run existing tests: `pytest tests/ -x` — ensure nothing broken
