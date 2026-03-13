"""MCP connection manager for tool discovery."""

from __future__ import annotations

import logging
from typing import Any, cast

from deep_agent.mcp.config import MCPConfig

logger = logging.getLogger(__name__)

try:
    from langchain_mcp_adapters.client import MultiServerMCPClient

    _HAS_MCP_ADAPTERS: bool = True
except ImportError:  # pragma: no cover
    _HAS_MCP_ADAPTERS = False


class MCPManager:
    """Manages MCP server connections and tool discovery."""

    def __init__(self, config: MCPConfig) -> None:
        """Initialize manager with tenant MCP configuration."""
        self._config = config
        self._client: Any | None = None
        self._tools: list[Any] = []
        self._tools_by_server: dict[str, list[Any]] = {}
        self._connected = False

    async def connect(self) -> None:
        """Connect to configured MCP servers and discover tools."""
        if self._client is not None:
            await self.disconnect()

        if not _HAS_MCP_ADAPTERS:
            logger.warning("langchain-mcp-adapters not installed — MCP tools unavailable")
            return

        if not self._config.servers:
            logger.debug("No MCP servers configured — skipping connection")
            return

        server_params = self._build_server_params()
        if not server_params:
            logger.debug("No valid MCP server params available")
            return

        try:
            self._client = MultiServerMCPClient(cast(Any, server_params))
            discovered: list[Any] = []
            discovered_by_server: dict[str, list[Any]] = {}
            for server_name in server_params:
                try:
                    server_tools = await self._client.get_tools(server_name=server_name)
                    for tool in server_tools:
                        _annotate_tool_server(tool, server_name)
                    discovered.extend(server_tools)
                    discovered_by_server[server_name] = list(server_tools)
                except Exception as exc:
                    logger.warning(
                        "Failed to discover tools from MCP server '%s': %s",
                        server_name,
                        exc,
                    )

            self._tools = discovered
            self._tools_by_server = discovered_by_server
            self._connected = bool(discovered)
            logger.info(
                "Connected to %d MCP server(s), discovered %d tool(s)",
                len(server_params),
                len(self._tools),
            )
        except Exception as exc:
            logger.warning("Failed to connect to MCP servers: %s", exc)
            self._client = None
            self._tools = []
            self._tools_by_server = {}
            self._connected = False

    async def get_tools(self) -> list[Any]:
        """Return discovered MCP tools."""
        return list(self._tools)

    async def get_tools_by_server(self) -> dict[str, list[Any]]:
        """Return discovered MCP tools keyed by MCP server name."""
        return {name: list(tools) for name, tools in self._tools_by_server.items()}

    async def disconnect(self) -> None:
        """Disconnect MCP client and clear discovered tools."""
        if self._client is not None:
            try:
                close = getattr(self._client, "close", None) or getattr(
                    self._client, "aclose", None
                )
                if close is not None:
                    result = close()
                    if hasattr(result, "__await__"):
                        await result
            except Exception as exc:
                logger.warning("Error closing MCP client: %s", exc)

        self._client = None
        self._tools = []
        self._tools_by_server = {}
        self._connected = False

    @property
    def connected(self) -> bool:
        """Whether manager currently has an active MCP connection."""
        return self._connected

    @property
    def config(self) -> MCPConfig:
        """Return the MCP configuration used by this manager."""
        return self._config

    def _build_server_params(self) -> dict[str, dict[str, Any]]:
        """Build connection mapping for MultiServerMCPClient."""
        params: dict[str, dict[str, Any]] = {}
        for server in self._config.servers:
            if server.transport == "stdio":
                if not server.command:
                    logger.warning(
                        "MCP server '%s' has stdio transport but no command — skipping",
                        server.name,
                    )
                    continue
                params[server.name] = {
                    "command": server.command[0],
                    "args": server.command[1:],
                    "transport": "stdio",
                    "env": server.env if server.env else None,
                }
                continue

            if server.transport == "sse":
                if not server.url:
                    logger.warning(
                        "MCP server '%s' has sse transport but no url — skipping",
                        server.name,
                    )
                    continue
                params[server.name] = {
                    "url": server.url,
                    "transport": "sse",
                }
                continue

            logger.warning(
                "Unknown transport '%s' for MCP server '%s'", server.transport, server.name
            )
        return params


def _annotate_tool_server(tool: Any, server_name: str) -> None:
    """Attach server metadata to a discovered tool for downstream routing."""
    try:
        tool.mcp_server_name = server_name
    except Exception:
        pass

    metadata = getattr(tool, "metadata", None)
    if isinstance(metadata, dict):
        metadata["mcp_server_name"] = server_name
