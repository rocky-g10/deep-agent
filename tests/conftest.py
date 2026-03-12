"""Shared pytest fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from deep_agent.models import TenantContext

# Make stubs/ importable for firm.stats tests.
_stubs_dir = Path(__file__).resolve().parent.parent / "stubs"
if str(_stubs_dir) not in sys.path:
    sys.path.insert(0, str(_stubs_dir))


@pytest.fixture
def tenant_equities() -> TenantContext:
    """Standard equities tenant context used across tests."""
    return TenantContext(
        tenant_id="equities",
        user_id="test-user",
        skills_dirs=("skills/common", "skills/equities"),
        db_aliases=("ch-equities",),
    )
