# CC Review Request — HITL Batch 3 (HITL-7, HITL-8)

Review Codex's implementation of HITL-7 and HITL-8.

**Files changed:**
- `src/deep_agent/orchestrator/agent_orchestrator.py` (HITL-7 + HITL-8 — main changes)
- `src/deep_agent/models/events.py` (added tool_call_id to ToolCallEvent)
- `src/deep_agent/hitl/checkpoint.py` (added tenant_context, skill_bindings, original_message)
- `src/deep_agent/runtime/langgraph_adapter.py` (populate tool_call_id)
- `tests/integration/test_hitl_orchestrator.py` (new integration tests)

**Spec reference:** `docs/tasks/HITL-TASKS.md` tasks HITL-7 and HITL-8
**Codex summary:** `docs/tasks/HITL-BATCH3-REVIEW.md`

## What to verify:

### HITL-7 (System Prompt Injection):
- `_build_system_prompt()` appends HITL base block when `human_interaction` is in toolset
- `requires_approval=True` skills trigger the approval directive
- `clarification_hints` from multiple skills are merged correctly
- Existing tests pass (no regression)

### HITL-8 (Orchestrator Suspend/Resume — the critical one):
- `handle_message()` always includes `human_interaction` tool, not filtered by allowlist
- `ToolCallEvent` with `tool="human_interaction"` triggers: checkpoint save → state suspend → `InteractionRequiredEvent` yield → stream stop
- `tool_call_id` is correctly captured and stored in checkpoint
- `resume_run()`: loads checkpoint, validates suspended state, reconstructs conversation history, injects `ToolMessage` with correct `tool_call_id`, resumes stream
- Double suspend/resume (agent asks two questions) works correctly
- On completion: run marked completed, checkpoint deleted
- Unknown run_id and non-suspended states yield `ErrorEvent`
- Backward compatible: no HITL tool call → run completes normally

### Tests:
- All 6 integration test cases cover the spec requirements
- MockRuntime (or equivalent) properly simulates HITL tool call events
- Tests are not brittle (don't depend on internals that could change)

Run validation yourself:
```bash
cd /home/ubuntu/deep-agent && source .venv/bin/activate
ruff check src/ tests/ && mypy src/ && pytest tests/ -x -q
```

Write your findings to `docs/tasks/CC-REVIEW-BATCH3-RESULT.md`.
End with **ACCEPT** or **REVISE** as the final line.
