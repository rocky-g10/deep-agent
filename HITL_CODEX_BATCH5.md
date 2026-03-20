# HITL Implementation — Batch 5 (HITL-11, HITL-12, HITL-13)

Implement HITL-11, HITL-12, and HITL-13 from `docs/tasks/HITL-TASKS.md`.
Batches 1–4 (HITL-1 through HITL-10) are complete and committed.

**Read `docs/tasks/HITL-TASKS.md` for full task specs before starting.**
Key files to read first:
- `src/deep_agent/hitl/run_state.py` (RunStateManager — HITL-4)
- `src/deep_agent/hitl/checkpoint.py` (CheckpointStore — HITL-5)
- `src/deep_agent/orchestrator/agent_orchestrator.py` (has resume_run — HITL-8)
- `src/deep_agent/models/hitl.py` (all HITL models)

---

## HITL-11: Timeout Manager (M complexity)

**Create** `src/deep_agent/hitl/timeout_manager.py`:

```python
class TimeoutManager:
    def __init__(
        self,
        run_state_manager: RunStateManager,
        checkpoint_store: CheckpointStore,
        orchestrator: AgentOrchestrator,
        check_interval: float = 5.0,
    ) -> None: ...

    async def start(self) -> None:
        """Start the background polling loop via asyncio.create_task."""

    async def stop(self) -> None:
        """Cancel the background task cleanly."""

    async def _check_timeouts(self) -> None:
        """Single sweep: find expired runs and apply fallback strategy."""
```

For each expired run (`time.time() > run_info.suspended_at + interaction.timeout_seconds`):
1. Call `run_state_manager.timeout(run_id)`
2. Check `interaction.fallback`:
   - `"abort"`: call `run_state_manager.abort(run_id)`, delete checkpoint,
     yield `ErrorEvent(error="HITL_TIMEOUT: interaction timed out", type="error")` to session
   - `"default"`: build synthetic `InteractionResponse` with defaults from `FieldSpec.default`
     (or empty string for clarify/approve), call `orchestrator.resume_run()`
   - `"skip"`: build synthetic `InteractionResponse` with `value="[skipped]"`,
     call `orchestrator.resume_run()`

---

## HITL-12: Audit Logging (M complexity)

**Create** `src/deep_agent/hitl/audit.py`:

```python
@dataclass
class HITLAuditEvent:
    timestamp: str               # ISO 8601
    trace_id: str
    session_id: str
    user_id: str
    tenant_id: str
    category: str = "hitl_interaction"
    action: str = ""             # interaction_requested | response_submitted | interaction_timed_out
    interaction_kind: str = ""   # clarify | approve | collect
    question_or_action: str = "" # question asked or action proposed
    response: str | None = None  # serialized user response
    responder_id: str | None = None
    latency_ms: int | None = None
    risk_level: str | None = None
    outcome: str | None = None   # approved | denied | timed_out | skipped

def emit_hitl_audit(event: HITLAuditEvent) -> None:
    """MVP: structured JSON log via Python logging. Post-MVP: Redis audit queue."""
    import logging, json
    logger = logging.getLogger("deep_agent.hitl.audit")
    logger.info(json.dumps(dataclasses.asdict(event)))
```

**Modify** `src/deep_agent/orchestrator/agent_orchestrator.py` to call audit hooks:
- On suspend: `emit_hitl_audit(action="interaction_requested", ...)`
- On resume: `emit_hitl_audit(action="response_submitted", latency_ms=..., outcome=...)`
- On timeout: `emit_hitl_audit(action="interaction_timed_out", outcome="timed_out"/"skipped")`

---

## HITL-13: Multi-Skill HITL (M complexity)

**Modify** `src/deep_agent/orchestrator/agent_orchestrator.py`:

Per PRD §11.4.8: the current architecture uses a single LLM stream (not parallel branches),
so multi-skill HITL is simpler — the LLM decides when to invoke `human_interaction` based
on the merged system prompt. The suspension/resume mechanism is identical to single-skill.

Changes needed:
1. In the `InteractionRequiredEvent`, set `skill_id` to the highest-scored skill with
   `requires_approval=True` among active skills — or the first active skill if none have the flag
2. On timeout/abort in `TimeoutManager`, include a note in the error message if multiple
   skills were active: `f"HITL timeout on skill {skill_id}; {n} total active skills terminated"`
3. In `resume_run()`, ensure the reconstructed system prompt merges ALL originally-active
   skills (already in checkpoint.skill_bindings — verify this is correctly used)

---

## Tests

**Create** `tests/unit/test_hitl_audit.py`:
- `emit_hitl_audit()` produces structured JSON log (capture with `caplog`)
- All fields present in logged output
- `latency_ms` correctly computed
- `outcome` set appropriately for approve/deny/timeout/skip

**Create** `tests/integration/test_hitl_timeout.py`:
- Suspend a run with `timeout_seconds=1`
- Start `TimeoutManager` with `check_interval=0.1`
- Wait 1.5s — verify run is `timed_out`
- `fallback="abort"` → run is `aborted`
- `fallback="skip"` → run resumes (mock orchestrator)
- Manager stops cleanly via `stop()`

---

## Validation

```bash
cd /home/ubuntu/deep-agent && source .venv/bin/activate
ruff check src/ tests/
mypy src/
pytest tests/ -x -q
```

All must pass. Write summary to `docs/tasks/HITL-BATCH5-REVIEW.md`, end with `READY_FOR_REVIEW`.
