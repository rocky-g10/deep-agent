"""Unit tests for LLMRouter."""

from __future__ import annotations

from pydantic import SecretStr

from deep_agent.config import AppSettings
from deep_agent.models import TenantContext
from deep_agent.runtime import LLMRouter


def test_resolve_returns_default_config(
    monkeypatch: object,
    tenant_equities: TenantContext,
) -> None:
    """Default settings should resolve to openai/gpt-5."""
    _ = monkeypatch
    settings = AppSettings(OPENAI_API_KEY=SecretStr("test-key"))
    router = LLMRouter(settings)

    config = router.resolve(tenant_equities)

    assert config.provider == "openai"
    assert config.model == "gpt-5"
    assert config.temperature == 0.0
    assert config.max_tokens == 4096


def test_resolve_with_custom_model(
    monkeypatch: object,
    tenant_equities: TenantContext,
) -> None:
    """Custom OPENAI_MODEL should be reflected by router output."""
    _ = monkeypatch
    settings = AppSettings(OPENAI_API_KEY=SecretStr("test-key"), OPENAI_MODEL="gpt-4o")
    router = LLMRouter(settings)

    config = router.resolve(tenant_equities)

    assert config.model == "gpt-4o"


def test_resolve_ignores_task_hint(
    monkeypatch: object,
    tenant_equities: TenantContext,
) -> None:
    """task_hint is accepted but ignored in Phase 1."""
    _ = monkeypatch
    settings = AppSettings(OPENAI_API_KEY=SecretStr("test-key"))
    router = LLMRouter(settings)

    default_config = router.resolve(tenant_equities, task_hint=None)
    hinted_config = router.resolve(tenant_equities, task_hint="summarize")

    assert default_config == hinted_config


def test_resolve_uses_custom_temperature(
    monkeypatch: object,
    tenant_equities: TenantContext,
) -> None:
    """Custom temperature and token settings should flow into LLMConfig."""
    _ = monkeypatch
    settings = AppSettings(
        OPENAI_API_KEY=SecretStr("test-key"),
        OPENAI_TEMPERATURE=0.7,
        OPENAI_MAX_TOKENS=2048,
    )
    router = LLMRouter(settings)

    config = router.resolve(tenant_equities)

    assert config.temperature == 0.7
    assert config.max_tokens == 2048
