"""Unit tests for DatabaseRegistry."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from deep_agent.config import AppSettings
from deep_agent.database import AliasNotFoundError, DatabaseRegistry
from deep_agent.database.registry import _ALIASES
from deep_agent.models import DatabaseAlias, TenantContext


def _tenant_no_db() -> TenantContext:
    return TenantContext(
        tenant_id="empty",
        user_id="test-user",
        skills_dirs=(),
        db_aliases=(),
    )


def _settings() -> AppSettings:
    return AppSettings(OPENAI_API_KEY=SecretStr("test-key"))


def test_list_aliases_returns_ch_equities(tenant_equities: TenantContext) -> None:
    """Equities tenant should see the ch-equities alias."""
    registry = DatabaseRegistry(_settings())

    aliases = registry.list_aliases(tenant_equities)

    assert len(aliases) == 1
    assert aliases[0].alias == "ch-equities"
    assert aliases[0].engine == "clickhouse"


def test_list_aliases_empty_for_no_db_tenant() -> None:
    """Tenant with empty db_aliases should see no databases."""
    registry = DatabaseRegistry(_settings())

    aliases = registry.list_aliases(_tenant_no_db())

    assert aliases == []


def test_get_metadata_returns_fundamentals_table(tenant_equities: TenantContext) -> None:
    """get_metadata should return the fundamentals_daily table schema."""
    registry = DatabaseRegistry(_settings())

    meta = registry.get_metadata("ch-equities", tenant_equities)

    assert meta.alias == "ch-equities"
    assert meta.engine == "clickhouse"
    assert len(meta.tables) == 1
    assert meta.tables[0].name == "fundamentals_daily"
    assert "date" in meta.tables[0].columns
    assert "volume" in meta.tables[0].columns
    assert meta.tables[0].columns["volume"] == "UInt64"
    assert meta.tables[0].columns["pe_ratio"] == "Nullable(Float64)"


def test_get_metadata_unknown_alias_raises(tenant_equities: TenantContext) -> None:
    """Unknown alias should raise AliasNotFoundError."""
    registry = DatabaseRegistry(_settings())

    with pytest.raises(AliasNotFoundError):
        registry.get_metadata("ch-unknown", tenant_equities)


def test_get_metadata_wrong_tenant_raises() -> None:
    """Alias not in tenant's db_aliases should raise AliasNotFoundError."""
    registry = DatabaseRegistry(_settings())

    with pytest.raises(AliasNotFoundError):
        registry.get_metadata("ch-equities", _tenant_no_db())


def test_get_connection_returns_config_from_settings(tenant_equities: TenantContext) -> None:
    """get_connection should populate host/port from AppSettings."""
    settings = AppSettings(
        OPENAI_API_KEY=SecretStr("test-key"),
        CLICKHOUSE_HOST="db.example.com",
        CLICKHOUSE_PORT=9000,
        CLICKHOUSE_DATABASE="equities_db",
    )
    registry = DatabaseRegistry(settings)

    conn = registry.get_connection("ch-equities", tenant_equities)

    assert conn.engine == "clickhouse"
    assert conn.host == "db.example.com"
    assert conn.port == 9000
    assert conn.database == "equities_db"


def test_get_connection_unknown_alias_raises(tenant_equities: TenantContext) -> None:
    """Unknown alias should raise AliasNotFoundError for get_connection."""
    registry = DatabaseRegistry(_settings())

    with pytest.raises(AliasNotFoundError):
        registry.get_connection("ch-unknown", tenant_equities)


def test_metadata_has_all_eight_columns(tenant_equities: TenantContext) -> None:
    """fundamentals_daily should have exactly 8 columns."""
    registry = DatabaseRegistry(_settings())

    meta = registry.get_metadata("ch-equities", tenant_equities)
    columns = meta.tables[0].columns

    expected_columns = {"date", "symbol", "open", "high", "low", "close", "volume", "pe_ratio"}
    assert set(columns.keys()) == expected_columns


def test_get_connection_engine_from_alias(
    monkeypatch: pytest.MonkeyPatch,
    tenant_equities: TenantContext,
) -> None:
    """Connection engine should be sourced from alias metadata."""
    monkeypatch.setitem(
        _ALIASES,
        "ch-equities",
        DatabaseAlias(alias="ch-equities", engine="custom-engine", description="x"),
    )
    registry = DatabaseRegistry(_settings())

    conn = registry.get_connection("ch-equities", tenant_equities)

    assert conn.engine == "custom-engine"
