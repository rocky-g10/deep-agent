"""Agent orchestration flow for skill, tools, and runtime coordination."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage, messages_from_dict, messages_to_dict
from langchain_core.tools import BaseTool

from deep_agent.hitl.audit import HITLAuditEvent, emit_hitl_audit
from deep_agent.hitl.checkpoint import Checkpoint, CheckpointStore, InMemoryCheckpointStore
from deep_agent.hitl.run_state import InvalidStateTransition, RunStateManager
from deep_agent.mcp.config import MCPConfig, merge_mcp_configs
from deep_agent.mcp.manager import MCPManager
from deep_agent.models import (
    AgentCompleteEvent,
    AgentEvent,
    ErrorEvent,
    HumanInteractionRequest,
    InteractionRequiredEvent,
    InteractionResponse,
    SkillContent,
    SkillMatchEvent,
    SkillSummary,
    TenantContext,
    ToolCallEvent,
)
from deep_agent.models.skills import AgentSkillBindings, MCPToolBinding, SkillMCPServer
from deep_agent.runtime.llm_router import LLMRouter
from deep_agent.runtime.protocol import RuntimeAdapter
from deep_agent.sandbox.protocol import SandboxManager
from deep_agent.skills.engine import SkillEngine
from deep_agent.tools.execute_code import create_execute_code_tool
from deep_agent.tools.human_interaction import create_human_interaction_tool

logger = logging.getLogger(__name__)

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
        run_state_manager: RunStateManager | None = None,
        checkpoint_store: CheckpointStore | None = None,
    ) -> None:
        """Initialize orchestrator with required subsystems."""
        self._skill_engine = skill_engine
        self._llm_router = llm_router
        self._runtime = runtime
        self._sandbox = sandbox
        self._mcp_manager = mcp_manager
        self._extra_tools = extra_tools or []
        self._run_state_manager = run_state_manager or RunStateManager()
        self._checkpoint_store = checkpoint_store or InMemoryCheckpointStore()

    async def handle_message(
        self,
        message: str,
        context: TenantContext,
        skill_bindings: AgentSkillBindings,
        history: list[Any] | None = None,
        session_id: str | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Process a message and stream normalized runtime events."""
        _temp_mcp: MCPManager | None = None
        run_id: str | None = None
        try:
            if not skill_bindings.bound_skill_ids:
                logger.warning(
                    "Agent '%s' has no bound skills — no skills will be matched",
                    skill_bindings.agent_id,
                )

            effective_session_id = session_id or f"{context.tenant_id}:{context.user_id}"
            run = self._run_state_manager.create_run(session_id=effective_session_id)
            run_id = run.run_id

            all_skills = self._skill_engine.discover(skill_bindings)
            matched_skills = self._skill_engine.match(
                message,
                skill_bindings,
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

            llm_config = self._llm_router.resolve(context)
            builtin_tools = self._build_builtin_tools(
                context, scripts_dirs=scripts_dirs, timeout=skill_timeout
            )

            mcp_tools, _temp_mcp = await self._resolve_mcp_tools(skill_mcp, skill_mcp_bindings)

            all_tools = builtin_tools + self._extra_tools + mcp_tools
            if allowed_tools is not None:
                all_tools = _filter_tools(all_tools, allowed_tools)
            all_tools.append(create_human_interaction_tool())

            system_prompt = self._build_system_prompt(
                context=context,
                active_skills=active_skills,
                all_skills=all_skills,
                has_human_interaction=True,
            )

            agent = self._runtime.create_agent(
                model=llm_config.model,
                tools=all_tools,
                system_prompt=system_prompt,
                temperature=llm_config.temperature,
                max_tokens=llm_config.max_tokens,
            )

            async for event in self._runtime.stream(agent, message, context, history=history):
                if (
                    isinstance(event, ToolCallEvent)
                    and event.tool == "human_interaction"
                    and run_id is not None
                ):
                    interaction = HumanInteractionRequest.model_validate(event.input)
                    tool_call_id = event.tool_call_id
                    interaction_skill_id = _select_interaction_skill_id(
                        active_skills, matched_skills
                    )
                    checkpoint = Checkpoint(
                        run_id=run_id,
                        session_id=effective_session_id,
                        conversation_history=self._serialize_history(history, message),
                        pending_interaction=interaction,
                        skill_id=interaction_skill_id,
                        tool_call_id=tool_call_id,
                        created_at=time.time(),
                        active_skill_ids=[skill.skill_id for skill in active_skills],
                        tenant_context={
                            "tenant_id": context.tenant_id,
                            "user_id": context.user_id,
                            "mcp_config_path": context.mcp_config_path,
                            "resource_env": context.resource_env,
                        },
                        skill_bindings={
                            "agent_id": skill_bindings.agent_id,
                            "bound_skill_ids": list(skill_bindings.bound_skill_ids),
                        },
                        original_message=message,
                    )
                    await self._checkpoint_store.save(checkpoint)
                    self._run_state_manager.suspend(run_id, interaction)
                    emit_hitl_audit(
                        HITLAuditEvent(
                            timestamp=datetime.now(UTC).isoformat(),
                            trace_id=run_id,
                            session_id=effective_session_id,
                            user_id=context.user_id,
                            tenant_id=context.tenant_id,
                            action="interaction_requested",
                            interaction_kind=interaction.kind,
                            question_or_action=interaction.question
                            or interaction.action_description
                            or "collect_fields",
                            risk_level=interaction.risk_level,
                        )
                    )
                    yield InteractionRequiredEvent(
                        run_id=run_id,
                        skill_id=interaction_skill_id,
                        interaction=interaction,
                    )
                    return
                yield event
                if isinstance(event, AgentCompleteEvent) and run_id is not None:
                    self._run_state_manager.complete(run_id)
                    break
        except Exception as exc:
            logger.exception("Orchestrator error")
            if run_id is not None:
                run_info = self._run_state_manager.get_run(run_id)
                if run_info is not None and run_info.state.value == "running":
                    try:
                        self._run_state_manager.fail(run_id)
                    except Exception:
                        logger.debug("Failed to mark run as failed", exc_info=True)
            yield ErrorEvent(code="ORCHESTRATOR_ERROR", message=str(exc))
        finally:
            if _temp_mcp is not None:
                await _temp_mcp.disconnect()

    async def resume_run(
        self,
        run_id: str,
        response: InteractionResponse,
    ) -> AsyncIterator[AgentEvent]:
        """Resume a suspended run with a human response payload."""
        _temp_mcp: MCPManager | None = None
        checkpoint = await self._checkpoint_store.load(run_id)
        if checkpoint is None:
            yield ErrorEvent(code="HITL_UNKNOWN_RUN", message="Unknown or expired run_id")
            return

        run_info = self._run_state_manager.get_run(run_id)
        if run_info is None:
            yield ErrorEvent(code="HITL_UNKNOWN_RUN", message="Unknown run_id")
            return
        if run_info.state.value == "timed_out":
            try:
                self._run_state_manager.apply_fallback(run_id)
            except InvalidStateTransition as exc:
                yield ErrorEvent(code="HITL_INVALID_STATE", message=str(exc))
                return
            run_info = self._run_state_manager.get_run(run_id)
            if run_info is None:
                yield ErrorEvent(code="HITL_UNKNOWN_RUN", message="Unknown run_id")
                return
        if run_info.state.value != "suspended" and run_info.state.value != "running":
            yield ErrorEvent(code="HITL_NOT_SUSPENDED", message="Run is not suspended")
            return

        if run_info.state.value == "suspended":
            try:
                self._run_state_manager.resume(run_id, response)
            except InvalidStateTransition as exc:
                yield ErrorEvent(code="HITL_INVALID_STATE", message=str(exc))
                return
        post_resume = self._run_state_manager.get_run(run_id)
        if post_resume is not None:
            latency_ms = None
            if post_resume.suspended_at is not None and post_resume.responded_at is not None:
                latency_ms = int((post_resume.responded_at - post_resume.suspended_at) * 1000)
            checkpoint_context = checkpoint.tenant_context
            emit_hitl_audit(
                HITLAuditEvent(
                    timestamp=datetime.now(UTC).isoformat(),
                    trace_id=run_id,
                    session_id=post_resume.session_id,
                    user_id=str(checkpoint_context.get("user_id", "")),
                    tenant_id=str(checkpoint_context.get("tenant_id", "")),
                    action="response_submitted",
                    interaction_kind=response.kind,
                    question_or_action=checkpoint.pending_interaction.question
                    or checkpoint.pending_interaction.action_description
                    or "collect_fields",
                    response=response.model_dump_json(),
                    responder_id=str(checkpoint_context.get("user_id", "")),
                    latency_ms=latency_ms,
                    risk_level=checkpoint.pending_interaction.risk_level,
                    outcome=_response_outcome(response),
                )
            )

        try:
            context_data = checkpoint.tenant_context
            bindings_data = checkpoint.skill_bindings
            context = TenantContext(
                tenant_id=str(context_data.get("tenant_id", "default")),
                user_id=str(context_data.get("user_id", "anonymous")),
                mcp_config_path=str(context_data.get("mcp_config_path", "")),
                resource_env=dict(context_data.get("resource_env", {})),
            )
            skill_bindings = AgentSkillBindings(
                agent_id=str(bindings_data.get("agent_id", "")),
                bound_skill_ids=tuple(bindings_data.get("bound_skill_ids", [])),
            )

            all_skills = self._skill_engine.discover(skill_bindings)
            matched_skills = self._skill_engine.match(
                checkpoint.original_message,
                skill_bindings,
                min_score=_DEFAULT_MULTI_SKILL_MIN_SCORE,
            )
            active_skills: list[SkillContent] = []
            for match in matched_skills:
                try:
                    active_skills.append(self._skill_engine.load(match.skill_id, skill_bindings))
                except Exception as exc:
                    logger.warning("Failed to load matched skill '%s': %s", match.skill_id, exc)

            merged = _merge_skill_contents(active_skills)
            scripts_dirs = merged["scripts_dirs"]
            skill_timeout = merged["skill_timeout"]
            skill_mcp = merged["mcp_servers"]
            skill_mcp_bindings = merged["mcp_tool_bindings"]
            allowed_tools = merged["allowed_tools"]

            llm_config = self._llm_router.resolve(context)
            builtin_tools = self._build_builtin_tools(
                context, scripts_dirs=scripts_dirs, timeout=skill_timeout
            )
            mcp_tools, _temp_mcp = await self._resolve_mcp_tools(skill_mcp, skill_mcp_bindings)
            all_tools = builtin_tools + self._extra_tools + mcp_tools
            if allowed_tools is not None:
                all_tools = _filter_tools(all_tools, allowed_tools)
            all_tools.append(create_human_interaction_tool())

            system_prompt = self._build_system_prompt(
                context=context,
                active_skills=active_skills,
                all_skills=all_skills,
                has_human_interaction=True,
            )
            agent = self._runtime.create_agent(
                model=llm_config.model,
                tools=all_tools,
                system_prompt=system_prompt,
                temperature=llm_config.temperature,
                max_tokens=llm_config.max_tokens,
            )

            history = list(messages_from_dict(checkpoint.conversation_history))
            history.append(
                ToolMessage(
                    content=response.model_dump_json(),
                    tool_call_id=checkpoint.tool_call_id or "human_interaction",
                )
            )
            async for event in self._runtime.stream(agent, "", context, history=history):
                if isinstance(event, ToolCallEvent) and event.tool == "human_interaction":
                    interaction = HumanInteractionRequest.model_validate(event.input)
                    updated = checkpoint.model_copy(
                        update={
                            "conversation_history": messages_to_dict(history),
                            "pending_interaction": interaction,
                            "skill_id": _select_interaction_skill_id(active_skills, matched_skills),
                            "tool_call_id": event.tool_call_id,
                            "created_at": time.time(),
                            "active_skill_ids": [skill.skill_id for skill in active_skills],
                        }
                    )
                    await self._checkpoint_store.save(updated)
                    self._run_state_manager.suspend(run_id, interaction)
                    checkpoint_context = checkpoint.tenant_context
                    emit_hitl_audit(
                        HITLAuditEvent(
                            timestamp=datetime.now(UTC).isoformat(),
                            trace_id=run_id,
                            session_id=checkpoint.session_id,
                            user_id=str(checkpoint_context.get("user_id", "")),
                            tenant_id=str(checkpoint_context.get("tenant_id", "")),
                            action="interaction_requested",
                            interaction_kind=interaction.kind,
                            question_or_action=interaction.question
                            or interaction.action_description
                            or "collect_fields",
                            risk_level=interaction.risk_level,
                        )
                    )
                    yield InteractionRequiredEvent(
                        run_id=run_id,
                        skill_id=_select_interaction_skill_id(active_skills, matched_skills),
                        interaction=interaction,
                    )
                    return
                yield event
                if isinstance(event, AgentCompleteEvent):
                    self._run_state_manager.complete(run_id)
                    await self._checkpoint_store.delete(run_id)
                    break
        except Exception as exc:
            logger.exception("Resume run error")
            yield ErrorEvent(code="HITL_RESUME_ERROR", message=str(exc))
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
        active_skills: list[SkillContent],
        all_skills: list[SkillSummary],
        has_human_interaction: bool = False,
    ) -> str:
        """Construct a full system prompt with skills, resources, and tool instructions."""
        parts: list[str] = []

        parts.append(f"You are Deep Agent, an AI assistant for the {context.tenant_id} desk.")

        if all_skills:
            parts.append("")
            parts.append("## Available Skills")
            for skill_summary in all_skills:
                parts.append(f"- {skill_summary.name}: {skill_summary.description}")

        if len(active_skills) == 1:
            skill = active_skills[0]
            parts.append("")
            parts.append(f"## Active Skill: {skill.name}")
            parts.append(skill.body)
        elif len(active_skills) > 1:
            parts.append("")
            parts.append("## Active Skills")
            parts.append(
                "You may combine functionality from multiple active skills in a single "
                "`execute_code` call. Each skill's `scripts/` directory is on PYTHONPATH."
            )
            for skill in active_skills:
                parts.append("")
                parts.append(f"### Skill: {skill.name}")
                parts.append(skill.body)

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

        if has_human_interaction:
            parts.append("")
            parts.append("## Human Interaction")
            parts.append(
                "You have access to the `human_interaction` tool. Use it when you need "
                "clarification, approval for a risky action, or structured input from the user."
            )
            parts.append('The three interaction kinds are: "clarify", "approve", "collect".')
            if any(skill.requires_approval for skill in active_skills):
                parts.append("")
                parts.append(
                    'IMPORTANT: You MUST call the `human_interaction` tool with kind="approve" '
                    "before executing any trade, order, or irreversible action. Present the "
                    "full action details and risk level."
                )
            hint_lines = [
                hint for skill in active_skills for hint in skill.clarification_hints.values()
            ]
            if hint_lines:
                parts.append("")
                parts.append("Clarification guidance:")
                for hint in hint_lines:
                    parts.append(f"- {hint}")

        return "\n".join(parts)

    @staticmethod
    def _serialize_history(history: list[Any] | None, message: str) -> list[dict[str, Any]]:
        messages: list[Any] = list(history or [])
        messages.append(HumanMessage(content=message))
        return messages_to_dict(messages)

    @property
    def run_state_manager(self) -> RunStateManager:
        """Expose run-state manager for API handlers."""
        return self._run_state_manager

    @property
    def checkpoint_store(self) -> CheckpointStore:
        """Expose checkpoint store for API handlers."""
        return self._checkpoint_store


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
    max_timeout = max(skill.quality.timeout for skill in active_skills)
    skill_timeout: int | None = max_timeout if max_timeout > 60 else None

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


def _select_interaction_skill_id(
    active_skills: list[SkillContent], matched_skills: list[SkillSummary]
) -> str | None:
    """Choose skill attribution for HITL interaction events."""
    by_id = {skill.skill_id: skill for skill in active_skills}
    for matched in matched_skills:
        skill = by_id.get(matched.skill_id)
        if skill is not None and skill.requires_approval:
            return skill.skill_id
    if active_skills:
        return active_skills[0].skill_id
    return None


def _response_outcome(response: InteractionResponse) -> str:
    if response.kind == "approve":
        return "approved" if response.approved else "denied"
    return "submitted"
