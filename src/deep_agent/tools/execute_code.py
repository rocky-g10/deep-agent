"""execute_code LangChain tool factory."""

from __future__ import annotations

import json
import logging

from langchain_core.tools import BaseTool, tool

from deep_agent.models import TenantContext
from deep_agent.sandbox.protocol import SandboxManager

logger = logging.getLogger(__name__)


def create_execute_code_tool(
    sandbox: SandboxManager,
    tenant: TenantContext,
) -> BaseTool:
    """Create an execute_code tool with injected sandbox and tenant dependencies."""
    resource_env = _build_resource_env(tenant)

    @tool
    async def execute_code(code: str, timeout: int = 60) -> str:
        """Execute Python code in a sandboxed environment."""
        try:
            result = await sandbox.execute(code=code, timeout=timeout, env=resource_env)
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

    return execute_code


def _build_resource_env(tenant: TenantContext) -> dict[str, str]:
    """Flatten tenant resource aliases into a single env var dict."""
    env: dict[str, str] = {}
    for alias_name, alias_vars in tenant.resource_env.items():
        for key, value in alias_vars.items():
            env[key] = value
        # Also set prefixed vars for multi-resource disambiguation
        prefix = alias_name.upper().replace("-", "_")
        for key, value in alias_vars.items():
            prefixed_key = f"{prefix}_{key}"
            env[prefixed_key] = value
    return env
