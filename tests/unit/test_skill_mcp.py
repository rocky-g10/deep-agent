"""Tests for skill-level MCP server declaration and merge logic."""
from __future__ import annotations

from pathlib import Path

import pytest

from deep_agent.mcp.config import MCPConfig, MCPServerConfig, merge_mcp_configs
from deep_agent.models.skills import MCPToolBinding, SkillMCPServer
from deep_agent.orchestrator.agent_orchestrator import (
    _apply_mcp_tool_bindings,
    _validate_mcp_tool_bindings,
)
from deep_agent.skills.parser import parse_skill_file

# ---------------------------------------------------------------------------
# merge_mcp_configs
# ---------------------------------------------------------------------------


def test_skill_mcp_servers_used_when_no_tenant_config() -> None:
    """Skill MCP servers should be used as-is when tenant config is empty."""
    skill_servers = [
        SkillMCPServer(name="market-data", transport="sse", url="http://localhost:8080/sse"),
    ]
    tenant_config = MCPConfig()

    merged = merge_mcp_configs(skill_servers, tenant_config)

    assert len(merged.servers) == 1
    assert merged.servers[0].name == "market-data"
    assert merged.servers[0].url == "http://localhost:8080/sse"


def test_tenant_overrides_skill_on_name_conflict() -> None:
    """When both skill and tenant define a server with the same name, tenant wins."""
    skill_servers = [
        SkillMCPServer(name="market-data", transport="sse", url="http://skill:8080/sse"),
    ]
    tenant_config = MCPConfig(
        servers=[
            MCPServerConfig(
                name="market-data",
                transport="sse",
                url="http://tenant-override:9090/sse",
            ),
        ]
    )

    merged = merge_mcp_configs(skill_servers, tenant_config)

    assert len(merged.servers) == 1
    assert merged.servers[0].url == "http://tenant-override:9090/sse"


def test_skill_and_tenant_different_names_both_available() -> None:
    """Servers with different names from skill and tenant should both be present."""
    skill_servers = [
        SkillMCPServer(name="analytics", transport="sse", url="http://analytics:8080/sse"),
    ]
    tenant_config = MCPConfig(
        servers=[
            MCPServerConfig(
                name="market-data",
                transport="sse",
                url="http://market:9090/sse",
            ),
        ]
    )

    merged = merge_mcp_configs(skill_servers, tenant_config)

    assert len(merged.servers) == 2
    names = {s.name for s in merged.servers}
    assert names == {"analytics", "market-data"}


def test_empty_skill_and_empty_tenant_gives_empty_config() -> None:
    """No servers from either source should produce an empty config."""
    merged = merge_mcp_configs([], MCPConfig())
    assert merged.servers == []


# ---------------------------------------------------------------------------
# Parser: mcp-servers in SKILL.md frontmatter
# ---------------------------------------------------------------------------


def test_parse_skill_with_mcp_servers(tmp_path: Path) -> None:
    """Parser should extract mcp-servers from frontmatter into SkillMCPServer list."""
    skill_path = tmp_path / "skills" / "test" / "mcp-skill" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        """---
name: mcp-skill
description: Skill with MCP servers
version: "1.0.0"
tags: [test]
allowed-tools: [execute_code, get_data]
mcp-servers:
  - name: data-source
    transport: sse
    url: http://localhost:9090/sse
  - name: local-tool
    transport: stdio
    command: ["python", "-m", "my_server"]
---
Body
""",
        encoding="utf-8",
    )

    skill = parse_skill_file(skill_path)

    assert len(skill.mcp_servers) == 2
    assert skill.mcp_servers[0].name == "data-source"
    assert skill.mcp_servers[0].transport == "sse"
    assert skill.mcp_servers[0].url == "http://localhost:9090/sse"
    assert skill.mcp_servers[1].name == "local-tool"
    assert skill.mcp_servers[1].transport == "stdio"
    assert skill.mcp_servers[1].command == ["python", "-m", "my_server"]


def test_parse_skill_without_mcp_servers_defaults_empty(tmp_path: Path) -> None:
    """Skills without mcp-servers should have an empty list."""
    skill_path = tmp_path / "skills" / "test" / "no-mcp" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        """---
name: no-mcp
description: No MCP
version: "1.0.0"
tags: [test]
allowed-tools: [execute_code]
---
Body
""",
        encoding="utf-8",
    )

    skill = parse_skill_file(skill_path)

    assert skill.mcp_servers == []


def test_skill_mcp_server_roundtrip() -> None:
    """SkillMCPServer should serialize and deserialize cleanly."""
    server = SkillMCPServer(
        name="test",
        transport="sse",
        url="http://example.com/sse",
        env={"API_KEY": "secret"},
    )
    loaded = SkillMCPServer.model_validate(server.model_dump())
    assert loaded == server


# ---------------------------------------------------------------------------
# Parser + validation: mcp-tool-bindings
# ---------------------------------------------------------------------------


def test_parse_skill_with_mcp_tool_bindings(tmp_path: Path) -> None:
    """Parser should extract mcp-tool-bindings from frontmatter."""
    skill_path = tmp_path / "skills" / "test" / "bound-skill" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        """---
name: bound-skill
description: Skill with MCP tool bindings
version: "1.0.0"
tags: [test]
allowed-tools: [execute_code, get_market_data, get_fx_rates]
mcp-servers:
  - name: market-data
    transport: sse
    url: http://localhost:8080/sse
  - name: fx-service
    transport: sse
    url: http://localhost:9090/sse
mcp-tool-bindings:
  - tool: get_market_data
    server: market-data
  - tool: get_fx_rates
    server: fx-service
---
Body
""",
        encoding="utf-8",
    )

    skill = parse_skill_file(skill_path)

    assert len(skill.mcp_tool_bindings) == 2
    assert skill.mcp_tool_bindings[0] == MCPToolBinding(
        tool_name="get_market_data", server_name="market-data"
    )
    assert skill.mcp_tool_bindings[1] == MCPToolBinding(
        tool_name="get_fx_rates", server_name="fx-service"
    )


def test_binding_references_valid_server() -> None:
    """Binding server that exists in merged config should pass validation."""
    merged = merge_mcp_configs(
        [SkillMCPServer(name="market-data", transport="sse", url="http://skill:8080/sse")],
        MCPConfig(),
    )
    bindings = [MCPToolBinding(tool_name="get_market_data", server_name="market-data")]

    _validate_mcp_tool_bindings(bindings, merged)


def test_binding_references_missing_server_raises() -> None:
    """Binding server missing from merged config should raise validation error."""
    merged = merge_mcp_configs([], MCPConfig())
    bindings = [MCPToolBinding(tool_name="get_market_data", server_name="market-data")]

    with pytest.raises(ValueError, match="unknown server"):
        _validate_mcp_tool_bindings(bindings, merged)


class _DummyTool:
    def __init__(self, name: str, server: str) -> None:
        self.name = name
        self.server = server


def test_binding_enforced_in_tool_routing() -> None:
    """Bound tool should resolve only from the specified server."""
    tools_by_server = {
        "market-data": [_DummyTool("get_data", "market-data")],
        "alt-market-data": [_DummyTool("get_data", "alt-market-data")],
    }
    bindings = [MCPToolBinding(tool_name="get_data", server_name="market-data")]

    selected = _apply_mcp_tool_bindings(tools_by_server, bindings)

    assert len(selected) == 1
    assert selected[0].name == "get_data"
    assert selected[0].server == "market-data"


def test_unbound_tool_falls_back_to_discovery() -> None:
    """Unbound tool should remain available from all discovered servers."""
    tools_by_server = {
        "market-data": [_DummyTool("get_market_data", "market-data")],
        "fx-service": [_DummyTool("get_fx_rates", "fx-service")],
    }
    bindings = [MCPToolBinding(tool_name="get_market_data", server_name="market-data")]

    selected = _apply_mcp_tool_bindings(tools_by_server, bindings)

    names_by_server = {(tool.name, tool.server) for tool in selected}
    assert ("get_market_data", "market-data") in names_by_server
    assert ("get_fx_rates", "fx-service") in names_by_server


def test_duplicate_binding_different_servers_raises() -> None:
    """Binding the same tool to two different servers should raise."""
    tools_by_server = {
        "server-a": [_DummyTool("get_data", "server-a")],
        "server-b": [_DummyTool("get_data", "server-b")],
    }
    bindings = [
        MCPToolBinding(tool_name="get_data", server_name="server-a"),
        MCPToolBinding(tool_name="get_data", server_name="server-b"),
    ]

    with pytest.raises(ValueError, match="bound to multiple servers"):
        _apply_mcp_tool_bindings(tools_by_server, bindings)


def test_tenant_override_still_works_with_bindings() -> None:
    """Binding by server name should respect tenant override URL on merge."""
    skill_servers = [
        SkillMCPServer(name="market-data", transport="sse", url="http://skill:8080/sse"),
    ]
    tenant_config = MCPConfig(
        servers=[
            MCPServerConfig(
                name="market-data",
                transport="sse",
                url="http://tenant-override:9090/sse",
            ),
        ]
    )
    merged = merge_mcp_configs(skill_servers, tenant_config)
    bindings = [MCPToolBinding(tool_name="get_market_data", server_name="market-data")]

    _validate_mcp_tool_bindings(bindings, merged)
    server = next(s for s in merged.servers if s.name == "market-data")
    assert server.url == "http://tenant-override:9090/sse"
