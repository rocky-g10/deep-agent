"""Database alias registry for tenant-scoped metadata and connections."""

from __future__ import annotations

import logging

from deep_agent.config import AppSettings
from deep_agent.models import (
    ConnectionConfig,
    DatabaseAlias,
    DatabaseMetadata,
    TableMeta,
    TenantContext,
)

logger = logging.getLogger(__name__)


class AliasNotFoundError(KeyError):
    """Raised when a database alias is not accessible for a tenant."""


_ALIASES: dict[str, DatabaseAlias] = {
    "ch-equities": DatabaseAlias(
        alias="ch-equities",
        engine="clickhouse",
        description="Equities fundamentals — daily OHLCV, splits, dividends",
    )
}

_SCHEMAS: dict[str, list[TableMeta]] = {
    "ch-equities": [
        TableMeta(
            name="fundamentals_daily",
            columns={
                "date": "Date",
                "symbol": "String",
                "open": "Float64",
                "high": "Float64",
                "low": "Float64",
                "close": "Float64",
                "volume": "UInt64",
                "pe_ratio": "Nullable(Float64)",
            },
            row_count_estimate=None,
        )
    ]
}


class DatabaseRegistry:
    """Registry of database aliases with tenant-aware access control."""

    def __init__(self, settings: AppSettings) -> None:
        """Initialize registry with settings used for connection resolution."""
        self._settings = settings

    def list_aliases(self, tenant: TenantContext) -> list[DatabaseAlias]:
        """Return database aliases accessible to the tenant."""
        visible_aliases = [
            db_alias
            for alias, db_alias in sorted(_ALIASES.items())
            if alias in tenant.db_aliases
        ]
        return visible_aliases

    def get_metadata(self, alias: str, tenant: TenantContext) -> DatabaseMetadata:
        """Return schema metadata for an accessible alias."""
        entry = self._get_accessible_alias(alias=alias, tenant=tenant)
        tables = _SCHEMAS.get(alias, [])
        return DatabaseMetadata(alias=alias, engine=entry.engine, tables=tables)

    def get_connection(self, alias: str, tenant: TenantContext) -> ConnectionConfig:
        """Return connection configuration for an accessible alias."""
        entry = self._get_accessible_alias(alias=alias, tenant=tenant)

        return ConnectionConfig(
            engine=entry.engine,
            host=self._settings.clickhouse_host,
            port=self._settings.clickhouse_port,
            database=self._settings.clickhouse_database,
            credentials_ref=f"env://CLICKHOUSE_USER:{self._settings.clickhouse_user}",
        )

    def _get_accessible_alias(self, alias: str, tenant: TenantContext) -> DatabaseAlias:
        if alias not in _ALIASES or alias not in tenant.db_aliases:
            raise AliasNotFoundError(f"Alias '{alias}' not found for tenant '{tenant.tenant_id}'")
        return _ALIASES[alias]
