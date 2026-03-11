"""Unit tests for execute_code and query_database tool factories."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from deep_agent.config import AppSettings
from deep_agent.database import DatabaseRegistry
from deep_agent.models import ExecuteResult, TenantContext
from deep_agent.tools.execute_code import create_execute_code_tool
from deep_agent.tools.query_database import create_query_database_tool


def _tenant() -> TenantContext:
    return TenantContext(
        tenant_id="equities",
        user_id="test-user",
        skills_dirs=["skills/common", "skills/equities"],
        db_aliases=["ch-equities"],
    )


@pytest.mark.asyncio
async def test_execute_code_tool_has_correct_name() -> None:
    """Factory should produce a tool named 'execute_code'."""
    sandbox = AsyncMock()
    db_registry = MagicMock()
    db_registry.list_aliases.return_value = []

    tool = create_execute_code_tool(sandbox, db_registry, _tenant())

    assert tool.name == "execute_code"


@pytest.mark.asyncio
async def test_execute_code_tool_returns_json() -> None:
    """Successful execution should return valid JSON with expected fields."""
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


@pytest.mark.asyncio
async def test_execute_code_tool_handles_sandbox_error() -> None:
    """Sandbox exceptions should be returned as error output, not raised."""
    sandbox = AsyncMock()
    sandbox.execute.side_effect = RuntimeError("sandbox crashed")
    db_registry = MagicMock()
    db_registry.list_aliases.return_value = []

    tool = create_execute_code_tool(sandbox, db_registry, _tenant())
    result = await tool.ainvoke({"code": "print('hello')"})

    parsed = json.loads(result)
    assert parsed["exit_code"] == -1
    assert "sandbox crashed" in parsed["stderr"]


@pytest.mark.asyncio
async def test_execute_code_tool_injects_db_env() -> None:
    """Tool should inject DB env vars from the registry into sandbox.execute."""
    sandbox = AsyncMock()
    sandbox.execute.return_value = ExecuteResult(
        execution_id="exec-2",
        exit_code=0,
        stdout="",
        stderr="",
        output_files={},
        duration_ms=1,
    )
    db_registry = DatabaseRegistry(AppSettings(OPENAI_API_KEY="test-key"))

    tool = create_execute_code_tool(sandbox, db_registry, _tenant())
    await tool.ainvoke({"code": "print('ok')"})

    _, kwargs = sandbox.execute.call_args
    env = kwargs.get("env", {})
    assert env["DB_HOST"] == "localhost"
    assert env["DB_PORT"] == "8123"
    assert env["DB_NAME"] == "default"


def test_query_database_tool_has_correct_name() -> None:
    """Factory should produce a tool named 'query_database'."""
    db_registry = MagicMock()
    tool = create_query_database_tool(db_registry, _tenant())

    assert tool.name == "query_database"


def test_query_database_list_aliases() -> None:
    """list_aliases action should return formatted alias text."""
    settings = AppSettings(OPENAI_API_KEY="test-key")
    db_registry = DatabaseRegistry(settings)
    tool = create_query_database_tool(db_registry, _tenant())

    result = tool.invoke({"alias": "", "action": "list_aliases"})

    assert "ch-equities" in result
    assert "clickhouse" in result


def test_query_database_get_schema() -> None:
    """get_schema action should return table and column info."""
    settings = AppSettings(OPENAI_API_KEY="test-key")
    db_registry = DatabaseRegistry(settings)
    tool = create_query_database_tool(db_registry, _tenant())

    result = tool.invoke({"alias": "ch-equities", "action": "get_schema"})

    assert "fundamentals_daily" in result
    assert "volume" in result
    assert "UInt64" in result


def test_query_database_unknown_alias() -> None:
    """Unknown alias should return error message, not raise exception."""
    settings = AppSettings(OPENAI_API_KEY="test-key")
    db_registry = DatabaseRegistry(settings)
    tool = create_query_database_tool(db_registry, _tenant())

    result = tool.invoke({"alias": "ch-bad", "action": "get_schema"})

    assert "not found" in result.lower()


def test_query_database_unknown_action() -> None:
    """Unknown action should return error message with supported actions."""
    db_registry = MagicMock()
    tool = create_query_database_tool(db_registry, _tenant())

    result = tool.invoke({"alias": "", "action": "execute_query"})

    assert "Unknown action" in result
