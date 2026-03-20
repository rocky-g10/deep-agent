"""Human-in-the-loop (HITL) data models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, model_validator


class FieldSpec(BaseModel):
    """One field in a structured input collection form."""

    name: str
    type: Literal["string", "number", "boolean", "date", "enum"]
    required: bool = True
    description: str = ""
    enum_values: list[str] | None = None
    default: str | None = None


class HumanInteractionRequest(BaseModel):
    """Payload the LLM produces when calling the human_interaction tool."""

    kind: Literal["clarify", "approve", "collect"]
    question: str | None = None
    options: list[str] | None = None
    action_description: str | None = None
    risk_level: Literal["low", "medium", "high"] | None = None
    fields: list[FieldSpec] | None = None
    timeout_seconds: int = 300
    fallback: Literal["abort", "default", "skip"] = "abort"

    @model_validator(mode="after")
    def _validate_kind_payload(self) -> HumanInteractionRequest:
        if self.kind == "clarify" and not self.question:
            raise ValueError("question is required when kind='clarify'")
        if self.kind == "approve" and not self.action_description:
            raise ValueError("action_description is required when kind='approve'")
        if self.kind == "collect" and not self.fields:
            raise ValueError("fields is required when kind='collect'")
        return self


class InteractionResponse(BaseModel):
    """User response to a HumanInteractionRequest."""

    kind: Literal["clarify", "approve", "collect"]
    value: str | None = None
    approved: bool | None = None
    reason: str | None = None
    values: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_kind_payload(self) -> InteractionResponse:
        if self.kind == "clarify" and self.value is None:
            raise ValueError("value is required when kind='clarify'")
        if self.kind == "approve" and self.approved is None:
            raise ValueError("approved is required when kind='approve'")
        if self.kind == "collect" and self.values is None:
            raise ValueError("values is required when kind='collect'")
        return self


class RunState(StrEnum):
    """Lifecycle state for one agent run."""

    running = "running"
    suspended = "suspended"
    timed_out = "timed_out"
    aborted = "aborted"
    completed = "completed"
    failed = "failed"

    def can_transition_to(self, target: RunState, allow_fallback: bool = False) -> bool:
        """Return whether transition to target state is valid."""
        transitions: dict[RunState, set[RunState]] = {
            RunState.running: {RunState.suspended, RunState.completed, RunState.failed},
            RunState.suspended: {RunState.running, RunState.timed_out},
            RunState.timed_out: {RunState.aborted},
            RunState.aborted: set(),
            RunState.completed: set(),
            RunState.failed: set(),
        }
        if allow_fallback and self is RunState.timed_out and target is RunState.running:
            return True
        return target in transitions[self]


class RunInfo(BaseModel):
    """Tracks lifecycle metadata for a single agent run."""

    run_id: str
    session_id: str
    state: RunState = RunState.running
    skill_id: str | None = None
    interaction: HumanInteractionRequest | None = None
    suspended_at: float | None = None
    responded_at: float | None = None
    response: InteractionResponse | None = None
