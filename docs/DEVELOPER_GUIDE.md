# Deep Agent — Developer Quick-Start Guide

> **Time to first skill:** ~15 minutes. This guide walks you through creating, configuring, and running a skill from scratch.
>
> For architecture details, see [PRD.md](./PRD.md).

---

## 1. Prerequisites

```bash
# Requirements
python3 --version   # 3.12+
docker --version    # For local data sources (optional)
git --version

# Clone and install
git clone <repo-url> && cd deep-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pip install -e .
```

---

## 2. Project Structure

```
deep-agent/
├── skills/                  ← YOU OWN THIS — your skills live here
│   ├── risk/
│   ├── equities/
│   └── ...
├── config/
│   ├── agents/              ← Agent → skill bindings
│   └── tenants/{id}/        ← (optional) Resource aliases + MCP config
├── src/deep_agent/          ← Framework core — DO NOT MODIFY
├── tests/
└── docs/
```

**Your workflow:** create skill directories under `skills/`, bind them in `config/agents/`, and let the framework handle everything else. Tenant config is optional — add it when you need environment separation or multi-tenancy.

---

## 3. Getting Started: Progression Path

You don't need to configure everything at once. Start simple and add layers as needed:

| Level | What you need | When |
|-------|--------------|------|
| **1. Quickstart** | A `SKILL.md` + agent YAML. Hardcode DB connections in your skill code. | Getting started, prototyping |
| **2. Environment separation** | Add `resources.yaml` to externalize connection strings (dev vs prod) | Multiple environments |
| **3. MCP tools** | Add `mcp-servers` to your SKILL.md (or tenant `mcp.json` for overrides) | Your skill needs external tool servers |
| **4. Multi-tenancy** | Different tenants get different resources and MCP servers | Enterprise deployment |

---

## 4. Creating Your First Skill

Every skill is a self-contained directory:

```
skills/risk/portfolio-var/
├── SKILL.md                 # Skill definition (required)
├── scripts/
│   ├── requirements.txt     # Python dependencies (pip-installed at runtime)
│   └── risk_calc.py         # Your bundled Python modules
├── references/
│   └── var_methodology.md   # Extended docs (overflow from SKILL.md)
└── assets/
    └── sector_weights.csv   # Static data, templates, configs
```

### 4.1 `skills/risk/portfolio-var/SKILL.md`

```yaml
---
name: "Portfolio VaR Report"
description: "Compute Value at Risk for a portfolio using historical simulation. Pulls positions from KDB+, market data via MCP, and generates a risk summary with chart."
version: "1.0.0"
tags:
  - risk
  - var
  - portfolio
  - kdb
  - market-data
allowed-tools:
  - execute_code
  - get_market_data
mcp-servers:                              # Optional: declare MCP servers the skill needs
  - name: market-data-mcp
    transport: sse
    url: http://market-data-mcp.internal:8080/sse
inputs:
  - name: portfolio_id
    type: string
    description: "Portfolio identifier (e.g., EQ-MACRO-1)"
  - name: confidence
    type: number
    description: "VaR confidence level (default: 0.95)"
  - name: horizon_days
    type: integer
    description: "Holding period in days (default: 1)"
quality:
  timeout: 90
  max-retries: 1
  validation: "Output must include VaR number, confidence level, and a P&L distribution chart."
---

# Portfolio VaR Report

## Purpose
Use this skill when the user asks about portfolio risk, Value at Risk, or P&L distribution for a portfolio.

## Instructions

1. **Get positions from KDB+** — Write Python code that connects to the `kdb-trading` resource using env vars and queries current positions for the requested portfolio.

2. **Get market data via MCP** — Call the `get_market_data` tool with the list of symbols from step 1 to retrieve current prices and 1-year daily returns.

3. **Compute VaR** — Use `from risk_calc import calculate_var` (bundled in `scripts/risk_calc.py`) to run historical VaR simulation on the portfolio.

4. **Generate report** — Output a summary table (VaR, expected shortfall, worst-case) and save a P&L distribution histogram to `/output/chart.png`.

## Examples

**User:** "What's the 1-day 95% VaR for portfolio EQ-MACRO-1?"

**Agent generates:**
```python
import os
import pandas as pd
from qpython import qconnection
from risk_calc import calculate_var

# --- 1. Query positions from KDB+ ---
q = qconnection.QConnection(
    host=os.environ["KDB_HOST"],
    port=int(os.environ["KDB_PORT"]),
    username=os.environ.get("KDB_USER", ""),
    password=os.environ.get("KDB_PASS", ""),
)
q.open()
positions = pd.DataFrame(
    q.sendSync("select sym, qty, avgCost from portfolio where portfolioId=`$\"EQ-MACRO-1\"")
)
q.close()

# --- 2. Market data arrives via MCP tool (passed as argument) ---
# The agent calls get_market_data separately and injects returns here.

# --- 3. Compute VaR ---
result = calculate_var(positions, returns_df, confidence=0.95, horizon=1)

print(f"Portfolio:           EQ-MACRO-1")
print(f"1-Day 95% VaR:      ${result['var']:,.0f}")
print(f"Expected Shortfall:  ${result['es']:,.0f}")

# --- 4. Chart ---
import matplotlib.pyplot as plt
plt.figure(figsize=(10, 5))
plt.hist(result["pnl_distribution"], bins=50, edgecolor="black", alpha=0.7)
plt.axvline(x=-result["var"], color="red", linestyle="--", label=f"VaR ({result['var']:,.0f})")
plt.title("Portfolio P&L Distribution — Historical Simulation")
plt.xlabel("P&L ($)")
plt.ylabel("Frequency")
plt.legend()
plt.grid(True, alpha=0.3)
plt.savefig("/output/chart.png", dpi=150, bbox_inches="tight")
```

## Quality Standards
- Always state the confidence level and horizon in the output.
- Use `risk_calc.calculate_var` — do not re-implement VaR from scratch.
- Chart must have title, axis labels, and a VaR line marker.
```

### 4.2 `skills/risk/portfolio-var/scripts/risk_calc.py`

```python
"""Bundled VaR calculation module.

Imported by sandbox code: `from risk_calc import calculate_var`.
The skill's scripts/ directory is automatically on PYTHONPATH.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def calculate_var(
    positions: pd.DataFrame,
    returns: pd.DataFrame,
    confidence: float = 0.95,
    horizon: int = 1,
) -> dict:
    """Historical simulation VaR.

    Args:
        positions: DataFrame with columns [sym, qty, avgCost].
        returns: DataFrame with daily return columns per symbol.
        confidence: Confidence level (e.g. 0.95).
        horizon: Holding period in days.

    Returns:
        Dict with keys: var, es, pnl_distribution.
    """
    symbols = positions["sym"].tolist()
    weights = (positions["qty"] * positions["avgCost"]).values
    portfolio_value = weights.sum()

    # Align returns to position symbols
    aligned = returns[[s for s in symbols if s in returns.columns]]
    port_returns = aligned.values @ (weights[: aligned.shape[1]] / portfolio_value)

    # Scale to horizon
    if horizon > 1:
        port_returns = port_returns * np.sqrt(horizon)

    pnl = port_returns * portfolio_value
    var_value = float(-np.percentile(pnl, (1 - confidence) * 100))
    tail = pnl[pnl <= -var_value]
    es_value = float(-tail.mean()) if len(tail) > 0 else var_value

    return {"var": var_value, "es": es_value, "pnl_distribution": pnl.tolist()}
```

### 4.3 `skills/risk/portfolio-var/scripts/requirements.txt`

```
qpython>=2.0
pandas>=2.2
numpy>=1.26
matplotlib>=3.9
```

---

## 5. Configuring Your Agent

### 5.1 Agent Skill Bindings

Each agent config declares which skills it can use. Create or edit your agent config:

```yaml
# config/agents/risk-desk-agent.yaml
agent_id: "risk-desk-agent"
bound_skill_ids:
  - "risk/portfolio-var"
  - "data-query/db-query"
  - "data-query/visualization"
```

Only skills in `bound_skill_ids` are discoverable by this agent.

### 5.2 MCP Servers

Skills can declare MCP server dependencies directly in `SKILL.md` frontmatter — no tenant config required. There are two ways to use MCP servers from a skill:

---

#### Mode 1: Connect to an MCP server (use all its tools)

Declare the server and let the framework discover all tools it exposes. The agent picks whichever tools are appropriate at runtime. Best for general-purpose servers where you don't need to control exactly which tool is called.

```yaml
---
name: "Market Scanner"
description: "Scan for unusual market activity using a market data MCP server."
version: "1.0.0"
mcp-servers:
  - name: market-data
    transport: sse
    url: http://localhost:8080/sse
---

# Market Scanner

## Instructions

1. **Connect to the `market-data` MCP server** — discover available tools and use whichever are relevant to the user's query.
2. **Analyze the data** — use `execute_code` to compute metrics and generate charts.
```

The framework connects to the server, discovers its tools, and makes them all available to the agent.

---

#### Mode 2: Connect to a specific server and call a specific tool

Declare one or more servers AND explicitly bind steps to specific tools on specific servers. This is the most precise approach — each step says exactly which server provides which tool. Best for multi-server skills where different steps hit different data sources.

```yaml
---
name: "Portfolio VaR Report"
description: "Compute Value at Risk using positions from a database and market data from MCP servers."
version: "1.0.0"
allowed-tools:
  - execute_code
  - get_market_data
  - get_fx_rates
mcp-servers:
  - name: market-data
    transport: sse
    url: http://localhost:8080/sse
  - name: fx-service
    transport: sse
    url: http://localhost:9090/sse
mcp-tool-bindings:
  - tool: get_market_data
    server: market-data
  - tool: get_fx_rates
    server: fx-service
---

# Portfolio VaR Report

## Instructions

1. **Get positions from the database** — use `execute_code` to query positions from SQLite via env vars.

2. **Get market data** — call `get_market_data` from the `market-data` MCP server with the list of symbols from step 1.

3. **Get FX rates for cross-currency positions** — call `get_fx_rates` from the `fx-service` MCP server to convert non-USD positions.

4. **Compute VaR** — use `execute_code` to run historical VaR simulation and generate the report.
```

In this example:
- Step 2 explicitly routes `get_market_data` → `market-data` server
- Step 3 explicitly routes `get_fx_rates` → `fx-service` server
- The frontmatter `mcp-tool-bindings` field enforces those routes (not just "any server that has this tool")

---

#### Tenant-level override (recommended for production)

Ops teams can redirect MCP endpoints without modifying skills by defining servers with the same name in tenant config (`config/tenants/{id}/mcp.json`). **Tenant config is the recommended best practice** for production deployments — it centralizes endpoint management, supports secrets, and enables environment separation (dev/staging/prod).

```json
// config/tenants/risk/mcp.json — overrides skill's "market-data" endpoint
{
  "servers": [
    {
      "name": "market-data",
      "transport": "sse",
      "url": "http://market-data-mcp.prod.internal:8080/sse"
    }
  ]
}
```

**Merge rules:**

| Scenario | Result |
|----------|--------|
| Skill has `mcp-servers`, no tenant `mcp.json` | Skill's URLs used directly — fully self-contained |
| Tenant has `mcp.json`, skill has no `mcp-servers` | Tenant config used |
| Both exist, same server name | **Tenant wins** — ops override without touching the skill |
| Both exist, different server names | Both available — merged |

**When to use which:**
- **Skill-level `mcp-servers`:** Rapid prototyping, self-contained skills, single-tenant setups. Simpler — everything in one file.
- **Tenant `mcp.json`:** Production deployments, multi-tenancy, when ops needs to control endpoints separately from skill authors.

---

## 6. Tenant Configuration (Optional)

Tenant config is **entirely optional**. It adds value for environment separation, multi-tenancy, and externalizing secrets. You can skip it entirely for simple setups.

### 6.1 resources.yaml — Sandbox Environment Variables

When user code runs inside the sandbox, the framework reads `resources.yaml` and injects all listed env vars into the sandbox environment. Skill code can then use `os.environ["DB_PATH"]` without hardcoding connection strings.

```yaml
# config/tenants/risk/resources.yaml
resource_aliases:
  kdb-trading:
    KDB_HOST: "kdb-trading.risk.internal"
    KDB_PORT: "5000"
    KDB_USER: "reader"
    KDB_PASS_REF: "vault:kdb/trading/password"
```

**Multi-tenant use case:** A "risk" tenant connects to KDB+ on `db-risk.internal:5000`, an "equities" tenant connects to `db-eq.internal:5001`. Same skill code, different data sources — controlled entirely by which tenant's `resources.yaml` is loaded.

**Single-tenant use case:** You can skip this entirely. Hardcode your DB connection in your skill code if that's simpler for your setup. The framework doesn't require it.

### 6.2 mcp.json — Tenant MCP Servers

Defines which MCP servers are available for a tenant. This is the **override layer** — it takes precedence over skill-level `mcp-servers` declarations when server names conflict.

```json
// config/tenants/risk/mcp.json
{
  "servers": [
    {
      "name": "market-data-mcp",
      "transport": "sse",
      "url": "http://market-data-mcp.deep-agent-mcp.svc:8080/sse"
    }
  ]
}
```

**Multi-tenant use case:** Different tenants can have different MCP server topologies — risk desk uses one market data provider, equities desk uses another.

**Single-tenant use case:** If your skill already declares `mcp-servers` in its `SKILL.md`, you may not need tenant-level MCP config at all. Use tenant config when ops teams need to override endpoints (e.g., dev vs prod).

### 6.3 When to Use What

| Scenario | Agent YAML | resources.yaml | mcp.json |
|----------|-----------|----------------|----------|
| Prototyping a new skill | Required | Skip — hardcode connections | Skip — use `mcp-servers` in SKILL.md |
| Dev vs prod environments | Required | Use — externalize connection strings | Optional — override skill MCP endpoints |
| Multi-tenant deployment | Required | Use — different data sources per tenant | Use — different MCP topologies per tenant |

---

## 7. Running Locally

The fastest way to test your skill is `scripts/test_agent.py` — a single-command invoke that wires up the full orchestrator (SkillEngine, LLMRouter, LangGraphAdapter, sandbox) without starting a server.

```bash
# 1. Activate the environment
source .venv/bin/activate

# 2. Set required env vars
export OPENAI_API_KEY="your-key"
```

### 7.1 test_agent.py — Recommended Starting Point

```bash
# Run with all discovered skills
python scripts/test_agent.py "What tables are available in the database?"

# Test a specific skill
python scripts/test_agent.py --skill risk/portfolio-var "What's the 1-day 95% VaR for EQ-MACRO-1?"

# Stream tokens as they arrive
python scripts/test_agent.py --stream "Explain z-scores"

# Bind multiple skills
python scripts/test_agent.py --skill risk/portfolio-var --skill data-query/db-query "Show positions"

# Inject resource env vars (simulates tenant config without files)
python scripts/test_agent.py \
  --resource "kdb-trading:KDB_HOST=localhost,KDB_PORT=5000" \
  "Show top positions"

# Override the model via environment
OPENAI_MODEL=gpt-4.1 python scripts/test_agent.py "Hello"
```

The script prints structured output — skill match, tool calls with inputs, tool results, and the final agent response with token count. Use `--stream` to see tokens as they arrive.

### 7.2 WebSocket Server (Full API)

For integration testing or when you need the full WebSocket API:

```bash
# Start the dev server
python -m deep_agent.api.main

# Send a test query (separate terminal)
python -c "
import asyncio, json, websockets

async def test():
    async with websockets.connect('ws://localhost:8000/ws/chat') as ws:
        await ws.send(json.dumps({
            'type': 'user_message',
            'content': 'What is the 1-day 95% VaR for portfolio EQ-MACRO-1?'
        }))
        async for msg in ws:
            event = json.loads(msg)
            print(f\"[{event['type']}] {event.get('content', event.get('summary', ''))[:200]}\")
            if event['type'] in ('agent_complete', 'error'):
                break

asyncio.run(test())
"
```

---

## 8. Testing Your Skill

### Validate structure

```bash
# Check frontmatter and required fields
python -c "
from deep_agent.skills.parser import parse_skill_file
from pathlib import Path
skill = parse_skill_file(Path('skills/risk/portfolio-var/SKILL.md'))
print(f'Skill: {skill.name}')
print(f'Tags:  {skill.tags}')
print(f'Tools: {skill.allowed_tools}')
print(f'MCP:   {[s.name for s in skill.mcp_servers]}')
"
```

### Test your bundled scripts

```bash
# Run your module's logic directly
PYTHONPATH=skills/risk/portfolio-var/scripts python -c "
from risk_calc import calculate_var
import pandas as pd, numpy as np
pos = pd.DataFrame({'sym': ['AAPL'], 'qty': [100], 'avgCost': [150.0]})
ret = pd.DataFrame({'AAPL': np.random.normal(0, 0.02, 252)})
result = calculate_var(pos, ret)
print(f'VaR: \${result[\"var\"]:,.0f}')
"
```

### Debugging tips

| Symptom | Fix |
|---------|-----|
| `ModuleNotFoundError` in sandbox | Check `scripts/requirements.txt` has the package; verify `scripts/` contains your `.py` files |
| `KeyError: 'DB_HOST'` | Verify your resource alias is configured in tenant config and matches the env var name your code uses |
| MCP tool not found | Confirm the tool name in `allowed-tools` matches exactly what the MCP server exposes; check `mcp-servers` in SKILL.md or tenant `mcp.json` |
| Skill not discovered | Check that your agent's `bound_skill_ids` includes your skill's `skill_id` (the path relative to `skills/`) |

---

## 9. Multi-Skill Composition

The orchestrator activates **multiple skills** for a single user message when a query spans domains. For example, "Compute VaR for EQ-MACRO-1 and flag z-score outliers in the positions" activates both the `portfolio-var` and `zscore-monitor` skills. The LLM then generates a single Python script importing from both skills' `scripts/` directories:

```python
from risk_calc import calculate_var   # from portfolio-var skill
from firm_stats import zscore          # from zscore-monitor skill
```

### How it works

1. `SkillEngine.match()` accepts a `min_score` parameter as the sole relevance filter. All bound skills scoring at or above `min_score` are activated — there is no artificial cap.
2. The orchestrator merges their `scripts/` directories onto `PYTHONPATH`, unions their `allowed-tools`, and concatenates their instructions into the system prompt.
3. One `SkillMatchEvent` is emitted per activated skill (same schema, multiple emissions).
4. Higher-scored skill wins on MCP binding or script filename conflicts.

For single-skill queries, behavior is identical to before: one `SkillMatchEvent`, singular `## Active Skill:` heading. The multi-skill prompt format (`## Active Skills` with `### Skill:` subsections) only appears when two or more skills activate.

### Authoring skills for composition

- **Keep script names unique across skills.** Use descriptive names like `risk_calc.py` instead of generic `utils.py`. The higher-scored skill's version shadows duplicates on `PYTHONPATH`.
- **Use descriptive tags** so the matcher can detect cross-skill queries. A query containing both "VaR" and "z-score" triggers both skills. The more specific your tags, the better multi-skill matching works.
- **`scripts/` directories use flat imports.** Skill directories may use kebab-case names (e.g., `portfolio-var/`), but this doesn't affect Python imports — the framework puts each skill's `scripts/` directory directly on `PYTHONPATH`, so `from risk_calc import calculate_var` works without any package prefix.
- **Skills must remain independently functional.** Composition is additive — your skill must work on its own, not only in combination with another.

---

## 10. Testing the Agent in Isolation

Before spinning up the full WebSocket server, use `scripts/invoke_agent.py` to test the entire agent stack — SkillEngine, skill matching, prompt injection, LLM, tool calls, and sandbox execution — with a single command.

This is the recommended way to iterate on skills. Full app startup (FastAPI + WebSocket) adds overhead and noise when all you need is to verify a skill matches, loads, and executes correctly.

### Prerequisites

```bash
export OPENAI_API_KEY="sk-..."       # required
export OPENAI_MODEL="gpt-4o"         # optional — overrides default (gpt-5)
```

### Basic usage

```bash
# Stream the agent response token by token (default)
python scripts/invoke_agent.py "Show me z-scores for AAPL volume over 60 days"

# Use a specific agent binding (controls which skills are available)
python scripts/invoke_agent.py --agent risk-desk-agent \
    "What is the 1-day 95% VaR for portfolio EQ-MACRO-1?"

# Print final answer only (no streaming)
python scripts/invoke_agent.py --no-stream "List all available skills"
```

### Example output

```
============================================================
  Agent : default
  Prompt: Show me z-scores for AAPL volume over 60 days
============================================================

[skill matched] equities/zscore-monitor (score: 0.67)
[tool call] execute_code({"code": "import os\nimport clickhouse_connect\n..."})
[tool result] Symbol: AAPL | Z-Score: 1.84 | Outliers: 2...
Analysing AAPL volume using a 60-day rolling window...
The current z-score is 1.84 — within normal range.

[done] tokens used: 842
```

### Customising the script

Three things developers typically change:

1. **Agent bindings** — Edit the `AGENT_CONFIGS` dict at the top of the script to add a new agent or change which skills it can use:
   ```python
   AGENT_CONFIGS["my-agent"] = AgentSkillBindings(
       agent_id="my-agent",
       bound_skill_ids=("equities/my-new-skill", "common/db-query"),
   )
   ```

2. **Resource env vars** — Populate `resource_env` in the `TenantContext` to inject DB credentials into the sandbox:
   ```python
   context = TenantContext(
       tenant_id="local-dev",
       user_id="developer",
       resource_env={
           "kdb-trading": {
               "KDB_HOST": "localhost",
               "KDB_PORT": "5000",
           },
       },
   )
   ```

3. **MCP servers** — Pass an `MCPManager` to the orchestrator to attach MCP tool servers:
   ```python
   from deep_agent.mcp.manager import MCPManager
   from deep_agent.mcp.config import MCPConfig, MCPServerConfig

   mcp_config = MCPConfig(servers=[
       MCPServerConfig(name="market-data", transport="sse",
                       url="http://localhost:8080/sse"),
   ])
   mcp_manager = MCPManager(mcp_config)
   orchestrator = AgentOrchestrator(..., mcp_manager=mcp_manager)
   ```

### How it maps to the full app

The script uses the exact same code paths as the WebSocket API — same orchestrator, same runtime, same sandbox. The only difference is that events are printed to stdout instead of streamed over WebSocket.

---

## 11. Human-in-the-Loop (HITL)

> **Planned Feature — Not Yet Implemented**
> The HITL framework described in this section is a design specification. No runtime implementation exists in `src/` as of v0.2.0-draft. The demo in `scripts/demo_risk_agent.py` simulates the intended behavior for illustration purposes.

The framework will support three interaction patterns that let the agent pause, collect human input, and resume. Skill authors will write **zero HITL code** — the LLM will decide when to ask based on your skill's prompt guidance, and the engine will handle suspension and resumption automatically.

### 11.1 The Three Patterns

| Pattern | When the agent uses it | User sees |
|---------|----------------------|-----------|
| **Clarify** | Query is ambiguous or missing context | A chat-style question, optionally with choices |
| **Approve** | Action is high-risk or irreversible | A modal dialog with approve/deny buttons |
| **Collect** | Multiple structured fields are needed | A form with typed, validated fields |

### 11.2 Enabling HITL in Your Skill

HITL will be driven entirely by frontmatter configuration and prompt wording. No Python code will be needed.

**Clarification** — just write clear instructions. The LLM will naturally ask when information is missing once HITL is implemented:

```yaml
---
name: "Portfolio VaR Report"
description: "Compute VaR for a portfolio using historical simulation."
clarification-hints:
  - missing_portfolio: "Which portfolio should I analyze?"
  - ambiguous_period: "What time range — YTD or trailing 12 months?"
---

# Portfolio VaR Report

## Instructions

1. If the user doesn't specify a portfolio, ask which one they want.
2. If the time period is ambiguous, clarify before computing.
3. Compute VaR using historical simulation.
```

**Approval gates** — add `requires-approval: true` and mention approval in your instructions:

```yaml
---
name: "Hedging Executor"
description: "Execute hedging trades to reduce portfolio risk."
requires-approval: true
---

# Hedging Executor

## Instructions

1. Analyze the portfolio's risk exposure.
2. Propose a hedging strategy with specific trades.
3. **Before executing any trade**, present the full trade details
   (symbol, quantity, side, estimated notional) and request explicit approval.
```

**Structured input** — describe the fields in your prompt. The LLM will present them as a form-like interaction:

```yaml
---
name: "Trade Booking"
description: "Book a trade order via the OMS."
requires-approval: true
---

# Trade Booking

## Instructions

1. Collect the following from the user: ticker, quantity, side (buy/sell),
   limit price (optional), and time-in-force (DAY, GTC, or IOC).
2. Validate the inputs against the instrument reference data.
3. Present a summary and request approval before submitting.
```

### 11.3 How the LLM Decides When to Ask

The LLM will call the built-in `human_interaction` tool, which the engine will intercept. You will not need to call it explicitly — the orchestrator will inject it into the tool set automatically. The LLM will decide when to invoke it based on:

1. **Missing information** — the skill instructions say "if the user doesn't specify X, ask" → LLM will call `human_interaction(kind="clarify", question="Which X?")`.
2. **`requires-approval: true`** — the orchestrator will add a system directive requiring approval before irreversible actions → LLM will call `human_interaction(kind="approve", ...)`.
3. **Multiple fields needed** — the skill instructions describe a set of required inputs → LLM will call `human_interaction(kind="collect", fields=[...])`.

### 11.4 WebSocket Events

When the agent suspends, clients will receive an `interaction_required` event:

```json
{
  "type": "interaction_required",
  "run_id": "run-abc123",
  "skill_id": "risk/portfolio-var",
  "interaction": {
    "kind": "clarify",
    "question": "Which portfolio should I analyze?",
    "options": ["EQ-MACRO-1", "FI-GOV-2", "MULTI-STRAT-3"],
    "timeout_seconds": 300
  }
}
```

The client will render the appropriate UI and submit the response via the REST API:

```
POST /api/v1/runs/run-abc123/respond

{"response": {"kind": "clarify", "value": "EQ-MACRO-1"}}
```

The agent will then resume with the user's answer and continue execution.

### 11.5 Timeout and Fallback

Every interaction will have a timeout (default: 300 seconds). When a timeout fires, the `fallback` strategy will determine what happens:

| Fallback | Behavior |
|----------|----------|
| `abort` (default) | Run will be terminated; user sees a timeout error |
| `default` | Engine will inject default values and resume (only for `collect` with defaults) |
| `skip` | Engine will skip the interaction; LLM continues without the answer |

Configure timeouts in the skill frontmatter:

```yaml
quality:
  hitl-timeout: 600          # 10 minutes (for approval gates routed to managers)
  hitl-fallback: abort       # abort | default | skip
```

### 11.6 Testing HITL Flows Locally

Once implemented, use `scripts/invoke_agent.py` with `--interactive` to test HITL flows. When the agent suspends, the script will prompt you in the terminal:

```bash
python scripts/invoke_agent.py --interactive \
  "What's the VaR for the portfolio?"

# Output:
# [skill_match] risk/portfolio-var (score: 0.52)
# [interaction_required] clarify: "Which portfolio should I analyze?"
#   Options: EQ-MACRO-1, FI-GOV-2, MULTI-STRAT-3
# > Your answer: EQ-MACRO-1          ← you type this
# [tool_call] execute_code(...)
# [tool_result] Portfolio: EQ-MACRO-1 ...
# [done] tokens used: 1,247
```

For approval gates:

```bash
python scripts/invoke_agent.py --interactive \
  "VaR is too high, hedge the NVDA exposure"

# [interaction_required] approve: "Execute hedge: SELL 200 NVDA @ market (~$184,160)"
#   Risk level: high
# > Approve? (y/n): y
# [tool_call] execute_code(...)
# [agent_complete] Hedge executed successfully.
```

### 11.7 HITL in the Risk Demo

The risk demo (`scripts/demo_risk_agent.py`) simulates a concrete HITL scenario:

1. The agent computes VaR and detects it exceeds the 2% risk threshold.
2. It proposes a hedging trade and triggers an **approval gate**.
3. The demo simulates user approval and the agent resumes execution.
4. Before executing, the agent asks a **clarification**: "Apply hedge to the full position or only the excess?"
5. The demo simulates the user choosing "excess only" and the agent completes.

This demonstrates the full suspend → interact → resume lifecycle in a realistic risk management workflow.

---

## 12. Deploying to Production

```
1. Create a PR adding your skill directory to the skills repo
2. CI automatically:
   ├─ Validates YAML frontmatter (required fields, schema)
   ├─ Checks directory structure (SKILL.md, scripts/, etc.)
   └─ Requires approval from desk_admin or peer skill_author
3. Merge to main
4. CD syncs skills to the platform — SkillEngine hot-reloads (no restart)
```

Your skill is live. Bind it to an agent via `bound_skill_ids` and users can start querying.

---

*For architecture details, security model, and multi-tenancy design, see [PRD.md](./PRD.md).*
