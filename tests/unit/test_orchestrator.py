"""Unit tests for AgentOrchestrator."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import SecretStr

from deep_agent.config import AppSettings
from deep_agent.models import (
    AgentChunkEvent,
    AgentCompleteEvent,
    AgentEvent,
    ErrorEvent,
    LLMConfig,
    SkillSummary,
    TenantContext,
)
from deep_agent.orchestrator.agent_orchestrator import AgentOrchestrator, _filter_tools


def _mock_skill_engine(matches: list[SkillSummary] | None = None) -> MagicMock:
    engine = MagicMock()
    engine.discover.return_value = matches or []
    engine.match.return_value = matches or []
    if matches:
        skill_content = MagicMock()
        skill_content.name = matches[0].name
        skill_content.skill_id = matches[0].skill_id
        skill_content.body = "## Instructions\nDo stuff."
        skill_content.allowed_tools = ["query_database", "execute_code"]
        engine.load.return_value = skill_content
    return engine


async def _fake_stream(*_args: Any, **_kwargs: Any) -> AsyncIterator[AgentEvent]:
    yield AgentChunkEvent(content="Hello")
    yield AgentCompleteEvent(summary="Hello", tokens_used=10)


@pytest.mark.asyncio
async def test_handle_message_yields_skill_match_first(tenant_equities: TenantContext) -> None:
    """First event should be SkillMatchEvent when a skill matches."""
    skill_match = SkillSummary(
        skill_id="equities/zscore-monitor",
        name="zscore-monitor",
        description="Monitor z-scores",
        tags=["zscore"],
    )
    engine = _mock_skill_engine([skill_match])

    runtime = MagicMock()
    runtime.create_agent.return_value = MagicMock()
    runtime.stream = _fake_stream

    orchestrator = AgentOrchestrator(
        skill_engine=engine,
        llm_router=MagicMock(resolve=MagicMock(return_value=LLMConfig())),
        runtime=runtime,
        sandbox=AsyncMock(),
        db_registry=MagicMock(
            list_aliases=MagicMock(return_value=[]),
            get_metadata=MagicMock(),
            _settings=AppSettings(OPENAI_API_KEY=SecretStr("test-key")),
        ),
    )

    events = [
        event async for event in orchestrator.handle_message("z-scores for AAPL", tenant_equities)
    ]

    assert events[0].type == "skill_match"
    assert events[0].skill_id == "equities/zscore-monitor"
    assert events[0].confidence < 1.0


@pytest.mark.asyncio
async def test_handle_message_no_skill_match_no_filter(tenant_equities: TenantContext) -> None:
    """When no skills match, all tools should be available (no filtering)."""
    engine = _mock_skill_engine([])

    runtime = MagicMock()
    runtime.create_agent.return_value = MagicMock()
    runtime.stream = _fake_stream

    db_registry = MagicMock()
    db_registry.list_aliases.return_value = []
    db_registry._settings = AppSettings(OPENAI_API_KEY=SecretStr("test-key"))

    orchestrator = AgentOrchestrator(
        skill_engine=engine,
        llm_router=MagicMock(resolve=MagicMock(return_value=LLMConfig())),
        runtime=runtime,
        sandbox=AsyncMock(),
        db_registry=db_registry,
    )

    events = [
        event async for event in orchestrator.handle_message("random question", tenant_equities)
    ]

    assert not any(event.type == "skill_match" for event in events)
    tools = runtime.create_agent.call_args.kwargs["tools"]
    assert len(tools) >= 2


@pytest.mark.asyncio
async def test_system_prompt_contains_skill_body(tenant_equities: TenantContext) -> None:
    """System prompt should include the matched skill instructions."""
    skill_match = SkillSummary(
        skill_id="common/db-query",
        name="db-query",
        description="Query databases",
        tags=["database"],
    )
    engine = _mock_skill_engine([skill_match])

    runtime = MagicMock()
    runtime.create_agent.return_value = MagicMock()
    runtime.stream = _fake_stream

    db_registry = MagicMock()
    db_registry.list_aliases.return_value = []
    db_registry._settings = AppSettings(OPENAI_API_KEY=SecretStr("test-key"))

    orchestrator = AgentOrchestrator(
        skill_engine=engine,
        llm_router=MagicMock(resolve=MagicMock(return_value=LLMConfig())),
        runtime=runtime,
        sandbox=AsyncMock(),
        db_registry=db_registry,
    )

    _ = [event async for event in orchestrator.handle_message("query data", tenant_equities)]

    system_prompt = runtime.create_agent.call_args.kwargs["system_prompt"]
    assert "Active Skill: db-query" in system_prompt
    assert "Do stuff" in system_prompt


@pytest.mark.asyncio
async def test_tool_filtering_by_allowed_tools() -> None:
    """Only tools listed in allowed_tools should be passed through."""
    tool_a = MagicMock()
    tool_a.name = "execute_code"
    tool_b = MagicMock()
    tool_b.name = "query_database"
    tool_c = MagicMock()
    tool_c.name = "mcp_echo"

    filtered = _filter_tools([tool_a, tool_b, tool_c], ["execute_code", "query_database"])

    assert len(filtered) == 2
    names = {tool.name for tool in filtered}
    assert "execute_code" in names
    assert "query_database" in names
    assert "mcp_echo" not in names


@pytest.mark.asyncio
async def test_handle_message_error_yields_error_event(tenant_equities: TenantContext) -> None:
    """Unexpected orchestrator errors should emit ErrorEvent."""
    engine = MagicMock()
    engine.discover.return_value = []
    engine.match.side_effect = RuntimeError("engine crashed")

    orchestrator = AgentOrchestrator(
        skill_engine=engine,
        llm_router=MagicMock(),
        runtime=MagicMock(),
        sandbox=AsyncMock(),
        db_registry=MagicMock(
            list_aliases=MagicMock(return_value=[]),
            _settings=AppSettings(OPENAI_API_KEY=SecretStr("test-key")),
        ),
    )

    events = [event async for event in orchestrator.handle_message("test", tenant_equities)]

    assert any(isinstance(event, ErrorEvent) for event in events)


@pytest.mark.asyncio
async def test_handle_message_without_mcp_manager(tenant_equities: TenantContext) -> None:
    """Orchestrator should work without MCPManager configured."""
    engine = _mock_skill_engine([])
    runtime = MagicMock()
    runtime.create_agent.return_value = MagicMock()
    runtime.stream = _fake_stream

    orchestrator = AgentOrchestrator(
        skill_engine=engine,
        llm_router=MagicMock(resolve=MagicMock(return_value=LLMConfig())),
        runtime=runtime,
        sandbox=AsyncMock(),
        db_registry=MagicMock(
            list_aliases=MagicMock(return_value=[]),
            _settings=AppSettings(OPENAI_API_KEY=SecretStr("test-key")),
        ),
        mcp_manager=None,
    )

    events = [event async for event in orchestrator.handle_message("hello", tenant_equities)]

    assert isinstance(events[-1], AgentCompleteEvent)
