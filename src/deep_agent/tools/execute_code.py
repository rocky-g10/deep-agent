"""execute_code LangChain tool factory."""

from __future__ import annotations

import json
import logging
import os

from langchain_core.tools import BaseTool, tool

from deep_agent.models import TenantContext
from deep_agent.sandbox.protocol import SandboxManager

logger = logging.getLogger(__name__)


def create_execute_code_tool(
    sandbox: SandboxManager,
    tenant: TenantContext,
    scripts_dirs: list[str] | None = None,
) -> BaseTool:
    """Create an execute_code tool with injected sandbox and tenant dependencies."""
    resource_env = _build_resource_env(tenant)
    if scripts_dirs:
        resource_env["PYTHONPATH"] = os.pathsep.join(scripts_dirs)

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
    """Flatten tenant resource aliases into a single env var dict.

    Always emits prefixed keys (e.g. CH_EQUITIES_DB_HOST).
    Emits unprefixed keys only when there is exactly one alias.
    Logs a warning if multiple aliases would collide on unprefixed keys.
    """
    env: dict[str, str] = {}
    aliases = tenant.resource_env

    # Always emit prefixed keys
    for alias_name, alias_vars in aliases.items():
        prefix = alias_name.upper().replace("-", "_")
        for key, value in alias_vars.items():
            env[f"{prefix}_{key}"] = value

    # Emit unprefixed convenience keys only for single-alias tenants
    if len(aliases) == 1:
        alias_vars = next(iter(aliases.values()))
        for key, value in alias_vars.items():
            env[key] = value
    elif len(aliases) > 1:
        # Check for collisions and warn
        seen: dict[str, str] = {}
        for alias_name, alias_vars in aliases.items():
            for key in alias_vars:
                if key in seen:
                    logger.warning(
                        "Resource env collision: key '%s' appears in aliases '%s' and '%s'; "
                        "only prefixed keys emitted",
                        key,
                        seen[key],
                        alias_name,
                    )
                else:
                    seen[key] = alias_name

    return env
