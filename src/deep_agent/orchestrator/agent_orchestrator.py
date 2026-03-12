"""Agent orchestration flow for skill, tools, and runtime coordination."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.tools import BaseTool

from deep_agent.mcp.manager import MCPManager
from deep_agent.models import (
    AgentEvent,
    ErrorEvent,
    SkillContent,
    SkillMatchEvent,
    SkillSummary,
    TenantContext,
)
from deep_agent.models.skills import AgentSkillBindings
from deep_agent.runtime.llm_router import LLMRouter
from deep_agent.runtime.protocol import RuntimeAdapter
from deep_agent.sandbox.protocol import SandboxManager
from deep_agent.skills.engine import SkillEngine
from deep_agent.tools.execute_code import create_execute_code_tool

logger = logging.getLogger(__name__)


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
        try:
            if not skill_bindings.bound_skill_ids:
                logger.warning(
                    "Agent '%s' has no bound skills — no skills will be matched",
                    skill_bindings.agent_id,
                )

            all_skills = self._skill_engine.discover(skill_bindings)
            matched_skills = self._skill_engine.match(message, skill_bindings, top_k=1)

            skill_content: SkillContent | None = None
            allowed_tools: list[str] | None = None

            if matched_skills:
                top_match = matched_skills[0]
                yield SkillMatchEvent(skill_id=top_match.skill_id, confidence=top_match.score)
                try:
                    skill_content = self._skill_engine.load(top_match.skill_id, skill_bindings)
                    allowed_tools = list(skill_content.allowed_tools)
                except Exception as exc:
                    logger.warning("Failed to load matched skill '%s': %s", top_match.skill_id, exc)

            llm_config = self._llm_router.resolve(context)
            skill_timeout: int | None = None
            if skill_content is not None and skill_content.quality.timeout != 60:
                skill_timeout = skill_content.quality.timeout
            scripts_dirs = (
                [skill_content.scripts_path]
                if skill_content and skill_content.scripts_path
                else None
            )
            builtin_tools = self._build_builtin_tools(
                context, scripts_dirs=scripts_dirs, timeout=skill_timeout
            )
            mcp_tools = await self._get_mcp_tools()
            all_tools = builtin_tools + self._extra_tools + mcp_tools
            if allowed_tools is not None:
                all_tools = _filter_tools(all_tools, allowed_tools)

            system_prompt = self._build_system_prompt(
                context=context,
                skill_content=skill_content,
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

    async def _get_mcp_tools(self) -> list[BaseTool]:
        """Return MCP tools if manager is configured and connected."""
        if self._mcp_manager is None:
            return []

        try:
            if not self._mcp_manager.connected:
                await self._mcp_manager.connect()
            return await self._mcp_manager.get_tools()
        except Exception as exc:
            logger.warning("Failed to get MCP tools: %s", exc)
            return []

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
