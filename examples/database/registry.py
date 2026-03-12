"""Database alias registry — example code, not core framework.

Demonstrates how skills can use resource aliases to connect to data sources.
The core framework provides generic resource env-var injection via TenantContext.resource_env.
"""

from __future__ import annotations

import logging

from examples.database.models import (
    ConnectionConfig,
    DatabaseAlias,
    DatabaseMetadata,
    TableMeta,
)

logger = logging.getLogger(__name__)


class AliasNotFoundError(KeyError):
    """Raised when a database alias is not accessible."""


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
    """Registry of database aliases with tenant-aware access control.

    This is EXAMPLE code showing how a specific data source registry works.
    The core framework is resource-agnostic — it only knows about generic
    env-var sets in TenantContext.resource_env.
    """

    def __init__(self, resource_env: dict[str, dict[str, str]] | None = None) -> None:
        """Initialize registry with optional resource env vars."""
        self._resource_env = resource_env or {}

    def list_aliases(self) -> list[DatabaseAlias]:
        """Return all registered database aliases."""
        return sorted(_ALIASES.values(), key=lambda a: a.alias)

    def get_metadata(self, alias: str) -> DatabaseMetadata:
        """Return schema metadata for an alias."""
        if alias not in _ALIASES:
            raise AliasNotFoundError(f"Alias '{alias}' not found")
        entry = _ALIASES[alias]
        tables = _SCHEMAS.get(alias, [])
        return DatabaseMetadata(alias=alias, engine=entry.engine, tables=tables)

    def get_connection(self, alias: str) -> ConnectionConfig:
        """Return connection configuration for an alias."""
        if alias not in _ALIASES:
            raise AliasNotFoundError(f"Alias '{alias}' not found")
        entry = _ALIASES[alias]
        env = self._resource_env.get(alias, {})
        return ConnectionConfig(
            engine=entry.engine,
            host=env.get("DB_HOST", "localhost"),
            port=int(env.get("DB_PORT", "8123")),
            database=env.get("DB_NAME", "default"),
            credentials_ref=f"env://DB_USER:{env.get('DB_USER', 'default')}",
        )
