"""Tenant context data types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TenantContext:
    """Tenant and user scope used throughout the orchestration flow."""

    tenant_id: str
    user_id: str
    skills_dirs: tuple[str, ...]
    db_aliases: tuple[str, ...]

    @classmethod
    def stub(cls) -> TenantContext:
        """Return a hardcoded equities context for local development."""
        return cls(
            tenant_id="equities",
            user_id="dev-user",
            skills_dirs=("skills/common", "skills/equities"),
            db_aliases=("ch-equities",),
        )
