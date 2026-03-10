"""LLM routing for tenant requests."""

from __future__ import annotations

from deep_agent.config import AppSettings
from deep_agent.models import LLMConfig, TenantContext


class LLMRouter:
    """Resolves LLM configuration from application settings."""

    def __init__(self, settings: AppSettings) -> None:
        """Initialize router with settings source."""
        self._settings = settings

    def resolve(self, tenant: TenantContext, task_hint: str | None = None) -> LLMConfig:
        """Return model config for the tenant.

        Args:
            tenant: Tenant context (unused in Phase 1).
            task_hint: Optional intent hint (unused in Phase 1).

        Returns:
            LLMConfig resolved from AppSettings.
        """
        _ = tenant
        _ = task_hint
        return LLMConfig(
            provider="openai",
            model=self._settings.openai_model,
            temperature=self._settings.openai_temperature,
            max_tokens=self._settings.openai_max_tokens,
        )
