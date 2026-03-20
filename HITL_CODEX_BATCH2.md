# HITL Implementation — Batch 2 (HITL-4, HITL-5, HITL-6)

Implement tasks HITL-4, HITL-5, and HITL-6 from `docs/tasks/HITL-TASKS.md`.
Batch 1 (HITL-1/2/3) is complete and committed. Build on top of it.

**Read the full task specs in `docs/tasks/HITL-TASKS.md` before starting.**

---

## HITL-4: Run State Manager

**Create** `src/deep_agent/hitl/__init__.py` (empty, just package marker)
**Create** `src/deep_agent/hitl/run_state.py` with `RunStateManager` class:

- `create_run(session_id, skill_id=None) -> RunInfo` — generates run_id (uuid4), stores RunInfo in state=running
- `get_run(run_id) -> RunInfo | None`
- `suspend(run_id, interaction: HumanInteractionRequest) -> RunInfo` — running→suspended, sets suspended_at
- `resume(run_id, response: InteractionResponse) -> RunInfo` — suspended→running, sets responded_at + response
- `timeout(run_id) -> RunInfo` — suspended→timed_out
- `complete(run_id) -> RunInfo` — running→completed
- `fail(run_id) -> RunInfo` — running→failed
- `abort(run_id) -> RunInfo` — timed_out→aborted
- `apply_fallback(run_id) -> RunInfo` — timed_out→running (pass allow_fallback=True to can_transition_to())
- `list_suspended() -> list[RunInfo]`
- Thread-safe (use threading.Lock or asyncio.Lock)

**Exception:** `class InvalidStateTransition(Exception)` in same file

Note: use `RunState.can_transition_to(target, allow_fallback=...)` from HITL-1 (already built).

---

## HITL-5: Checkpoint Store

**Create** `src/deep_agent/hitl/checkpoint.py`:

```python
class Checkpoint(BaseModel):
    run_id: str
    session_id: str
    conversation_history: list[dict[str, Any]]  # via messages_to_dict/messages_from_dict
    pending_interaction: HumanInteractionRequest
    skill_id: str | None = None
    tool_call_id: str | None = None
    env_snapshot: dict[str, str] = Field(default_factory=dict)
    scripts_dirs: list[str] = Field(default_factory=list)
    created_at: float

@runtime_checkable
class CheckpointStore(Protocol):
    async def save(self, checkpoint: Checkpoint) -> None: ...
    async def load(self, run_id: str) -> Checkpoint | None: ...
    async def delete(self, run_id: str) -> None: ...

class InMemoryCheckpointStore:
    """MVP in-memory implementation. Redis/PostgreSQL backends post-MVP."""
    async def save(...): ...
    async def load(...): ...
    async def delete(...): ...
```

Use `langchain_core.messages.messages_to_dict` / `messages_from_dict` for conversation_history serialization.

---

## HITL-6: HumanInteraction Tool

**Create** `src/deep_agent/tools/human_interaction.py`:

```python
class HumanInteractionTool(BaseTool):
    name: str = "human_interaction"
    description: str = (
        "Request input from the human user. Use this tool when you need "
        "clarification, approval for a risky action, or structured input. "
        "Specify 'kind' as 'clarify', 'approve', or 'collect'."
    )
    args_schema: type[BaseModel] = HumanInteractionRequest

    def _run(self, **kwargs) -> str:
        raise NotImplementedError("human_interaction is intercepted by the orchestrator")

    async def _arun(self, **kwargs) -> str:
        raise NotImplementedError("human_interaction is intercepted by the orchestrator")

def create_human_interaction_tool() -> HumanInteractionTool:
    return HumanInteractionTool()
```

**Modify** `src/deep_agent/tools/__init__.py` — export `HumanInteractionTool`, `create_human_interaction_tool`.

---

## Tests

**Create** `tests/unit/test_hitl_run_state.py`:
- All valid state transitions (happy path)
- Invalid transitions raise `InvalidStateTransition`
- `suspend()` sets suspended_at, stores interaction
- `resume()` sets responded_at, stores response
- `list_suspended()` returns only suspended runs
- Thread-safety: concurrent `create_run` calls produce unique run_ids

**Create** `tests/unit/test_hitl_checkpoint.py`:
- Save → load round-trip preserves all fields
- `delete()` then `load()` returns None
- `Checkpoint` serializes to JSON (model_dump)

**Create** `tests/unit/test_hitl_tool.py`:
- `name == "human_interaction"`
- `args_schema == HumanInteractionRequest`
- Direct `_run()` / `_arun()` raises NotImplementedError
- Tool appears in LangChain tool list with correct schema

---

## Validation

```bash
cd /home/ubuntu/deep-agent && source .venv/bin/activate
ruff check src/ tests/
mypy src/
pytest tests/ -x -q
```

All must pass. Then write summary to `docs/tasks/HITL-BATCH2-REVIEW.md` and end with `READY_FOR_REVIEW`.
