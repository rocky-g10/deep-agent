"""Unit tests for execute_code tool factory."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from deep_agent.models import ExecuteResult, TenantContext
from deep_agent.tools.execute_code import create_execute_code_tool


@pytest.mark.asyncio
async def test_execute_code_tool_has_correct_name(tenant_equities: TenantContext) -> None:
    """Factory should produce a tool named 'execute_code'."""
    sandbox = AsyncMock()

    tool = create_execute_code_tool(sandbox, tenant_equities)

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

    tool = create_execute_code_tool(sandbox, tenant_equities)
    result = await tool.ainvoke({"code": "print('hello')"})

    parsed = json.loads(result)
    assert parsed["exit_code"] == 0
    assert parsed["stdout"] == "hello\n"


@pytest.mark.asyncio
async def test_execute_code_tool_handles_sandbox_error(tenant_equities: TenantContext) -> None:
    """Sandbox exceptions should be returned as error output, not raised."""
    sandbox = AsyncMock()
    sandbox.execute.side_effect = RuntimeError("sandbox crashed")

    tool = create_execute_code_tool(sandbox, tenant_equities)
    result = await tool.ainvoke({"code": "print('hello')"})

    parsed = json.loads(result)
    assert parsed["exit_code"] == -1
    assert "sandbox crashed" in parsed["stderr"]


@pytest.mark.asyncio
async def test_execute_code_tool_injects_resource_env(tenant_equities: TenantContext) -> None:
    """Tool should inject resource env vars from the tenant context into sandbox.execute."""
    sandbox = AsyncMock()
    sandbox.execute.return_value = ExecuteResult(
        execution_id="exec-2",
        exit_code=0,
        stdout="",
        stderr="",
        output_files={},
        duration_ms=1,
    )

    tool = create_execute_code_tool(sandbox, tenant_equities)
    await tool.ainvoke({"code": "print('ok')"})

    _, kwargs = sandbox.execute.call_args
    env = kwargs.get("env", {})
    # Single alias: both unprefixed and prefixed should be present
    assert env["DB_HOST"] == "localhost"
    assert env["DB_PORT"] == "8123"
    assert env["DB_NAME"] == "default"
    assert env["CH_EQUITIES_DB_HOST"] == "localhost"
    assert env["CH_EQUITIES_DB_PORT"] == "8123"
    assert env["CH_EQUITIES_DB_NAME"] == "default"


@pytest.mark.asyncio
async def test_resource_env_multi_alias_only_prefixed() -> None:
    """Multi-alias tenants should only get prefixed env vars (no collision)."""
    tenant = TenantContext(
        tenant_id="multi",
        user_id="test-user",
        resource_env={
            "prod-db": {"DB_HOST": "prod.host", "DB_PORT": "5432"},
            "dev-db": {"DB_HOST": "dev.host", "DB_PORT": "5433"},
        },
    )
    sandbox = AsyncMock()
    sandbox.execute.return_value = ExecuteResult(
        execution_id="exec-3",
        exit_code=0,
        stdout="",
        stderr="",
        output_files={},
        duration_ms=1,
    )

    tool = create_execute_code_tool(sandbox, tenant)
    await tool.ainvoke({"code": "print('ok')"})

    _, kwargs = sandbox.execute.call_args
    env = kwargs.get("env", {})
    # Prefixed keys present
    assert env["PROD_DB_DB_HOST"] == "prod.host"
    assert env["DEV_DB_DB_HOST"] == "dev.host"
    assert env["PROD_DB_DB_PORT"] == "5432"
    assert env["DEV_DB_DB_PORT"] == "5433"
    # Unprefixed keys must NOT be present (collision would occur)
    assert "DB_HOST" not in env
    assert "DB_PORT" not in env


@pytest.mark.asyncio
async def test_execute_code_tool_injects_pythonpath() -> None:
    """scripts_dirs should be injected as PYTHONPATH in sandbox env."""
    tenant = TenantContext(tenant_id="t", user_id="u")
    sandbox = AsyncMock()
    sandbox.execute.return_value = ExecuteResult(
        execution_id="exec-4",
        exit_code=0,
        stdout="",
        stderr="",
        output_files={},
        duration_ms=1,
    )

    tool = create_execute_code_tool(sandbox, tenant, scripts_dirs=["/path/to/scripts"])
    await tool.ainvoke({"code": "pass"})

    _, kwargs = sandbox.execute.call_args
    env = kwargs.get("env", {})
    assert env["PYTHONPATH"] == "/path/to/scripts"


@pytest.mark.asyncio
async def test_execute_code_respects_max_timeout() -> None:
    """max_timeout should cap the sandbox timeout."""
    tenant = TenantContext(tenant_id="t", user_id="u")
    sandbox = AsyncMock()
    sandbox.execute.return_value = ExecuteResult(
        execution_id="e", exit_code=0, stdout="", stderr="", output_files={}, duration_ms=1
    )

    tool = create_execute_code_tool(sandbox, tenant, max_timeout=30)
    await tool.ainvoke({"code": "pass", "timeout": 90})

    _, kwargs = sandbox.execute.call_args
    assert kwargs["timeout"] <= 30
