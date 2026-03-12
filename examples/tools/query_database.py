"""query_database tool — example code, not core framework.

Demonstrates a metadata-query tool backed by DatabaseRegistry.
"""

from __future__ import annotations

import logging

from langchain_core.tools import BaseTool, tool

from examples.database.registry import AliasNotFoundError, DatabaseRegistry

logger = logging.getLogger(__name__)


def create_query_database_tool(db_registry: DatabaseRegistry) -> BaseTool:
    """Create a query_database tool with injected registry."""

    @tool
    def query_database(alias: str = "", action: str = "list_aliases") -> str:
        """Query database metadata by action."""
        if action == "list_aliases":
            return _handle_list_aliases(db_registry)
        if action == "get_schema":
            return _handle_get_schema(db_registry, alias)
        return "Unknown action '" + action + "'. Supported actions: list_aliases, get_schema"

    return query_database


def _handle_list_aliases(db_registry: DatabaseRegistry) -> str:
    aliases = db_registry.list_aliases()
    if not aliases:
        return "No databases available."
    lines = ["Available databases:"]
    for db_alias in aliases:
        lines.append(f"  - {db_alias.alias} ({db_alias.engine}): {db_alias.description}")
    return "\n".join(lines)


def _handle_get_schema(db_registry: DatabaseRegistry, alias: str) -> str:
    if not alias:
        return "Error: 'alias' is required for get_schema action."
    try:
        metadata = db_registry.get_metadata(alias)
    except AliasNotFoundError:
        return f"Error: Database alias '{alias}' not found. Use list_aliases to see available databases."
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
