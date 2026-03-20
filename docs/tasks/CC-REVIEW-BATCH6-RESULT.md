# CC Review — HITL Batch 6 (HITL-14, HITL-15) — FINAL BATCH

**Reviewer:** Claude Code (Opus 4.6)
**Date:** 2026-03-20

---

## Validation Results

```
ruff check src/ tests/  -> All checks passed!
mypy src/               -> Success: no issues found in 39 source files
pytest tests/ -q --tb=short -> 217 passed, 9 skipped in 3.61s
```

Full regression suite green. No test failures.

---

## HITL-14: CLI Interactive Mode

### `scripts/invoke_agent.py`

#### `--interactive` Flag

```python
parser.add_argument(
    "--interactive",
    action="store_true",
    default=False,
    help="Enable interactive HITL prompts for interaction_required events",
)
```

Correctly added. Defaults to non-interactive (backward compatible).

#### Resume Loop

```python
current_stream = orchestrator.handle_message(...)
while True:
    interaction_pending = False
    async for event in current_stream:
        if isinstance(event, InteractionRequiredEvent):
            interaction_pending = True
            if not interactive:
                print(event.model_dump_json())
                return
            response = await _prompt_interaction_response(event)
            if response is None:
                print("[hitl] Timed out waiting for user input; exiting.")
                return
            current_stream = orchestrator.resume_run(event.run_id, response)
            break
        _print_event(event, stream=stream)
    if not interaction_pending:
        break
```

Clean pattern:
- On `InteractionRequiredEvent` in non-interactive mode: print JSON and exit. Matches spec.
- On `InteractionRequiredEvent` in interactive mode: prompt user, build response, swap `current_stream` to `resume_run()`, break inner loop to re-enter with resumed stream.
- Supports multiple suspend/resume cycles (outer while loop continues until no more interactions).
- `None` response (timeout or Ctrl-C) exits gracefully.

#### Interaction Prompts

| Kind | Prompt | Response | Status |
|---|---|---|---|
| `clarify` | Prints question + numbered options, reads answer | `InteractionResponse(kind="clarify", value=...)` | OK |
| `approve` | Prints action + risk level, reads y/n | `InteractionResponse(kind="approve", approved=..., reason="")` | OK |
| `collect` | Prompts for each field (with description), builds values dict | `InteractionResponse(kind="collect", values=...)` | OK |

All three spec acceptance criteria met.

#### Timeout Handling

```python
async def _read_line_with_timeout(prompt: str, timeout: int) -> str | None:
    loop = asyncio.get_running_loop()
    print(prompt, end="", flush=True)
    try:
        value = await asyncio.wait_for(
            loop.run_in_executor(None, sys.stdin.readline), timeout=timeout
        )
    except TimeoutError:
        print("\n[hitl] input timed out")
        return None
    return value.rstrip("\n")
```

Uses `asyncio.wait_for` + `run_in_executor` for async-safe blocking stdin read with timeout. On timeout, returns `None` which triggers `_fallback_response`.

#### Fallback Strategy

```python
def _fallback_response(fallback, kind, fields=None) -> InteractionResponse | None:
```

| Fallback | Behavior | Status |
|---|---|---|
| `abort` | Returns `None` → caller exits | OK |
| `default` | Returns response with field defaults or empty strings | OK |
| `skip` | Returns response with `"[skipped]"` values | OK |

Matches spec: "Handle timeout gracefully (if the user doesn't respond within `timeout_seconds`, apply fallback)."

---

## HITL-15: Integration Test Suite Completion

### Test Coverage Matrix

Comparing HITL-TASKS.md §15 spec against implemented tests:

#### Unit Tests

| Spec Requirement | Test File | Status |
|---|---|---|
| Model validation, serialization, state transitions | `test_hitl_models.py` | OK (Batch 1) |
| RunStateManager state machine, concurrent access | `test_hitl_run_state.py` | OK (Batch 2) |
| InMemoryCheckpointStore save/load/delete | `test_hitl_checkpoint.py` | OK (Batch 2) |
| Tool schema matches, direct invocation raises | `test_hitl_tool.py` | OK (Batch 2) |
| System prompt HITL block, requires-approval, hints | `test_hitl_prompt.py` | OK (**NEW**) |

#### `test_hitl_prompt.py` (NEW — 4 tests)

| Test | Verifies |
|---|---|
| `test_prompt_contains_hitl_block_when_tool_present` | `## Human Interaction` and tool reference in prompt |
| `test_prompt_contains_requires_approval_directive` | Approval MUST directive when skill has `requires_approval=True` |
| `test_prompt_contains_merged_clarification_hints` | Hints from 2 skills merged under `Clarification guidance:` |
| `test_prompt_no_hitl_block_when_not_enabled` | No HITL section when `has_human_interaction=False` |

All HITL-7 prompt injection scenarios covered.

#### Integration Tests — Orchestrator

| Spec Requirement | Test | Status |
|---|---|---|
| human_interaction → InteractionRequiredEvent + stream stops | `test_hitl_orchestrator_suspends_on_human_interaction` | OK (Batch 3) |
| resume_run → AgentCompleteEvent | `test_hitl_orchestrator_resume_flow_to_completion` | OK (Batch 3) |
| Double suspend/resume | `test_hitl_orchestrator_double_suspend_resume` | OK (Batch 3) |
| Resume with invalid run_id → error | `test_hitl_orchestrator_resume_unknown_run_id_yields_error` | OK (Batch 3) |
| Resume non-suspended → HITL_NOT_SUSPENDED | `test_hitl_orchestrator_resume_non_suspended_run_yields_error` | OK (**NEW**) |
| Checkpoint deleted after completion | `test_hitl_orchestrator_deletes_checkpoint_after_completion` | OK (**NEW**) |
| Normal flow without HITL (backward compat) | `test_hitl_orchestrator_normal_flow_no_suspension` | OK (Batch 3) |
| System prompt contains HITL block | `test_system_prompt_contains_hitl_block` | OK (Batch 3) |

#### Integration Tests — WebSocket

| Spec Requirement | Test | Status |
|---|---|---|
| WS receives interaction_required event | `test_hitl_ws_suspend_and_resume_flow` | OK (Batch 4) |
| POST respond → resumes events on WS | `test_hitl_ws_suspend_and_resume_flow` | OK (Batch 4) |
| Full lifecycle event order | `test_hitl_ws_suspend_and_resume_flow` (enhanced) | OK (**NEW**) |
| 404 for unknown run_id | `test_hitl_respond_unknown_run_returns_404` | OK (Batch 4) |
| 409 for non-suspended run | `test_hitl_respond_non_suspended_run_returns_409` | OK (Batch 4) |

The lifecycle order verification is well-implemented:
```python
required_order = ["skill_match", "agent_chunk", "interaction_required", "agent_chunk", "agent_complete"]
```
Uses sequential index search to validate ordering while allowing interleaved events. The test app was enhanced with `_write_test_skill()` to create a real skill file so `SkillEngine` emits `skill_match`, and the first stream sequence now includes `AgentChunkEvent` before the suspension to provide the `agent_chunk` before `interaction_required`.

#### Integration Tests — Timeout

| Spec Requirement | Test | Status |
|---|---|---|
| abort → state aborted + checkpoint deleted + multi-skill note | `test_timeout_manager_abort_path_marks_aborted_and_logs_multiskill_note` | OK (Batch 5) |
| skip → resumes with skipped response | `test_timeout_manager_skip_path_resumes_with_skipped_response` | OK (Batch 5) |
| default → resumes with field defaults | `test_timeout_manager_default_path_uses_field_defaults` | OK (**NEW**) |
| Non-expired runs unaffected | `test_timeout_manager_does_not_touch_non_expired_runs` | OK (**NEW**) |
| Start/stop lifecycle | `test_timeout_manager_start_stop_cleanly` | OK (Batch 5) |

### New Tests Address Prior Review Gaps

This batch specifically addressed gaps noted in previous reviews:
- **Batch 3 gap**: "No test for resume on non-suspended run" → `test_hitl_orchestrator_resume_non_suspended_run_yields_error` (**fixed**)
- **Batch 3 gap**: "No verification that checkpoint is deleted after completion" → `test_hitl_orchestrator_deletes_checkpoint_after_completion` (**fixed**)
- **Batch 5 gap**: "No test for `fallback='default'` path" → `test_timeout_manager_default_path_uses_field_defaults` (**fixed**)
- **Batch 5 gap**: "No test for non-expired runs being skipped" → `test_timeout_manager_does_not_touch_non_expired_runs` (**fixed**)

### Remaining Minor Gaps (acceptable)

- No test for concurrent independent HITL sessions on WS (spec mentions "Multiple sessions can have independent HITL flows concurrently")
- No test for WS disconnect during suspension (spec mentions "run remains suspended, can be resumed later or times out")
- Timeout tests call `_check_timeouts()` directly rather than using the background polling loop (more deterministic, but doesn't test the real loop)

These are edge cases that are architecturally sound (per-session queues, task cancellation on disconnect) but not exercised. Acceptable for MVP.

---

## Spec Acceptance Criteria (HITL-15)

| Criterion | Status |
|---|---|
| All unit tests pass | OK (217 passed) |
| All integration tests pass | OK (0 failures) |
| Full lifecycle tested: message → skill match → tool calls → human_interaction → suspend → respond → resume → complete | OK (WS test with event ordering) |
| Timeout lifecycle tested: suspend → timeout → abort (or skip/default) | OK (all 3 fallbacks + non-expired) |
| WebSocket lifecycle tested end-to-end | OK |
| No regressions in existing test suite | OK (9 skipped are pre-existing) |

---

## Overall HITL Implementation Completeness

With this final batch, all 15 HITL tasks are implemented and reviewed:

| Task | Description | Batch | Review |
|---|---|---|---|
| HITL-1 | Core Data Models | 1 | ACCEPT |
| HITL-2 | Event Types | 1 | ACCEPT |
| HITL-3 | Skill Frontmatter | 1 | ACCEPT |
| HITL-4 | Run State Manager | 2 | ACCEPT |
| HITL-5 | Checkpoint Store | 2 | ACCEPT |
| HITL-6 | HumanInteraction Tool | 2 | ACCEPT |
| HITL-7 | System Prompt Injection | 3 | ACCEPT |
| HITL-8 | Orchestrator Suspend/Resume | 3 | ACCEPT |
| HITL-9 | Response REST API | 4 | ACCEPT |
| HITL-10 | WebSocket Integration | 4 | ACCEPT |
| HITL-11 | Timeout Manager | 5 | ACCEPT |
| HITL-12 | Audit Logging | 5 | ACCEPT |
| HITL-13 | Multi-Skill HITL | 5 | ACCEPT |
| HITL-14 | CLI Interactive Mode | 6 | ACCEPT |
| HITL-15 | Integration Tests | 6 | ACCEPT |

### Known Deferrals (from prior reviews, non-blocking)

1. **Timeout abort ErrorEvent to WS** — TimeoutManager doesn't push ErrorEvent to session resume_queue on abort (Batch 5 deferral)
2. **Empty HumanMessage on resume** — `resume_run()` sends `message=""` which creates empty HumanMessage in adapter (Batch 3 observation)
3. **tool_call_id in chunk path** — LangGraphAdapter chunk accumulation doesn't capture tool_call_id (Batch 3 observation)

All are noted for post-MVP follow-up.

**ACCEPT**
