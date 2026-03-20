"""Unit tests for HITL data models."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from deep_agent.models.hitl import (
    FieldSpec,
    HumanInteractionRequest,
    InteractionResponse,
    RunInfo,
    RunState,
)


def _roundtrip(model: Any) -> Any:
    model_type = type(model)
    return model_type.model_validate(model.model_dump())


def test_hitl_models_roundtrip() -> None:
    field = FieldSpec(name="ticker", type="string", description="Instrument ticker")
    request = HumanInteractionRequest(
        kind="collect",
        fields=[field],
        timeout_seconds=600,
        fallback="default",
    )
    response = InteractionResponse(kind="collect", values={"ticker": "NVDA"})
    run = RunInfo(
        run_id="run-1",
        session_id="session-1",
        state=RunState.suspended,
        skill_id="risk/portfolio-var",
        interaction=request,
        suspended_at=123.0,
        response=response,
        responded_at=124.0,
    )

    assert _roundtrip(field) == field
    assert _roundtrip(request) == request
    assert _roundtrip(response) == response
    assert _roundtrip(run) == run


@pytest.mark.parametrize(
    ("payload", "missing_field"),
    [
        ({"kind": "clarify"}, "question"),
        ({"kind": "approve"}, "action_description"),
        ({"kind": "collect"}, "fields"),
    ],
)
def test_human_interaction_request_requires_kind_specific_fields(
    payload: dict[str, Any], missing_field: str
) -> None:
    with pytest.raises(ValidationError, match=missing_field):
        HumanInteractionRequest(**payload)


@pytest.mark.parametrize(
    ("payload", "missing_field"),
    [
        ({"kind": "clarify"}, "value"),
        ({"kind": "approve"}, "approved"),
        ({"kind": "collect"}, "values"),
    ],
)
def test_interaction_response_requires_kind_specific_fields(
    payload: dict[str, Any], missing_field: str
) -> None:
    with pytest.raises(ValidationError, match=missing_field):
        InteractionResponse(**payload)


def test_run_state_transitions() -> None:
    assert RunState.running.can_transition_to(RunState.suspended)
    assert RunState.suspended.can_transition_to(RunState.running)
    assert RunState.suspended.can_transition_to(RunState.timed_out)
    assert RunState.timed_out.can_transition_to(RunState.aborted)
    assert RunState.timed_out.can_transition_to(RunState.running, allow_fallback=True)
    assert RunState.running.can_transition_to(RunState.completed)
    assert RunState.running.can_transition_to(RunState.failed)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (RunState.completed, RunState.running),
        (RunState.completed, RunState.suspended),
        (RunState.failed, RunState.running),
        (RunState.failed, RunState.completed),
        (RunState.aborted, RunState.running),
        (RunState.aborted, RunState.suspended),
        (RunState.running, RunState.aborted),
        (RunState.running, RunState.timed_out),
        (RunState.suspended, RunState.completed),
        (RunState.suspended, RunState.failed),
        (RunState.timed_out, RunState.completed),
        (RunState.timed_out, RunState.running),
    ],
)
def test_run_state_invalid_transitions(source: RunState, target: RunState) -> None:
    assert not source.can_transition_to(target)
