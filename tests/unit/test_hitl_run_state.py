"""Unit tests for HITL run state manager."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from deep_agent.hitl.run_state import InvalidStateTransition, RunStateManager
from deep_agent.models.hitl import HumanInteractionRequest, InteractionResponse, RunState


def test_run_state_manager_happy_path_transitions() -> None:
    manager = RunStateManager()
    run = manager.create_run(session_id="session-1", skill_id="risk/portfolio-var")

    assert run.state == RunState.running
    manager.suspend(
        run.run_id,
        HumanInteractionRequest(kind="clarify", question="Which portfolio?"),
    )
    assert manager.get_run(run.run_id).state == RunState.suspended

    manager.resume(run.run_id, InteractionResponse(kind="clarify", value="EQ-MACRO-1"))
    assert manager.get_run(run.run_id).state == RunState.running

    manager.complete(run.run_id)
    assert manager.get_run(run.run_id).state == RunState.completed


def test_suspend_sets_suspended_at_and_interaction() -> None:
    manager = RunStateManager()
    run = manager.create_run(session_id="session-1")
    interaction = HumanInteractionRequest(kind="approve", action_description="Execute hedge?")

    updated = manager.suspend(run.run_id, interaction)

    assert updated.state == RunState.suspended
    assert updated.suspended_at is not None
    assert updated.interaction == interaction


def test_resume_sets_responded_at_and_response() -> None:
    manager = RunStateManager()
    run = manager.create_run(session_id="session-1")
    manager.suspend(run.run_id, HumanInteractionRequest(kind="clarify", question="Which desk?"))
    response = InteractionResponse(kind="clarify", value="equities")

    updated = manager.resume(run.run_id, response)

    assert updated.state == RunState.running
    assert updated.responded_at is not None
    assert updated.response == response


def test_timeout_abort_and_fallback_flow() -> None:
    manager = RunStateManager()
    run = manager.create_run(session_id="session-1")
    manager.suspend(run.run_id, HumanInteractionRequest(kind="clarify", question="Which desk?"))
    manager.timeout(run.run_id)
    assert manager.get_run(run.run_id).state == RunState.timed_out

    manager.apply_fallback(run.run_id)
    assert manager.get_run(run.run_id).state == RunState.running

    manager.suspend(run.run_id, HumanInteractionRequest(kind="clarify", question="Which desk?"))
    manager.timeout(run.run_id)
    manager.abort(run.run_id)
    assert manager.get_run(run.run_id).state == RunState.aborted


def test_invalid_transition_raises() -> None:
    manager = RunStateManager()
    run = manager.create_run(session_id="session-1")
    manager.complete(run.run_id)

    with pytest.raises(InvalidStateTransition):
        manager.suspend(run.run_id, HumanInteractionRequest(kind="clarify", question="Which?"))


def test_list_suspended_returns_only_suspended_runs() -> None:
    manager = RunStateManager()
    suspended = manager.create_run(session_id="session-s")
    running = manager.create_run(session_id="session-r")

    manager.suspend(
        suspended.run_id,
        HumanInteractionRequest(kind="clarify", question="Which portfolio?"),
    )

    suspended_runs = manager.list_suspended()
    suspended_ids = {run.run_id for run in suspended_runs}

    assert suspended.run_id in suspended_ids
    assert running.run_id not in suspended_ids


def test_concurrent_create_run_has_unique_ids() -> None:
    manager = RunStateManager()

    def create() -> str:
        return manager.create_run(session_id="session-c").run_id

    with ThreadPoolExecutor(max_workers=8) as pool:
        run_ids = list(pool.map(lambda _: create(), range(64)))

    assert len(set(run_ids)) == 64
