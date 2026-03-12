"""Unit tests for application configuration."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from deep_agent.config import AppSettings, EnvironmentSettingsProvider


def test_app_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """AppSettings should apply default values for optional fields."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    settings = AppSettings()  # type: ignore[call-arg]

    assert settings.openai_model == "gpt-5"
    assert settings.openai_temperature == 0.0
    assert settings.openai_max_tokens == 4096
    assert settings.skills_root == Path("skills/")
    assert settings.cache_ttl_seconds == 300
    assert settings.log_level == "INFO"


def test_app_settings_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment variables should override defaults."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-override")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1")
    monkeypatch.setenv("OPENAI_TEMPERATURE", "0.7")
    monkeypatch.setenv("OPENAI_MAX_TOKENS", "2048")
    monkeypatch.setenv("SKILLS_ROOT", "/custom/skills")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    settings = AppSettings()  # type: ignore[call-arg]

    assert settings.openai_model == "gpt-4.1"
    assert settings.openai_temperature == 0.7
    assert settings.openai_max_tokens == 2048
    assert settings.skills_root == Path("/custom/skills")
    assert settings.log_level == "DEBUG"


def test_app_settings_api_key_is_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """OPENAI_API_KEY should be stored as SecretStr."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-123")
    settings = AppSettings()  # type: ignore[call-arg]

    assert isinstance(settings.openai_api_key, SecretStr)
    assert settings.openai_api_key.get_secret_value() == "sk-secret-123"
    assert "sk-secret-123" not in str(settings.openai_api_key)


def test_environment_settings_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """EnvironmentSettingsProvider.load() should return an AppSettings instance."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    provider = EnvironmentSettingsProvider()
    settings = provider.load()

    assert isinstance(settings, AppSettings)
    assert settings.openai_api_key.get_secret_value() == "sk-test"
