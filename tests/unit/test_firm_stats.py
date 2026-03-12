"""Unit tests for firm_stats module (formerly firm.stats stubs)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

# Add the canonical skill scripts directory to sys.path so firm_stats is importable.
_scripts_dir = str(
    Path(__file__).resolve().parent.parent.parent
    / "skills"
    / "equities"
    / "zscore-monitor"
    / "scripts"
)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from firm_stats import moving_avg, zscore  # noqa: E402


def test_moving_avg_basic() -> None:
    """Rolling mean should match expected values for a simple series."""
    series = pd.Series([1.0, 2.0, 3.0, 4.0])
    result = moving_avg(series, window=2)
    expected = pd.Series([float("nan"), 1.5, 2.5, 3.5])

    pd.testing.assert_series_equal(result, expected)


def test_moving_avg_empty_series() -> None:
    """Empty input should produce empty output."""
    series = pd.Series(dtype=float)
    result = moving_avg(series, window=3)

    assert result.empty


def test_moving_avg_window_larger_than_series() -> None:
    """Window larger than data should produce NaN-only output."""
    series = pd.Series([1.0, 2.0, 3.0])
    result = moving_avg(series, window=10)

    assert result.isna().all()


def test_zscore_basic() -> None:
    """Rolling z-score should match manual rolling computation."""
    series = pd.Series([1.0, 2.0, 3.0, 4.0])

    result = zscore(series, window=2)
    expected = (series - series.rolling(window=2).mean()) / series.rolling(window=2).std()

    pd.testing.assert_series_equal(result, expected)


def test_zscore_empty_series() -> None:
    """Empty series should return empty output."""
    series = pd.Series(dtype=float)
    result = zscore(series, window=3)

    assert result.empty


def test_zscore_window_1_returns_nan() -> None:
    """Window=1 should produce NaN due to std(ddof=1) behavior."""
    series = pd.Series([5.0, 6.0, 7.0])
    result = zscore(series, window=1)

    assert result.isna().all()


def test_zscore_nan_propagation() -> None:
    """NaN values should propagate through rolling z-score output."""
    series = pd.Series([1.0, float("nan"), 3.0, 4.0])
    result = zscore(series, window=2)

    assert result.isna().iloc[0]
    assert result.isna().iloc[1]
