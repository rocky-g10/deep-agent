"""Unit tests for HITL system prompt injection."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from deep_agent.models import TenantContext
from deep_agent.models.skills import SkillContent
from deep_agent.orchestrator.agent_orchestrator import AgentOrchestrator


def _skill(
    skill_id: str,
    *,
    requires_approval: bool = False,
    hints: dict[str, str] | None = None,
) -> SkillContent:
    return SkillContent(
        skill_id=skill_id,
        name=skill_id.split("/")[-1],
        description=f"{skill_id} description",
        version="1.0.0",
        tags=["risk"],
        allowed_tools=["execute_code"],
        body="Instructions",
        requires_approval=requires_approval,
        clarification_hints=hints or {},
    )


def _orchestrator() -> AgentOrchestrator:
    return AgentOrchestrator(
        skill_engine=MagicMock(),
        llm_router=MagicMock(),
        runtime=MagicMock(),
        sandbox=AsyncMock(),
    )


def test_prompt_contains_hitl_block_when_tool_present() -> None:
    prompt = _orchestrator()._build_system_prompt(
        context=TenantContext(tenant_id="risk", user_id="u"),
        active_skills=[_skill("risk/portfolio-var")],
        all_skills=[],
        has_human_interaction=True,
    )
    assert "## Human Interaction" in prompt
    assert "`human_interaction` tool" in prompt


def test_prompt_contains_requires_approval_directive() -> None:
    prompt = _orchestrator()._build_system_prompt(
        context=TenantContext(tenant_id="risk", user_id="u"),
        active_skills=[_skill("risk/portfolio-var", requires_approval=True)],
        all_skills=[],
        has_human_interaction=True,
    )
    assert "IMPORTANT: You MUST call the `human_interaction` tool with kind=\"approve\"" in prompt


def test_prompt_contains_merged_clarification_hints() -> None:
    prompt = _orchestrator()._build_system_prompt(
        context=TenantContext(tenant_id="risk", user_id="u"),
        active_skills=[
            _skill("risk/portfolio-var", hints={"missing_portfolio": "Which portfolio?"}),
            _skill("equities/zscore-monitor", hints={"missing_symbol": "Which symbol?"}),
        ],
        all_skills=[],
        has_human_interaction=True,
    )
    assert "Clarification guidance:" in prompt
    assert "- Which portfolio?" in prompt
    assert "- Which symbol?" in prompt


def test_prompt_no_hitl_block_when_not_enabled() -> None:
    prompt = _orchestrator()._build_system_prompt(
        context=TenantContext(tenant_id="risk", user_id="u"),
        active_skills=[_skill("risk/portfolio-var", requires_approval=True)],
        all_skills=[],
        has_human_interaction=False,
    )
    assert "## Human Interaction" not in prompt
