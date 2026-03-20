# CC Review — HITL Batch 5 (HITL-11, HITL-12, HITL-13)

**Reviewer:** Claude Code (Opus 4.6)
**Date:** 2026-03-20

---

## Validation Results

```
ruff check src/ tests/  -> All checks passed!
mypy src/               -> Success: no issues found in 39 source files
pytest tests/ -x -q     -> All tests pass (0 failures, 9 skipped from unrelated tests)
```

---

## HITL-11: Timeout Manager

### `src/deep_agent/hitl/timeout_manager.py`

#### Sweep Logic

The `_check_timeouts()` method correctly:
1. Iterates `list_suspended()` runs
2. Skips runs with no interaction or `suspended_at`
3. Computes expiry as `suspended_at + interaction.timeout_seconds`
4. Skips non-expired runs (`now <= expires_at`)
5. Calls `timeout(run_id)` to transition suspended → timed_out
6. Catches `InvalidStateTransition` (race between check and state change)

#### Fallback Strategies

| Strategy | State Transitions | Actions | Status |
|---|---|---|---|
| `abort` | suspended → timed_out → aborted | delete checkpoint, log warning, emit audit | OK |
| `default` | suspended → timed_out → running (via apply_fallback) | emit audit, build synthetic default response, resume_run | OK |
| `skip` | suspended → timed_out → running (via apply_fallback) | emit audit, build synthetic skip response, resume_run | OK |

**`_build_default_response`:** Uses `FieldSpec.default` values for collect fields, empty string fallback, `approved=False` for approve. Matches spec.

**`_build_skip_response`:** Uses `"[skipped]"` for all field values. Matches spec.

**`_drain()`:** Consumes the `resume_run()` async iterator to completion. Necessary since `resume_run()` is a generator that must be iterated to execute.

#### Start/Stop Lifecycle

- `start()`: Idempotent — no-op if task already running
- `stop()`: Cancel + await + set None. Clean shutdown.
- `_run_loop()`: Simple `while True` with sleep interval.

#### Spec Deviation: No ErrorEvent on Abort

The spec says `fallback="abort"` should "push `ErrorEvent` to session". The implementation only logs a warning and emits an audit event. The WS client won't be notified that the run was aborted due to timeout.

The batch review acknowledges this: "queue-level session event fanout for timeout-abort remains a separate concern for future WS event-bus enhancement." The timeout manager doesn't have access to `SessionManager` (which lives in the API layer), so adding this would create a cross-layer dependency. **This is a known deferral, not an oversight.** A callback or event bus pattern could bridge this in a future batch.

---

## HITL-12: Audit Logging

### `src/deep_agent/hitl/audit.py`

`HITLAuditEvent` dataclass with all spec fields:

| Field | Type (Spec) | Type (Impl) | Status |
|---|---|---|---|
| timestamp | str (ISO 8601) | str | OK |
| trace_id | str | str | OK |
| session_id | str | str | OK |
| user_id | str | str | OK |
| tenant_id | str | str | OK |
| category | `Literal["hitl_interaction"]` | `str` (default: "hitl_interaction") | OK (relaxed) |
| action | `Literal[...]` | `str` | OK (relaxed) |
| interaction_kind | `Literal[...]` | `str` | OK (relaxed) |
| question_or_action | str | str | OK |
| response | `str \| None` | `str \| None` | OK |
| responder_id | `str \| None` | `str \| None` | OK |
| latency_ms | `int \| None` | `int \| None` | OK |
| risk_level | `str \| None` | `str \| None` | OK |
| outcome | `str \| None` | `str \| None` | OK |

**Note:** Implementation uses plain `str` instead of `Literal` types for `category`, `action`, `interaction_kind`. Less strict but more pragmatic for a dataclass used only for logging. Type safety is enforced by call sites.

`emit_hitl_audit()`: `logger.info(json.dumps(dataclasses.asdict(event), sort_keys=True))` — structured JSON log via Python logging. Matches spec ("MVP: structured log via Python logging (JSON format)").

### Audit Hook Placement

| Hook Point | Where | Action | Status |
|---|---|---|---|
| On suspend (initial) | `handle_message()` lines 178-192 | `interaction_requested` | OK |
| On resume | `resume_run()` lines 259-277 | `response_submitted` with latency_ms + outcome | OK |
| On re-suspension | `resume_run()` lines 360-374 | `interaction_requested` | OK |
| On timeout (abort) | `timeout_manager._check_timeouts()` line 89 | `interaction_timed_out` outcome=`timed_out` | OK |
| On timeout (default) | `timeout_manager._check_timeouts()` line 94 | `interaction_timed_out` outcome=`timed_out` | OK |
| On timeout (skip) | `timeout_manager._check_timeouts()` line 101 | `interaction_timed_out` outcome=`skipped` | OK |

All three spec actions (`interaction_requested`, `response_submitted`, `interaction_timed_out`) emitted at correct moments.

### `_response_outcome` Helper

```python
def _response_outcome(response: InteractionResponse) -> str:
    if response.kind == "approve":
        return "approved" if response.approved else "denied"
    return "submitted"
```

Returns `approved`/`denied` for approve kind, `submitted` for clarify/collect. Spec defines `approved`/`denied` for approve and `timed_out`/`skipped` for timeouts — the timeout outcomes are handled separately by the timeout manager audit calls.

### Latency Computation

```python
if post_resume.suspended_at is not None and post_resume.responded_at is not None:
    latency_ms = int((post_resume.responded_at - post_resume.suspended_at) * 1000)
```

Correctly computes time between suspension and user response. Only populated for user-initiated resumes (not timeout-initiated, since `responded_at` is not set by `apply_fallback`). Acceptable — timeout-initiated resumes have their own audit events.

---

## HITL-13: Multi-Skill HITL

### `_select_interaction_skill_id`

```python
def _select_interaction_skill_id(
    active_skills: list[SkillContent], matched_skills: list[SkillSummary]
) -> str | None:
    by_id = {skill.skill_id: skill for skill in active_skills}
    for matched in matched_skills:
        skill = by_id.get(matched.skill_id)
        if skill is not None and skill.requires_approval:
            return skill.skill_id
    if active_skills:
        return active_skills[0].skill_id
    return None
```

Spec: "highest-scored skill with `requires_approval=True`, or the skill context the LLM was operating in"

- Iterates `matched_skills` in match order (highest score first from SkillEngine)
- Picks first active skill with `requires_approval=True`
- Falls back to first active skill
- Returns None if no active skills

Correctly implements the spec's attribution logic. Used in both `handle_message()` (line 152-153) and `resume_run()` re-suspension (lines 351, 377).

### `active_skill_ids` in Checkpoint

Added `active_skill_ids: list[str] = Field(default_factory=list)` to `Checkpoint`. Stored in both initial suspension (line 163) and re-suspension (line 354). Backward compatible via default.

Used by timeout manager for multi-skill abort messages:

```python
active_count = len(checkpoint.active_skill_ids) if checkpoint else 1
if active_count > 1:
    message = f"HITL timeout on skill {skill_id}; {active_count} total active skills terminated"
```

Matches spec: "include a note: 'HITL timeout on skill {skill_id}; other active skills were also terminated'"

### Orchestrator `resume_run()` State Handling

Updated to support timeout manager's default/skip flows:

```python
if run_info.state.value == "timed_out":
    self._run_state_manager.apply_fallback(run_id)
    ...
if run_info.state.value != "suspended" and run_info.state.value != "running":
    yield ErrorEvent(...)
if run_info.state.value == "suspended":
    self._run_state_manager.resume(run_id, response)
```

This allows `resume_run()` to handle:
1. **User-initiated resume**: suspended → `resume()` → running → stream
2. **Timeout default/skip**: running (post-apply_fallback) → skip `resume()` → stream

The timeout manager calls `apply_fallback()` before calling `resume_run()`, so the orchestrator sees `running` state and proceeds directly to streaming. Clean separation of concerns.

---

## Tests

### `tests/unit/test_hitl_audit.py` (2 tests)

| Test | Verifies | Status |
|---|---|---|
| `test_emit_hitl_audit_logs_structured_json` | JSON output, field values (category, trace_id, action, kind, question, risk_level) | OK |
| `test_emit_hitl_audit_fields_for_response_and_timeout` | latency_ms propagation, outcomes (approved, timed_out, skipped) across 3 events | OK |

### `tests/integration/test_hitl_timeout.py` (3 tests)

| Test | Verifies | Status |
|---|---|---|
| `test_timeout_manager_abort_path_marks_aborted_and_logs_multiskill_note` | Abort: state=aborted, checkpoint deleted, multi-skill warning in log | OK |
| `test_timeout_manager_skip_path_resumes_with_skipped_response` | Skip: orchestrator.resume_run called with skipped values, state=running | OK |
| `test_timeout_manager_start_stop_cleanly` | Start/stop lifecycle, task=None after stop | OK |

`_MockOrchestrator` is well-designed: captures resume calls for assertion without needing real runtime. Returns `AgentCompleteEvent` to satisfy the drain loop.

### Test Gaps

- **No test for `fallback="default"` path.** Only abort and skip tested. Default is structurally similar to skip (same `apply_fallback` + `resume_run` flow, different response builder). Low risk but a gap.
- **No test for `_build_default_response` with `FieldSpec.default` values.** The default builder uses `field.default` but no test exercises this with non-None defaults.
- **No test for non-expired runs being skipped** (the "does not interfere" criterion).
- **No test for audit events emitted by the orchestrator** during suspend/resume (audit hooks are only unit-tested via `test_hitl_audit.py`, not integration-tested via orchestrator).

These are acceptable gaps for MVP given the code simplicity.

---

## Summary

Implementation is correct for all three tasks:

- **HITL-11 (Timeout Manager):** Sweep logic correctly detects expired runs, all 3 fallback strategies implemented with correct state transitions, clean start/stop lifecycle. Known deferral: abort path doesn't push ErrorEvent to WS session (acknowledged in design notes).
- **HITL-12 (Audit Logging):** All 3 audit actions emitted at correct moments, all PRD fields populated, structured JSON logging, latency computation correct for user-initiated resumes.
- **HITL-13 (Multi-Skill):** Attribution logic prioritizes `requires_approval` skills by match score, `active_skill_ids` stored in checkpoint for timeout diagnostics, multi-skill abort message matches spec.

### Known Deferral (non-blocking)

The abort timeout path does not push an `ErrorEvent` to the session's `resume_queue`, meaning the WS client won't be notified of timeout-aborted runs. This is acknowledged as a future enhancement requiring an event bus or callback pattern to bridge the HITL layer to the API layer without creating a dependency cycle. Should be addressed before production deployment.

**ACCEPT**
