# HITL Implementation — Batch 4 (HITL-9, HITL-10)

Implement HITL-9 and HITL-10 from `docs/tasks/HITL-TASKS.md`.
Batches 1–3 (HITL-1 through HITL-8) are complete and committed.

**Read `docs/tasks/HITL-TASKS.md` for full task specs before starting.**
Also read the existing API layer carefully:
- `src/deep_agent/api/app.py`
- `src/deep_agent/api/ws_chat.py`
- `src/deep_agent/api/session.py`
- `src/deep_agent/api/schemas.py`
- `src/deep_agent/orchestrator/agent_orchestrator.py` (has resume_run() from HITL-8)

---

## HITL-9: Response REST API Endpoint (M complexity)

**Modify** `src/deep_agent/api/schemas.py` — add:
```python
class RunRespondRequest(BaseModel):
    response: InteractionResponse

class RunRespondResult(BaseModel):
    run_id: str
    status: str  # "resumed"
```

**Create** `src/deep_agent/api/runs.py`:
```python
router = APIRouter(prefix="/api/v1/runs", tags=["runs"])

@router.post("/{run_id}/respond", response_model=RunRespondResult)
async def respond_to_run(run_id: str, body: RunRespondRequest) -> RunRespondResult:
```

The endpoint must:
1. Look up the run via `RunStateManager.get_run(run_id)` — 404 if not found
2. Return 409 if run state is not `suspended`
3. Call `orchestrator.resume_run(run_id, response)` — iterate the async iterator
   and push each event into the session's `resume_queue` (see HITL-10)
4. Return 200 `{"run_id": ..., "status": "resumed"}`

The endpoint needs access to the orchestrator and run_state_manager — inject via
FastAPI dependency injection or app state (`request.app.state`).

**Modify** `src/deep_agent/api/app.py` — mount the new router:
```python
from deep_agent.api.runs import router as runs_router
app.include_router(runs_router)
```

---

## HITL-10: WebSocket Integration (L complexity)

**Modify** `src/deep_agent/api/session.py`:
- Add `active_run_id: str | None = None` to `Session`
- Add `resume_queue: asyncio.Queue = Field(default_factory=asyncio.Queue)` to `Session`

**Modify** `src/deep_agent/api/ws_chat.py`:
1. When `handle_message()` yields `InteractionRequiredEvent`:
   - Store `session.active_run_id = event.run_id`
   - Send the event to the client as JSON over WebSocket
   - Enter "waiting" state — stop processing new user messages until resume
     (the run is suspended; new user messages should queue or be rejected with
     a message like "Waiting for your response to pending interaction")
   - Start a background task that reads from `session.resume_queue` and
     forwards events to the WebSocket

2. In the REST response endpoint (`runs.py`), after calling `orchestrator.resume_run()`:
   - Look up the session associated with the run (via `session_id` on the checkpoint)
   - Iterate the `AsyncIterator[AgentEvent]` from `resume_run()`
   - Push each event into `session.resume_queue`
   - The background task in `ws_chat.py` then forwards them to the client

3. When the resumed stream completes (`AgentCompleteEvent` or `ErrorEvent`):
   - Clear `session.active_run_id = None`
   - Stop the background task

The goal: client sees seamless event stream — `skill_match → agent_chunk →
interaction_required → (user calls REST endpoint) → agent_chunk → agent_complete`
— all over the same WebSocket connection.

---

## Tests

**Create** `tests/integration/test_hitl_ws.py` (targeted, uses TestClient / httpx):
1. WebSocket connects, sends message, receives `interaction_required` event
2. `POST /api/v1/runs/{run_id}/respond` with valid response returns 200
3. After respond, WebSocket receives resumed events and `agent_complete`
4. `POST /api/v1/runs/unknown-id/respond` returns 404
5. `POST /api/v1/runs/{run_id}/respond` when not suspended returns 409

Use the `MockRuntime` from `tests/integration/test_hitl_orchestrator.py` to
control what the "LLM" returns during tests.

---

## Validation

```bash
cd /home/ubuntu/deep-agent && source .venv/bin/activate
ruff check src/ tests/
mypy src/
pytest tests/ -x -q
```

All must pass. Then write summary to `docs/tasks/HITL-BATCH4-REVIEW.md` and end
with `READY_FOR_REVIEW`.
