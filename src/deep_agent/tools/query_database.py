"""query_database LangChain tool factory."""

from __future__ import annotations

import logging

from langchain_core.tools import BaseTool, tool

from deep_agent.database.registry import AliasNotFoundError, DatabaseRegistry
from deep_agent.models import TenantContext

logger = logging.getLogger(__name__)


def create_query_database_tool(
    db_registry: DatabaseRegistry,
    tenant: TenantContext,
) -> BaseTool:
    """Create a query_database tool with injected registry and tenant dependencies."""

    @tool
    def query_database(alias: str = "", action: str = "list_aliases") -> str:
        """Query database metadata by action."""
        if action == "list_aliases":
            return _handle_list_aliases(db_registry=db_registry, tenant=tenant)
        if action == "get_schema":
            return _handle_get_schema(db_registry=db_registry, tenant=tenant, alias=alias)
        return "Unknown action '" + action + "'. Supported actions: list_aliases, get_schema"

    return query_database


def _handle_list_aliases(db_registry: DatabaseRegistry, tenant: TenantContext) -> str:
    """Format all visible aliases for the tenant."""
    aliases = db_registry.list_aliases(tenant)
    if not aliases:
        return "No databases available for this tenant."

    lines = ["Available databases:"]
    for db_alias in aliases:
        lines.append(f"  - {db_alias.alias} ({db_alias.engine}): {db_alias.description}")
    return "\n".join(lines)


def _handle_get_schema(
    db_registry: DatabaseRegistry,
    tenant: TenantContext,
    alias: str,
) -> str:
    """Format schema metadata for a specific alias."""
    if not alias:
        return "Error: 'alias' is required for get_schema action."

    try:
        metadata = db_registry.get_metadata(alias, tenant)
    except AliasNotFoundError:
        return (
            f"Error: Database alias '{alias}' not found. "
            "Use list_aliases to see available databases."
        )

    lines = [f"Database: {metadata.alias} (engine: {metadata.engine})", ""]
    for table in metadata.tables:
        lines.append(f"Table: {table.name}")
        if table.row_count_estimate is None:
            lines.append("  Row count estimate: unknown")
        else:
            lines.append(f"  Row count estimate: ~{table.row_count_estimate} rows")
        lines.append("  Columns:")
        for col_name, col_type in table.columns.items():
            lines.append(f"    - {col_name}: {col_type}")
        lines.append("")

    return "\n".join(lines)
