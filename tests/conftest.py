"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from deep_agent.models import TenantContext
from deep_agent.models.skills import AgentSkillBindings


@pytest.fixture
def tenant_equities() -> TenantContext:
    """Standard equities tenant context used across tests."""
    return TenantContext(
        tenant_id="equities",
        user_id="test-user",
        resource_env={
            "ch-equities": {
                "DB_HOST": "localhost",
                "DB_PORT": "8123",
                "DB_NAME": "default",
            }
        },
    )


@pytest.fixture
def skill_bindings() -> AgentSkillBindings:
    """Standard skill bindings for the equities agent."""
    return AgentSkillBindings(
        agent_id="equities-agent",
        bound_skill_ids=("common/db-query", "equities/zscore-monitor"),
    )
