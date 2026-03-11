"""Unit tests for MCP config loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from deep_agent.mcp import MCPConfigError, load_mcp_config
from deep_agent.models import TenantContext


def _tenant(tenant_id: str = "equities") -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        user_id="test-user",
        skills_dirs=[],
        db_aliases=[],
    )


def test_load_valid_config(tmp_path: Path) -> None:
    """Valid JSON should parse to MCPConfig with expected fields."""
    config_dir = tmp_path / "tenants" / "equities"
    config_dir.mkdir(parents=True)
    (config_dir / "mcp.json").write_text(
        (
            '{"servers": [{"name": "echo", "transport": "stdio", '
            '"command": ["python", "-m", "echo"]}]}'
        ),
        encoding="utf-8",
    )

    config = load_mcp_config(_tenant(), config_root=tmp_path)

    assert len(config.servers) == 1
    assert config.servers[0].name == "echo"
    assert config.servers[0].transport == "stdio"
    assert config.servers[0].command == ["python", "-m", "echo"]


def test_load_missing_file_returns_empty_config(tmp_path: Path) -> None:
    """Missing config file should return empty config without error."""
    config = load_mcp_config(_tenant("nonexistent"), config_root=tmp_path)

    assert config.servers == []


def test_load_malformed_json_raises_error(tmp_path: Path) -> None:
    """Malformed JSON should raise MCPConfigError."""
    config_dir = tmp_path / "tenants" / "equities"
    config_dir.mkdir(parents=True)
    (config_dir / "mcp.json").write_text("{invalid json", encoding="utf-8")

    with pytest.raises(MCPConfigError, match="Malformed JSON"):
        load_mcp_config(_tenant(), config_root=tmp_path)


def test_load_invalid_structure_raises_error(tmp_path: Path) -> None:
    """Invalid structure should raise MCPConfigError."""
    config_dir = tmp_path / "tenants" / "equities"
    config_dir.mkdir(parents=True)
    (config_dir / "mcp.json").write_text('{"servers": [{"transport": "stdio"}]}', encoding="utf-8")

    with pytest.raises(MCPConfigError):
        load_mcp_config(_tenant(), config_root=tmp_path)


def test_stdio_without_command_raises_error(tmp_path: Path) -> None:
    """stdio transport without command should raise MCPConfigError."""
    config_dir = tmp_path / "tenants" / "equities"
    config_dir.mkdir(parents=True)
    (config_dir / "mcp.json").write_text(
        '{"servers": [{"name": "bad", "transport": "stdio"}]}',
        encoding="utf-8",
    )

    with pytest.raises(MCPConfigError, match="no 'command' field"):
        load_mcp_config(_tenant(), config_root=tmp_path)


def test_sse_without_url_raises_error(tmp_path: Path) -> None:
    """sse transport without url should raise MCPConfigError."""
    config_dir = tmp_path / "tenants" / "equities"
    config_dir.mkdir(parents=True)
    (config_dir / "mcp.json").write_text(
        '{"servers": [{"name": "bad", "transport": "sse"}]}',
        encoding="utf-8",
    )

    with pytest.raises(MCPConfigError, match="no 'url' field"):
        load_mcp_config(_tenant(), config_root=tmp_path)


def test_sse_with_url_is_valid(tmp_path: Path) -> None:
    """sse transport with url should parse successfully."""
    config_dir = tmp_path / "tenants" / "equities"
    config_dir.mkdir(parents=True)
    (config_dir / "mcp.json").write_text(
        '{"servers": [{"name": "api", "transport": "sse", "url": "http://localhost:8080/sse"}]}',
        encoding="utf-8",
    )

    config = load_mcp_config(_tenant(), config_root=tmp_path)

    assert config.servers[0].url == "http://localhost:8080/sse"


def test_empty_servers_list_is_valid(tmp_path: Path) -> None:
    """Config with empty servers list should parse without error."""
    config_dir = tmp_path / "tenants" / "equities"
    config_dir.mkdir(parents=True)
    (config_dir / "mcp.json").write_text('{"servers": []}', encoding="utf-8")

    config = load_mcp_config(_tenant(), config_root=tmp_path)

    assert config.servers == []


def test_env_vars_parsed(tmp_path: Path) -> None:
    """Server env vars should be parsed into config model."""
    config_dir = tmp_path / "tenants" / "equities"
    config_dir.mkdir(parents=True)
    (config_dir / "mcp.json").write_text(
        (
            '{"servers": [{"name": "s", "transport": "stdio", '
            '"command": ["cmd"], "env": {"KEY": "VAL"}}]}'
        ),
        encoding="utf-8",
    )

    config = load_mcp_config(_tenant(), config_root=tmp_path)

    assert config.servers[0].env == {"KEY": "VAL"}
