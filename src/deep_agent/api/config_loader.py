"""Load agent bindings and tenant resource config from YAML files."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from deep_agent.models.context import TenantContext
from deep_agent.models.skills import AgentSkillBindings

logger = logging.getLogger(__name__)


class ConfigLoadError(ValueError):
    """Raised when a config file is malformed."""


def load_agent_bindings(
    agent_id: str,
    config_root: Path = Path("config"),
) -> AgentSkillBindings | None:
    """Load agent skill bindings from config/agents/{agent_id}.yaml.

    Returns None if the file does not exist (caller should apply a default).
    Raises ConfigLoadError if the file exists but is malformed.
    """
    config_path = (config_root / "agents" / f"{agent_id}.yaml").resolve()
    safe_root = config_root.resolve()
    if not config_path.is_relative_to(safe_root):
        raise ConfigLoadError("Agent config path escapes config root: path traversal detected")

    if not config_path.is_file():
        logger.debug("No agent config at %s — returning None", config_path)
        return None

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ConfigLoadError(f"Failed to parse agent config {config_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigLoadError(f"Agent config {config_path} must be a YAML mapping")

    agent_id_from_file = raw.get("agent_id", agent_id)
    bound_ids = raw.get("bound_skill_ids", [])
    if not isinstance(bound_ids, list):
        raise ConfigLoadError(f"Agent config {config_path}: bound_skill_ids must be a list")

    return AgentSkillBindings(
        agent_id=str(agent_id_from_file),
        bound_skill_ids=tuple(str(s) for s in bound_ids),
    )


def load_resource_env(
    tenant_id: str,
    config_root: Path = Path("config"),
) -> dict[str, dict[str, str]]:
    """Load resource aliases from config/tenants/{tenant_id}/resources.yaml.

    Returns empty dict if the file does not exist.
    Raises ConfigLoadError if the file exists but is malformed.
    """
    config_path = (config_root / "tenants" / tenant_id / "resources.yaml").resolve()
    safe_root = config_root.resolve()
    if not config_path.is_relative_to(safe_root):
        raise ConfigLoadError("Resource config path escapes config root: path traversal detected")

    if not config_path.is_file():
        logger.debug("No resource config at %s — returning empty", config_path)
        return {}

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ConfigLoadError(f"Failed to parse resource config {config_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigLoadError(f"Resource config {config_path} must be a YAML mapping")

    aliases = raw.get("resource_aliases", {})
    if not isinstance(aliases, dict):
        raise ConfigLoadError(f"Resource config {config_path}: resource_aliases must be a mapping")

    result: dict[str, dict[str, str]] = {}
    for alias_name, env_vars in aliases.items():
        if isinstance(env_vars, dict):
            result[str(alias_name)] = {str(k): str(v) for k, v in env_vars.items()}

    return result


def build_tenant_context(
    tenant_id: str,
    config_root: Path = Path("config"),
    user_id: str = "anonymous",
) -> TenantContext:
    """Build a TenantContext from config files.

    Loads resource env from config/tenants/{tenant_id}/resources.yaml.
    Sets mcp_config_path to tenants/{tenant_id}/mcp.json (relative to config_root).
    """
    resource_env = load_resource_env(tenant_id, config_root)
    mcp_config_path = f"tenants/{tenant_id}/mcp.json"
    return TenantContext(
        tenant_id=tenant_id,
        user_id=user_id,
        mcp_config_path=mcp_config_path,
        resource_env=resource_env,
    )
