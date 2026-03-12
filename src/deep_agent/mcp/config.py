"""MCP tenant configuration models and loader."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from deep_agent.models import TenantContext

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_ROOT = Path("config")


class MCPConfigError(ValueError):
    """Raised when MCP configuration is malformed or invalid."""


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server endpoint."""

    name: str
    transport: Literal["stdio", "sse"]
    command: list[str] | None = Field(default=None)
    url: str | None = Field(default=None)
    env: dict[str, str] = Field(default_factory=dict)


class MCPConfig(BaseModel):
    """Top-level MCP configuration for a tenant."""

    servers: list[MCPServerConfig] = Field(default_factory=list)


def load_mcp_config(
    tenant: TenantContext,
    config_root: Path = _DEFAULT_CONFIG_ROOT,
) -> MCPConfig:
    """Load and validate MCP config for a tenant.

    Uses tenant.mcp_config_path when set; otherwise derives path from tenant_id.
    """
    if tenant.mcp_config_path:
        config_path = (config_root / tenant.mcp_config_path).resolve()
    else:
        config_path = (config_root / "tenants" / tenant.tenant_id / "mcp.json").resolve()
    safe_root = config_root.resolve()
    if not config_path.is_relative_to(safe_root):
        raise MCPConfigError("MCP config path escapes config root: path traversal detected")

    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.debug("No MCP config found at %s — using empty config", config_path)
        return MCPConfig()
    except OSError as exc:
        raise MCPConfigError(f"Failed to read MCP config at {config_path}: {exc}") from exc

    try:
        raw_data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise MCPConfigError(f"Malformed JSON in {config_path}: {exc}") from exc

    try:
        config = MCPConfig.model_validate(raw_data)
    except Exception as exc:
        raise MCPConfigError(f"Invalid MCP config in {config_path}: {exc}") from exc

    for server in config.servers:
        if server.transport == "stdio" and not server.command:
            raise MCPConfigError(
                f"MCP server '{server.name}' uses stdio transport but has no 'command' field"
            )
        if server.transport == "sse" and not server.url:
            raise MCPConfigError(
                f"MCP server '{server.name}' uses sse transport but has no 'url' field"
            )

    return config
