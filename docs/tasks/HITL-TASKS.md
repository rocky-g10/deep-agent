# HITL Implementation Tasks

> **Spec reference:** `docs/PRD.md` §11.4, `docs/DEVELOPER_GUIDE.md` §11
> **Status:** Planning — no runtime implementation exists in `src/` yet
> **Date:** 2026-03-20

---

## Task Dependency Graph

```
HITL-1 (models) ──┬──► HITL-2 (events) ──────────────────────┐
                   │                                           │
                   ├──► HITL-4 (run state mgr) ──┬──► HITL-5  │
                   │                              │  (ckpt)    │
                   ├──► HITL-6 (tool) ────────────┤            │
                   │                              │            │
HITL-3 (skill fm) ─┬──► HITL-7 (prompt inject) ──┤            │
                   │                              │            │
                   │              ┌────────────────┘            │
                   │              ▼                             │
                   │         HITL-8 (orchestrator) ◄───────────┘
                   │              │
                   │    ┌─────────┼──────────┐
                   │    ▼         ▼          ▼
                   │  HITL-9   HITL-10    HITL-11
                   │  (REST)   (WS)       (timeout)
                   │    │         │          │
                   │    └────┬────┘          │
                   │         ▼              │
                   │      HITL-13 ◄─────────┘
                   │      (multi-skill)
                   │         │
                   ▼         ▼
               HITL-12    HITL-14
               (audit)    (CLI)
                   │         │
                   └────┬────┘
                        ▼
                     HITL-15
                     (integration tests)
```

---

## HITL-1: Core Data Models

**Title:** Define HITL data models (HumanInteraction, FieldSpec, InteractionResponse, RunState)

**Files to create/modify:**
- Create `src/deep_agent/models/hitl.py`
- Modify `src/deep_agent/models/__init__.py` (re-export new types)

**What to build:**

```python
# src/deep_agent/models/hitl.py

class FieldSpec(BaseModel):
    """One field in a structured input collection form."""
    name: str
    type: Literal["string", "number", "boolean", "date", "enum"]
    required: bool = True
    description: str = ""
    enum_values: list[str] | None = None
    default: str | None = None

class HumanInteractionRequest(BaseModel):
    """Payload the LLM produces when it calls the human_interaction tool."""
    kind: Literal["clarify", "approve", "collect"]
    # clarify
    question: str | None = None
    options: list[str] | None = None
    # approve
    action_description: str | None = None
    risk_level: Literal["low", "medium", "high"] | None = None
    # collect
    fields: list[FieldSpec] | None = None
    # timeout + fallback
    timeout_seconds: int = 300
    fallback: Literal["abort", "default", "skip"] = "abort"

class InteractionResponse(BaseModel):
    """User's response to a HumanInteractionRequest."""
    kind: Literal["clarify", "approve", "collect"]
    # clarify
    value: str | None = None
    # approve
    approved: bool | None = None
    reason: str | None = None
    # collect
    values: dict[str, Any] | None = None

class RunState(str, Enum):
    running = "running"
    suspended = "suspended"
    timed_out = "timed_out"
    aborted = "aborted"
    completed = "completed"
    failed = "failed"

class RunInfo(BaseModel):
    """Tracks the lifecycle of a single agent run."""
    run_id: str
    session_id: str
    state: RunState = RunState.running
    skill_id: str | None = None
    interaction: HumanInteractionRequest | None = None
    suspended_at: float | None = None
    responded_at: float | None = None
    response: InteractionResponse | None = None
```

**Dependencies:** None

**Acceptance criteria:**
- `pytest tests/unit/test_hitl_models.py` passes
- All models round-trip through `.model_dump()` / `.model_validate()`
- `RunState` transitions validated: `running→suspended`, `suspended→running`, `suspended→timed_out`, `timed_out→aborted`, `timed_out→running`, `running→completed`, `running→failed`
- `HumanInteractionRequest` validates that `question` is set when `kind="clarify"`, `action_description` when `kind="approve"`, `fields` when `kind="collect"`

**Complexity:** S

---

## HITL-2: Event Types for HITL

**Title:** Add `InteractionRequiredEvent` and `InteractionResponseEvent` to the event system

**Files to modify:**
- `src/deep_agent/models/events.py`

**What to build:**

```python
class InteractionRequiredEvent(BaseModel):
    type: Literal["interaction_required"] = "interaction_required"
    run_id: str
    skill_id: str | None = None
    interaction: HumanInteractionRequest

class InteractionResponseEvent(BaseModel):
    type: Literal["interaction_response"] = "interaction_response"
    run_id: str
    response: InteractionResponse
```

Add both to the `AgentEvent` discriminated union:

```python
AgentEvent = Annotated[
    AgentChunkEvent | ToolCallEvent | ToolResultEvent | SkillMatchEvent |
    AgentCompleteEvent | ErrorEvent |
    InteractionRequiredEvent | InteractionResponseEvent,
    Discriminator("type"),
]
```

**Dependencies:** HITL-1

**Acceptance criteria:**
- Existing `test_models.py` tests still pass (backward compatible)
- New events serialize/deserialize correctly via the `AgentEvent` union
- `InteractionRequiredEvent(run_id="r1", interaction=HumanInteractionRequest(kind="clarify", question="Which?"))` round-trips through JSON

**Complexity:** S

---

## HITL-3: Skill Frontmatter — HITL Fields

**Title:** Add `requires-approval`, `clarification-hints`, and HITL quality fields to skill parser and models

**Files to modify:**
- `src/deep_agent/models/skills.py`
- `src/deep_agent/skills/parser.py`

**What to build:**

In `skills.py`, add to `SkillContent`:
```python
requires_approval: bool = False
clarification_hints: dict[str, str] = Field(default_factory=dict)
```

In `SkillQuality`, add:
```python
hitl_timeout: int = Field(default=300, alias="hitl-timeout")
hitl_fallback: Literal["abort", "default", "skip"] = Field(default="abort", alias="hitl-fallback")
```

In `parser.py`, extend `parse_skill_file()`:
- Read `requires-approval` from frontmatter → `requires_approval`
- Read `clarification-hints` from frontmatter → `clarification_hints`
- Read `quality.hitl-timeout` and `quality.hitl-fallback`

**Dependencies:** None

**Acceptance criteria:**
- Existing parser tests pass unchanged (fields default to `False`/`{}`)
- A SKILL.md with `requires-approval: true` parses to `skill.requires_approval == True`
- A SKILL.md with `clarification-hints` parses to the correct dict
- A SKILL.md without these fields parses with defaults (backward compatible)

**Complexity:** S

---

## HITL-4: Run State Manager

**Title:** Implement `RunStateManager` to track agent run lifecycle and state transitions

**Files to create:**
- `src/deep_agent/hitl/__init__.py`
- `src/deep_agent/hitl/run_state.py`

**What to build:**

```python
class RunStateManager:
    """In-memory run state tracker with state machine enforcement."""

    def __init__(self) -> None:
        self._runs: dict[str, RunInfo] = {}

    def create_run(self, session_id: str, skill_id: str | None = None) -> RunInfo:
        """Create a new run in 'running' state. Returns RunInfo with generated run_id."""

    def get_run(self, run_id: str) -> RunInfo | None:

    def suspend(self, run_id: str, interaction: HumanInteractionRequest) -> RunInfo:
        """Transition running → suspended. Raises InvalidStateTransition if not running."""

    def resume(self, run_id: str, response: InteractionResponse) -> RunInfo:
        """Transition suspended → running. Raises InvalidStateTransition if not suspended."""

    def timeout(self, run_id: str) -> RunInfo:
        """Transition suspended → timed_out."""

    def complete(self, run_id: str) -> RunInfo:
        """Transition running → completed."""

    def fail(self, run_id: str) -> RunInfo:
        """Transition running → failed."""

    def abort(self, run_id: str) -> RunInfo:
        """Transition timed_out → aborted."""

    def apply_fallback(self, run_id: str) -> RunInfo:
        """For timed_out runs with fallback='default' or 'skip': transition timed_out → running."""

    def list_suspended(self) -> list[RunInfo]:
        """Return all runs in 'suspended' state (used by timeout manager)."""

class InvalidStateTransition(Exception):
    """Raised when a state transition is not allowed."""
```

**Dependencies:** HITL-1

**Acceptance criteria:**
- All valid state transitions succeed
- Invalid transitions raise `InvalidStateTransition` (e.g., `completed→suspended`)
- `suspend()` stores the `HumanInteractionRequest` and sets `suspended_at` timestamp
- `resume()` stores the `InteractionResponse` and sets `responded_at` timestamp
- `list_suspended()` returns only `suspended` runs
- Thread-safe (use a lock for in-memory dict mutations)

**Complexity:** M

---

## HITL-5: Checkpoint Store

**Title:** Implement checkpoint store protocol and in-memory backend for agent state serialization

**Files to create:**
- `src/deep_agent/hitl/checkpoint.py`

**What to build:**

```python
class Checkpoint(BaseModel):
    """Serialized agent state for suspend/resume."""
    run_id: str
    session_id: str
    conversation_history: list[dict[str, Any]]   # Serialized LangChain messages
    pending_interaction: HumanInteractionRequest
    skill_id: str | None = None
    tool_call_id: str | None = None              # The tool_call_id to respond to on resume
    env_snapshot: dict[str, str] = Field(default_factory=dict)
    scripts_dirs: list[str] = Field(default_factory=list)
    created_at: float

@runtime_checkable
class CheckpointStore(Protocol):
    async def save(self, checkpoint: Checkpoint) -> None: ...
    async def load(self, run_id: str) -> Checkpoint | None: ...
    async def delete(self, run_id: str) -> None: ...

class InMemoryCheckpointStore:
    """MVP checkpoint store. Replace with Redis/PostgreSQL post-MVP."""

    def __init__(self) -> None:
        self._store: dict[str, Checkpoint] = {}

    async def save(self, checkpoint: Checkpoint) -> None: ...
    async def load(self, run_id: str) -> Checkpoint | None: ...
    async def delete(self, run_id: str) -> None: ...
```

The `conversation_history` field stores serialized LangChain `BaseMessage` objects. Use `messages_to_dict()` / `messages_from_dict()` from `langchain_core.messages` for serialization.

**Dependencies:** HITL-1, HITL-4

**Acceptance criteria:**
- `InMemoryCheckpointStore` implements `CheckpointStore` protocol
- Save → load round-trip preserves all fields including conversation history
- `delete()` removes the checkpoint; subsequent `load()` returns `None`
- `Checkpoint` validates via Pydantic (all fields serialize to JSON)

**Complexity:** M

---

## HITL-6: HumanInteraction Tool

**Title:** Implement `human_interaction` as a LangChain `BaseTool` that the LLM can invoke

**Files to create:**
- `src/deep_agent/tools/human_interaction.py`
- Modify `src/deep_agent/tools/__init__.py`

**What to build:**

```python
class HumanInteractionTool(BaseTool):
    """Built-in tool the LLM calls to request human input.

    The orchestrator intercepts calls to this tool — it never actually
    'executes' in the normal sense. Instead, the orchestrator detects
    the tool call, suspends the agent run, and emits an
    InteractionRequiredEvent.
    """
    name: str = "human_interaction"
    description: str = (
        "Request input from the human user. Use this tool when you need "
        "clarification, approval for a risky action, or structured input. "
        "Specify 'kind' as 'clarify', 'approve', or 'collect'."
    )

    def _run(self, **kwargs: Any) -> str:
        """Synchronous fallback — should never be reached."""
        raise NotImplementedError("human_interaction is intercepted by the orchestrator")

    async def _arun(self, **kwargs: Any) -> str:
        """Async fallback — should never be reached."""
        raise NotImplementedError("human_interaction is intercepted by the orchestrator")

def create_human_interaction_tool() -> HumanInteractionTool:
    """Factory that returns the human_interaction tool instance."""
```

The tool's input schema must match `HumanInteractionRequest` so the LLM generates valid payloads. Use Pydantic `args_schema` on the `BaseTool`:

```python
args_schema: type[BaseModel] = HumanInteractionRequest
```

**Dependencies:** HITL-1, HITL-2

**Acceptance criteria:**
- Tool has `name="human_interaction"` and correct description
- `args_schema` matches `HumanInteractionRequest` (the LLM sees correct JSON schema)
- Direct invocation raises `NotImplementedError` (orchestrator intercepts, never calls `_arun`)
- Tool appears in LangChain tool list with proper schema when passed to `create_agent()`

**Complexity:** S

---

## HITL-7: System Prompt Injection for HITL

**Title:** Inject HITL directives into the system prompt based on skill frontmatter

**Files to modify:**
- `src/deep_agent/orchestrator/agent_orchestrator.py` (specifically `_build_system_prompt`)

**What to build:**

Extend `_build_system_prompt()` to append HITL-related directives when skills with HITL configuration are active:

1. **Always** (when `human_interaction` tool is in the toolset): append a base HITL instruction block:
   ```
   ## Human Interaction
   You have access to the `human_interaction` tool. Use it when you need
   clarification, approval, or structured input from the user. The three
   interaction kinds are: "clarify", "approve", "collect".
   ```

2. **When any active skill has `requires_approval: True`**: append:
   ```
   IMPORTANT: You MUST call the `human_interaction` tool with kind="approve"
   before executing any trade, order, or irreversible action. Present the
   full action details and risk level.
   ```

3. **When any active skill has `clarification_hints`**: append the hints as guidance:
   ```
   Clarification guidance:
   - If the user does not specify a portfolio: ask "Which portfolio should I analyze?"
   - If the time period is ambiguous: ask "What time range — YTD or trailing 12 months?"
   ```

**Dependencies:** HITL-3

**Acceptance criteria:**
- System prompt contains HITL block when `human_interaction` tool is present
- `requires-approval` directive injected only when at least one active skill has `requires_approval=True`
- Clarification hints from all active skills are merged and injected
- System prompt is unchanged when no HITL-enabled skills are active
- Existing `test_orchestrator.py` tests pass (no regression)

**Complexity:** S

---

## HITL-8: Orchestrator Suspend/Resume Integration

**Title:** Modify `AgentOrchestrator.handle_message()` to detect `human_interaction` tool calls, suspend runs, and support resumption

**Files to modify:**
- `src/deep_agent/orchestrator/agent_orchestrator.py`

**What to build:**

1. **Inject `human_interaction` tool** into the toolset in `handle_message()` by calling `create_human_interaction_tool()` and adding it to the tool list (always available, not filtered by `allowed_tools`).

2. **Detect `human_interaction` tool calls** in the streaming loop. When `RuntimeAdapter.stream()` yields a `ToolCallEvent` with `tool="human_interaction"`:
   - Parse the tool call input as `HumanInteractionRequest`
   - Call `RunStateManager.suspend(run_id, interaction)`
   - Serialize agent state to `CheckpointStore.save()`
   - Yield an `InteractionRequiredEvent`
   - **Stop** yielding further events (the run is suspended)

3. **Add `resume_run()` method**:
   ```python
   async def resume_run(
       self,
       run_id: str,
       response: InteractionResponse,
   ) -> AsyncIterator[AgentEvent]:
       """Resume a suspended run with the user's response."""
   ```
   This method:
   - Loads the checkpoint from `CheckpointStore`
   - Calls `RunStateManager.resume(run_id, response)`
   - Reconstructs agent state (conversation history, tools, system prompt)
   - Injects the `InteractionResponse` as a `ToolMessage` (the response to the `human_interaction` tool call)
   - Calls `RuntimeAdapter.stream()` with the reconstructed history
   - Continues yielding events until `AgentComplete` or another suspension

4. **Constructor changes**: accept `RunStateManager` and `CheckpointStore` as dependencies:
   ```python
   def __init__(
       self,
       ...,
       run_state_manager: RunStateManager | None = None,
       checkpoint_store: CheckpointStore | None = None,
   ) -> None:
   ```

**Dependencies:** HITL-4, HITL-5, HITL-6, HITL-7

**Acceptance criteria:**
- `handle_message()` includes `human_interaction` in the tool list
- When LLM calls `human_interaction`, the stream yields `InteractionRequiredEvent` and stops
- `resume_run()` successfully resumes a suspended run and yields subsequent events
- The LLM sees the user's response as a tool result for `human_interaction`
- Multiple suspend/resume cycles work (agent can ask multiple questions)
- Existing orchestrator tests pass (graceful no-op when no HITL tools are called)

**Complexity:** L

---

## HITL-9: Response REST API Endpoint

**Title:** Implement `POST /api/v1/runs/{run_id}/respond` endpoint

**Files to modify:**
- `src/deep_agent/api/app.py` (register new router)
- Create `src/deep_agent/api/runs.py`
- Modify `src/deep_agent/api/schemas.py` (add request/response schemas)

**What to build:**

In `schemas.py`, add:
```python
class RunRespondRequest(BaseModel):
    response: InteractionResponse

class RunRespondResult(BaseModel):
    run_id: str
    status: str  # "resumed"
```

In `runs.py`:
```python
router = APIRouter(prefix="/api/v1/runs", tags=["runs"])

@router.post("/{run_id}/respond", response_model=RunRespondResult)
async def respond_to_run(
    run_id: str,
    body: RunRespondRequest,
) -> RunRespondResult:
    """Submit a human response to a suspended agent run.

    Response codes:
    - 200: Response accepted, agent resumed
    - 404: Unknown run_id or run already completed
    - 409: Run is not in suspended state
    - 422: Validation failure
    """
```

The endpoint must:
1. Look up the run via `RunStateManager.get_run(run_id)`
2. Return 404 if not found
3. Return 409 if run state is not `suspended`
4. Call `orchestrator.resume_run(run_id, response)` to resume
5. Stream resumed events to the WebSocket connection associated with the run's session (via a shared event bus or callback registry)
6. Return 200 with `{"run_id": ..., "status": "resumed"}`

In `app.py`, mount the router:
```python
app.include_router(runs_router)
```

**Dependencies:** HITL-4, HITL-5, HITL-8

**Acceptance criteria:**
- `POST /api/v1/runs/{run_id}/respond` with valid payload returns 200
- Unknown `run_id` returns 404
- Responding to a non-suspended run returns 409
- Invalid `InteractionResponse` (e.g., missing required fields for `collect`) returns 422
- After responding, the agent run resumes and produces events

**Complexity:** M

---

## HITL-10: WebSocket Integration

**Title:** Wire HITL events through the WebSocket handler and connect response API to session streaming

**Files to modify:**
- `src/deep_agent/api/ws_chat.py`
- `src/deep_agent/api/session.py`

**What to build:**

1. **Session run tracking**: Add `active_run_id: str | None` to `Session` so the WebSocket handler knows which run is active and can route resumed events.

2. **Event bus for resume**: Add a mechanism for the REST response endpoint to push resumed events back to the WebSocket connection. Options:
   - Add an `asyncio.Queue` per session for resume events
   - Or store a reference to the WebSocket connection on the session

   Recommended: add `resume_queue: asyncio.Queue[AgentEvent]` to `Session`.

3. **WebSocket handler changes** in `ws_chat.py`:
   - When `handle_message()` yields an `InteractionRequiredEvent`, send it to the client as JSON and enter a "waiting" state for that session (stop reading new user messages until the run completes or is aborted).
   - Start a background task that reads from `session.resume_queue` and forwards events to the WebSocket.
   - When `resume_run()` is called (from the REST endpoint), it pushes events into `session.resume_queue` → the background task sends them to the client.

4. **REST→WS bridge** in `runs.py`:
   - After calling `orchestrator.resume_run()`, iterate the resulting `AsyncIterator[AgentEvent]` and push each event into the session's `resume_queue`.

**Dependencies:** HITL-2, HITL-8, HITL-9

**Acceptance criteria:**
- Client receives `interaction_required` JSON event over WebSocket when agent suspends
- After `POST /api/v1/runs/{run_id}/respond`, resumed events stream over the original WebSocket connection
- Client sees the full lifecycle: `skill_match → agent_chunk → interaction_required → (user responds) → agent_chunk → agent_complete`
- Multiple sessions can have independent HITL flows concurrently
- Error handling: if WebSocket disconnects during suspension, the run remains suspended (can be resumed later or times out)

**Complexity:** L

---

## HITL-11: Timeout Manager

**Title:** Implement background task that detects timed-out suspended runs and applies fallback strategies

**Files to create:**
- `src/deep_agent/hitl/timeout_manager.py`

**What to build:**

```python
class TimeoutManager:
    """Periodic background task that checks for expired suspensions."""

    def __init__(
        self,
        run_state_manager: RunStateManager,
        checkpoint_store: CheckpointStore,
        orchestrator: AgentOrchestrator,
        check_interval: float = 5.0,
    ) -> None: ...

    async def start(self) -> None:
        """Start the background polling loop."""

    async def stop(self) -> None:
        """Cancel the background task."""

    async def _check_timeouts(self) -> None:
        """Single sweep: find expired runs and apply fallback."""
```

For each expired run (current_time > suspended_at + timeout_seconds):
1. Call `run_state_manager.timeout(run_id)`
2. Check the `fallback` strategy from the stored `HumanInteractionRequest`:
   - `"abort"`: call `run_state_manager.abort(run_id)`, delete checkpoint, push `ErrorEvent` to session
   - `"default"`: build a synthetic `InteractionResponse` with default values from `FieldSpec.default`, call `orchestrator.resume_run()`
   - `"skip"`: build a synthetic `InteractionResponse` with `value="[skipped]"`, call `orchestrator.resume_run()`

**Dependencies:** HITL-4, HITL-5

**Acceptance criteria:**
- Runs that exceed `timeout_seconds` are transitioned to `timed_out`
- `fallback="abort"` produces an `ErrorEvent` with code `HITL_TIMEOUT`
- `fallback="default"` resumes with default values
- `fallback="skip"` resumes with a skip marker
- Manager is stoppable (clean shutdown)
- Does not interfere with runs that are still within their timeout window

**Complexity:** M

---

## HITL-12: Audit Logging for HITL Interactions

**Title:** Emit structured audit events for all HITL interactions

**Files to create:**
- `src/deep_agent/hitl/audit.py`

**Files to modify:**
- `src/deep_agent/orchestrator/agent_orchestrator.py` (call audit hooks)

**What to build:**

```python
@dataclass
class HITLAuditEvent:
    """Structured audit event for HITL interactions (PRD §11.4.10)."""
    timestamp: str               # ISO 8601
    trace_id: str
    session_id: str
    user_id: str
    tenant_id: str
    category: Literal["hitl_interaction"] = "hitl_interaction"
    action: Literal[
        "interaction_requested",
        "response_submitted",
        "interaction_timed_out",
    ]
    interaction_kind: Literal["clarify", "approve", "collect"]
    question_or_action: str      # The question asked or action proposed
    response: str | None = None  # Serialized user response
    responder_id: str | None = None
    latency_ms: int | None = None
    risk_level: str | None = None
    outcome: str | None = None   # approved, denied, timed_out, skipped

def emit_hitl_audit(event: HITLAuditEvent) -> None:
    """Log the HITL audit event.

    MVP: structured log via Python logging (JSON format).
    Post-MVP: push to Redis audit queue per PRD §6.5.
    """
```

Integration points in the orchestrator:
- On suspend: emit `action="interaction_requested"`
- On resume: emit `action="response_submitted"` with `latency_ms` and `outcome`
- On timeout: emit `action="interaction_timed_out"` with `outcome` based on fallback

**Dependencies:** HITL-1, HITL-2

**Acceptance criteria:**
- Every HITL interaction produces a structured audit log entry
- Audit events contain all fields from PRD §11.4.10 table
- `latency_ms` is correctly computed (time between request and response)
- `outcome` is set: `approved`/`denied` for approve, `timed_out`/`skipped` for timeouts
- Audit events are emitted even when the run is aborted

**Complexity:** M

---

## HITL-13: Multi-Skill HITL Handling

**Title:** Handle HITL suspension correctly when multiple skills are active

**Files to modify:**
- `src/deep_agent/orchestrator/agent_orchestrator.py`

**What to build:**

Per PRD §11.4.8, when multiple skills are active and the LLM calls `human_interaction`:

1. The **entire** agent run suspends (the LLM is a single execution thread even with multiple active skills — there are no parallel skill branches in the current LangGraph architecture).

2. On resume, the LLM continues with all active skills still in context. The merged system prompt, tools, and PYTHONPATH from all active skills remain intact.

3. If the suspended run times out with `fallback="abort"`:
   - Emit an `ErrorEvent` noting which skill triggered the HITL interaction
   - Include a note in the error message: `"HITL timeout on skill {skill_id}; other active skills were also terminated"`

4. Track which skill triggered the suspension by including `skill_id` in the `InteractionRequiredEvent` (use the highest-scored skill with `requires_approval=True`, or the skill context the LLM was operating in when it called the tool).

Implementation note: Since the current architecture uses a single LLM stream (not parallel branches), multi-skill HITL is simpler than the PRD's branching model. The LLM decides when to invoke `human_interaction` based on the merged prompt. The suspension/resume mechanism is identical to single-skill — the only difference is that the `InteractionRequiredEvent` should reflect which skill context triggered it, and system prompt reconstruction on resume must include all originally-active skills.

**Dependencies:** HITL-8

**Acceptance criteria:**
- With 2+ active skills, `human_interaction` tool call suspends the run correctly
- Resume reconstructs the full multi-skill system prompt (all skills, merged tools, merged PYTHONPATH)
- `InteractionRequiredEvent.skill_id` reflects the triggering context
- Timeout/abort produces an error noting multi-skill context
- Single-skill behavior is unchanged (regression test)

**Complexity:** M

---

## HITL-14: CLI Interactive Mode

**Title:** Add `--interactive` flag to `scripts/invoke_agent.py` for terminal-based HITL testing

**Files to modify:**
- `scripts/invoke_agent.py`

**What to build:**

Add an `--interactive` CLI flag. When set:

1. When the orchestrator yields `InteractionRequiredEvent`, print it to the terminal and prompt the user:
   - **Clarify**: print question and options, read a line from stdin
   - **Approve**: print action description and risk level, prompt `Approve? (y/n):`
   - **Collect**: print each field with its description, prompt for each value

2. Build an `InteractionResponse` from the user's input.

3. Call `orchestrator.resume_run(run_id, response)` and continue streaming events.

4. Handle timeout gracefully (if the user doesn't respond within `timeout_seconds`, apply fallback).

Without `--interactive`, `InteractionRequiredEvent` is printed as a JSON event and the script exits (current behavior for unhandled events).

**Dependencies:** HITL-6, HITL-8

**Acceptance criteria:**
- `invoke_agent.py --interactive "query"` prompts in terminal on HITL events
- Clarify: shows question, accepts typed answer, resumes
- Approve: shows action, accepts y/n, resumes with `approved=True/False`
- Collect: prompts for each field, builds values dict, resumes
- Non-interactive mode prints the event and exits cleanly

**Complexity:** M

---

## HITL-15: Integration Tests

**Title:** End-to-end integration tests for the full HITL lifecycle

**Files to create:**
- `tests/unit/test_hitl_models.py`
- `tests/unit/test_hitl_run_state.py`
- `tests/unit/test_hitl_checkpoint.py`
- `tests/unit/test_hitl_tool.py`
- `tests/unit/test_hitl_prompt.py`
- `tests/integration/test_hitl_orchestrator.py`
- `tests/integration/test_hitl_ws.py`
- `tests/integration/test_hitl_timeout.py`

**What to build:**

**Unit tests:**
- `test_hitl_models.py`: model validation, serialization, state transitions
- `test_hitl_run_state.py`: `RunStateManager` state machine — valid/invalid transitions, concurrent access
- `test_hitl_checkpoint.py`: `InMemoryCheckpointStore` save/load/delete round-trips
- `test_hitl_tool.py`: tool schema matches `HumanInteractionRequest`, direct invocation raises
- `test_hitl_prompt.py`: system prompt contains HITL block, `requires-approval` directive, clarification hints

**Integration tests (using `ScriptedRuntime` from `tests/support/`):**
- `test_hitl_orchestrator.py`:
  - Scripted runtime returns a `human_interaction` tool call → verify `InteractionRequiredEvent` is yielded and stream stops
  - Call `resume_run()` with a response → verify agent continues and yields `AgentCompleteEvent`
  - Double suspend/resume (agent asks two questions)
  - Resume with invalid run_id → error
- `test_hitl_ws.py`:
  - WebSocket client receives `interaction_required` event
  - `POST /api/v1/runs/{run_id}/respond` returns 200 and resumes events on WS
  - 404 for unknown run_id, 409 for non-suspended run
- `test_hitl_timeout.py`:
  - Suspend a run with `timeout_seconds=1`, wait for timeout manager to fire
  - Verify `fallback="abort"` produces `ErrorEvent`
  - Verify `fallback="skip"` resumes the run

Use the existing `ScriptedRuntime` from `tests/support/scripted_runtime.py` to control what the "LLM" returns. Script it to emit a `ToolCallEvent(tool="human_interaction", ...)` at the right moment.

**Dependencies:** All previous tasks

**Acceptance criteria:**
- All unit tests pass
- All integration tests pass
- Full lifecycle tested: message → skill match → tool calls → human_interaction → suspend → respond → resume → complete
- Timeout lifecycle tested: suspend → timeout → abort (or skip/default)
- WebSocket lifecycle tested end-to-end
- No regressions in existing test suite

**Complexity:** L

---

## Implementation Order (Sequential)

| Order | Task | Complexity | Est. Files Changed |
|-------|------|-----------|-------------------|
| 1 | HITL-1: Core Data Models | S | 2 new, 1 modified |
| 2 | HITL-2: Event Types | S | 1 modified |
| 3 | HITL-3: Skill Frontmatter | S | 2 modified |
| 4 | HITL-4: Run State Manager | M | 2 new |
| 5 | HITL-5: Checkpoint Store | M | 1 new |
| 6 | HITL-6: HumanInteraction Tool | S | 1 new, 1 modified |
| 7 | HITL-7: System Prompt Injection | S | 1 modified |
| 8 | HITL-8: Orchestrator Suspend/Resume | L | 1 modified |
| 9 | HITL-9: Response REST API | M | 2 new, 1 modified |
| 10 | HITL-10: WebSocket Integration | L | 2 modified |
| 11 | HITL-11: Timeout Manager | M | 1 new |
| 12 | HITL-12: Audit Logging | M | 1 new, 1 modified |
| 13 | HITL-13: Multi-Skill HITL | M | 1 modified |
| 14 | HITL-14: CLI Interactive Mode | M | 1 modified |
| 15 | HITL-15: Integration Tests | L | 8 new |

**Total:** 4S + 6M + 3L + 2 test tasks = ~19 new files, ~10 modified files

---

## Notes

- **Backward compatibility:** All changes default to no-op when HITL is not triggered. Existing tests must pass at every step.
- **No external dependencies added:** MVP uses in-memory stores. Redis/PostgreSQL checkpoint backends are post-MVP (noted in HITL-5 as future work).
- **LangGraph specifics:** The `tool_call_id` from the LLM's `human_interaction` call must be captured and used when injecting the `ToolMessage` on resume. This is how LangGraph associates tool results with tool calls.
- **Skill author experience:** Zero code. The LLM naturally calls `human_interaction` based on prompt guidance. The `requires-approval` and `clarification-hints` frontmatter fields are optional enhancers.
