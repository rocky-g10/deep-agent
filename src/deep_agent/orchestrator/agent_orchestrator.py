"""Agent orchestration flow for skill, tools, and runtime coordination."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool

from deep_agent.mcp.config import MCPConfig, merge_mcp_configs
from deep_agent.mcp.manager import MCPManager
from deep_agent.models import (
    AgentEvent,
    ErrorEvent,
    SkillContent,
    SkillMatchEvent,
    SkillSummary,
    TenantContext,
)
from deep_agent.models.skills import AgentSkillBindings, MCPToolBinding, SkillMCPServer
from deep_agent.runtime.llm_router import LLMRouter
from deep_agent.runtime.protocol import RuntimeAdapter
from deep_agent.sandbox.protocol import SandboxManager
from deep_agent.skills.engine import SkillEngine
from deep_agent.tools.execute_code import create_execute_code_tool

logger = logging.getLogger(__name__)

_DEFAULT_MULTI_SKILL_TOP_K = 3
_DEFAULT_MULTI_SKILL_MIN_SCORE = 0.01


class AgentOrchestrator:
    """Coordinates skills, tools, and runtime streaming for one user message."""

    def __init__(
        self,
        skill_engine: SkillEngine,
        llm_router: LLMRouter,
        runtime: RuntimeAdapter,
        sandbox: SandboxManager,
        mcp_manager: MCPManager | None = None,
        extra_tools: list[BaseTool] | None = None,
    ) -> None:
        """Initialize orchestrator with required subsystems."""
        self._skill_engine = skill_engine
        self._llm_router = llm_router
        self._runtime = runtime
        self._sandbox = sandbox
        self._mcp_manager = mcp_manager
        self._extra_tools = extra_tools or []

    async def handle_message(
        self,
        message: str,
        context: TenantContext,
        skill_bindings: AgentSkillBindings,
        history: list[Any] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Process a message and stream normalized runtime events."""
        _temp_mcp: MCPManager | None = None
        try:
            if not skill_bindings.bound_skill_ids:
                logger.warning(
                    "Agent '%s' has no bound skills — no skills will be matched",
                    skill_bindings.agent_id,
                )

            all_skills = self._skill_engine.discover(skill_bindings)
            matched_skills = self._skill_engine.match(
                message,
                skill_bindings,
                top_k=_DEFAULT_MULTI_SKILL_TOP_K,
                min_score=_DEFAULT_MULTI_SKILL_MIN_SCORE,
            )

            active_skills: list[SkillContent] = []
            allowed_tools: list[str] | None = None

            for match in matched_skills:
                yield SkillMatchEvent(skill_id=match.skill_id, confidence=match.score)
                try:
                    content = self._skill_engine.load(match.skill_id, skill_bindings)
                    active_skills.append(content)
                except Exception as exc:
                    logger.warning("Failed to load matched skill '%s': %s", match.skill_id, exc)

            merged = _merge_skill_contents(active_skills)
            allowed_tools = merged["allowed_tools"]
            scripts_dirs = merged["scripts_dirs"]
            skill_timeout = merged["skill_timeout"]
            skill_mcp = merged["mcp_servers"]
            skill_mcp_bindings = merged["mcp_tool_bindings"]

            primary_skill = active_skills[0] if active_skills else None

            llm_config = self._llm_router.resolve(context)
            builtin_tools = self._build_builtin_tools(
                context, scripts_dirs=scripts_dirs, timeout=skill_timeout
            )

            mcp_tools, _temp_mcp = await self._resolve_mcp_tools(skill_mcp, skill_mcp_bindings)

            all_tools = builtin_tools + self._extra_tools + mcp_tools
            if allowed_tools is not None:
                all_tools = _filter_tools(all_tools, allowed_tools)

            system_prompt = self._build_system_prompt(
                context=context,
                skill_content=primary_skill,
                all_skills=all_skills,
            )

            agent = self._runtime.create_agent(
                model=llm_config.model,
                tools=all_tools,
                system_prompt=system_prompt,
                temperature=llm_config.temperature,
                max_tokens=llm_config.max_tokens,
            )

            async for event in self._runtime.stream(agent, message, context, history=history):
                yield event
        except Exception as exc:
            logger.exception("Orchestrator error")
            yield ErrorEvent(code="ORCHESTRATOR_ERROR", message=str(exc))
        finally:
            if _temp_mcp is not None:
                await _temp_mcp.disconnect()

    def _build_builtin_tools(
        self,
        context: TenantContext,
        scripts_dirs: list[str] | None = None,
        timeout: int | None = None,
    ) -> list[BaseTool]:
        """Create built-in tools bound to tenant-scoped dependencies."""
        tools: list[BaseTool] = []
        tools.append(
            create_execute_code_tool(
                sandbox=self._sandbox,
                tenant=context,
                scripts_dirs=scripts_dirs,
                max_timeout=timeout or 60,
            )
        )
        return tools

    async def _resolve_mcp_tools(
        self,
        skill_mcp_servers: list[SkillMCPServer],
        skill_mcp_tool_bindings: list[MCPToolBinding],
    ) -> tuple[list[BaseTool], MCPManager | None]:
        """Resolve MCP tools from skill-level and/or tenant-level configs.

        Returns a tuple of (tools, temp_manager).  *temp_manager* is non-None
        only when a temporary MCPManager was created for skill-level servers;
        the caller is responsible for disconnecting it.
        """
        has_tenant = self._mcp_manager is not None
        has_skill = bool(skill_mcp_servers)

        if not has_tenant and not has_skill:
            return [], None

        # Tenant-only — use the pre-configured manager (no temp manager)
        if not has_skill:
            assert self._mcp_manager is not None
            try:
                if not self._mcp_manager.connected:
                    await self._mcp_manager.connect()
                return await self._mcp_manager.get_tools(), None
            except Exception as exc:
                logger.warning("Failed to get MCP tools: %s", exc)
                return [], None

        # Skill-level servers present — merge with tenant config
        tenant_config = self._mcp_manager.config if self._mcp_manager else MCPConfig()
        merged = merge_mcp_configs(skill_mcp_servers, tenant_config)
        _validate_mcp_tool_bindings(skill_mcp_tool_bindings, merged)

        if not merged.servers:
            return [], None

        manager = MCPManager(merged)
        try:
            await manager.connect()
            if skill_mcp_tool_bindings:
                tools_by_server = await manager.get_tools_by_server()
                tools = _apply_mcp_tool_bindings(tools_by_server, skill_mcp_tool_bindings)
            else:
                tools = await manager.get_tools()
            return tools, manager
        except Exception as exc:
            logger.warning("Failed to get MCP tools: %s", exc)
            await manager.disconnect()
            return [], None

    def _build_system_prompt(
        self,
        context: TenantContext,
        skill_content: SkillContent | None,
        all_skills: list[SkillSummary],
    ) -> str:
        """Construct a full system prompt with skills, resources, and tool instructions."""
        parts: list[str] = []

        parts.append(f"You are Deep Agent, an AI assistant for the {context.tenant_id} desk.")

        if all_skills:
            parts.append("")
            parts.append("## Available Skills")
            for skill_summary in all_skills:
                parts.append(f"- {skill_summary.name}: {skill_summary.description}")

        if skill_content is not None:
            parts.append("")
            parts.append(f"## Active Skill: {skill_content.name}")
            parts.append(skill_content.body)

        if context.resource_env:
            parts.append("")
            parts.append("## Available Resources")
            for alias_name, env_vars in context.resource_env.items():
                keys = ", ".join(sorted(env_vars.keys()))
                parts.append(f"- {alias_name}: env vars [{keys}]")

        parts.append("")
        parts.append("## Tool Usage")
        parts.append("- Use `execute_code` to run Python code in a sandboxed environment.")
        parts.append(
            "- Resource credentials are available as env vars "
            "(e.g., DB_HOST, DB_PORT, KDB_HOST, etc.)."
        )
        parts.append("- Save output files (charts, CSVs) to the output/ directory.")

        return "\n".join(parts)


def _filter_tools(tools: list[BaseTool], allowed_tools: list[str]) -> list[BaseTool]:
    """Filter tools by name against a skill's allowlist."""
    allowed_set = set(allowed_tools)
    return [tool for tool in tools if getattr(tool, "name", None) in allowed_set]


def _validate_mcp_tool_bindings(
    bindings: list[MCPToolBinding],
    merged_config: MCPConfig,
) -> None:
    """Validate binding server names against merged skill+tenant MCP config."""
    if not bindings:
        return

    servers = {server.name for server in merged_config.servers}
    missing = sorted(
        {
            binding.server_name
            for binding in bindings
            if binding.server_name not in servers
        }
    )
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"Invalid mcp-tool-bindings: unknown server(s): {joined}")


def _apply_mcp_tool_bindings(
    tools_by_server: dict[str, list[BaseTool]],
    bindings: list[MCPToolBinding],
) -> list[BaseTool]:
    """Apply explicit tool->server bindings while preserving fallback for unbound tools."""
    bound_server_for_tool: dict[str, str] = {}
    for binding in bindings:
        existing = bound_server_for_tool.get(binding.tool_name)
        if existing and existing != binding.server_name:
            raise ValueError(
                "Invalid mcp-tool-bindings: "
                f"tool '{binding.tool_name}' is bound to multiple servers"
            )
        bound_server_for_tool[binding.tool_name] = binding.server_name

    selected: list[BaseTool] = []

    # Default behavior for unbound tools: include all discovered instances.
    for tools in tools_by_server.values():
        for tool in tools:
            if getattr(tool, "name", None) not in bound_server_for_tool:
                selected.append(tool)

    # Bound tools: include only instances discovered from the bound server.
    for tool_name, server_name in bound_server_for_tool.items():
        matches = [
            tool
            for tool in tools_by_server.get(server_name, [])
            if getattr(tool, "name", None) == tool_name
        ]
        if not matches:
            logger.warning(
                "Bound MCP tool '%s' was not discovered on server '%s'",
                tool_name,
                server_name,
            )
            continue
        selected.extend(matches)

    return selected


def _merge_skill_contents(active_skills: list[SkillContent]) -> dict[str, Any]:
    """Merge multiple skill contents into one execution context."""
    if not active_skills:
        return {
            "allowed_tools": None,
            "scripts_dirs": None,
            "skill_timeout": None,
            "mcp_servers": [],
            "mcp_tool_bindings": [],
        }

    allowed_tools = sorted(
        {
            tool_name
            for skill in active_skills
            for tool_name in skill.allowed_tools
        }
    )
    scripts_dirs = [skill.scripts_path for skill in active_skills if skill.scripts_path]
    skill_timeout = max(skill.quality.timeout for skill in active_skills)
    if skill_timeout <= 60:
        skill_timeout = None

    mcp_servers_by_name: dict[str, SkillMCPServer] = {}
    for skill in active_skills:
        for server in skill.mcp_servers:
            mcp_servers_by_name.setdefault(server.name, server)

    mcp_bindings_by_tool: dict[str, MCPToolBinding] = {}
    for skill in active_skills:
        for binding in skill.mcp_tool_bindings:
            if binding.tool_name in mcp_bindings_by_tool:
                logger.debug(
                    "Dropping duplicate MCP tool binding for '%s' from skill '%s'",
                    binding.tool_name,
                    skill.skill_id,
                )
                continue
            mcp_bindings_by_tool[binding.tool_name] = binding

    _log_script_filename_collisions(active_skills)

    return {
        "allowed_tools": allowed_tools,
        "scripts_dirs": scripts_dirs or None,
        "skill_timeout": skill_timeout,
        "mcp_servers": list(mcp_servers_by_name.values()),
        "mcp_tool_bindings": list(mcp_bindings_by_tool.values()),
    }


def _log_script_filename_collisions(active_skills: list[SkillContent]) -> None:
    """Log warning when python script filenames collide across active skills."""
    filename_to_skills: dict[str, list[str]] = {}
    for skill in active_skills:
        if not skill.scripts_path:
            continue
        scripts_path = Path(skill.scripts_path)
        if not scripts_path.is_dir():
            continue
        for script_file in scripts_path.iterdir():
            if script_file.is_file() and script_file.suffix == ".py":
                filename_to_skills.setdefault(script_file.name, []).append(skill.skill_id)

    for filename, skill_ids in filename_to_skills.items():
        if len(skill_ids) > 1:
            logger.warning(
                "Script filename '%s' exists in multiple skills: %s — "
                "higher-scored skill's version will take precedence on PYTHONPATH",
                filename,
                skill_ids,
            )
