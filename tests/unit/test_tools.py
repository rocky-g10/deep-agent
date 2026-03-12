"""Unit tests for execute_code and query_database tool factories."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import SecretStr

from deep_agent.config import AppSettings
from deep_agent.database import DatabaseRegistry
from deep_agent.models import ConnectionConfig, DatabaseAlias, ExecuteResult, TenantContext
from deep_agent.tools.execute_code import _build_db_env, create_execute_code_tool
from deep_agent.tools.query_database import create_query_database_tool


@pytest.mark.asyncio
async def test_execute_code_tool_has_correct_name(tenant_equities: TenantContext) -> None:
    """Factory should produce a tool named 'execute_code'."""
    sandbox = AsyncMock()
    db_registry = MagicMock()
    db_registry.list_aliases.return_value = []

    tool = create_execute_code_tool(
        sandbox,
        db_registry,
        tenant_equities,
        settings=AppSettings(OPENAI_API_KEY=SecretStr("test-key")),
    )

    assert tool.name == "execute_code"


@pytest.mark.asyncio
async def test_execute_code_tool_returns_json(tenant_equities: TenantContext) -> None:
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

    tool = create_execute_code_tool(
        sandbox,
        db_registry,
        tenant_equities,
        settings=AppSettings(OPENAI_API_KEY=SecretStr("test-key")),
    )
    result = await tool.ainvoke({"code": "print('hello')"})

    parsed = json.loads(result)
    assert parsed["exit_code"] == 0
    assert parsed["stdout"] == "hello\n"


@pytest.mark.asyncio
async def test_execute_code_tool_handles_sandbox_error(tenant_equities: TenantContext) -> None:
    """Sandbox exceptions should be returned as error output, not raised."""
    sandbox = AsyncMock()
    sandbox.execute.side_effect = RuntimeError("sandbox crashed")
    db_registry = MagicMock()
    db_registry.list_aliases.return_value = []

    tool = create_execute_code_tool(
        sandbox,
        db_registry,
        tenant_equities,
        settings=AppSettings(OPENAI_API_KEY=SecretStr("test-key")),
    )
    result = await tool.ainvoke({"code": "print('hello')"})

    parsed = json.loads(result)
    assert parsed["exit_code"] == -1
    assert "sandbox crashed" in parsed["stderr"]


@pytest.mark.asyncio
async def test_execute_code_tool_injects_db_env(tenant_equities: TenantContext) -> None:
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
    db_registry = DatabaseRegistry(AppSettings(OPENAI_API_KEY=SecretStr("test-key")))

    tool = create_execute_code_tool(
        sandbox,
        db_registry,
        tenant_equities,
        settings=AppSettings(OPENAI_API_KEY=SecretStr("test-key")),
    )
    await tool.ainvoke({"code": "print('ok')"})

    _, kwargs = sandbox.execute.call_args
    env = kwargs.get("env", {})
    assert env["CH_EQUITIES_HOST"] == "localhost"
    assert env["CH_EQUITIES_PORT"] == "8123"
    assert env["CH_EQUITIES_NAME"] == "default"
    assert env["DB_HOST"] == "localhost"
    assert env["DB_PORT"] == "8123"
    assert env["DB_NAME"] == "default"


def test_query_database_tool_has_correct_name(tenant_equities: TenantContext) -> None:
    """Factory should produce a tool named 'query_database'."""
    db_registry = MagicMock()
    tool = create_query_database_tool(db_registry, tenant_equities)

    assert tool.name == "query_database"


def test_query_database_list_aliases(tenant_equities: TenantContext) -> None:
    """list_aliases action should return formatted alias text."""
    settings = AppSettings(OPENAI_API_KEY=SecretStr("test-key"))
    db_registry = DatabaseRegistry(settings)
    tool = create_query_database_tool(db_registry, tenant_equities)

    result = tool.invoke({"alias": "", "action": "list_aliases"})

    assert "ch-equities" in result
    assert "clickhouse" in result


def test_query_database_get_schema(tenant_equities: TenantContext) -> None:
    """get_schema action should return table and column info."""
    settings = AppSettings(OPENAI_API_KEY=SecretStr("test-key"))
    db_registry = DatabaseRegistry(settings)
    tool = create_query_database_tool(db_registry, tenant_equities)

    result = tool.invoke({"alias": "ch-equities", "action": "get_schema"})

    assert "fundamentals_daily" in result
    assert "volume" in result
    assert "UInt64" in result


def test_query_database_unknown_alias(tenant_equities: TenantContext) -> None:
    """Unknown alias should return error message, not raise exception."""
    settings = AppSettings(OPENAI_API_KEY=SecretStr("test-key"))
    db_registry = DatabaseRegistry(settings)
    tool = create_query_database_tool(db_registry, tenant_equities)

    result = tool.invoke({"alias": "ch-bad", "action": "get_schema"})

    assert "not found" in result.lower()


def test_query_database_unknown_action(tenant_equities: TenantContext) -> None:
    """Unknown action should return error message with supported actions."""
    db_registry = MagicMock()
    tool = create_query_database_tool(db_registry, tenant_equities)

    result = tool.invoke({"alias": "", "action": "execute_query"})

    assert "Unknown action" in result


def test_db_pass_populated_from_settings(tenant_equities: TenantContext) -> None:
    """DB_PASS should be populated from clickhouse_password in settings."""
    settings = AppSettings(
        OPENAI_API_KEY=SecretStr("test-key"),
        CLICKHOUSE_PASSWORD=SecretStr("secret-pass"),
    )
    db_registry = DatabaseRegistry(settings)

    env = _build_db_env(db_registry=db_registry, tenant=tenant_equities, settings=settings)

    assert env["DB_PASS"] == "secret-pass"
    assert env["CH_EQUITIES_PASS"] == "secret-pass"


def test_build_db_env_multiple_aliases() -> None:
    """Multiple aliases should produce prefixed env vars and DB_* from first alias."""

    class MultiAliasRegistry:
        def list_aliases(self, _tenant_ctx: TenantContext) -> list[DatabaseAlias]:
            return [
                DatabaseAlias(alias="ch-equities", engine="clickhouse", description="e"),
                DatabaseAlias(alias="ch-risk", engine="clickhouse", description="r"),
            ]

        def get_connection(self, alias: str, _tenant_ctx: TenantContext) -> ConnectionConfig:
            if alias == "ch-equities":
                return ConnectionConfig(
                    engine="clickhouse",
                    host="eq-host",
                    port=8123,
                    database="eq_db",
                    credentials_ref="env://CLICKHOUSE_USER:eq_user",
                )
            return ConnectionConfig(
                engine="clickhouse",
                host="risk-host",
                port=9000,
                database="risk_db",
                credentials_ref="env://CLICKHOUSE_USER:risk_user",
            )

    tenant = TenantContext(
        tenant_id="multi",
        user_id="u",
        skills_dirs=(),
        db_aliases=("ch-equities", "ch-risk"),
    )
    settings = AppSettings(OPENAI_API_KEY=SecretStr("test-key"))
    env = _build_db_env(
        db_registry=MultiAliasRegistry(),  # type: ignore[arg-type]
        tenant=tenant,
        settings=settings,
    )

    assert env["CH_EQUITIES_HOST"] == "eq-host"
    assert env["CH_RISK_HOST"] == "risk-host"
    assert env["DB_HOST"] == "eq-host"
