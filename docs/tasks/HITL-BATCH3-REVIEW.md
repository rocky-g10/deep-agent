# HITL Batch 3 Implementation Summary

## Files Created
- `tests/integration/test_hitl_orchestrator.py`

## Files Modified
- `src/deep_agent/models/events.py`
- `src/deep_agent/hitl/checkpoint.py`
- `src/deep_agent/orchestrator/agent_orchestrator.py`
- `src/deep_agent/runtime/langgraph_adapter.py`

## What Was Implemented

### HITL-7: System Prompt Injection
- Extended `AgentOrchestrator._build_system_prompt()` to support HITL directives when `has_human_interaction=True`.
- Added base HITL block:
  - `## Human Interaction`
  - usage guidance for `human_interaction`
  - supported kinds: `clarify`, `approve`, `collect`
- Added conditional approval directive when any active skill has `requires_approval=True`.
- Added clarification guidance section by merging `clarification_hints` from active skills.
- `handle_message()` and `resume_run()` now pass `has_human_interaction=True`.

### HITL-8: Orchestrator Suspend/Resume
- Constructor now accepts optional HITL dependencies:
  - `run_state_manager: RunStateManager | None = None`
  - `checkpoint_store: CheckpointStore | None = None`
- Defaults wired when not provided:
  - `RunStateManager()`
  - `InMemoryCheckpointStore()`
- `handle_message()` now:
  - creates run state via `create_run()`
  - always injects `human_interaction` tool into toolset
  - keeps `human_interaction` outside allowlist filtering
  - detects `ToolCallEvent(tool="human_interaction")`
  - validates payload as `HumanInteractionRequest`
  - stores checkpoint (context, bindings, message, history, pending interaction, tool_call_id)
  - transitions run to suspended
  - yields `InteractionRequiredEvent`
  - stops streaming for suspended run
  - marks run completed on `AgentCompleteEvent`
- Added `resume_run(run_id, response)`:
  - loads checkpoint
  - validates run existence and suspended state
  - resumes run state with `InteractionResponse`
  - reconstructs context/bindings/runtime config
  - rebuilds tools + system prompt (including HITL tool)
  - reconstructs history and appends `ToolMessage` with response JSON and stored `tool_call_id`
  - resumes stream and supports repeated suspension if `human_interaction` is called again
  - on completion: marks run completed and deletes checkpoint
  - on invalid/unknown state: emits `ErrorEvent` codes
- Added `tool_call_id` field to `ToolCallEvent` for tool-result correlation in resume path.
- Updated `LangGraphAdapter` to populate `ToolCallEvent.tool_call_id` when available.

### Checkpoint Model Enhancements
- Extended `Checkpoint` with fields used for resume reconstruction:
  - `tenant_context`
  - `skill_bindings`
  - `original_message`

## Tests Added
- `tests/integration/test_hitl_orchestrator.py` with cases:
  1. Normal flow without suspension
  2. Single suspend on `human_interaction`
  3. Resume to completion
  4. Double suspend/resume cycle
  5. Resume with unknown run_id yields `ErrorEvent`
  6. System prompt contains HITL block when HITL tool is present

## Validation Results
- `ruff check src/ tests/`:
  - Passed (`All checks passed!`)
- `mypy src/`:
  - Passed (`Success: no issues found in 36 source files`)
- `pytest tests/ -x -q`:
  - Passed (suite completed with no failures)

## Design Decisions / Notes
- Resume uses checkpointed context/bindings/message + reconstructed runtime state because current `RuntimeAdapter` protocol is message-driven and does not expose full internal graph state snapshots.
- Conversation history persisted in checkpoint uses `messages_to_dict()` and resumed with `messages_from_dict()` plus appended `ToolMessage` carrying the human response.

READY_FOR_REVIEW
