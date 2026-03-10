"""Database-related models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DatabaseAlias(BaseModel):
    """Tenant-visible database alias descriptor."""

    alias: str
    engine: str
    description: str


class TableMeta(BaseModel):
    """Metadata for a table exposed through an aliased data source."""

    name: str
    columns: dict[str, str]
    row_count_estimate: int | None = Field(default=None)


class DatabaseMetadata(BaseModel):
    """Schema metadata available to the agent without credentials."""

    alias: str
    engine: str
    tables: list[TableMeta]


class ConnectionConfig(BaseModel):
    """Connection details resolved by the registry at execution time."""

    engine: str
    host: str
    port: int
    database: str
    credentials_ref: str
