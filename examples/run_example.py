#!/usr/bin/env python3
"""Run the Portfolio VaR example end-to-end.

This script demonstrates the Deep Agent framework capabilities without
requiring an LLM API key. It:
1. Seeds a local SQLite DB with sample portfolio data
2. Generates synthetic market returns (mimicking the MCP tool)
3. Runs the bundled risk_calc module to compute VaR
4. Produces a P&L distribution chart

Usage:
    python -m examples.run_example
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

# Ensure examples/ and skill scripts are importable
_examples_root = Path(__file__).resolve().parent
_project_root = _examples_root.parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_examples_root / "skills" / "risk" / "portfolio-var" / "scripts"))


def main() -> None:
    # --- Step 0: Seed data ---
    from examples.seed_data import seed

    seed()

    # --- Step 1: Load positions from SQLite ---
    import pandas as pd

    db_path = os.environ.get("DB_PATH", "/tmp/portfolio.db")
    conn = sqlite3.connect(db_path)
    positions = pd.read_sql(
        "SELECT sym, qty, avg_cost FROM positions WHERE portfolio_id='EQ-MACRO-1'",
        conn,
    )
    conn.close()
    print("\n--- Portfolio Positions (EQ-MACRO-1) ---")
    print(positions.to_string(index=False))

    # --- Step 2: Generate synthetic returns (mimics MCP get_market_data) ---
    import numpy as np

    rng = np.random.default_rng(42)
    symbols = positions["sym"].tolist()
    returns_data = {sym: rng.normal(0.0005, 0.02, 252) for sym in symbols}
    returns_df = pd.DataFrame(returns_data)

    # --- Step 3: Compute VaR using the bundled skill script ---
    from risk_calc import calculate_var

    result = calculate_var(positions, returns_df, confidence=0.95, horizon=1)

    print("\n--- VaR Results ---")
    print(f"Portfolio:           EQ-MACRO-1")
    print(f"1-Day 95% VaR:      ${result['var']:,.0f}")
    print(f"Expected Shortfall:  ${result['es']:,.0f}")
    print(f"P&L samples:         {len(result['pnl_distribution'])}")

    # --- Step 4: Generate chart ---
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output_dir = _examples_root / "output"
    output_dir.mkdir(exist_ok=True)
    chart_path = output_dir / "var_chart.png"

    plt.figure(figsize=(10, 5))
    plt.hist(result["pnl_distribution"], bins=50, edgecolor="black", alpha=0.7, color="#4C72B0")
    plt.axvline(
        x=-result["var"],
        color="red",
        linestyle="--",
        linewidth=2,
        label=f"95% VaR (${result['var']:,.0f})",
    )
    plt.title("Portfolio P&L Distribution — Historical Simulation (EQ-MACRO-1)")
    plt.xlabel("P&L ($)")
    plt.ylabel("Frequency")
    plt.legend(fontsize=11)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(str(chart_path), dpi=150)
    plt.close()

    print(f"\nChart saved to: {chart_path}")
    print("\nExample complete. This demonstrates:")
    print("  - Pattern A: Custom code import (risk_calc.py)")
    print("  - Pattern B: Database query via resource env vars (SQLite)")
    print("  - Pattern C: Market data (synthetic, mimicking MCP tool)")


if __name__ == "__main__":
    main()
