# HITL Implementation — Batch 3 (HITL-7, HITL-8)

Implement HITL-7 and HITL-8 from `docs/tasks/HITL-TASKS.md`.
Batches 1 & 2 (HITL-1 through HITL-6) are complete and committed.

**Read the full task specs in `docs/tasks/HITL-TASKS.md` before starting.**
Read the existing codebase carefully, especially:
- `src/deep_agent/orchestrator/agent_orchestrator.py`
- `src/deep_agent/runtime/protocol.py`
- `src/deep_agent/models/events.py`
- `src/deep_agent/hitl/` (HITL-4/5/6 just landed)
- `src/deep_agent/tools/human_interaction.py`

---

## HITL-7: System Prompt Injection (S complexity)

**Modify** `src/deep_agent/orchestrator/agent_orchestrator.py` — extend
`_build_system_prompt()` (or equivalent prompt construction method) to inject
HITL directives:

1. **Always** when `human_interaction` tool is in the toolset, append a base block:
   ```
   ## Human Interaction
   You have access to the `human_interaction` tool. Use it when you need
   clarification, approval for a risky action, or structured input from the user.
   The three interaction kinds are: "clarify", "approve", "collect".
   ```

2. **When any active skill has `requires_approval=True`**, append:
   ```
   IMPORTANT: You MUST call the `human_interaction` tool with kind="approve"
   before executing any trade, order, or irreversible action. Present the
   full action details and risk level.
   ```

3. **When any active skill has `clarification_hints`**, merge and append hints:
   ```
   Clarification guidance:
   - {hint1}
   - {hint2}
   ```

Existing tests must pass unchanged (no regression).

---

## HITL-8: Orchestrator Suspend/Resume (L complexity — the core)

This is the most complex task. Read it carefully and implement precisely.

**Modify** `src/deep_agent/orchestrator/agent_orchestrator.py`:

### Constructor changes
Accept optional HITL dependencies:
```python
def __init__(
    self,
    ...,                                    # existing params unchanged
    run_state_manager: RunStateManager | None = None,
    checkpoint_store: CheckpointStore | None = None,
) -> None:
```
Store as `self._run_state_manager` and `self._checkpoint_store`. When None,
use `RunStateManager()` and `InMemoryCheckpointStore()` as defaults.

### Inject human_interaction tool into handle_message()
In `handle_message()` (or wherever tools are assembled for the agent):
- Call `create_human_interaction_tool()` and add it to the tool list unconditionally
  (always available, NOT filtered by `allowed_tools`).
- Create a run via `self._run_state_manager.create_run(session_id)` at the start
  of each `handle_message()` call. Store `run_id` locally.

### Detect and handle human_interaction tool calls
In the streaming loop, when `RuntimeAdapter.stream()` yields a `ToolCallEvent`
with `tool_name == "human_interaction"` (or equivalent field name — check the
actual ToolCallEvent schema):
1. Parse tool call input as `HumanInteractionRequest`
2. Capture `tool_call_id` from the event
3. Serialize current conversation state to `Checkpoint`:
   ```python
   checkpoint = Checkpoint(
       run_id=run_id,
       session_id=session_id,
       conversation_history=messages_to_dict(current_messages),
       pending_interaction=interaction_request,
       skill_id=...,         # active skill if known
       tool_call_id=tool_call_id,
       created_at=time.time(),
   )
   await self._checkpoint_store.save(checkpoint)
   ```
4. Call `self._run_state_manager.suspend(run_id, interaction_request)`
5. Yield `InteractionRequiredEvent(run_id=run_id, skill_id=..., interaction=interaction_request)`
6. **Stop** — return from the generator (run is suspended, no more events)

### Add resume_run() method
```python
async def resume_run(
    self,
    run_id: str,
    response: InteractionResponse,
) -> AsyncIterator[AgentEvent]:
```

This method:
1. Load checkpoint: `checkpoint = await self._checkpoint_store.load(run_id)`
   - If None: yield `ErrorEvent(error="Unknown or expired run_id")` and return
2. Check state: `run_info = self._run_state_manager.get_run(run_id)`
   - If not suspended: yield `ErrorEvent(error="Run is not suspended")` and return
3. Call `self._run_state_manager.resume(run_id, response)`
4. Reconstruct conversation history from `messages_from_dict(checkpoint.conversation_history)`
5. Build a `ToolMessage` injecting the user's response as the tool result:
   ```python
   tool_message = ToolMessage(
       content=response.model_dump_json(),
       tool_call_id=checkpoint.tool_call_id,
   )
   ```
6. Append `tool_message` to the reconstructed conversation history
7. Reconstruct the same toolset (re-create tools, system prompt) from checkpoint context
8. Call `RuntimeAdapter.stream()` with the reconstructed history
9. Yield events from the resumed stream — handling any further `human_interaction`
   tool calls the same way (suspend again if the LLM asks another question)
10. On completion: call `self._run_state_manager.complete(run_id)`,
    delete checkpoint: `await self._checkpoint_store.delete(run_id)`

---

## Tests

**Create** `tests/integration/test_hitl_orchestrator.py`:

Use a scripted/mock runtime that can be configured to emit specific events.
If `ScriptedRuntime` doesn't exist in `tests/support/`, create a minimal mock:

```python
class MockRuntime:
    """Emits a pre-configured sequence of AgentEvents."""
    def __init__(self, events: list[AgentEvent]):
        self._events = events

    async def stream(self, messages, tools, system_prompt) -> AsyncIterator[AgentEvent]:
        for event in self._events:
            yield event
```

Test cases:
1. **Normal flow** (no HITL): mock emits `AgentCompleteEvent` — run completes, no suspension
2. **Single HITL suspend**: mock emits `ToolCallEvent(tool="human_interaction", ...)` →
   verify `InteractionRequiredEvent` is yielded, stream stops, run is in `suspended` state
3. **Resume**: after suspend, call `resume_run(run_id, response)` → verify agent continues,
   yields `AgentCompleteEvent`, run moves to `completed`
4. **Double suspend/resume**: mock emits two sequential `human_interaction` tool calls —
   agent suspends twice, resumes twice
5. **Resume with unknown run_id**: yields `ErrorEvent`
6. **System prompt contains HITL block** when `human_interaction` is in toolset

---

## Validation

```bash
cd /home/ubuntu/deep-agent && source .venv/bin/activate
ruff check src/ tests/
mypy src/
pytest tests/ -x -q
```

All must pass. Then write summary to `docs/tasks/HITL-BATCH3-REVIEW.md` and end
with `READY_FOR_REVIEW`.
