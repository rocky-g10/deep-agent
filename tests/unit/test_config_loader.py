"""Unit tests for API config loading utilities."""

from __future__ import annotations

from pathlib import Path

import pytest

from deep_agent.api.config_loader import (
    ConfigLoadError,
    build_tenant_context,
    load_agent_bindings,
    load_resource_env,
)


def test_load_agent_bindings_from_yaml(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "test-agent.yaml").write_text(
        'agent_id: "test-agent"\nbound_skill_ids:\n  - "risk/var"\n  - "common/db-query"\n'
    )
    bindings = load_agent_bindings("test-agent", config_root=tmp_path)
    assert bindings is not None
    assert bindings.agent_id == "test-agent"
    assert bindings.bound_skill_ids == ("risk/var", "common/db-query")


def test_load_agent_bindings_missing_file(tmp_path: Path) -> None:
    result = load_agent_bindings("nonexistent", config_root=tmp_path)
    assert result is None


def test_load_resource_env_from_yaml(tmp_path: Path) -> None:
    tenant_dir = tmp_path / "tenants" / "risk"
    tenant_dir.mkdir(parents=True)
    (tenant_dir / "resources.yaml").write_text(
        'resource_aliases:\n  my-db:\n    DB_HOST: "localhost"\n    DB_PORT: "5432"\n'
    )
    env = load_resource_env("risk", config_root=tmp_path)
    assert env == {"my-db": {"DB_HOST": "localhost", "DB_PORT": "5432"}}


def test_load_resource_env_missing_file(tmp_path: Path) -> None:
    env = load_resource_env("missing", config_root=tmp_path)
    assert env == {}


def test_build_tenant_context(tmp_path: Path) -> None:
    tenant_dir = tmp_path / "tenants" / "risk"
    tenant_dir.mkdir(parents=True)
    (tenant_dir / "resources.yaml").write_text(
        'resource_aliases:\n  db:\n    DB_HOST: "host"\n'
    )
    ctx = build_tenant_context("risk", config_root=tmp_path, user_id="user1")
    assert ctx.tenant_id == "risk"
    assert ctx.user_id == "user1"
    assert ctx.resource_env == {"db": {"DB_HOST": "host"}}
    assert ctx.mcp_config_path == "tenants/risk/mcp.json"


def test_path_traversal_blocked(tmp_path: Path) -> None:
    with pytest.raises(ConfigLoadError):
        load_agent_bindings("../../etc/passwd", config_root=tmp_path)
    with pytest.raises(ConfigLoadError):
        load_resource_env("../../etc", config_root=tmp_path)
