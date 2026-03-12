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
    def stub(cls) -> TenantContext:
        """Return a hardcoded equities context for local development."""
        return cls(
            tenant_id="equities",
            user_id="dev-user",
            mcp_config_path="config/tenants/equities/mcp.json",
            resource_env={
                "ch-equities": {
                    "DB_HOST": "localhost",
                    "DB_PORT": "8123",
                    "DB_USER": "default",
                    "DB_PASS": "",
                    "DB_NAME": "default",
                }
            },
        )
