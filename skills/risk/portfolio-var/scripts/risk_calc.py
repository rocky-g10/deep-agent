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
        positions: DataFrame with columns [sym, qty, avg_cost].
        returns: DataFrame with daily return columns per symbol.
        confidence: Confidence level (e.g. 0.95).
        horizon: Holding period in days.

    Returns:
        Dict with keys: var, es, pnl_distribution.
    """
    symbols = positions["sym"].tolist()
    weights = (positions["qty"] * positions["avg_cost"]).values.astype(float)
    portfolio_value = weights.sum()

    # Align returns to position symbols
    available = [s for s in symbols if s in returns.columns]
    if not available:
        return {"var": 0.0, "es": 0.0, "pnl_distribution": []}

    aligned = returns[available]
    w = weights[: aligned.shape[1]]
    port_returns = aligned.values @ (w / portfolio_value)

    # Scale to horizon
    if horizon > 1:
        port_returns = port_returns * np.sqrt(horizon)

    pnl = port_returns * portfolio_value
    var_value = float(-np.percentile(pnl, (1 - confidence) * 100))
    tail = pnl[pnl <= -var_value]
    es_value = float(-tail.mean()) if len(tail) > 0 else var_value

    return {"var": var_value, "es": es_value, "pnl_distribution": pnl.tolist()}
