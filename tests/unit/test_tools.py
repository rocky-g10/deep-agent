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
    # Direct env vars from resource_env
    assert env["DB_HOST"] == "localhost"
    assert env["DB_PORT"] == "8123"
    assert env["DB_NAME"] == "default"
    # Prefixed env vars for multi-resource disambiguation
    assert env["CH_EQUITIES_DB_HOST"] == "localhost"
    assert env["CH_EQUITIES_DB_PORT"] == "8123"
    assert env["CH_EQUITIES_DB_NAME"] == "default"
