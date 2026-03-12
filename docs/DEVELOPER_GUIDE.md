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
│   └── tenants/{id}/       ← Tenant resource aliases + MCP config
├── src/deep_agent/          ← Framework core — DO NOT MODIFY
├── tests/
└── docs/
```

**Your workflow:** create skill directories under `skills/`, configure resources under `config/`, and let the framework handle everything else.

---

## 3. Creating Your First Skill

Every skill is a self-contained directory following the Anthropic AgentSkills spec:

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

The full example below demonstrates all three integration patterns in one skill.

---

## 4. Example Skill: Portfolio Risk Report

This skill computes Value at Risk (VaR) for a portfolio by:
- **Pattern A** — importing a bundled `risk_calc.py` module
- **Pattern B** — querying KDB+ for live trading positions via resource env vars
- **Pattern C** — calling an MCP tool (`get_market_data`) for real-time pricing

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

### 5.2 Resource Aliases

Define resource env vars for your data sources in tenant config:

```yaml
# config/tenants/risk/resources.yaml
resource_aliases:
  kdb-trading:
    KDB_HOST: "kdb-trading.risk.internal"
    KDB_PORT: "5000"
    KDB_USER: "reader"
    KDB_PASS_REF: "vault:kdb/trading/password"
```

These env vars are injected into the sandbox at runtime. Your skill code reads them via `os.environ`.

### 5.3 MCP Servers

Add MCP servers to your tenant's MCP config:

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

The `get_market_data` tool becomes available to skills that list it in `allowed-tools`.

---

## 6. Running Locally

```bash
# 1. Activate the environment
source .venv/bin/activate

# 2. Set required env vars
export OPENAI_API_KEY="your-key"

# 3. Start the dev server
python -m deep_agent.api.main

# 4. Send a test query (separate terminal)
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

## 7. Testing Your Skill

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
| MCP tool not found | Confirm the tool name in `allowed-tools` matches exactly what the MCP server exposes |
| Skill not discovered | Check that your agent's `bound_skill_ids` includes your skill's `skill_id` (the path relative to `skills/`) |

---

## 8. Deploying to Production

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
