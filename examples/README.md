# Deep Agent — Runnable Example

> **Time to first result:** ~2 minutes. No Docker, no API keys, no external databases.

## What This Demonstrates

A **Portfolio VaR (Value at Risk)** agent that shows all three integration patterns:

| Pattern | What | How |
|---------|------|-----|
| **A — Custom Code Import** | Bundled `risk_calc.py` module | `from risk_calc import calculate_var` in sandbox |
| **B — Database Query** | Positions from SQLite via env vars | `os.environ["DB_PATH"]` injected by framework |
| **C — MCP Tool Call** | Market data from mock MCP server | `get_market_data` tool (mock returns synthetic data) |

## Quick Start

```bash
# 1. From the project root, activate your venv
cd deep-agent
source .venv/bin/activate
pip install -e .

# 2. Run the example (seeds data + computes VaR + generates chart)
python -m examples.run_example
```

**Expected output:**
```
Seeded /tmp/portfolio.db with 3 positions and 756 daily prices.

--- Portfolio Positions (EQ-MACRO-1) ---
  sym    qty  avg_cost
 AAPL  500.0    178.50
 MSFT  300.0    415.20
 GOOG  200.0    141.80

--- VaR Results ---
Portfolio:           EQ-MACRO-1
1-Day 95% VaR:      $4,XXX
Expected Shortfall:  $5,XXX
P&L samples:         252

Chart saved to: examples/output/var_chart.png
```

## File Structure

```
examples/
├── run_example.py              ← One-command launcher
├── seed_data.py                ← Seeds SQLite with portfolio data
├── mock_mcp_server.py          ← Mock MCP server (market data)
├── docker-compose.yml          ← Optional infrastructure
├── README.md                   ← This file
├── agents/
│   └── risk-desk-agent.yaml    ← Agent skill bindings
├── tenants/
│   └── risk/
│       ├── resources.yaml      ← Resource aliases (env vars)
│       └── mcp.json            ← MCP server config
├── skills/
│   └── risk/
│       └── portfolio-var/
│           ├── SKILL.md        ← Skill definition
│           └── scripts/
│               ├── risk_calc.py      ← VaR calculation module
│               └── requirements.txt  ← Skill dependencies
├── database/                   ← Example DatabaseRegistry (moved from core)
├── tools/                      ← Example tools (moved from core)
└── tests/                      ← Tests for example code
```

## How It Maps to the Framework

| Framework Concept | Example Implementation |
|-------------------|----------------------|
| `TenantContext.resource_env` | `tenants/risk/resources.yaml` → `DB_PATH` env var |
| `AgentSkillBindings` | `agents/risk-desk-agent.yaml` → binds `risk/portfolio-var` |
| Skill scripts (AgentSkills spec) | `skills/risk/portfolio-var/scripts/risk_calc.py` |
| MCP server config | `tenants/risk/mcp.json` → `mock_mcp_server.py` |
| `execute_code` tool | Framework core — runs Python in sandbox with env vars |

## Next Steps

- Replace SQLite with a real database (KDB+, ClickHouse, etc.) by updating `resources.yaml`
- Replace the mock MCP server with a real market data provider
- Add more skills to `agents/risk-desk-agent.yaml`
- See [docs/DEVELOPER_GUIDE.md](../docs/DEVELOPER_GUIDE.md) for the full guide
