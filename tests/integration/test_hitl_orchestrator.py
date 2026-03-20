"""Integration tests for HITL suspend/resume orchestration behavior."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from deep_agent.hitl.checkpoint import Checkpoint, InMemoryCheckpointStore
from deep_agent.hitl.run_state import RunStateManager
from deep_agent.models import (
    AgentCompleteEvent,
    AgentEvent,
    ErrorEvent,
    InteractionResponse,
    LLMConfig,
    ToolCallEvent,
    ToolResultEvent,
)
from deep_agent.models.skills import AgentSkillBindings
from deep_agent.orchestrator.agent_orchestrator import AgentOrchestrator


class MockRuntime:
    """Runtime that replays a configured event sequence per stream call."""

    def __init__(self, stream_sequences: list[list[AgentEvent]]) -> None:
        self._stream_sequences = stream_sequences
        self._stream_turn = 0
        self.last_system_prompt = ""

    def create_agent(
        self,
        model: str,
        tools: list[Any],
        system_prompt: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        _ = model, kwargs
        self.last_system_prompt = system_prompt
        return {"tools": tools, "system_prompt": system_prompt}

    async def invoke(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - not used here
        raise NotImplementedError

    async def stream(
        self,
        agent: dict[str, Any],
        message: str,
        context: Any,
        history: list[Any] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        _ = agent, message, context, history
        events = self._stream_sequences[self._stream_turn]
        self._stream_turn += 1
        for event in events:
            yield event


def _mock_skill_engine() -> MagicMock:
    engine = MagicMock()
    engine.discover.return_value = []
    engine.match.return_value = []
    return engine


def _bindings() -> AgentSkillBindings:
    return AgentSkillBindings(agent_id="equities-agent", bound_skill_ids=("common/db-query",))


@pytest.mark.asyncio
async def test_hitl_orchestrator_normal_flow_no_suspension(tenant_equities: Any) -> None:
    runtime = MockRuntime(
        stream_sequences=[
            [
                ToolResultEvent(tool="execute_code", output="ok"),
                AgentCompleteEvent(summary="done", tokens_used=1),
            ]
        ]
    )
    manager = RunStateManager()
    orchestrator = AgentOrchestrator(
        skill_engine=_mock_skill_engine(),
        llm_router=MagicMock(resolve=MagicMock(return_value=LLMConfig())),
        runtime=runtime,
        sandbox=AsyncMock(),
        run_state_manager=manager,
    )

    events = [
        event
        async for event in orchestrator.handle_message(
            "hello",
            tenant_equities,
            skill_bindings=_bindings(),
        )
    ]

    assert any(event.type == "agent_complete" for event in events)
    assert not any(event.type == "interaction_required" for event in events)
    assert manager.list_suspended() == []


@pytest.mark.asyncio
async def test_hitl_orchestrator_suspends_on_human_interaction(tenant_equities: Any) -> None:
    runtime = MockRuntime(
        stream_sequences=[
            [
                ToolCallEvent(
                    tool="human_interaction",
                    input={"kind": "clarify", "question": "Which portfolio?"},
                    tool_call_id="tc-1",
                )
            ]
        ]
    )
    manager = RunStateManager()
    orchestrator = AgentOrchestrator(
        skill_engine=_mock_skill_engine(),
        llm_router=MagicMock(resolve=MagicMock(return_value=LLMConfig())),
        runtime=runtime,
        sandbox=AsyncMock(),
        run_state_manager=manager,
    )

    events = [
        event
        async for event in orchestrator.handle_message(
            "need clarification",
            tenant_equities,
            skill_bindings=_bindings(),
        )
    ]

    interaction = next(event for event in events if event.type == "interaction_required")
    assert interaction.interaction.kind == "clarify"
    run = manager.get_run(interaction.run_id)
    assert run is not None
    assert run.state.value == "suspended"


@pytest.mark.asyncio
async def test_hitl_orchestrator_resume_flow_to_completion(tenant_equities: Any) -> None:
    runtime = MockRuntime(
        stream_sequences=[
            [
                ToolCallEvent(
                    tool="human_interaction",
                    input={"kind": "clarify", "question": "Which portfolio?"},
                    tool_call_id="tc-1",
                )
            ],
            [AgentCompleteEvent(summary="resumed complete", tokens_used=2)],
        ]
    )
    manager = RunStateManager()
    orchestrator = AgentOrchestrator(
        skill_engine=_mock_skill_engine(),
        llm_router=MagicMock(resolve=MagicMock(return_value=LLMConfig())),
        runtime=runtime,
        sandbox=AsyncMock(),
        run_state_manager=manager,
    )

    first_events = [
        event
        async for event in orchestrator.handle_message(
            "need clarification",
            tenant_equities,
            skill_bindings=_bindings(),
        )
    ]
    interaction = next(event for event in first_events if event.type == "interaction_required")

    resumed_events = [
        event
        async for event in orchestrator.resume_run(
            interaction.run_id,
            InteractionResponse(kind="clarify", value="EQ-MACRO-1"),
        )
    ]

    assert any(event.type == "agent_complete" for event in resumed_events)
    run = manager.get_run(interaction.run_id)
    assert run is not None
    assert run.state.value == "completed"


@pytest.mark.asyncio
async def test_hitl_orchestrator_double_suspend_resume(tenant_equities: Any) -> None:
    runtime = MockRuntime(
        stream_sequences=[
            [
                ToolCallEvent(
                    tool="human_interaction",
                    input={"kind": "clarify", "question": "Which portfolio?"},
                    tool_call_id="tc-1",
                )
            ],
            [
                ToolCallEvent(
                    tool="human_interaction",
                    input={"kind": "approve", "action_description": "Execute hedge?"},
                    tool_call_id="tc-2",
                )
            ],
            [AgentCompleteEvent(summary="all done", tokens_used=3)],
        ]
    )
    manager = RunStateManager()
    orchestrator = AgentOrchestrator(
        skill_engine=_mock_skill_engine(),
        llm_router=MagicMock(resolve=MagicMock(return_value=LLMConfig())),
        runtime=runtime,
        sandbox=AsyncMock(),
        run_state_manager=manager,
    )

    first_events = [
        event
        async for event in orchestrator.handle_message(
            "start",
            tenant_equities,
            skill_bindings=_bindings(),
        )
    ]
    first_interaction = next(
        event for event in first_events if event.type == "interaction_required"
    )

    second_events = [
        event
        async for event in orchestrator.resume_run(
            first_interaction.run_id,
            InteractionResponse(kind="clarify", value="EQ-MACRO-1"),
        )
    ]
    second_interaction = next(
        event for event in second_events if event.type == "interaction_required"
    )
    assert second_interaction.run_id == first_interaction.run_id

    final_events = [
        event
        async for event in orchestrator.resume_run(
            first_interaction.run_id,
            InteractionResponse(kind="approve", approved=True),
        )
    ]
    assert any(event.type == "agent_complete" for event in final_events)


@pytest.mark.asyncio
async def test_hitl_orchestrator_resume_unknown_run_id_yields_error() -> None:
    runtime = MockRuntime(stream_sequences=[])
    orchestrator = AgentOrchestrator(
        skill_engine=_mock_skill_engine(),
        llm_router=MagicMock(resolve=MagicMock(return_value=LLMConfig())),
        runtime=runtime,
        sandbox=AsyncMock(),
    )

    events = [
        event
        async for event in orchestrator.resume_run(
            "run-unknown",
            InteractionResponse(kind="clarify", value="EQ-MACRO-1"),
        )
    ]

    assert len(events) == 1
    assert isinstance(events[0], ErrorEvent)


@pytest.mark.asyncio
async def test_hitl_orchestrator_resume_non_suspended_run_yields_error() -> None:
    runtime = MockRuntime(stream_sequences=[])
    manager = RunStateManager()
    checkpoints = InMemoryCheckpointStore()
    run = manager.create_run(session_id="session-1")
    manager.complete(run.run_id)
    await checkpoints.save(
        Checkpoint(
            run_id=run.run_id,
            session_id=run.session_id,
            conversation_history=[],
            pending_interaction={"kind": "clarify", "question": "Which?"},
            created_at=time.time(),
        )
    )
    orchestrator = AgentOrchestrator(
        skill_engine=_mock_skill_engine(),
        llm_router=MagicMock(resolve=MagicMock(return_value=LLMConfig())),
        runtime=runtime,
        sandbox=AsyncMock(),
        run_state_manager=manager,
        checkpoint_store=checkpoints,
    )

    events = [
        event
        async for event in orchestrator.resume_run(
            run.run_id,
            InteractionResponse(kind="clarify", value="EQ-MACRO-1"),
        )
    ]

    assert len(events) == 1
    assert isinstance(events[0], ErrorEvent)
    assert events[0].code == "HITL_NOT_SUSPENDED"


@pytest.mark.asyncio
async def test_hitl_orchestrator_deletes_checkpoint_after_completion(tenant_equities: Any) -> None:
    runtime = MockRuntime(
        stream_sequences=[
            [
                ToolCallEvent(
                    tool="human_interaction",
                    input={"kind": "clarify", "question": "Which portfolio?"},
                    tool_call_id="tc-1",
                )
            ],
            [AgentCompleteEvent(summary="resumed complete", tokens_used=1)],
        ]
    )
    manager = RunStateManager()
    orchestrator = AgentOrchestrator(
        skill_engine=_mock_skill_engine(),
        llm_router=MagicMock(resolve=MagicMock(return_value=LLMConfig())),
        runtime=runtime,
        sandbox=AsyncMock(),
        run_state_manager=manager,
    )

    events = [
        event
        async for event in orchestrator.handle_message(
            "need clarification",
            tenant_equities,
            skill_bindings=_bindings(),
        )
    ]
    interaction = next(event for event in events if event.type == "interaction_required")
    assert await orchestrator.checkpoint_store.load(interaction.run_id) is not None

    _ = [
        event
        async for event in orchestrator.resume_run(
            interaction.run_id,
            InteractionResponse(kind="clarify", value="EQ-MACRO-1"),
        )
    ]
    assert await orchestrator.checkpoint_store.load(interaction.run_id) is None


@pytest.mark.asyncio
async def test_system_prompt_contains_hitl_block(tenant_equities: Any) -> None:
    runtime = MockRuntime(stream_sequences=[[AgentCompleteEvent(summary="done", tokens_used=1)]])
    orchestrator = AgentOrchestrator(
        skill_engine=_mock_skill_engine(),
        llm_router=MagicMock(resolve=MagicMock(return_value=LLMConfig())),
        runtime=runtime,
        sandbox=AsyncMock(),
    )

    _ = [
        event
        async for event in orchestrator.handle_message(
            "hello",
            tenant_equities,
            skill_bindings=_bindings(),
        )
    ]

    assert "## Human Interaction" in runtime.last_system_prompt
    assert "`human_interaction` tool" in runtime.last_system_prompt
