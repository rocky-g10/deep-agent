"""Integration tests for MCPManager with the test echo server."""

from __future__ import annotations

import sys

import pytest

from deep_agent.mcp.config import MCPConfig, MCPServerConfig
from deep_agent.mcp.manager import MCPManager


def _echo_server_config() -> MCPConfig:
    """Config pointing to the test echo MCP server."""
    return MCPConfig(
        servers=[
            MCPServerConfig(
                name="echo-test",
                transport="stdio",
                command=[sys.executable, "-m", "tests_mcp.echo_server"],
            )
        ]
    )


@pytest.mark.timeout(30)
@pytest.mark.asyncio
async def test_connect_discovers_three_tools() -> None:
    """connect() should discover echo, add, and multiply tools."""
    manager = MCPManager(_echo_server_config())

    await manager.connect()
    try:
        tools = await manager.get_tools()
        assert len(tools) == 3
        tool_names = {tool.name for tool in tools}
        assert "echo" in tool_names
        assert "add" in tool_names
        assert "multiply" in tool_names
    finally:
        await manager.disconnect()


@pytest.mark.timeout(30)
@pytest.mark.asyncio
async def test_invoke_add_tool() -> None:
    """Invoking add with (2, 3) should return 5."""
    manager = MCPManager(_echo_server_config())

    await manager.connect()
    try:
        tools = await manager.get_tools()
        add_tool = next(tool for tool in tools if tool.name == "add")
        result = await add_tool.ainvoke({"a": 2.0, "b": 3.0})
        assert "5" in str(result)
    finally:
        await manager.disconnect()


@pytest.mark.timeout(30)
@pytest.mark.asyncio
async def test_invoke_echo_tool() -> None:
    """Invoking echo should return the input message."""
    manager = MCPManager(_echo_server_config())

    await manager.connect()
    try:
        tools = await manager.get_tools()
        echo_tool = next(tool for tool in tools if tool.name == "echo")
        result = await echo_tool.ainvoke({"message": "hello world"})
        assert "hello world" in str(result)
    finally:
        await manager.disconnect()


@pytest.mark.timeout(30)
@pytest.mark.asyncio
async def test_disconnect_cleans_up() -> None:
    """disconnect() should reset connected state and clear tools."""
    manager = MCPManager(_echo_server_config())

    await manager.connect()
    assert manager.connected is True

    await manager.disconnect()

    assert manager.connected is False
    tools = await manager.get_tools()
    assert tools == []


@pytest.mark.asyncio
async def test_get_tools_before_connect_returns_empty() -> None:
    """get_tools() before connect() should return empty list."""
    manager = MCPManager(_echo_server_config())

    tools = await manager.get_tools()

    assert tools == []


@pytest.mark.asyncio
async def test_disconnect_without_connect_is_noop() -> None:
    """disconnect() without prior connect should not raise."""
    manager = MCPManager(_echo_server_config())

    await manager.disconnect()


@pytest.mark.asyncio
async def test_empty_config_connect_is_noop() -> None:
    """connect() with empty config should be a no-op."""
    manager = MCPManager(MCPConfig(servers=[]))

    await manager.connect()
    tools = await manager.get_tools()

    assert tools == []
    assert manager.connected is False
