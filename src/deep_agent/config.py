"""Application configuration models and loaders."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Protocol

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class SettingsProvider(Protocol):
    """Protocol for objects that return validated app settings."""

    def load(self) -> AppSettings:
        """Load and return application settings."""


class AppSettings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: SecretStr = Field(alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-5", alias="OPENAI_MODEL")
    openai_temperature: float = Field(default=0.0, alias="OPENAI_TEMPERATURE")
    openai_max_tokens: int = Field(default=4096, alias="OPENAI_MAX_TOKENS")

    clickhouse_host: str = Field(default="localhost", alias="CLICKHOUSE_HOST")
    clickhouse_port: int = Field(default=8123, alias="CLICKHOUSE_PORT")
    clickhouse_database: str = Field(default="default", alias="CLICKHOUSE_DATABASE")
    clickhouse_user: str = Field(default="default", alias="CLICKHOUSE_USER")
    clickhouse_password: SecretStr | None = Field(default=None, alias="CLICKHOUSE_PASSWORD")

    skills_root: Path = Field(default=Path("skills/"), alias="SKILLS_ROOT")
    cache_ttl_seconds: int = Field(default=300, alias="CACHE_TTL_SECONDS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


class EnvironmentSettingsProvider:
    """Settings provider that reads configuration from environment variables."""

    def load(self) -> AppSettings:
        """Instantiate and return settings from the current environment."""
        return AppSettings()  # type: ignore[call-arg]


@lru_cache(maxsize=1)
def get_settings(provider: SettingsProvider | None = None) -> AppSettings:
    """Return cached application settings."""
    settings_provider = provider or EnvironmentSettingsProvider()
    return settings_provider.load()
