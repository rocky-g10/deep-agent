"""Tenant context data types."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TenantContext:
    """Tenant and user scope used throughout the orchestration flow."""

    tenant_id: str
    user_id: str
    mcp_config_path: str = ""
    resource_env: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def default(cls) -> TenantContext:
        """Return a generic default context for local development."""
        return cls(
            tenant_id="default",
            user_id="anonymous",
        )
