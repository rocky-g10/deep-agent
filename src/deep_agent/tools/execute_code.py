"""execute_code LangChain tool factory."""

from __future__ import annotations

import json
import logging

from langchain_core.tools import BaseTool, tool

from deep_agent.config import AppSettings
from deep_agent.database.registry import DatabaseRegistry
from deep_agent.models import TenantContext
from deep_agent.sandbox.protocol import SandboxManager

logger = logging.getLogger(__name__)


def create_execute_code_tool(
    sandbox: SandboxManager,
    db_registry: DatabaseRegistry,
    tenant: TenantContext,
    settings: AppSettings,
) -> BaseTool:
    """Create an execute_code tool with injected sandbox and tenant dependencies."""
    db_env = _build_db_env(db_registry=db_registry, tenant=tenant, settings=settings)

    @tool
    async def execute_code(code: str, timeout: int = 60) -> str:
        """Execute Python code in a sandboxed environment."""
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

    return execute_code


def _build_db_env(
    db_registry: DatabaseRegistry,
    tenant: TenantContext,
    settings: AppSettings,
) -> dict[str, str]:
    """Build database-related environment variables from accessible aliases."""
    env: dict[str, str] = {}
    aliases = db_registry.list_aliases(tenant)

    for alias_info in aliases:
        try:
            conn = db_registry.get_connection(alias_info.alias, tenant)
            prefix = alias_info.alias.upper().replace("-", "_")
            env[f"{prefix}_HOST"] = conn.host
            env[f"{prefix}_PORT"] = str(conn.port)
            env[f"{prefix}_NAME"] = conn.database
            env[f"{prefix}_USER"] = _extract_db_user(conn.credentials_ref)
            env[f"{prefix}_PASS"] = _extract_db_pass(settings)
        except Exception:
            logger.warning("Failed to resolve connection for alias %s", alias_info.alias)

    if aliases:
        first = aliases[0]
        try:
            conn = db_registry.get_connection(first.alias, tenant)
            env["DB_HOST"] = conn.host
            env["DB_PORT"] = str(conn.port)
            env["DB_NAME"] = conn.database
            env["DB_USER"] = _extract_db_user(conn.credentials_ref)
            env["DB_PASS"] = _extract_db_pass(settings)
        except Exception:
            logger.warning("Failed to resolve default DB_* env for alias %s", first.alias)

    return env


def _extract_db_user(credentials_ref: str) -> str:
    """Extract username hint from credentials_ref format used in Phase 1."""
    if ":" in credentials_ref:
        return credentials_ref.rsplit(":", maxsplit=1)[-1]
    return "default"


def _extract_db_pass(settings: AppSettings) -> str:
    """Extract database password from application settings."""
    if settings.clickhouse_password is not None:
        return settings.clickhouse_password.get_secret_value()
    return ""
