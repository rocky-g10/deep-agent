"""Integration tests for HITL timeout manager."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

import pytest

from deep_agent.hitl.checkpoint import Checkpoint, InMemoryCheckpointStore
from deep_agent.hitl.run_state import RunStateManager
from deep_agent.hitl.timeout_manager import TimeoutManager
from deep_agent.models.events import AgentCompleteEvent
from deep_agent.models.hitl import FieldSpec, HumanInteractionRequest, InteractionResponse


class _MockOrchestrator:
    def __init__(self) -> None:
        self.resume_calls: list[tuple[str, InteractionResponse]] = []

    async def resume_run(
        self,
        run_id: str,
        response: InteractionResponse,
    ) -> AsyncIterator[AgentCompleteEvent]:
        self.resume_calls.append((run_id, response))
        yield AgentCompleteEvent(summary="resumed", tokens_used=0)


@pytest.mark.asyncio
async def test_timeout_manager_abort_path_marks_aborted_and_logs_multiskill_note(
    caplog: Any,
) -> None:
    run_state = RunStateManager()
    checkpoints = InMemoryCheckpointStore()
    orchestrator = _MockOrchestrator()
    manager = TimeoutManager(
        run_state_manager=run_state,
        checkpoint_store=checkpoints,
        orchestrator=orchestrator,  # type: ignore[arg-type]
        check_interval=0.1,
    )

    run = run_state.create_run(session_id="session-1", skill_id="risk/portfolio-var")
    interaction = HumanInteractionRequest(
        kind="clarify",
        question="Which portfolio?",
        timeout_seconds=1,
        fallback="abort",
    )
    run_state.suspend(run.run_id, interaction)
    run.suspended_at = time.time() - 2.0
    await checkpoints.save(
        Checkpoint(
            run_id=run.run_id,
            session_id=run.session_id,
            conversation_history=[],
            pending_interaction=interaction,
            skill_id="risk/portfolio-var",
            active_skill_ids=["risk/portfolio-var", "equities/zscore-monitor"],
            created_at=time.time(),
        )
    )

    with caplog.at_level("WARNING"):
        await manager._check_timeouts()

    updated = run_state.get_run(run.run_id)
    assert updated is not None
    assert updated.state.value == "aborted"
    assert await checkpoints.load(run.run_id) is None
    assert "2 total active skills terminated" in caplog.text


@pytest.mark.asyncio
async def test_timeout_manager_skip_path_resumes_with_skipped_response() -> None:
    run_state = RunStateManager()
    checkpoints = InMemoryCheckpointStore()
    orchestrator = _MockOrchestrator()
    manager = TimeoutManager(
        run_state_manager=run_state,
        checkpoint_store=checkpoints,
        orchestrator=orchestrator,  # type: ignore[arg-type]
        check_interval=0.1,
    )

    run = run_state.create_run(session_id="session-2", skill_id="risk/portfolio-var")
    interaction = HumanInteractionRequest(
        kind="collect",
        fields=[FieldSpec(name="ticker", type="string")],
        timeout_seconds=1,
        fallback="skip",
    )
    run_state.suspend(run.run_id, interaction)
    run.suspended_at = time.time() - 2.0
    await checkpoints.save(
        Checkpoint(
            run_id=run.run_id,
            session_id=run.session_id,
            conversation_history=[],
            pending_interaction=interaction,
            skill_id="risk/portfolio-var",
            created_at=time.time(),
        )
    )

    await manager._check_timeouts()

    assert orchestrator.resume_calls
    resumed_run_id, response = orchestrator.resume_calls[0]
    assert resumed_run_id == run.run_id
    assert response.kind == "collect"
    assert response.values == {"ticker": "[skipped]"}
    updated = run_state.get_run(run.run_id)
    assert updated is not None
    assert updated.state.value == "running"


@pytest.mark.asyncio
async def test_timeout_manager_default_path_uses_field_defaults() -> None:
    run_state = RunStateManager()
    checkpoints = InMemoryCheckpointStore()
    orchestrator = _MockOrchestrator()
    manager = TimeoutManager(
        run_state_manager=run_state,
        checkpoint_store=checkpoints,
        orchestrator=orchestrator,  # type: ignore[arg-type]
        check_interval=0.1,
    )

    run = run_state.create_run(session_id="session-3", skill_id="risk/portfolio-var")
    interaction = HumanInteractionRequest(
        kind="collect",
        fields=[
            FieldSpec(name="ticker", type="string", default="NVDA"),
            FieldSpec(name="qty", type="number"),
        ],
        timeout_seconds=1,
        fallback="default",
    )
    run_state.suspend(run.run_id, interaction)
    run.suspended_at = time.time() - 2.0
    await checkpoints.save(
        Checkpoint(
            run_id=run.run_id,
            session_id=run.session_id,
            conversation_history=[],
            pending_interaction=interaction,
            skill_id="risk/portfolio-var",
            created_at=time.time(),
        )
    )

    await manager._check_timeouts()

    assert orchestrator.resume_calls
    _, response = orchestrator.resume_calls[0]
    assert response.kind == "collect"
    assert response.values == {"ticker": "NVDA", "qty": ""}


@pytest.mark.asyncio
async def test_timeout_manager_does_not_touch_non_expired_runs() -> None:
    run_state = RunStateManager()
    checkpoints = InMemoryCheckpointStore()
    orchestrator = _MockOrchestrator()
    manager = TimeoutManager(
        run_state_manager=run_state,
        checkpoint_store=checkpoints,
        orchestrator=orchestrator,  # type: ignore[arg-type]
        check_interval=0.1,
    )

    run = run_state.create_run(session_id="session-4", skill_id="risk/portfolio-var")
    interaction = HumanInteractionRequest(
        kind="clarify",
        question="Which portfolio?",
        timeout_seconds=60,
        fallback="abort",
    )
    run_state.suspend(run.run_id, interaction)
    run.suspended_at = time.time()
    await checkpoints.save(
        Checkpoint(
            run_id=run.run_id,
            session_id=run.session_id,
            conversation_history=[],
            pending_interaction=interaction,
            skill_id="risk/portfolio-var",
            created_at=time.time(),
        )
    )

    await manager._check_timeouts()

    assert not orchestrator.resume_calls
    updated = run_state.get_run(run.run_id)
    assert updated is not None
    assert updated.state.value == "suspended"


@pytest.mark.asyncio
async def test_timeout_manager_start_stop_cleanly() -> None:
    run_state = RunStateManager()
    checkpoints = InMemoryCheckpointStore()
    orchestrator = _MockOrchestrator()
    manager = TimeoutManager(
        run_state_manager=run_state,
        checkpoint_store=checkpoints,
        orchestrator=orchestrator,  # type: ignore[arg-type]
        check_interval=0.1,
    )

    await manager.start()
    await asyncio.sleep(0.15)
    await manager.stop()
    assert manager._task is None  # noqa: SLF001 - verifies clean shutdown contract
