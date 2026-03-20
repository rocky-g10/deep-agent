# HITL Implementation — Batch 6 (HITL-14, HITL-15)

Final batch. Implement HITL-14 and HITL-15 from `docs/tasks/HITL-TASKS.md`.
Batches 1–5 (HITL-1 through HITL-13) are complete and committed.

**Read `docs/tasks/HITL-TASKS.md` for full task specs.**
Also read:
- `scripts/invoke_agent.py` (add --interactive flag here)
- `src/deep_agent/orchestrator/agent_orchestrator.py` (resume_run available)
- `src/deep_agent/models/hitl.py` (HumanInteractionRequest, InteractionResponse, FieldSpec)
- All existing tests in `tests/` for reference

---

## HITL-14: CLI Interactive Mode (M complexity)

**Modify** `scripts/invoke_agent.py`:

Add `--interactive` flag. When set and `InteractionRequiredEvent` is received:

- **clarify**: print `❓ {question}` + options if any, read line from stdin → `InteractionResponse(kind="clarify", value=input)`
- **approve**: print `⚠️ Action: {action_description}` + risk level, prompt `Approve? (y/n):` → `InteractionResponse(kind="approve", approved=answer=="y")`
- **collect**: for each FieldSpec, print `{name} ({description}):`, read input → `InteractionResponse(kind="collect", values={name: input})`

Then call `orchestrator.resume_run(run_id, response)` and continue streaming.

Without `--interactive`: print `InteractionRequiredEvent` as JSON and exit (existing behavior for unhandled events).

Include a basic timeout: if user doesn't respond within `interaction.timeout_seconds`, apply the fallback strategy (print a message and move on).

---

## HITL-15: Integration Test Suite (L complexity)

This is the final validation gate. Create comprehensive integration tests.

**Create/update these test files per HITL-TASKS.md spec:**

`tests/unit/test_hitl_prompt.py`:
- System prompt contains `## Human Interaction` base block when tool present
- `requires-approval` directive appears when skill has `requires_approval=True`
- Clarification hints from skills appear in prompt
- No HITL block when no HITL-enabled skills

`tests/integration/test_hitl_orchestrator.py` — extend existing (if not already covered):
- Resume on non-suspended run yields ErrorEvent
- Checkpoint deleted after run completes

`tests/integration/test_hitl_ws.py` — extend if gaps:
- Full lifecycle: `skill_match → agent_chunk → interaction_required → respond → agent_chunk → agent_complete`

`tests/integration/test_hitl_timeout.py` — extend if gaps:
- `fallback="default"` resumes with field defaults
- Non-expired runs not affected by timeout sweep

After all tests pass, also run the **full existing test suite** to confirm zero regressions:
```bash
pytest tests/ -q --tb=short
```

---

## Validation

```bash
cd /home/ubuntu/deep-agent && source .venv/bin/activate
ruff check src/ tests/
mypy src/
pytest tests/ -x -q
```

All must pass with 0 failures. Write summary to `docs/tasks/HITL-BATCH6-REVIEW.md`, end with `READY_FOR_REVIEW`.
