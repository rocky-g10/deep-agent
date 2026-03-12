---
name: "Portfolio VaR Report"
description: "Compute Value at Risk for a portfolio using historical simulation. Pulls positions from a database, market data via MCP, and generates a risk summary with chart."
version: "1.0.0"
tags:
  - risk
  - var
  - portfolio
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

1. **Get positions from the database** — Write Python code that reads portfolio positions from the database using env vars (DB_PATH for SQLite in this example).

2. **Get market data via MCP** — Call the `get_market_data` tool with the list of symbols from step 1 to retrieve historical daily returns.

3. **Compute VaR** — Use `from risk_calc import calculate_var` (bundled in `scripts/risk_calc.py`) to run historical VaR simulation on the portfolio.

4. **Generate report** — Output a summary table (VaR, expected shortfall, worst-case) and save a P&L distribution histogram to `/output/chart.png`.

## Examples

**User:** "What's the 1-day 95% VaR for portfolio EQ-MACRO-1?"

**Agent generates:**
```python
import sqlite3
import pandas as pd
import os
from risk_calc import calculate_var

# 1. Query positions from SQLite
conn = sqlite3.connect(os.environ["DB_PATH"])
positions = pd.read_sql("SELECT sym, qty, avg_cost FROM positions WHERE portfolio_id='EQ-MACRO-1'", conn)
conn.close()

# 2. Market data arrives via MCP tool (passed as argument)
# The agent calls get_market_data separately and injects returns here.

# 3. Compute VaR
result = calculate_var(positions, returns_df, confidence=0.95, horizon=1)

print(f"Portfolio:           EQ-MACRO-1")
print(f"1-Day 95% VaR:      ${result['var']:,.0f}")
print(f"Expected Shortfall:  ${result['es']:,.0f}")

# 4. Chart
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
