"""Skill-bundled analytics module for zscore-monitor.

Imported by sandbox code: `from firm_stats import zscore, moving_avg`.
The skill's scripts/ directory is automatically on PYTHONPATH.
"""

from __future__ import annotations

import pandas as pd


def moving_avg(series: pd.Series, window: int) -> pd.Series:
    """Compute rolling mean over a fixed window."""
    return series.rolling(window=window).mean()


def zscore(series: pd.Series, window: int) -> pd.Series:
    """Compute rolling z-score using rolling mean and std (ddof=1)."""
    rolling = series.rolling(window=window)
    mean = rolling.mean()
    std = rolling.std()
    return (series - mean) / std
