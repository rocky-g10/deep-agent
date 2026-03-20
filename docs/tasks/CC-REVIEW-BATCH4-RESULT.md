# CC Review — HITL Batch 4 (HITL-9, HITL-10)

**Reviewer:** Claude Code (Opus 4.6)
**Date:** 2026-03-20

---

## Validation Results

```
ruff check src/ tests/  -> All checks passed!
mypy src/               -> Success: no issues found in 37 source files
pytest tests/ -x -q     -> All tests pass (0 failures, 9 skipped from unrelated tests)
```

---

## HITL-9: Response REST API Endpoint

### `src/deep_agent/api/runs.py`

| Spec Requirement | Status | Implementation |
|---|---|---|
| `POST /api/v1/runs/{run_id}/respond` | OK | `router = APIRouter(prefix="/api/v1/runs")`, `@router.post("/{run_id}/respond")` |
| 404 if unknown run_id | OK | Lines 25-29: `HTTPException(status_code=404)` |
| 409 if run not suspended | OK | Lines 30-34: `HTTPException(status_code=409)` |
| Call `orchestrator.resume_run()` | OK | Line 43 |
| Push resumed events to session resume_queue | OK | Lines 43-44: `await session.resume_queue.put(event)` |
| Return 200 `{"run_id": ..., "status": "resumed"}` | OK | Line 46 |
| Router mounted in `app.py` | OK | `app.include_router(runs_router)` |

**Good additions beyond spec:**
- Session lookup (lines 36-41): validates the run's session exists before attempting resume. Returns 404 if session is missing — necessary for queue bridging.

### `src/deep_agent/api/schemas.py`

- `RunRespondRequest(response: InteractionResponse)` — matches spec exactly
- `RunRespondResult(run_id: str, status: str)` — matches spec exactly

### Design Note

The REST endpoint always returns `{"status": "resumed"}` after iterating all events from `resume_run()`, even if the orchestrator yields an `ErrorEvent` internally. Errors are pushed to the resume_queue and surfaced to the WS client. This is acceptable — "resumed" means "resume accepted", not "resume succeeded end-to-end". For MVP this is fine; a production version might want to distinguish.

---

## HITL-10: WebSocket Integration

### `src/deep_agent/api/session.py`

| Spec Requirement | Status | Implementation |
|---|---|---|
| `active_run_id: str \| None` on Session | OK | Line 24 |
| `resume_queue: asyncio.Queue` on Session | OK | Line 25, `default_factory=asyncio.Queue` |

Clean, minimal changes. Backward compatible — existing session creation code is unaffected.

### `src/deep_agent/api/ws_chat.py`

| Spec Requirement | Status | Implementation |
|---|---|---|
| `InteractionRequiredEvent` sent to WS client | OK | Line 168: all events (including interaction_required) sent via `send_text` |
| Waiting state — block new messages while suspended | OK | Lines 148-154: `active_run_id is not None` → `WAITING_FOR_INTERACTION` error |
| Background forwarder reads from resume_queue | OK | `_forward_resume_events()` (lines 193-208) |
| Forwarder sends resumed events over original WS | OK | Line 203: `websocket.send_text(event.model_dump_json())` |
| Forwarder starts on suspend | OK | Lines 169-172: `ensure_resume_task()` called on `interaction_required` |
| Forwarder stops on complete/error | OK | Lines 206-208: returns on `agent_complete` or `error` |
| `active_run_id` cleared on completion | OK | Line 207: `session.active_run_id = None` |
| Forwarder cancelled on WS disconnect | OK | Lines 100-101: `resume_task.cancel()` in `finally` |
| Session cleaned up on disconnect | OK | Line 102: `session_manager.delete(session.session_id)` |

### Forwarder Lifecycle Analysis

The `_forward_resume_events` function correctly handles:

1. **Normal resume flow:** Reads events from queue → sends to WS → on `agent_complete`, clears `active_run_id` and returns.
2. **Re-suspension:** On `interaction_required`, updates `active_run_id` and continues looping (doesn't return).
3. **Error during resume:** On `error` event, clears `active_run_id` and returns.
4. **Session deletion:** Checks `session_manager.get(session_id)` at top of loop — returns if session gone.
5. **WS disconnect:** The `send_text` raises, task exits with exception. Parent's `finally` block cancels the task (no-op if already done) and deletes the session.

### Callback/Closure Pattern

The `resume_task` variable is managed via `nonlocal` + a `_set_resume_task` callback, and passed to `_handle_client_message` via a lambda that captures it by reference. This works correctly in Python — the lambda reads the current value of `resume_task` when called, and `_set_resume_task` updates it via `nonlocal`.

### `session_id` Threading

The orchestrator now accepts `session_id: str | None = None` in `handle_message()`:
```python
effective_session_id = session_id or f"{context.tenant_id}:{context.user_id}"
```
The WS handler passes `session.session_id` (line 166), which is a UUID hex from `SessionManager.create()`. The REST endpoint looks up `run_info.session_id` to find the correct session and its resume_queue. This ensures stable association between WS connection and REST respond call.

### Orchestrator Property Additions

```python
@property
def run_state_manager(self) -> RunStateManager: ...
@property
def checkpoint_store(self) -> CheckpointStore: ...
```

Needed by the REST endpoint to access run state. Clean, read-only exposure.

---

## Tests

### `tests/integration/test_hitl_ws.py`

| Test | What it verifies | Status |
|---|---|---|
| `test_hitl_ws_suspend_and_resume_flow` | Full lifecycle: WS connect → message → suspend → REST respond → resumed events forwarded over WS → completion | OK |
| `test_hitl_respond_unknown_run_returns_404` | Unknown run_id → HTTPException(404) | OK |
| `test_hitl_respond_non_suspended_run_returns_409` | Non-suspended run → HTTPException(409) | OK |

### Test Infrastructure

- `_AsyncFakeWebSocket`: Async WS double with push queue for inbound messages and list capture for sent texts. Supports triggering disconnect. Well-designed.
- `_FakeRequest`: Minimal request stub carrying `app` reference for `request.app.state` access.
- `_wait_for_event`: Polls `sent_texts` for a specific event type with timeout. Adequate for these tests.
- Reuses `MockRuntime` from `test_hitl_orchestrator.py` — good code reuse.

### Test Approach Trade-offs

Tests use async WS doubles + direct `respond_to_run()` invocation rather than a full ASGI test client. The design note explains this avoids deadlock from mixed sync WebSocket/REST test-client behavior. This is a pragmatic choice that still exercises the core logic: orchestrator, session management, queue bridging, and event forwarding.

### Minor Test Gaps

- No test for 422 (validation failure on malformed `InteractionResponse`). Handled by Pydantic/FastAPI automatically — low risk.
- No test for WS disconnect during suspension (spec: "run remains suspended, can be resumed later or times out"). The cleanup code handles this, but it's not exercised.
- No test for concurrent independent HITL sessions (spec acceptance criterion). The architecture supports it (per-session queues), but it's not tested.
- `_wait_for_event` scans all `sent_texts` including previously matched events — could false-match if duplicate event types appear. Not an issue for current test scenarios.

These gaps are acceptable for MVP integration tests.

---

## Backward Compatibility

- `handle_message()` signature: `session_id` parameter is optional with default `None` — existing callers unaffected.
- `Session` dataclass: new fields have defaults — existing session creation unaffected.
- `schemas.py`: new models added, existing `UserMessage` and `SessionStartedMessage` unchanged.
- All existing tests pass.

---

## Summary

Implementation correctly wires HITL-9 (REST endpoint) and HITL-10 (WebSocket integration) together:

- REST endpoint validates state (404/409), calls `resume_run()`, bridges events to session's `resume_queue`
- WS handler enters waiting state on suspend, starts background forwarder to relay resumed events
- Forwarder correctly handles completion, re-suspension, errors, and disconnect
- `session_id` threading ensures stable run ↔ session association across WS and REST paths
- Clean property exposure on orchestrator for API access

No blocking issues found.

**ACCEPT**
