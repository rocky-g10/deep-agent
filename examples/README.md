# Deep Agent — End-to-End Example

A self-contained demo that exercises the **full deep-agent pipeline** through the WebSocket API. No LLM API key required.

## What It Demonstrates

1. **WebSocket API** — Real uvicorn server on a random port, client connects via `websockets`
2. **Agent Resolution** — `risk-desk-agent` loaded from `agents/risk-desk-agent.yaml`
3. **Tenant Context** — Resource env vars (`DB_PATH`) loaded from `tenants/risk/resources.yaml`
4. **Skill Orchestration** — Orchestrator matches `risk/portfolio-var` skill by tag overlap
5. **Sandbox Execution** — Python code runs in a subprocess sandbox with env var injection
6. **PYTHONPATH Injection** — `risk_calc.py` from the skill's `scripts/` dir is importable
7. **Multi-Turn Sessions** — Two turns on the same WebSocket connection (95% then 99% VaR)
8. **Mock LLM** — `ScriptedRuntime` replays predetermined code blocks (CI-safe, no API key)

## Quick Start

```bash
# From the project root:
python -m examples.run
```

## Expected Output

```
============================================================
  Deep Agent — End-to-End Demo
============================================================

  Seeding database...
  Starting server on 127.0.0.1:xxxxx...
  Server healthy.

  SESSION <uuid>

============================================================
  Turn 1: Calculate 95% VaR
============================================================
  SKILL MATCH risk/portfolio-var (confidence: 0.75)
  TOOL CALL execute_code
    import sqlite3, os | import pandas as pd | ...
  TOOL RESULT
    Portfolio Positions (EQ-MACRO-1):
    sym  qty  avg_cost
    AAPL  500    178.5
    MSFT  300    415.2
    GOOG  200    141.8

    1-Day 95% VaR: $X,XXX.XX
    Expected Shortfall: $X,XXX.XX
    P&L samples: 252
  COMPLETE (tokens_used=0)
------------------------------------------------------------

============================================================
  Turn 2: Calculate 99% VaR
============================================================
  SKILL MATCH risk/portfolio-var (confidence: 0.75)
  TOOL CALL execute_code
    ...
  TOOL RESULT
    ...
    1-Day 99% VaR: $X,XXX.XX
    ...
  COMPLETE (tokens_used=0)

============================================================
  Demo Complete
============================================================
  Two-turn VaR calculation over WebSocket — no LLM API key required.
```

## Architecture

```
python -m examples.run
  |
  +-- seed SQLite (/tmp/portfolio.db)
  +-- create_app(settings, config_root=examples/, runtime=ScriptedRuntime)
  +-- start uvicorn on 127.0.0.1:{random_port}
  +-- websockets.connect("ws://127.0.0.1:{port}/ws/chat?tenant_id=risk&agent_id=risk-desk-agent")
  |
  Server-side on connect:
  |  +-- build_tenant_context("risk") -> resource_env with DB_PATH
  |  +-- load_agent_bindings("risk-desk-agent") -> bound to risk/portfolio-var
  |  +-- session_manager.create() -> Session
  |  +-- send session_started
  |
  Turn 1: "Calculate the 1-day 95% VaR for portfolio EQ-MACRO-1"
  |  +-- orchestrator.handle_message()
  |     +-- skill_engine.match() -> risk/portfolio-var
  |     +-- skill_engine.load() -> SkillContent with scripts_path
  |     +-- create_execute_code_tool(sandbox, tenant, scripts_dirs)
  |     +-- ScriptedRuntime.stream() -> executes turn 1 code in sandbox
  |     +-- yield: skill_match, tool_call, tool_result, agent_chunk, agent_complete
  |
  Turn 2: "What about at 99% confidence?"
     +-- Same flow, ScriptedRuntime uses turn 2 code (confidence=0.99)
     +-- Session history includes turn 1 messages (multi-turn proof)
```

## File Structure

```
examples/
├── __init__.py              # Package marker
├── __main__.py              # python -m examples entry point
├── README.md                # This file
├── run.py                   # Main demo: server + WebSocket client
├── scripted_runtime.py      # Mock RuntimeAdapter (no LLM needed)
├── display.py               # ANSI-colored event pretty-printer
├── seed_data.py             # Seeds SQLite with sample portfolio data
├── agents/
│   └── risk-desk-agent.yaml # Agent -> skill bindings
├── tenants/
│   └── risk/
│       └── resources.yaml   # DB_PATH env var mapping
└── skills/
    └── risk/
        └── portfolio-var/
            ├── SKILL.md     # Skill definition (tags, allowed-tools)
            └── scripts/
                ├── risk_calc.py      # VaR calculation module
                └── requirements.txt  # Script dependencies
```

## Extending the Example

- **Real LLM**: Replace `ScriptedRuntime` with `LangGraphAdapter` and set a real `OPENAI_API_KEY`
- **Add MCP**: Create `tenants/risk/mcp.json` with server configs, add `get_market_data` to allowed-tools
- **New skills**: Add a `SKILL.md` under `skills/`, bind it in the agent YAML
- **New tenants**: Add `tenants/{name}/resources.yaml` with resource env vars

See [docs/DEVELOPER_GUIDE.md](../docs/DEVELOPER_GUIDE.md) for the full framework reference.
