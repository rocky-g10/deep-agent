# CC Review — HITL Batch 3 (HITL-7, HITL-8)

**Reviewer:** Claude Code (Opus 4.6)
**Date:** 2026-03-20

---

## Validation Results

```
ruff check src/ tests/  -> All checks passed!
mypy src/               -> Success: no issues found in 36 source files
pytest tests/ -x -q     -> All tests pass (0 failures, 9 skipped from unrelated tests)
```

---

## HITL-7: System Prompt Injection

### Spec Compliance

| Requirement | Status | Notes |
|---|---|---|
| Base HITL block when `human_interaction` tool present | OK | `has_human_interaction=True` always passed; `## Human Interaction` section appended |
| `requires_approval` directive when skill flag set | OK | Conditional on `any(skill.requires_approval for skill in active_skills)` |
| `clarification_hints` merged from all active skills | OK | Iterates `.values()` from all active skills, deduplicates by merge |
| System prompt unchanged when no HITL skills active | OK | Approval/hint sections only appear when skills have those fields |
| Existing tests pass (no regression) | OK | Full suite green |

### Code Quality

`_build_system_prompt()` (lines 385-460) is cleanly structured:
- Base HITL block: always when `has_human_interaction=True`
- Approval directive: conditional on skill flag
- Clarification hints: conditional on non-empty hints

**Minor note:** Hints use `skill.clarification_hints.values()` only, discarding the dict keys. If the keys are meaningful conditions (e.g., `"portfolio"`, `"time_period"`), they're lost. Acceptable if values contain the full hint text (which appears to be the intended format based on the SkillContent model).

---

## HITL-8: Orchestrator Suspend/Resume

### Spec Compliance

| Requirement | Status | Notes |
|---|---|---|
| `handle_message()` includes `human_interaction` tool | OK | Line 124: appended AFTER allowlist filtering — never filtered out |
| `human_interaction` ToolCallEvent triggers suspend flow | OK | Lines 142-176: detect → checkpoint save → state suspend → yield InteractionRequiredEvent → return |
| `tool_call_id` captured in checkpoint | OK | Line 148/155: extracted from event, stored in checkpoint |
| `resume_run()` loads checkpoint, validates state | OK | Lines 202-218: load checkpoint, check existence, check suspended state |
| `resume_run()` reconstructs history + injects ToolMessage | OK | Lines 279-285: deserialize history, append ToolMessage with response and tool_call_id |
| `resume_run()` resumes stream | OK | Lines 286-309: streams from runtime, handles re-suspension or completion |
| Double suspend/resume works | OK | Lines 287-304: resume path detects re-suspension and re-checkpoints |
| On completion: run completed, checkpoint deleted | OK | Lines 306-308: state marked completed, checkpoint deleted |
| Unknown run_id yields ErrorEvent | OK | Lines 203-205, 208-210 |
| Non-suspended state yields ErrorEvent | OK | Lines 211-213 |
| Backward compatible | OK | When no `human_interaction` call occurs, run completes normally |
| Constructor accepts optional HITL deps | OK | Lines 55-56: `RunStateManager | None`, `CheckpointStore | None`; defaults wired on 65-66 |

### Checkpoint Model Changes

Three fields added to `Checkpoint` for resume reconstruction:
- `tenant_context: dict[str, Any]` — serialized TenantContext
- `skill_bindings: dict[str, Any]` — serialized AgentSkillBindings
- `original_message: str` — for re-matching skills on resume

All have defaults (`Field(default_factory=dict)` / `""`) so existing code and Batch 2 tests are unaffected. Good backward compatibility.

### ToolCallEvent Change

`tool_call_id: str | None = None` added to `ToolCallEvent` — backward compatible, defaults to None.

### LangGraphAdapter Change

Line 128: `tool_call_id=str(tool_id) if isinstance(tool_id, str) else None` — correctly propagates the ID from completed tool calls.

### Design Observations (non-blocking)

1. **Empty HumanMessage on resume:** `resume_run()` calls `self._runtime.stream(agent, "", context, history=history)`. The `LangGraphAdapter.stream()` always appends `HumanMessage(content=message)` — resulting in an empty `HumanMessage("")` after the `ToolMessage`. In a real LangGraph react agent, the expected flow after a tool result is AI continuation, not another user message. This won't cause issues with MockRuntime, but may produce unexpected LLM behavior in production. Consider either: (a) having the adapter skip empty messages, or (b) having `resume_run()` pass a sentinel that the adapter recognizes.

2. **tool_call_id lost in chunk accumulation path:** The LangGraphAdapter accumulates tool call chunks (lines 131-147) and emits them as `ToolCallEvent` when a `ToolMessage` arrives, but the chunk path doesn't capture `tool_call_id`. If `human_interaction` arrives as chunks rather than a completed tool call, the ID would be None. In practice, completed tool calls (lines 120-129) are the primary path and do capture the ID. Low risk but worth noting.

3. **`Checkpoint.from_messages()` not updated:** The classmethod doesn't accept `tenant_context`, `skill_bindings`, or `original_message`. The orchestrator constructs Checkpoints directly (not via `from_messages`), so this is internally consistent. But the helper is now incomplete relative to the model.

4. **Skill re-matching on resume:** `resume_run()` re-runs `skill_engine.match()` with the original message. If matching is non-deterministic or skill definitions changed between suspend and resume, results could differ. Acceptable for MVP in-memory flows where suspend/resume is fast.

---

## Tests

### Coverage

| Test | What it verifies | Status |
|---|---|---|
| `test_hitl_orchestrator_normal_flow_no_suspension` | Backward compat — no HITL → completes normally | OK |
| `test_hitl_orchestrator_suspends_on_human_interaction` | ToolCallEvent → InteractionRequiredEvent, run state suspended | OK |
| `test_hitl_orchestrator_resume_flow_to_completion` | Suspend → resume → AgentCompleteEvent, run state completed | OK |
| `test_hitl_orchestrator_double_suspend_resume` | Two suspend/resume cycles, same run_id preserved | OK |
| `test_hitl_orchestrator_resume_unknown_run_id_yields_error` | Unknown run_id → ErrorEvent | OK |
| `test_system_prompt_contains_hitl_block` | System prompt includes `## Human Interaction` section | OK |

### MockRuntime Quality

Well-designed: supports multiple stream sequences for multi-turn testing, captures `last_system_prompt` for verification, implements the RuntimeAdapter interface correctly.

### Minor Test Gaps

- No test for resume on a non-suspended (but existing) run — code handles this (line 211-213) but it's not exercised. Low risk.
- No verification that checkpoint is deleted after completion in resume path. Internal concern.
- No test with active skills having `requires_approval` or `clarification_hints` to verify those prompt paths. HITL-7 prompt injection is only tested via the base block.

These gaps are acceptable for an integration test file. Unit-level prompt tests are deferred to `test_hitl_prompt.py` per HITL-15.

---

## Summary

Implementation is correct and matches both HITL-7 and HITL-8 specs. The orchestrator properly:
- Injects HITL directives into the system prompt
- Detects `human_interaction` tool calls and suspends with checkpointing
- Resumes with ToolMessage injection and correct tool_call_id correlation
- Handles double suspend/resume cycles
- Provides clean error handling for unknown/invalid runs
- Maintains backward compatibility

The design observations noted above are non-blocking concerns for MVP — the empty-message-on-resume issue (#1) should be addressed before production use with a real LLM backend.

**ACCEPT**
