"""Run lifecycle tracking for HITL suspend/resume flows."""

from __future__ import annotations

import threading
import time
from uuid import uuid4

from deep_agent.models.hitl import HumanInteractionRequest, InteractionResponse, RunInfo, RunState


class InvalidStateTransition(Exception):
    """Raised when a run state transition is not allowed."""


class RunStateManager:
    """In-memory run state tracker with state machine enforcement."""

    def __init__(self) -> None:
        self._runs: dict[str, RunInfo] = {}
        self._lock = threading.Lock()

    def create_run(self, session_id: str, skill_id: str | None = None) -> RunInfo:
        """Create and store a new run in running state."""
        run = RunInfo(
            run_id=f"run-{uuid4()}",
            session_id=session_id,
            skill_id=skill_id,
            state=RunState.running,
        )
        with self._lock:
            self._runs[run.run_id] = run
        return run

    def get_run(self, run_id: str) -> RunInfo | None:
        """Get run info by run_id."""
        with self._lock:
            return self._runs.get(run_id)

    def suspend(self, run_id: str, interaction: HumanInteractionRequest) -> RunInfo:
        """Transition running -> suspended and store pending interaction."""
        with self._lock:
            run = self._require_run(run_id)
            self._transition(run, RunState.suspended)
            run.interaction = interaction
            run.suspended_at = time.time()
            return run

    def resume(self, run_id: str, response: InteractionResponse) -> RunInfo:
        """Transition suspended -> running and store response metadata."""
        with self._lock:
            run = self._require_run(run_id)
            self._transition(run, RunState.running)
            run.response = response
            run.responded_at = time.time()
            return run

    def timeout(self, run_id: str) -> RunInfo:
        """Transition suspended -> timed_out."""
        with self._lock:
            run = self._require_run(run_id)
            self._transition(run, RunState.timed_out)
            return run

    def complete(self, run_id: str) -> RunInfo:
        """Transition running -> completed."""
        with self._lock:
            run = self._require_run(run_id)
            self._transition(run, RunState.completed)
            return run

    def fail(self, run_id: str) -> RunInfo:
        """Transition running -> failed."""
        with self._lock:
            run = self._require_run(run_id)
            self._transition(run, RunState.failed)
            return run

    def abort(self, run_id: str) -> RunInfo:
        """Transition timed_out -> aborted."""
        with self._lock:
            run = self._require_run(run_id)
            self._transition(run, RunState.aborted)
            return run

    def apply_fallback(self, run_id: str) -> RunInfo:
        """Transition timed_out -> running using fallback path."""
        with self._lock:
            run = self._require_run(run_id)
            self._transition(run, RunState.running, allow_fallback=True)
            return run

    def list_suspended(self) -> list[RunInfo]:
        """Return runs currently suspended."""
        with self._lock:
            return [run for run in self._runs.values() if run.state == RunState.suspended]

    def _require_run(self, run_id: str) -> RunInfo:
        run = self._runs.get(run_id)
        if run is None:
            raise InvalidStateTransition(f"Unknown run_id: {run_id}")
        return run

    def _transition(self, run: RunInfo, target: RunState, allow_fallback: bool = False) -> None:
        if not run.state.can_transition_to(target, allow_fallback=allow_fallback):
            raise InvalidStateTransition(
                f"Invalid run state transition: {run.state.value} -> {target.value}"
            )
        run.state = target
