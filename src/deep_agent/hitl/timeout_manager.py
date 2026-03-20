"""Background timeout handling for suspended HITL runs."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator

from deep_agent.hitl.audit import HITLAuditEvent, emit_hitl_audit
from deep_agent.hitl.checkpoint import CheckpointStore
from deep_agent.hitl.run_state import InvalidStateTransition, RunStateManager
from deep_agent.models.hitl import HumanInteractionRequest, InteractionResponse
from deep_agent.orchestrator.agent_orchestrator import AgentOrchestrator

logger = logging.getLogger(__name__)


class TimeoutManager:
    """Periodic background task that checks for expired HITL suspensions."""

    def __init__(
        self,
        run_state_manager: RunStateManager,
        checkpoint_store: CheckpointStore,
        orchestrator: AgentOrchestrator,
        check_interval: float = 5.0,
    ) -> None:
        self._run_state_manager = run_state_manager
        self._checkpoint_store = checkpoint_store
        self._orchestrator = orchestrator
        self._check_interval = check_interval
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start background polling task."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Stop background polling task."""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run_loop(self) -> None:
        while True:
            await self._check_timeouts()
            await asyncio.sleep(self._check_interval)

    async def _check_timeouts(self) -> None:
        """Single timeout sweep for suspended runs."""
        now = time.time()
        for run in self._run_state_manager.list_suspended():
            interaction = run.interaction
            if interaction is None or run.suspended_at is None:
                continue
            expires_at = run.suspended_at + interaction.timeout_seconds
            if now <= expires_at:
                continue

            run_id = run.run_id
            checkpoint = await self._checkpoint_store.load(run_id)
            try:
                self._run_state_manager.timeout(run_id)
            except InvalidStateTransition:
                continue

            if interaction.fallback == "abort":
                self._run_state_manager.abort(run_id)
                await self._checkpoint_store.delete(run_id)
                skill_id = (checkpoint.skill_id if checkpoint else None) or (
                    run.skill_id or "unknown"
                )
                active_count = len(checkpoint.active_skill_ids) if checkpoint else 1
                message = "HITL_TIMEOUT: interaction timed out"
                if active_count > 1:
                    message = (
                        "HITL timeout on skill "
                        f"{skill_id}; {active_count} total active skills terminated"
                    )
                logger.warning(message)
                self._emit_timeout_audit(run, checkpoint, interaction, outcome="timed_out")
                continue

            if interaction.fallback == "default":
                self._run_state_manager.apply_fallback(run_id)
                self._emit_timeout_audit(run, checkpoint, interaction, outcome="timed_out")
                response = self._build_default_response(interaction)
                await self._drain(self._orchestrator.resume_run(run_id, response))
                continue

            if interaction.fallback == "skip":
                self._run_state_manager.apply_fallback(run_id)
                self._emit_timeout_audit(run, checkpoint, interaction, outcome="skipped")
                response = self._build_skip_response(interaction)
                await self._drain(self._orchestrator.resume_run(run_id, response))

    @staticmethod
    async def _drain(events: AsyncIterator[object]) -> None:
        async for _ in events:
            pass

    @staticmethod
    def _build_default_response(interaction: HumanInteractionRequest) -> InteractionResponse:
        if interaction.kind == "clarify":
            return InteractionResponse(kind="clarify", value="")
        if interaction.kind == "approve":
            return InteractionResponse(kind="approve", approved=False, reason="")
        values = {
            field.name: (field.default if field.default is not None else "")
            for field in (interaction.fields or [])
        }
        return InteractionResponse(kind="collect", values=values)

    @staticmethod
    def _build_skip_response(interaction: HumanInteractionRequest) -> InteractionResponse:
        if interaction.kind == "clarify":
            return InteractionResponse(kind="clarify", value="[skipped]")
        if interaction.kind == "approve":
            return InteractionResponse(kind="approve", approved=False, reason="[skipped]")
        values = {field.name: "[skipped]" for field in (interaction.fields or [])}
        return InteractionResponse(kind="collect", values=values)

    @staticmethod
    def _emit_timeout_audit(
        run: object,
        checkpoint: object | None,
        interaction: HumanInteractionRequest,
        outcome: str,
    ) -> None:
        session_id = getattr(run, "session_id", "")
        tenant_context = getattr(checkpoint, "tenant_context", {}) if checkpoint else {}
        emit_hitl_audit(
            HITLAuditEvent(
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                trace_id=getattr(run, "run_id", ""),
                session_id=session_id,
                user_id=str(tenant_context.get("user_id", "")),
                tenant_id=str(tenant_context.get("tenant_id", "")),
                action="interaction_timed_out",
                interaction_kind=interaction.kind,
                question_or_action=interaction.question
                or interaction.action_description
                or "collect_fields",
                outcome=outcome,
                risk_level=interaction.risk_level,
            )
        )
