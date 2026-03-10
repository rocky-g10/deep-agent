"""Shared pytest fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make stubs/ importable for firm.stats tests.
_stubs_dir = Path(__file__).resolve().parent.parent / "stubs"
if str(_stubs_dir) not in sys.path:
    sys.path.insert(0, str(_stubs_dir))


@pytest.fixture
def placeholder_fixture() -> None:
    """Placeholder fixture for initial test scaffolding."""
    return None
