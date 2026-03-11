# Week 3: Database, Tools, MCP, and Orchestrator — T3.1–T3.9

> **Reference:** `docs/IMPLEMENTATION_PLAN.md` — Week 3 section
> **Depends on:** T1.1–T1.6 (skills layer), T2.1–T2.6 (runtime, sandbox, LLM router)
> **Scope:** Database registry, LangChain tool wrappers (execute_code, query_database), MCP config loader, MCPManager, test MCP server, AgentOrchestrator, and comprehensive unit + integration tests

---

## Batch Layout

| Batch | Tasks | Parallelizable? | Rationale |
|-------|-------|-----------------|-----------|
| **1** | T3.1, T3.6, T3.8 | Yes | No cross-dependencies: DatabaseRegistry depends only on T1.2, MCP config depends only on T1.2, test MCP server has no deps |
| **2** | T3.2, T3.3, T3.7 | Yes | T3.2 depends on T2.4 (SandboxManager), T3.3 depends on T3.1 (DatabaseRegistry), T3.7 depends on T3.6 (MCP config) |
| **3** | T3.4 | No | AgentOrchestrator depends on T3.2, T3.3, T3.7 — must wait for Batch 2 |
| **4** | T3.5, T3.9 | Yes | Tests for everything above: T3.5 tests registry + orchestrator, T3.9 tests MCP config + manager |

---

## T3.1 — DatabaseRegistry (ClickHouse)

Implement `DatabaseRegistry` with a single hardcoded ClickHouse alias (`ch-equities`). The registry provides schema metadata (table/column definitions) and connection configuration resolved from `AppSettings`. Phase 1 hardcodes the schema rather than querying ClickHouse's `system.columns` table — the metadata is baked into code for deterministic offline operation. Tenant scoping is enforced: only aliases listed in `TenantContext.db_aliases` are accessible.

### Files

| File | Action | Purpose |
|------|--------|---------|
| `src/deep_agent/database/registry.py` | Create | `DatabaseRegistry` class + `AliasNotFoundError` |
| `src/deep_agent/database/__init__.py` | Modify | Add exports: `DatabaseRegistry`, `AliasNotFoundError` |

### Interface

```python
# src/deep_agent/database/registry.py
from __future__ import annotations

import logging
from typing import Any

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
    """Raised when a database alias is not registered or not accessible for a tenant."""


class DatabaseRegistry:
    """Registry of database aliases with schema metadata and connection resolution.

    Phase 1: single hardcoded alias (ch-equities) with ClickHouse config
    from AppSettings. Schema metadata is embedded in code.
    """

    def __init__(self, settings: AppSettings) -> None:
        """Initialize registry with application settings for connection resolution.

        Args:
            settings: Application settings containing ClickHouse connection config.
        """

    def list_aliases(self, tenant: TenantContext) -> list[DatabaseAlias]:
        """Return database aliases accessible to the given tenant.

        Args:
            tenant: Current tenant context with db_aliases whitelist.

        Returns:
            List of DatabaseAlias descriptors visible to this tenant.
        """

    def get_metadata(self, alias: str, tenant: TenantContext) -> DatabaseMetadata:
        """Return schema metadata (tables, columns, types) for a database alias.

        Args:
            alias: Database alias identifier (e.g. "ch-equities").
            tenant: Current tenant context for access control.

        Returns:
            DatabaseMetadata with table and column information.

        Raises:
            AliasNotFoundError: If alias does not exist or tenant lacks access.
        """

    def get_connection(self, alias: str, tenant: TenantContext) -> ConnectionConfig:
        """Return connection configuration for a database alias.

        Args:
            alias: Database alias identifier.
            tenant: Current tenant context for access control.

        Returns:
            ConnectionConfig with host, port, database, and credentials reference.

        Raises:
            AliasNotFoundError: If alias does not exist or tenant lacks access.
        """
```

### Implementation Details

**Internal data structures:**

```python
# Hardcoded registry — Phase 1
_ALIASES: dict[str, DatabaseAlias] = {
    "ch-equities": DatabaseAlias(
        alias="ch-equities",
        engine="clickhouse",
        description="Equities fundamentals — daily OHLCV, splits, dividends",
    ),
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
        ),
    ],
}
```

**`__init__(settings)`:**
- Store `self._settings = settings`

**`list_aliases(tenant)`:**
1. Filter `_ALIASES` to include only keys present in `tenant.db_aliases`
2. Return the filtered `DatabaseAlias` list, sorted by alias name

**`get_metadata(alias, tenant)`:**
1. Check that `alias` is in `_ALIASES` AND in `tenant.db_aliases` — otherwise raise `AliasNotFoundError(f"Alias '{alias}' not found for tenant '{tenant.tenant_id}'")`
2. Retrieve the alias entry and schema tables from `_SCHEMAS`
3. Return `DatabaseMetadata(alias=alias, engine=entry.engine, tables=tables)`

**`get_connection(alias, tenant)`:**
1. Same access check as `get_metadata`
2. Return `ConnectionConfig(engine="clickhouse", host=self._settings.clickhouse_host, port=self._settings.clickhouse_port, database=self._settings.clickhouse_database, credentials_ref=f"env://CLICKHOUSE_USER:{self._settings.clickhouse_user}")`

### Connections to Week 1/2

- Imports `DatabaseAlias`, `DatabaseMetadata`, `TableMeta`, `ConnectionConfig` from `deep_agent.models.database` (T1.2)
- Imports `TenantContext` from `deep_agent.models.context` (T1.2)
- Imports `AppSettings` from `deep_agent.config` (T1.1)
- Used by `query_database` tool (T3.3) and `execute_code` tool (T3.2) for env var injection
- Used by `AgentOrchestrator` (T3.4) for system prompt database metadata

### Acceptance Criteria

1. `list_aliases(tenant)` returns `[DatabaseAlias(alias="ch-equities", ...)]` for the equities tenant
2. `get_metadata("ch-equities", tenant)` returns `DatabaseMetadata` with table `fundamentals_daily` and all 8 columns (`date`, `symbol`, `open`, `high`, `low`, `close`, `volume`, `pe_ratio`) with correct ClickHouse types
3. `get_connection("ch-equities", tenant)` returns `ConnectionConfig` with host/port/database from `AppSettings`
4. `AliasNotFoundError` raised for unknown alias (e.g. `"ch-unknown"`)
5. `AliasNotFoundError` raised when alias exists but tenant lacks access (e.g. tenant with `db_aliases=["ch-risk"]` requesting `"ch-equities"`)
6. Module-level constants `_ALIASES` and `_SCHEMAS` hold the hardcoded Phase 1 data

### Edge Cases

- Tenant with empty `db_aliases=[]` — `list_aliases` returns `[]`, `get_metadata`/`get_connection` always raise
- Alias exists but not in tenant's whitelist — treated as not found (no information leakage)
- Multiple calls with same alias — returns identical objects (immutable data)

---

## T3.2 — execute_code Tool

LangChain-compatible tool that wraps `SandboxManager.execute()`. Uses a factory function pattern to inject `SandboxManager` and `DatabaseRegistry` dependencies at construction time, producing a bound `@tool`-decorated function. The factory injects ClickHouse connection details as environment variables (`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASS`, `DB_NAME`) so sandbox code can connect to databases. Errors (timeout, crashes) are returned as formatted output rather than raised as exceptions, allowing the agent to self-correct.

### Files

| File | Action | Purpose |
|------|--------|---------|
| `src/deep_agent/tools/execute_code.py` | Create | `create_execute_code_tool` factory + tool definition |
| `src/deep_agent/tools/__init__.py` | Modify | Add export: `create_execute_code_tool` |

### Interface

```python
# src/deep_agent/tools/execute_code.py
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from langchain_core.tools import BaseTool, tool

from deep_agent.database.registry import DatabaseRegistry
from deep_agent.models import TenantContext
from deep_agent.sandbox.protocol import SandboxManager

logger = logging.getLogger(__name__)


def create_execute_code_tool(
    sandbox: SandboxManager,
    db_registry: DatabaseRegistry,
    tenant: TenantContext,
) -> BaseTool:
    """Create an execute_code LangChain tool with injected dependencies.

    Args:
        sandbox: SandboxManager instance for code execution.
        db_registry: DatabaseRegistry for resolving database env vars.
        tenant: Current tenant context for database access.

    Returns:
        A LangChain BaseTool named "execute_code".
    """
```

### Implementation Details

**Factory function `create_execute_code_tool()`:**

```python
def create_execute_code_tool(
    sandbox: SandboxManager,
    db_registry: DatabaseRegistry,
    tenant: TenantContext,
) -> BaseTool:
    db_env = _build_db_env(db_registry, tenant)

    @tool
    async def execute_code(code: str, timeout: int = 60) -> str:
        """Execute Python code in a sandboxed environment.

        The sandbox has access to database connection environment variables
        (DB_HOST, DB_PORT, DB_USER, DB_PASS, DB_NAME) and the firm.stats
        library. Save output files (charts, CSVs) to the output/ directory.

        Args:
            code: Python source code to execute.
            timeout: Maximum execution time in seconds (default: 60).

        Returns:
            JSON string with exit_code, stdout, stderr, and output_files.
        """
        try:
            result = await sandbox.execute(code=code, timeout=timeout, env=db_env)
            return json.dumps(
                {
                    "exit_code": result.exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "output_files": result.output_files,
                    "duration_ms": result.duration_ms,
                },
                indent=2,
            )
        except Exception as exc:
            logger.exception("execute_code tool error")
            return json.dumps(
                {
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": f"Tool execution error: {exc}",
                    "output_files": {},
                    "duration_ms": 0,
                }
            )

    return execute_code  # type: ignore[return-value]
```

**Helper `_build_db_env()`:**

```python
def _build_db_env(db_registry: DatabaseRegistry, tenant: TenantContext) -> dict[str, str]:
    """Build database environment variables from all accessible aliases."""
    env: dict[str, str] = {}
    for alias_info in db_registry.list_aliases(tenant):
        try:
            conn = db_registry.get_connection(alias_info.alias, tenant)
            env["DB_HOST"] = conn.host
            env["DB_PORT"] = str(conn.port)
            env["DB_NAME"] = conn.database
            env["DB_USER"] = "default"  # Phase 1: extract from credentials_ref
            env["DB_PASS"] = ""  # Phase 1: no password for local dev
        except Exception:
            logger.warning("Failed to resolve connection for alias %s", alias_info.alias)
    return env
```

**Key design decisions:**
- The `@tool` decorator creates the LangChain tool with name `"execute_code"` (derived from function name)
- The inner function is `async` because `sandbox.execute()` is async
- Dependencies are captured via closure — the factory returns a fully-bound tool
- Return type is always a JSON string — the agent parses the structured output
- Errors are caught and returned as output (never raised), so the LLM can self-correct

### Connections to Week 1/2

- Imports `SandboxManager` protocol from `deep_agent.sandbox.protocol` (T2.4)
- Imports `DatabaseRegistry` from `deep_agent.database.registry` (T3.1)
- Imports `TenantContext` from `deep_agent.models.context` (T1.2)
- Used by `AgentOrchestrator` (T3.4) as one of the built-in tools

### Acceptance Criteria

1. `create_execute_code_tool(sandbox, db_registry, tenant)` returns a `BaseTool` with `name="execute_code"`
2. Tool input schema accepts `code: str` and optional `timeout: int`
3. Successful execution returns JSON with `exit_code=0`, stdout, stderr, output_files, duration_ms
4. Timeout returns JSON with `exit_code != 0` and stderr mentioning timeout — no exception raised
5. Syntax error in code returns JSON with `exit_code != 0` and SyntaxError in stderr
6. Database env vars (`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASS`, `DB_NAME`) injected from registry
7. Unexpected exceptions caught and returned as JSON error output

### Edge Cases

- No accessible database aliases — `db_env` is empty dict, tool still works (code that doesn't use DB)
- Multiple database aliases — last alias wins for env vars (Phase 1: only one alias)
- Very large stdout — truncation handled by `SandboxManager`, tool passes through
- `sandbox.execute()` raises unexpected exception — caught, returned as error JSON

---

## T3.3 — query_database Tool

LangChain-compatible tool providing database schema discovery. Uses the same factory/closure pattern as `execute_code` to inject `DatabaseRegistry` and `TenantContext`. The tool supports two actions: `list_aliases` (enumerate available databases) and `get_schema` (retrieve table/column metadata for a specific alias). This is metadata-only — no query execution. The agent uses this tool to understand database structure before writing code.

### Files

| File | Action | Purpose |
|------|--------|---------|
| `src/deep_agent/tools/query_database.py` | Create | `create_query_database_tool` factory + tool definition |
| `src/deep_agent/tools/__init__.py` | Modify | Add export: `create_query_database_tool` |

### Interface

```python
# src/deep_agent/tools/query_database.py
from __future__ import annotations

import logging
from typing import Literal

from langchain_core.tools import BaseTool, tool

from deep_agent.database.registry import AliasNotFoundError, DatabaseRegistry
from deep_agent.models import TenantContext

logger = logging.getLogger(__name__)


def create_query_database_tool(
    db_registry: DatabaseRegistry,
    tenant: TenantContext,
) -> BaseTool:
    """Create a query_database LangChain tool with injected dependencies.

    Args:
        db_registry: DatabaseRegistry for schema metadata retrieval.
        tenant: Current tenant context for database access.

    Returns:
        A LangChain BaseTool named "query_database".
    """
```

### Implementation Details

```python
def create_query_database_tool(
    db_registry: DatabaseRegistry,
    tenant: TenantContext,
) -> BaseTool:

    @tool
    def query_database(alias: str = "", action: str = "list_aliases") -> str:
        """Query database metadata — list available databases or get table schemas.

        This tool provides database discovery only (no query execution).
        Use execute_code to run actual SQL queries.

        Args:
            alias: Database alias to inspect (required for get_schema action).
            action: One of "list_aliases" or "get_schema".

        Returns:
            Formatted text with database metadata or an error message.
        """
        if action == "list_aliases":
            return _handle_list_aliases(db_registry, tenant)
        elif action == "get_schema":
            return _handle_get_schema(db_registry, tenant, alias)
        else:
            return f"Unknown action '{action}'. Supported actions: list_aliases, get_schema"

    return query_database  # type: ignore[return-value]
```

**Helper functions:**

```python
def _handle_list_aliases(db_registry: DatabaseRegistry, tenant: TenantContext) -> str:
    """Format available database aliases as readable text."""
    aliases = db_registry.list_aliases(tenant)
    if not aliases:
        return "No databases available for this tenant."
    lines = ["Available databases:"]
    for db_alias in aliases:
        lines.append(f"  - {db_alias.alias} ({db_alias.engine}): {db_alias.description}")
    return "\n".join(lines)


def _handle_get_schema(
    db_registry: DatabaseRegistry, tenant: TenantContext, alias: str
) -> str:
    """Format table/column metadata as readable text."""
    if not alias:
        return "Error: 'alias' is required for get_schema action."
    try:
        metadata = db_registry.get_metadata(alias, tenant)
    except AliasNotFoundError:
        return f"Error: Database alias '{alias}' not found. Use list_aliases to see available databases."

    lines = [f"Database: {metadata.alias} (engine: {metadata.engine})", ""]
    for table in metadata.tables:
        lines.append(f"Table: {table.name}")
        estimate = f" (~{table.row_count_estimate} rows)" if table.row_count_estimate else ""
        lines.append(f"  Row count estimate:{estimate}")
        lines.append("  Columns:")
        for col_name, col_type in table.columns.items():
            lines.append(f"    - {col_name}: {col_type}")
        lines.append("")
    return "\n".join(lines)
```

**Key design decisions:**
- `query_database` is synchronous (no async) because `DatabaseRegistry` methods are synchronous
- `action` parameter is a plain `str` rather than `Literal` in the runtime signature — LangChain's `@tool` decorator handles schema generation from the docstring, and using `str` avoids tool invocation failures when the LLM sends an unexpected value
- Unknown actions return a clear error message (not an exception) so the agent can retry
- Missing alias for `get_schema` returns a clear error message
- Output is human-readable text (not JSON) since this is informational metadata for the LLM

### Connections to Week 1/2

- Imports `DatabaseRegistry`, `AliasNotFoundError` from `deep_agent.database.registry` (T3.1)
- Imports `TenantContext` from `deep_agent.models.context` (T1.2)
- Used by `AgentOrchestrator` (T3.4) as one of the built-in tools

### Acceptance Criteria

1. `create_query_database_tool(db_registry, tenant)` returns a `BaseTool` with `name="query_database"`
2. `action="list_aliases"` returns formatted text listing `ch-equities` with description
3. `action="get_schema"` with `alias="ch-equities"` returns table `fundamentals_daily` with all column names and types
4. Unknown alias returns clear error message (not an exception): `"Error: Database alias 'bad' not found..."`
5. Unknown action returns clear error message listing supported actions
6. Missing alias for `get_schema` returns clear error message
7. Tenant with no accessible aliases returns `"No databases available for this tenant."`

### Edge Cases

- Empty alias string with `get_schema` — error message prompts providing alias
- Alias exists but tenant lacks access — treated as not found (same as `AliasNotFoundError`)
- `action` parameter has unexpected casing (e.g. `"LIST_ALIASES"`) — returns unknown action error (case-sensitive matching, consistent with LLM tool calling)

---

## T3.4 — AgentOrchestrator

Central coordinator that ties together `SkillEngine`, `LLMRouter`, `RuntimeAdapter`, `SandboxManager`, `DatabaseRegistry`, and `MCPManager` into a single `handle_message` flow. Given a user message and tenant context, the orchestrator: discovers skills, matches the best skill, loads its instructions, resolves database metadata, gathers MCP tools, builds a system prompt, filters tools by the matched skill's `allowed_tools`, creates an agent graph, and streams response events. The orchestrator is the only component the API layer calls directly.

### Files

| File | Action | Purpose |
|------|--------|---------|
| `src/deep_agent/orchestrator/agent_orchestrator.py` | Create | `AgentOrchestrator` class |
| `src/deep_agent/orchestrator/__init__.py` | Modify | Add export: `AgentOrchestrator` |

### Interface

```python
# src/deep_agent/orchestrator/agent_orchestrator.py
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from deep_agent.config import AppSettings
from deep_agent.database.registry import DatabaseRegistry
from deep_agent.mcp.manager import MCPManager
from deep_agent.models import (
    AgentEvent,
    ErrorEvent,
    SkillMatchEvent,
    TenantContext,
)
from deep_agent.runtime.protocol import RuntimeAdapter
from deep_agent.runtime.llm_router import LLMRouter
from deep_agent.sandbox.protocol import SandboxManager
from deep_agent.skills.engine import SkillEngine
from deep_agent.tools.execute_code import create_execute_code_tool
from deep_agent.tools.query_database import create_query_database_tool

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """Orchestrates the complete agent interaction flow.

    Connects skill matching, tool discovery, prompt construction,
    and runtime streaming into a single handle_message entry point.
    """

    def __init__(
        self,
        skill_engine: SkillEngine,
        llm_router: LLMRouter,
        runtime: RuntimeAdapter,
        sandbox: SandboxManager,
        db_registry: DatabaseRegistry,
        mcp_manager: MCPManager | None = None,
    ) -> None:
        """Initialize orchestrator with all required services.

        Args:
            skill_engine: Engine for skill discovery, matching, and loading.
            llm_router: Router for resolving LLM configuration.
            runtime: RuntimeAdapter for agent creation and streaming.
            sandbox: SandboxManager for code execution.
            db_registry: DatabaseRegistry for database metadata and connections.
            mcp_manager: Optional MCPManager for MCP tool discovery.
        """

    async def handle_message(
        self,
        message: str,
        context: TenantContext,
    ) -> AsyncIterator[AgentEvent]:
        """Process a user message and stream agent response events.

        Flow:
        1. Discover and match skills for the tenant
        2. Yield SkillMatchEvent for the top match
        3. Load matched skill body
        4. Gather MCP tools (if MCPManager configured)
        5. Build and filter tool set by skill's allowed_tools
        6. Construct system prompt
        7. Create agent and stream response

        Args:
            message: User's natural language message.
            context: Tenant context for access control and routing.

        Yields:
            AgentEvent objects: SkillMatchEvent, AgentChunkEvent,
            ToolCallEvent, ToolResultEvent, AgentCompleteEvent, or ErrorEvent.
        """
```

### Implementation Details

**Constructor:**

```python
def __init__(
    self,
    skill_engine: SkillEngine,
    llm_router: LLMRouter,
    runtime: RuntimeAdapter,
    sandbox: SandboxManager,
    db_registry: DatabaseRegistry,
    mcp_manager: MCPManager | None = None,
) -> None:
    self._skill_engine = skill_engine
    self._llm_router = llm_router
    self._runtime = runtime
    self._sandbox = sandbox
    self._db_registry = db_registry
    self._mcp_manager = mcp_manager
```

**`handle_message()` flow:**

```python
async def handle_message(
    self,
    message: str,
    context: TenantContext,
) -> AsyncIterator[AgentEvent]:
    try:
        # 1. Match skills
        matched_skills = self._skill_engine.match(message, context, top_k=1)
        skill_content = None
        allowed_tools: list[str] | None = None

        if matched_skills:
            top_match = matched_skills[0]
            yield SkillMatchEvent(
                skill_id=top_match.skill_id,
                confidence=1.0,  # Phase 1: binary match
            )
            try:
                skill_content = self._skill_engine.load(top_match.skill_id, context)
                allowed_tools = skill_content.allowed_tools
            except Exception as exc:
                logger.warning("Failed to load skill %s: %s", top_match.skill_id, exc)

        # 2. Build tools
        builtin_tools = self._build_builtin_tools(context)
        mcp_tools = await self._get_mcp_tools()
        all_tools = builtin_tools + mcp_tools

        # 3. Filter tools by allowed_tools
        if allowed_tools is not None:
            all_tools = _filter_tools(all_tools, allowed_tools)

        # 4. Build system prompt
        system_prompt = self._build_system_prompt(
            context=context,
            skill_content=skill_content,
            all_skills=self._skill_engine.discover(context),
        )

        # 5. Resolve LLM config and create agent
        llm_config = self._llm_router.resolve(context)
        agent = self._runtime.create_agent(
            model=llm_config.model,
            tools=all_tools,
            system_prompt=system_prompt,
            temperature=llm_config.temperature,
        )

        # 6. Stream response
        async for event in self._runtime.stream(agent, message, context):
            yield event

    except Exception as exc:
        logger.exception("Orchestrator error")
        yield ErrorEvent(code="ORCHESTRATOR_ERROR", message=str(exc))
```

**`_build_builtin_tools()`:**

```python
def _build_builtin_tools(self, context: TenantContext) -> list[Any]:
    """Create the standard built-in tools with injected dependencies."""
    tools: list[Any] = []
    tools.append(
        create_execute_code_tool(
            sandbox=self._sandbox,
            db_registry=self._db_registry,
            tenant=context,
        )
    )
    tools.append(
        create_query_database_tool(
            db_registry=self._db_registry,
            tenant=context,
        )
    )
    return tools
```

**`_get_mcp_tools()`:**

```python
async def _get_mcp_tools(self) -> list[Any]:
    """Retrieve MCP tools if MCPManager is configured."""
    if self._mcp_manager is None:
        return []
    try:
        return await self._mcp_manager.get_tools()
    except Exception as exc:
        logger.warning("Failed to get MCP tools: %s", exc)
        return []
```

**Tool filtering — `_filter_tools()`:**

```python
def _filter_tools(tools: list[Any], allowed_tools: list[str]) -> list[Any]:
    """Filter tools by name against the skill's allowed_tools list.

    Each tool is expected to have a `.name` attribute (LangChain BaseTool convention).
    A tool is included if its name appears in the allowed_tools list.
    """
    allowed_set = set(allowed_tools)
    return [t for t in tools if getattr(t, "name", None) in allowed_set]
```

**System prompt builder — `_build_system_prompt()`:**

```python
def _build_system_prompt(
    self,
    context: TenantContext,
    skill_content: Any | None,
    all_skills: list[Any],
) -> str:
    """Construct the full system prompt with skills, databases, and instructions."""
    parts: list[str] = []

    # Header
    parts.append(
        f"You are Deep Agent, an AI assistant for the {context.tenant_id} desk."
    )

    # Available Skills section
    if all_skills:
        parts.append("")
        parts.append("## Available Skills")
        for skill_summary in all_skills:
            parts.append(f"- {skill_summary.name}: {skill_summary.description}")

    # Active Skill section (matched skill body)
    if skill_content is not None:
        parts.append("")
        parts.append(f"## Active Skill: {skill_content.name}")
        parts.append(skill_content.body)

    # Database section
    aliases = self._db_registry.list_aliases(context)
    if aliases:
        parts.append("")
        parts.append("## Available Databases")
        for db_alias in aliases:
            parts.append(
                f"- {db_alias.alias} ({db_alias.engine}): {db_alias.description}"
            )
        # Include schema details for each alias
        for db_alias in aliases:
            try:
                meta = self._db_registry.get_metadata(db_alias.alias, context)
                for table in meta.tables:
                    parts.append(f"\n### Table: {table.name}")
                    parts.append("Columns:")
                    for col_name, col_type in table.columns.items():
                        parts.append(f"  - {col_name}: {col_type}")
            except Exception:
                pass  # Skip schemas that fail to load

    # Tool usage instructions
    parts.append("")
    parts.append("## Tool Usage")
    parts.append("- Use `query_database` to discover schema before writing queries.")
    parts.append("- Use `execute_code` to run Python code in a sandboxed environment.")
    parts.append(
        "- Database credentials are available as env vars: "
        "DB_HOST, DB_PORT, DB_USER, DB_PASS, DB_NAME."
    )
    parts.append("- Save output files (charts, CSVs) to the output/ directory.")

    return "\n".join(parts)
```

### Connections to Week 1/2

- Imports `SkillEngine`, `SkillNotFoundError` from `deep_agent.skills.engine` (T1.4)
- Imports `LLMRouter` from `deep_agent.runtime.llm_router` (T2.1)
- Imports `RuntimeAdapter` from `deep_agent.runtime.protocol` (T2.2)
- Imports `SandboxManager` from `deep_agent.sandbox.protocol` (T2.4)
- Imports `DatabaseRegistry` from `deep_agent.database.registry` (T3.1)
- Imports `MCPManager` from `deep_agent.mcp.manager` (T3.7)
- Imports `create_execute_code_tool` from `deep_agent.tools.execute_code` (T3.2)
- Imports `create_query_database_tool` from `deep_agent.tools.query_database` (T3.3)
- Imports all `AgentEvent` subtypes from `deep_agent.models.events` (T1.2)
- Used by WebSocket API (T4.1) as the single entry point for message handling

### Acceptance Criteria

1. Constructor accepts `skill_engine`, `llm_router`, `runtime`, `sandbox`, `db_registry`, and optional `mcp_manager`
2. `handle_message()` yields `SkillMatchEvent` as the first event when a skill matches
3. System prompt contains available skill summaries, matched skill body, database metadata, and tool usage instructions
4. Tools are filtered by matched skill's `allowed_tools` list — only tools whose `.name` is in `allowed_tools` are passed to the agent
5. When no skills match, agent runs with base instructions and ALL tools (no filtering)
6. When `mcp_manager` is `None`, orchestrator works with only built-in tools
7. MCP tool discovery failures are logged and gracefully degraded (empty MCP tools)
8. Unexpected errors during orchestration yield `ErrorEvent` with code `"ORCHESTRATOR_ERROR"`
9. LLM config (model, temperature) resolved via `LLMRouter.resolve()` and passed to `runtime.create_agent()`

### Edge Cases

- No skills match the query — `allowed_tools` is `None`, no filtering applied, base prompt used
- Matched skill fails to load — logs warning, continues without skill body, no tool filtering
- MCP manager configured but `get_tools()` raises — returns empty MCP tools list
- Database registry has no aliases for tenant — database section omitted from prompt
- Runtime `stream()` yields `ErrorEvent` — passed through unchanged to caller
- Empty message string — still processes through the full flow (LLM handles empty input)

---

## T3.5 — Unit Tests for DatabaseRegistry, Tools, and Orchestrator

Comprehensive unit tests covering the `DatabaseRegistry`, tool factories (`execute_code`, `query_database`), and the `AgentOrchestrator`. All tests use mocked dependencies — no real LLM calls, no real sandbox execution, no real database connections.

### Files

| File | Action | Purpose |
|------|--------|---------|
| `tests/unit/test_database_registry.py` | Create | DatabaseRegistry tests |
| `tests/unit/test_tools.py` | Create | execute_code and query_database tool tests |
| `tests/unit/test_orchestrator.py` | Create | AgentOrchestrator tests |

### test_database_registry.py

```python
"""Unit tests for DatabaseRegistry."""

from __future__ import annotations

import pytest

from deep_agent.config import AppSettings
from deep_agent.database import AliasNotFoundError, DatabaseRegistry
from deep_agent.models import TenantContext


def _tenant_equities() -> TenantContext:
    return TenantContext(
        tenant_id="equities",
        user_id="test-user",
        skills_dirs=["skills/common", "skills/equities"],
        db_aliases=["ch-equities"],
    )


def _tenant_no_db() -> TenantContext:
    return TenantContext(
        tenant_id="empty",
        user_id="test-user",
        skills_dirs=[],
        db_aliases=[],
    )


def _settings() -> AppSettings:
    return AppSettings(OPENAI_API_KEY="test-key")


def test_list_aliases_returns_ch_equities() -> None:
    """Equities tenant should see the ch-equities alias."""
    registry = DatabaseRegistry(_settings())

    aliases = registry.list_aliases(_tenant_equities())

    assert len(aliases) == 1
    assert aliases[0].alias == "ch-equities"
    assert aliases[0].engine == "clickhouse"


def test_list_aliases_empty_for_no_db_tenant() -> None:
    """Tenant with empty db_aliases should see no databases."""
    registry = DatabaseRegistry(_settings())

    aliases = registry.list_aliases(_tenant_no_db())

    assert aliases == []


def test_get_metadata_returns_fundamentals_table() -> None:
    """get_metadata should return the fundamentals_daily table schema."""
    registry = DatabaseRegistry(_settings())

    meta = registry.get_metadata("ch-equities", _tenant_equities())

    assert meta.alias == "ch-equities"
    assert meta.engine == "clickhouse"
    assert len(meta.tables) == 1
    assert meta.tables[0].name == "fundamentals_daily"
    assert "date" in meta.tables[0].columns
    assert "volume" in meta.tables[0].columns
    assert meta.tables[0].columns["volume"] == "UInt64"
    assert meta.tables[0].columns["pe_ratio"] == "Nullable(Float64)"


def test_get_metadata_unknown_alias_raises() -> None:
    """Unknown alias should raise AliasNotFoundError."""
    registry = DatabaseRegistry(_settings())

    with pytest.raises(AliasNotFoundError):
        registry.get_metadata("ch-unknown", _tenant_equities())


def test_get_metadata_wrong_tenant_raises() -> None:
    """Alias not in tenant's db_aliases should raise AliasNotFoundError."""
    registry = DatabaseRegistry(_settings())

    with pytest.raises(AliasNotFoundError):
        registry.get_metadata("ch-equities", _tenant_no_db())


def test_get_connection_returns_config_from_settings() -> None:
    """get_connection should populate host/port from AppSettings."""
    settings = AppSettings(
        OPENAI_API_KEY="test-key",
        CLICKHOUSE_HOST="db.example.com",
        CLICKHOUSE_PORT=9000,
        CLICKHOUSE_DATABASE="equities_db",
    )
    registry = DatabaseRegistry(settings)

    conn = registry.get_connection("ch-equities", _tenant_equities())

    assert conn.engine == "clickhouse"
    assert conn.host == "db.example.com"
    assert conn.port == 9000
    assert conn.database == "equities_db"


def test_get_connection_unknown_alias_raises() -> None:
    """Unknown alias should raise AliasNotFoundError for get_connection."""
    registry = DatabaseRegistry(_settings())

    with pytest.raises(AliasNotFoundError):
        registry.get_connection("ch-unknown", _tenant_equities())


def test_metadata_has_all_eight_columns() -> None:
    """fundamentals_daily should have exactly 8 columns."""
    registry = DatabaseRegistry(_settings())

    meta = registry.get_metadata("ch-equities", _tenant_equities())
    columns = meta.tables[0].columns

    expected_columns = {"date", "symbol", "open", "high", "low", "close", "volume", "pe_ratio"}
    assert set(columns.keys()) == expected_columns
```

### test_tools.py

```python
"""Unit tests for execute_code and query_database tool factories."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from deep_agent.models import ExecuteResult, TenantContext


def _tenant() -> TenantContext:
    return TenantContext(
        tenant_id="equities",
        user_id="test-user",
        skills_dirs=["skills/common", "skills/equities"],
        db_aliases=["ch-equities"],
    )


# --- execute_code tool tests ---

async def test_execute_code_tool_has_correct_name() -> None:
    """Factory should produce a tool named 'execute_code'."""
    from deep_agent.tools.execute_code import create_execute_code_tool

    sandbox = AsyncMock()
    db_registry = MagicMock()
    db_registry.list_aliases.return_value = []

    tool = create_execute_code_tool(sandbox, db_registry, _tenant())

    assert tool.name == "execute_code"


async def test_execute_code_tool_returns_json() -> None:
    """Successful execution should return valid JSON with expected fields."""
    from deep_agent.tools.execute_code import create_execute_code_tool

    sandbox = AsyncMock()
    sandbox.execute.return_value = ExecuteResult(
        execution_id="exec-1",
        exit_code=0,
        stdout="hello\n",
        stderr="",
        output_files={},
        duration_ms=50,
    )
    db_registry = MagicMock()
    db_registry.list_aliases.return_value = []

    tool = create_execute_code_tool(sandbox, db_registry, _tenant())
    result = await tool.ainvoke({"code": "print('hello')"})

    parsed = json.loads(result)
    assert parsed["exit_code"] == 0
    assert parsed["stdout"] == "hello\n"


async def test_execute_code_tool_handles_sandbox_error() -> None:
    """Sandbox exceptions should be returned as error output, not raised."""
    from deep_agent.tools.execute_code import create_execute_code_tool

    sandbox = AsyncMock()
    sandbox.execute.side_effect = RuntimeError("sandbox crashed")
    db_registry = MagicMock()
    db_registry.list_aliases.return_value = []

    tool = create_execute_code_tool(sandbox, db_registry, _tenant())
    result = await tool.ainvoke({"code": "print('hello')"})

    parsed = json.loads(result)
    assert parsed["exit_code"] == -1
    assert "sandbox crashed" in parsed["stderr"]


# --- query_database tool tests ---

def test_query_database_tool_has_correct_name() -> None:
    """Factory should produce a tool named 'query_database'."""
    from deep_agent.tools.query_database import create_query_database_tool

    db_registry = MagicMock()
    tool = create_query_database_tool(db_registry, _tenant())

    assert tool.name == "query_database"


def test_query_database_list_aliases() -> None:
    """list_aliases action should return formatted alias text."""
    from deep_agent.database.registry import DatabaseRegistry
    from deep_agent.config import AppSettings
    from deep_agent.tools.query_database import create_query_database_tool

    settings = AppSettings(OPENAI_API_KEY="test-key")
    db_registry = DatabaseRegistry(settings)
    tool = create_query_database_tool(db_registry, _tenant())

    result = tool.invoke({"alias": "", "action": "list_aliases"})

    assert "ch-equities" in result
    assert "clickhouse" in result


def test_query_database_get_schema() -> None:
    """get_schema action should return table and column info."""
    from deep_agent.database.registry import DatabaseRegistry
    from deep_agent.config import AppSettings
    from deep_agent.tools.query_database import create_query_database_tool

    settings = AppSettings(OPENAI_API_KEY="test-key")
    db_registry = DatabaseRegistry(settings)
    tool = create_query_database_tool(db_registry, _tenant())

    result = tool.invoke({"alias": "ch-equities", "action": "get_schema"})

    assert "fundamentals_daily" in result
    assert "volume" in result
    assert "UInt64" in result


def test_query_database_unknown_alias() -> None:
    """Unknown alias should return error message, not raise exception."""
    from deep_agent.database.registry import DatabaseRegistry
    from deep_agent.config import AppSettings
    from deep_agent.tools.query_database import create_query_database_tool

    settings = AppSettings(OPENAI_API_KEY="test-key")
    db_registry = DatabaseRegistry(settings)
    tool = create_query_database_tool(db_registry, _tenant())

    result = tool.invoke({"alias": "ch-bad", "action": "get_schema"})

    assert "not found" in result.lower()


def test_query_database_unknown_action() -> None:
    """Unknown action should return error message with supported actions."""
    from deep_agent.tools.query_database import create_query_database_tool

    db_registry = MagicMock()
    tool = create_query_database_tool(db_registry, _tenant())

    result = tool.invoke({"alias": "", "action": "execute_query"})

    assert "Unknown action" in result
```

### test_orchestrator.py

```python
"""Unit tests for AgentOrchestrator."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deep_agent.models import (
    AgentChunkEvent,
    AgentCompleteEvent,
    AgentEvent,
    ErrorEvent,
    SkillMatchEvent,
    SkillSummary,
    TenantContext,
)


def _tenant() -> TenantContext:
    return TenantContext(
        tenant_id="equities",
        user_id="test-user",
        skills_dirs=["skills/common", "skills/equities"],
        db_aliases=["ch-equities"],
    )


def _mock_skill_engine(
    matches: list[SkillSummary] | None = None,
) -> MagicMock:
    engine = MagicMock()
    engine.discover.return_value = matches or []
    engine.match.return_value = matches or []
    if matches:
        skill_content = MagicMock()
        skill_content.name = matches[0].name
        skill_content.skill_id = matches[0].skill_id
        skill_content.body = "## Instructions\nDo stuff."
        skill_content.allowed_tools = ["query_database", "execute_code"]
        engine.load.return_value = skill_content
    return engine


async def _fake_stream(*_args: Any, **_kwargs: Any) -> AsyncIterator[AgentEvent]:
    yield AgentChunkEvent(content="Hello")
    yield AgentCompleteEvent(summary="Hello", tokens_used=10)


async def test_handle_message_yields_skill_match_first() -> None:
    """First event should be SkillMatchEvent when a skill matches."""
    from deep_agent.orchestrator.agent_orchestrator import AgentOrchestrator

    skill_match = SkillSummary(
        skill_id="equities/zscore-monitor",
        name="zscore-monitor",
        description="Monitor z-scores",
        tags=["zscore"],
    )
    engine = _mock_skill_engine([skill_match])

    runtime = MagicMock()
    runtime.create_agent.return_value = MagicMock()
    runtime.stream = _fake_stream

    orchestrator = AgentOrchestrator(
        skill_engine=engine,
        llm_router=MagicMock(resolve=MagicMock(return_value=MagicMock(model="gpt-5", temperature=0.0))),
        runtime=runtime,
        sandbox=AsyncMock(),
        db_registry=MagicMock(list_aliases=MagicMock(return_value=[]), get_metadata=MagicMock()),
    )

    events = []
    async for event in orchestrator.handle_message("z-scores for AAPL", _tenant()):
        events.append(event)

    assert isinstance(events[0], SkillMatchEvent)
    assert events[0].skill_id == "equities/zscore-monitor"


async def test_handle_message_no_skill_match_no_filter() -> None:
    """When no skills match, all tools should be available (no filtering)."""
    from deep_agent.orchestrator.agent_orchestrator import AgentOrchestrator

    engine = _mock_skill_engine([])  # No matches

    runtime = MagicMock()
    runtime.create_agent.return_value = MagicMock()
    runtime.stream = _fake_stream

    db_registry = MagicMock()
    db_registry.list_aliases.return_value = []

    orchestrator = AgentOrchestrator(
        skill_engine=engine,
        llm_router=MagicMock(resolve=MagicMock(return_value=MagicMock(model="gpt-5", temperature=0.0))),
        runtime=runtime,
        sandbox=AsyncMock(),
        db_registry=db_registry,
    )

    events = []
    async for event in orchestrator.handle_message("random question", _tenant()):
        events.append(event)

    # No SkillMatchEvent should be yielded
    assert not any(isinstance(e, SkillMatchEvent) for e in events)
    # create_agent should have been called with all tools (no filtering)
    call_args = runtime.create_agent.call_args
    tools = call_args.kwargs.get("tools", call_args[1].get("tools", call_args[0][1] if len(call_args[0]) > 1 else []))
    assert len(tools) >= 2  # at least execute_code and query_database


async def test_system_prompt_contains_skill_body() -> None:
    """System prompt should include the matched skill's instructions."""
    from deep_agent.orchestrator.agent_orchestrator import AgentOrchestrator

    skill_match = SkillSummary(
        skill_id="common/db-query",
        name="db-query",
        description="Query databases",
        tags=["database"],
    )
    engine = _mock_skill_engine([skill_match])

    runtime = MagicMock()
    runtime.create_agent.return_value = MagicMock()
    runtime.stream = _fake_stream

    db_registry = MagicMock()
    db_registry.list_aliases.return_value = []

    orchestrator = AgentOrchestrator(
        skill_engine=engine,
        llm_router=MagicMock(resolve=MagicMock(return_value=MagicMock(model="gpt-5", temperature=0.0))),
        runtime=runtime,
        sandbox=AsyncMock(),
        db_registry=db_registry,
    )

    events = []
    async for event in orchestrator.handle_message("query data", _tenant()):
        events.append(event)

    # Verify system prompt passed to create_agent contains skill body
    call_args = runtime.create_agent.call_args
    system_prompt = call_args.kwargs.get("system_prompt", call_args[0][2] if len(call_args[0]) > 2 else "")
    assert "Active Skill: db-query" in system_prompt
    assert "Do stuff" in system_prompt


async def test_tool_filtering_by_allowed_tools() -> None:
    """Only tools listed in skill's allowed_tools should be passed to agent."""
    from deep_agent.orchestrator.agent_orchestrator import _filter_tools

    tool_a = MagicMock()
    tool_a.name = "execute_code"
    tool_b = MagicMock()
    tool_b.name = "query_database"
    tool_c = MagicMock()
    tool_c.name = "mcp_echo"

    filtered = _filter_tools([tool_a, tool_b, tool_c], ["execute_code", "query_database"])

    assert len(filtered) == 2
    names = {t.name for t in filtered}
    assert "execute_code" in names
    assert "query_database" in names
    assert "mcp_echo" not in names


async def test_handle_message_error_yields_error_event() -> None:
    """Unexpected errors should yield ErrorEvent."""
    from deep_agent.orchestrator.agent_orchestrator import AgentOrchestrator

    engine = MagicMock()
    engine.match.side_effect = RuntimeError("engine crashed")

    orchestrator = AgentOrchestrator(
        skill_engine=engine,
        llm_router=MagicMock(),
        runtime=MagicMock(),
        sandbox=AsyncMock(),
        db_registry=MagicMock(list_aliases=MagicMock(return_value=[])),
    )

    events = []
    async for event in orchestrator.handle_message("test", _tenant()):
        events.append(event)

    assert any(isinstance(e, ErrorEvent) for e in events)


async def test_handle_message_without_mcp_manager() -> None:
    """Orchestrator should work without MCPManager (mcp_manager=None)."""
    from deep_agent.orchestrator.agent_orchestrator import AgentOrchestrator

    engine = _mock_skill_engine([])
    runtime = MagicMock()
    runtime.create_agent.return_value = MagicMock()
    runtime.stream = _fake_stream

    orchestrator = AgentOrchestrator(
        skill_engine=engine,
        llm_router=MagicMock(resolve=MagicMock(return_value=MagicMock(model="gpt-5", temperature=0.0))),
        runtime=runtime,
        sandbox=AsyncMock(),
        db_registry=MagicMock(list_aliases=MagicMock(return_value=[])),
        mcp_manager=None,
    )

    events = []
    async for event in orchestrator.handle_message("hello", _tenant()):
        events.append(event)

    assert isinstance(events[-1], AgentCompleteEvent)
```

**Patterns:**
- Use `MagicMock` and `AsyncMock` for all dependencies — no real LLM, sandbox, or database calls
- Helper `_mock_skill_engine()` creates a pre-configured mock for common scenarios
- Helper `_fake_stream()` async generator returns minimal events for runtime.stream()
- Tests verify both the event types yielded AND the arguments passed to `runtime.create_agent()`
- `_filter_tools()` tested directly as a standalone function

### Acceptance Criteria

1. DatabaseRegistry: at least 8 test cases covering list, get_metadata, get_connection, errors, tenant scoping
2. Tool tests: at least 8 test cases covering both tool factories (name, output format, error handling)
3. Orchestrator tests: at least 6 test cases covering skill match events, no-match behavior, system prompt content, tool filtering, error handling, MCP-less operation
4. All tests pass with `pytest tests/unit/ -v`
5. No real LLM calls, no real sandbox execution in any test

### Edge Cases Tested

- Tenant with empty `db_aliases` sees no databases
- Unknown database alias returns error message (not exception) in tools
- Unknown action returns helpful error in query_database
- Orchestrator with no skill match runs without filtering
- Orchestrator with engine crash yields ErrorEvent
- Orchestrator without MCPManager completes normally

---

## T3.6 — MCP Config Loader

Implement a configuration loader that reads per-tenant MCP server definitions from `config/tenants/{tenant_id}/mcp.json`. Each MCP server config specifies transport type (`stdio` or `sse`), connection details, and optional environment variables. The loader returns a validated `MCPConfig` model. Missing config files result in graceful degradation (empty config), while malformed JSON raises `MCPConfigError`.

### Files

| File | Action | Purpose |
|------|--------|---------|
| `src/deep_agent/mcp/config.py` | Create | `MCPServerConfig`, `MCPConfig`, `MCPConfigError`, `load_mcp_config()` |
| `src/deep_agent/mcp/__init__.py` | Modify | Add exports: `MCPServerConfig`, `MCPConfig`, `MCPConfigError`, `load_mcp_config` |
| `config/tenants/equities/mcp.json` | Create | Example MCP config for equities tenant |

### Interface

```python
# src/deep_agent/mcp/config.py
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from deep_agent.models import TenantContext

logger = logging.getLogger(__name__)

# Default config root — relative to project root
_DEFAULT_CONFIG_ROOT = Path("config")


class MCPConfigError(ValueError):
    """Raised when MCP configuration is malformed or invalid."""


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server connection."""

    name: str
    transport: Literal["stdio", "sse"]
    command: list[str] | None = Field(default=None)
    url: str | None = Field(default=None)
    env: dict[str, str] = Field(default_factory=dict)


class MCPConfig(BaseModel):
    """Top-level MCP configuration for a tenant."""

    servers: list[MCPServerConfig] = Field(default_factory=list)


def load_mcp_config(
    tenant: TenantContext,
    config_root: Path = _DEFAULT_CONFIG_ROOT,
) -> MCPConfig:
    """Load MCP configuration for a tenant from the filesystem.

    Reads from config/tenants/{tenant_id}/mcp.json. Returns empty
    MCPConfig if the file does not exist (graceful degradation).

    Args:
        tenant: Tenant context identifying which config to load.
        config_root: Root directory for configuration files.

    Returns:
        Validated MCPConfig with server definitions.

    Raises:
        MCPConfigError: If the JSON file exists but is malformed or invalid.
    """
```

### Implementation Details

```python
def load_mcp_config(
    tenant: TenantContext,
    config_root: Path = _DEFAULT_CONFIG_ROOT,
) -> MCPConfig:
    config_path = config_root / "tenants" / tenant.tenant_id / "mcp.json"

    if not config_path.exists():
        logger.debug("No MCP config found at %s — using empty config", config_path)
        return MCPConfig()

    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MCPConfigError(f"Failed to read MCP config at {config_path}: {exc}") from exc

    try:
        raw_data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise MCPConfigError(f"Malformed JSON in {config_path}: {exc}") from exc

    try:
        config = MCPConfig.model_validate(raw_data)
    except Exception as exc:
        raise MCPConfigError(f"Invalid MCP config in {config_path}: {exc}") from exc

    # Validate transport-specific requirements
    for server in config.servers:
        if server.transport == "stdio" and not server.command:
            raise MCPConfigError(
                f"MCP server '{server.name}' uses stdio transport but has no 'command' field"
            )
        if server.transport == "sse" and not server.url:
            raise MCPConfigError(
                f"MCP server '{server.name}' uses sse transport but has no 'url' field"
            )

    return config
```

**Example `config/tenants/equities/mcp.json`:**

```json
{
  "servers": [
    {
      "name": "echo-test",
      "transport": "stdio",
      "command": ["python", "-m", "tests_mcp.echo_server"]
    }
  ]
}
```

### Connections to Week 1/2

- Imports `TenantContext` from `deep_agent.models.context` (T1.2)
- Used by `MCPManager` (T3.7) to resolve server connection parameters
- Used by `AgentOrchestrator` (T3.4) indirectly via `MCPManager`

### Acceptance Criteria

1. `MCPServerConfig` has fields: `name: str`, `transport: Literal["stdio", "sse"]`, `command: list[str] | None`, `url: str | None`, `env: dict[str, str]`
2. `MCPConfig` has field: `servers: list[MCPServerConfig]`
3. `load_mcp_config(tenant)` reads from `config/tenants/{tenant_id}/mcp.json`
4. Missing config file returns `MCPConfig(servers=[])` without error
5. Malformed JSON raises `MCPConfigError` with clear message mentioning the file path
6. Invalid structure (e.g. missing `name` field) raises `MCPConfigError`
7. stdio server without `command` raises `MCPConfigError`
8. sse server without `url` raises `MCPConfigError`
9. Valid config parses with correct server count and fields

### Edge Cases

- Config file exists but is empty (`""`) — raises `MCPConfigError` (invalid JSON)
- Config file exists with `{"servers": []}` — returns empty but valid `MCPConfig`
- Extra fields in JSON — ignored by Pydantic (no error)
- Config file with read permission errors — raises `MCPConfigError`
- Tenant ID with special characters — path constructed normally, file likely missing, returns empty config

---

## T3.7 — MCPManager (Adapter Service)

Implement `MCPManager` which wraps `langchain-mcp-adapters` to manage the lifecycle of MCP server connections. The manager connects to configured MCP servers, discovers their tools (exposed as LangChain `BaseTool` instances), and provides clean connect/disconnect lifecycle management. Supports graceful degradation when `langchain-mcp-adapters` is not installed or when individual servers fail to connect.

### Files

| File | Action | Purpose |
|------|--------|---------|
| `src/deep_agent/mcp/manager.py` | Create | `MCPManager` class |
| `src/deep_agent/mcp/__init__.py` | Modify | Add export: `MCPManager` |

### Interface

```python
# src/deep_agent/mcp/manager.py
from __future__ import annotations

import logging
from typing import Any

from deep_agent.mcp.config import MCPConfig

logger = logging.getLogger(__name__)

# Detect langchain-mcp-adapters availability
try:
    from langchain_mcp_adapters.client import MultiServerMCPClient

    _HAS_MCP_ADAPTERS: bool = True
except ImportError:  # pragma: no cover
    _HAS_MCP_ADAPTERS = False


class MCPManager:
    """Manages MCP server connections and tool discovery.

    Uses langchain-mcp-adapters to connect to MCP servers and expose
    their tools as LangChain BaseTool instances. Supports async
    connect/disconnect lifecycle management.
    """

    def __init__(self, config: MCPConfig) -> None:
        """Initialize manager with MCP server configuration.

        Args:
            config: MCPConfig with server definitions.
        """

    async def connect(self) -> None:
        """Establish connections to all configured MCP servers.

        Logs warnings for servers that fail to connect. If
        langchain-mcp-adapters is not installed, logs a warning
        and returns without connecting.
        """

    async def get_tools(self) -> list[Any]:
        """Return LangChain BaseTool instances from connected MCP servers.

        Tools are cached after first discovery within a session.

        Returns:
            List of BaseTool instances. Empty list if not connected
            or no tools discovered.
        """

    async def disconnect(self) -> None:
        """Disconnect from all MCP servers and clean up resources."""

    @property
    def connected(self) -> bool:
        """Whether the manager has an active connection."""
```

### Implementation Details

```python
class MCPManager:
    def __init__(self, config: MCPConfig) -> None:
        self._config = config
        self._client: Any | None = None  # MultiServerMCPClient or None
        self._tools: list[Any] = []
        self._connected = False

    async def connect(self) -> None:
        if not _HAS_MCP_ADAPTERS:
            logger.warning(
                "langchain-mcp-adapters not installed — MCP tools unavailable"
            )
            return

        if not self._config.servers:
            logger.debug("No MCP servers configured — skipping connection")
            return

        server_params = self._build_server_params()
        if not server_params:
            return

        try:
            self._client = MultiServerMCPClient(server_params)
            await self._client.__aenter__()
            self._tools = self._client.get_tools()
            self._connected = True
            logger.info(
                "Connected to %d MCP server(s), discovered %d tool(s)",
                len(server_params),
                len(self._tools),
            )
        except Exception as exc:
            logger.warning("Failed to connect to MCP servers: %s", exc)
            self._tools = []
            self._connected = False

    async def get_tools(self) -> list[Any]:
        return list(self._tools)

    async def disconnect(self) -> None:
        if self._client is not None:
            try:
                await self._client.__aexit__(None, None, None)
            except Exception as exc:
                logger.warning("Error disconnecting MCP client: %s", exc)
            finally:
                self._client = None
                self._tools = []
                self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def _build_server_params(self) -> dict[str, dict[str, Any]]:
        """Build the server params dict for MultiServerMCPClient."""
        params: dict[str, dict[str, Any]] = {}
        for server in self._config.servers:
            if server.transport == "stdio":
                if not server.command:
                    logger.warning(
                        "MCP server '%s' has stdio transport but no command — skipping",
                        server.name,
                    )
                    continue
                params[server.name] = {
                    "command": server.command[0],
                    "args": server.command[1:],
                    "transport": "stdio",
                    "env": server.env if server.env else None,
                }
            elif server.transport == "sse":
                if not server.url:
                    logger.warning(
                        "MCP server '%s' has sse transport but no url — skipping",
                        server.name,
                    )
                    continue
                params[server.name] = {
                    "url": server.url,
                    "transport": "sse",
                }
            else:
                logger.warning("Unknown transport '%s' for MCP server '%s'", server.transport, server.name)
        return params
```

### Connections to Week 1/2

- Imports `MCPConfig` from `deep_agent.mcp.config` (T3.6)
- Uses `langchain_mcp_adapters.client.MultiServerMCPClient` (external dependency)
- Used by `AgentOrchestrator` (T3.4) for MCP tool discovery

### Acceptance Criteria

1. `MCPManager(config)` stores config and initializes in disconnected state
2. `connect()` establishes connections to all configured servers via `MultiServerMCPClient`
3. `get_tools()` returns list of LangChain `BaseTool` instances; empty list if not connected
4. `disconnect()` cleanly shuts down all connections; idempotent (safe to call twice)
5. `connected` property reflects current connection state
6. If `langchain-mcp-adapters` not installed, `connect()` logs warning and returns
7. If server connection fails, logs warning and continues (partial availability)
8. Tools are cached after first `connect()` — `get_tools()` returns same list without re-discovery

### Edge Cases

- `langchain-mcp-adapters` not installed — `_HAS_MCP_ADAPTERS=False`, connect is no-op
- Empty config (`servers=[]`) — connect is no-op, get_tools returns `[]`
- Server process fails to start (bad command) — logs warning, continues
- `disconnect()` called without prior `connect()` — no-op
- `disconnect()` called twice — second call is idempotent
- `get_tools()` before `connect()` — returns empty list

---

## T3.8 — Test MCP Server (Echo/Calculator)

Create a simple MCP server for integration testing. The server exposes three trivial tools (`echo`, `add`, `multiply`) via the MCP protocol using the `mcp` Python SDK's `FastMCP` high-level API. It communicates over stdio transport and is runnable as a standalone module. This server is used exclusively for testing — it validates that `MCPManager` can correctly discover and invoke MCP-provided tools.

### Files

| File | Action | Purpose |
|------|--------|---------|
| `tests_mcp/__init__.py` | Create | Package marker for test MCP server |
| `tests_mcp/echo_server.py` | Create | MCP server with echo, add, multiply tools |

### Interface

```python
# tests_mcp/echo_server.py
"""Simple MCP server exposing echo, add, and multiply tools for testing.

Run via: python -m tests_mcp.echo_server

Uses stdio transport — reads MCP protocol messages from stdin,
writes responses to stdout.
"""
from __future__ import annotations


def main() -> None:
    """Start the MCP echo server with stdio transport."""
```

### Implementation Details

```python
# tests_mcp/echo_server.py
"""Simple MCP server exposing echo, add, and multiply tools for testing."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("echo-test")


@mcp.tool()
def echo(message: str) -> str:
    """Echo back the input message.

    Args:
        message: The message to echo.

    Returns:
        The same message that was received.
    """
    return message


@mcp.tool()
def add(a: float, b: float) -> float:
    """Add two numbers.

    Args:
        a: First number.
        b: Second number.

    Returns:
        Sum of a and b.
    """
    return a + b


@mcp.tool()
def multiply(a: float, b: float) -> float:
    """Multiply two numbers.

    Args:
        a: First number.
        b: Second number.

    Returns:
        Product of a and b.
    """
    return a * b


def main() -> None:
    """Start the MCP echo server with stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
```

**`tests_mcp/__init__.py`:**

```python
"""Test MCP server package for integration testing."""
```

**Key design decisions:**
- Uses `FastMCP` (high-level API from the `mcp` SDK) for simplicity
- `@mcp.tool()` decorator automatically handles schema generation and MCP protocol marshaling
- `mcp.run(transport="stdio")` starts the server reading from stdin and writing to stdout
- The `if __name__ == "__main__"` guard plus `python -m tests_mcp.echo_server` entry point
- Functions are synchronous (no async needed for simple operations)
- Return types match what the agent expects: `str` for echo, `float` for math

### Connections to Week 1/2

- No internal dependencies — standalone package
- Used by `MCPManager` integration tests (T3.9) via stdio transport
- Referenced in `config/tenants/equities/mcp.json` (T3.6) as `["python", "-m", "tests_mcp.echo_server"]`

### Acceptance Criteria

1. `python -m tests_mcp.echo_server` starts the server without errors (exits on stdin close)
2. Server exposes exactly 3 tools: `echo`, `add`, `multiply`
3. `echo("hello")` returns `"hello"`
4. `add(2.0, 3.0)` returns `5.0`
5. `multiply(4.0, 5.0)` returns `20.0`
6. Uses stdio transport (stdin/stdout)
7. Built with the `mcp` Python SDK — no raw protocol implementation

### Edge Cases

- Server receives malformed MCP message — SDK handles error response
- Server receives request for unknown tool — SDK returns tool-not-found error
- stdin closed — server exits cleanly
- Large message payload — handled by SDK's buffering

---

## T3.9 — MCP Unit and Integration Tests

Write unit tests for the MCP config loader and integration tests for the MCPManager using the test echo server. Config tests validate JSON parsing, error handling, and transport-specific validation. Integration tests verify the full connect-discover-invoke-disconnect lifecycle.

### Files

| File | Action | Purpose |
|------|--------|---------|
| `tests/unit/test_mcp_config.py` | Create | MCP config loader unit tests |
| `tests/integration/test_mcp_manager.py` | Create | MCPManager integration tests with echo server |

### test_mcp_config.py

```python
"""Unit tests for MCP config loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from deep_agent.mcp import MCPConfig, MCPConfigError, load_mcp_config
from deep_agent.models import TenantContext


def _tenant(tenant_id: str = "equities") -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        user_id="test-user",
        skills_dirs=[],
        db_aliases=[],
    )


def test_load_valid_config(tmp_path: Path) -> None:
    """Valid JSON should parse to MCPConfig with correct server entries."""
    config_dir = tmp_path / "tenants" / "equities"
    config_dir.mkdir(parents=True)
    (config_dir / "mcp.json").write_text(
        '{"servers": [{"name": "echo", "transport": "stdio", "command": ["python", "-m", "echo"]}]}',
        encoding="utf-8",
    )

    config = load_mcp_config(_tenant(), config_root=tmp_path)

    assert len(config.servers) == 1
    assert config.servers[0].name == "echo"
    assert config.servers[0].transport == "stdio"
    assert config.servers[0].command == ["python", "-m", "echo"]


def test_load_missing_file_returns_empty_config(tmp_path: Path) -> None:
    """Missing config file should return empty MCPConfig without error."""
    config = load_mcp_config(_tenant("nonexistent"), config_root=tmp_path)

    assert config.servers == []


def test_load_malformed_json_raises_error(tmp_path: Path) -> None:
    """Malformed JSON should raise MCPConfigError."""
    config_dir = tmp_path / "tenants" / "equities"
    config_dir.mkdir(parents=True)
    (config_dir / "mcp.json").write_text("{invalid json", encoding="utf-8")

    with pytest.raises(MCPConfigError, match="Malformed JSON"):
        load_mcp_config(_tenant(), config_root=tmp_path)


def test_load_invalid_structure_raises_error(tmp_path: Path) -> None:
    """JSON with invalid structure should raise MCPConfigError."""
    config_dir = tmp_path / "tenants" / "equities"
    config_dir.mkdir(parents=True)
    (config_dir / "mcp.json").write_text(
        '{"servers": [{"transport": "stdio"}]}',  # missing required 'name'
        encoding="utf-8",
    )

    with pytest.raises(MCPConfigError):
        load_mcp_config(_tenant(), config_root=tmp_path)


def test_stdio_without_command_raises_error(tmp_path: Path) -> None:
    """stdio transport without command should raise MCPConfigError."""
    config_dir = tmp_path / "tenants" / "equities"
    config_dir.mkdir(parents=True)
    (config_dir / "mcp.json").write_text(
        '{"servers": [{"name": "bad", "transport": "stdio"}]}',
        encoding="utf-8",
    )

    with pytest.raises(MCPConfigError, match="no 'command' field"):
        load_mcp_config(_tenant(), config_root=tmp_path)


def test_sse_without_url_raises_error(tmp_path: Path) -> None:
    """sse transport without url should raise MCPConfigError."""
    config_dir = tmp_path / "tenants" / "equities"
    config_dir.mkdir(parents=True)
    (config_dir / "mcp.json").write_text(
        '{"servers": [{"name": "bad", "transport": "sse"}]}',
        encoding="utf-8",
    )

    with pytest.raises(MCPConfigError, match="no 'url' field"):
        load_mcp_config(_tenant(), config_root=tmp_path)


def test_sse_with_url_is_valid(tmp_path: Path) -> None:
    """sse transport with url should parse successfully."""
    config_dir = tmp_path / "tenants" / "equities"
    config_dir.mkdir(parents=True)
    (config_dir / "mcp.json").write_text(
        '{"servers": [{"name": "api", "transport": "sse", "url": "http://localhost:8080/sse"}]}',
        encoding="utf-8",
    )

    config = load_mcp_config(_tenant(), config_root=tmp_path)

    assert config.servers[0].url == "http://localhost:8080/sse"


def test_empty_servers_list_is_valid(tmp_path: Path) -> None:
    """Config with empty servers list should parse without error."""
    config_dir = tmp_path / "tenants" / "equities"
    config_dir.mkdir(parents=True)
    (config_dir / "mcp.json").write_text('{"servers": []}', encoding="utf-8")

    config = load_mcp_config(_tenant(), config_root=tmp_path)

    assert config.servers == []


def test_env_vars_parsed(tmp_path: Path) -> None:
    """Server env vars should be parsed into the config."""
    config_dir = tmp_path / "tenants" / "equities"
    config_dir.mkdir(parents=True)
    (config_dir / "mcp.json").write_text(
        '{"servers": [{"name": "s", "transport": "stdio", "command": ["cmd"], "env": {"KEY": "VAL"}}]}',
        encoding="utf-8",
    )

    config = load_mcp_config(_tenant(), config_root=tmp_path)

    assert config.servers[0].env == {"KEY": "VAL"}
```

### test_mcp_manager.py

```python
"""Integration tests for MCPManager with the test echo server.

These tests spawn the echo_server as a real MCP subprocess via stdio transport
and verify tool discovery and invocation through langchain-mcp-adapters.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest

from deep_agent.mcp.config import MCPConfig, MCPServerConfig
from deep_agent.mcp.manager import MCPManager


def _echo_server_config() -> MCPConfig:
    """Config pointing to the test echo MCP server."""
    return MCPConfig(
        servers=[
            MCPServerConfig(
                name="echo-test",
                transport="stdio",
                command=[sys.executable, "-m", "tests_mcp.echo_server"],
            ),
        ],
    )


@pytest.mark.timeout(30)
async def test_connect_discovers_three_tools() -> None:
    """connect() should discover echo, add, and multiply tools."""
    manager = MCPManager(_echo_server_config())

    await manager.connect()
    try:
        tools = await manager.get_tools()
        assert len(tools) == 3
        tool_names = {t.name for t in tools}
        assert "echo" in tool_names
        assert "add" in tool_names
        assert "multiply" in tool_names
    finally:
        await manager.disconnect()


@pytest.mark.timeout(30)
async def test_invoke_add_tool() -> None:
    """Invoking the add tool with (2, 3) should return 5."""
    manager = MCPManager(_echo_server_config())

    await manager.connect()
    try:
        tools = await manager.get_tools()
        add_tool = next(t for t in tools if t.name == "add")
        result = await add_tool.ainvoke({"a": 2.0, "b": 3.0})
        assert float(result) == pytest.approx(5.0)
    finally:
        await manager.disconnect()


@pytest.mark.timeout(30)
async def test_invoke_echo_tool() -> None:
    """Invoking the echo tool should return the input message."""
    manager = MCPManager(_echo_server_config())

    await manager.connect()
    try:
        tools = await manager.get_tools()
        echo_tool = next(t for t in tools if t.name == "echo")
        result = await echo_tool.ainvoke({"message": "hello world"})
        assert "hello world" in str(result)
    finally:
        await manager.disconnect()


@pytest.mark.timeout(30)
async def test_disconnect_cleans_up() -> None:
    """disconnect() should set connected=False and clear tools."""
    manager = MCPManager(_echo_server_config())

    await manager.connect()
    assert manager.connected is True

    await manager.disconnect()

    assert manager.connected is False
    tools = await manager.get_tools()
    assert tools == []


async def test_get_tools_before_connect_returns_empty() -> None:
    """get_tools() before connect() should return empty list."""
    manager = MCPManager(_echo_server_config())

    tools = await manager.get_tools()

    assert tools == []


async def test_disconnect_without_connect_is_noop() -> None:
    """disconnect() without prior connect should not raise."""
    manager = MCPManager(_echo_server_config())

    await manager.disconnect()  # Should not raise


async def test_empty_config_connect_is_noop() -> None:
    """connect() with empty config should be a no-op."""
    manager = MCPManager(MCPConfig(servers=[]))

    await manager.connect()
    tools = await manager.get_tools()

    assert tools == []
    assert manager.connected is False
```

**Patterns:**
- Integration tests use `pytest.mark.timeout(30)` — MCP server startup may take a few seconds
- `sys.executable` used for command to ensure the same Python interpreter is used
- All integration tests use try/finally to ensure `disconnect()` is called (cleanup)
- Unit tests for config use `tmp_path` fixture for isolated filesystem
- Config tests validate both happy path and all error branches

### Acceptance Criteria

1. Config unit tests: at least 9 test cases covering valid config, missing file, malformed JSON, invalid structure, transport-specific validation, env vars, empty servers
2. Manager integration tests: at least 7 test cases covering connect, tool discovery (3 tools), tool invocation (add, echo), disconnect, pre-connect behavior, empty config
3. All config unit tests pass with `pytest tests/unit/test_mcp_config.py -v`
4. All integration tests pass with `pytest tests/integration/test_mcp_manager.py -v`
5. Integration tests spawn a real MCP server process and verify tool discovery and invocation

### Edge Cases Tested

- Missing config file — empty config (no error)
- Malformed JSON — `MCPConfigError` with file path in message
- stdio without command — `MCPConfigError`
- sse without url — `MCPConfigError`
- `get_tools()` before `connect()` — empty list
- `disconnect()` without `connect()` — no-op
- Empty server config — connect is no-op

---

## Design Principles (apply to ALL Week 3 code)

1. **Factory pattern for tools** — `create_execute_code_tool()` and `create_query_database_tool()` capture dependencies via closures, producing bound `BaseTool` instances. This avoids global state and enables per-tenant tool construction.

2. **Errors as output, not exceptions** — Tools return error information as formatted output (JSON or text) rather than raising exceptions. This gives the LLM agent the opportunity to self-correct.

3. **Protocol-based interfaces** — `SandboxManager` and `RuntimeAdapter` remain `typing.Protocol`; `DatabaseRegistry` is a concrete class for Phase 1 but could be converted to a protocol later.

4. **Zero circular imports** — `models/` imports nothing internal. `database/` imports only `models/` and `config`. `tools/` imports `database/`, `sandbox/`, and `models/`. `mcp/` imports only `models/`. `orchestrator/` imports everything.

5. **Graceful degradation** — MCPManager works without `langchain-mcp-adapters` installed. Orchestrator works without MCPManager. Tools return errors instead of raising. Missing MCP config returns empty config.

6. **Type annotations** on ALL functions and methods. `from __future__ import annotations` at the top of every module.

7. **Docstrings** on all public classes, methods, and module-level functions.

8. **Async-first** — `handle_message()`, `execute_code` tool, `MCPManager.connect/disconnect/get_tools` are all async. `query_database` tool is synchronous (no I/O).

9. **Dependency injection** — `DatabaseRegistry` takes `AppSettings`. Tool factories take their dependencies as arguments. `AgentOrchestrator` constructor takes all service instances. No global singletons.

---

## Validation

After all Week 3 implementation, run:

```bash
source .venv/bin/activate

# Lint and type checks
ruff check src/ tests/ stubs/
mypy src/

# Unit tests
pytest tests/unit/ -v

# Integration tests (requires MCP dependencies)
pytest tests/integration/test_mcp_manager.py -v

# Import smoke tests
python -c "from deep_agent.database import DatabaseRegistry, AliasNotFoundError; print('database OK')"
python -c "from deep_agent.tools.execute_code import create_execute_code_tool; print('execute_code OK')"
python -c "from deep_agent.tools.query_database import create_query_database_tool; print('query_database OK')"
python -c "from deep_agent.mcp import MCPConfig, MCPServerConfig, load_mcp_config, MCPConfigError; print('mcp config OK')"
python -c "from deep_agent.mcp.manager import MCPManager; print('mcp manager OK')"
python -c "from deep_agent.orchestrator import AgentOrchestrator; print('orchestrator OK')"

# Test MCP server standalone
timeout 5 python -m tests_mcp.echo_server < /dev/null 2>&1 || echo "echo_server exits cleanly on stdin close"
```

All must pass cleanly. Expected total test count: 52 (Week 1-2) + ~40 (Week 3) = ~92+ tests.