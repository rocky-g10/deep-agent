# HITL Implementation — Batch 1 (HITL-1, HITL-2, HITL-3)

Implement the first three HITL tasks from `docs/tasks/HITL-TASKS.md`. These are the
foundation layer — data models, event types, and skill frontmatter. All are S complexity.

**Read the full task specs in `docs/tasks/HITL-TASKS.md` before starting.**

---

## HITL-1: Core Data Models

**Create** `src/deep_agent/models/hitl.py` with these Pydantic models:
- `FieldSpec` — one field in a structured input collection form
- `HumanInteractionRequest` — payload the LLM produces when calling the tool (kind: clarify/approve/collect; timeout_seconds=300; fallback=abort/default/skip)
- `InteractionResponse` — user's response to a request
- `RunState` (StrEnum) — running/suspended/timed_out/aborted/completed/failed
- `RunInfo` — tracks lifecycle of a single agent run

**Modify** `src/deep_agent/models/__init__.py` — re-export all new types.

**Create** `tests/unit/test_hitl_models.py`:
- All models round-trip through .model_dump() / .model_validate()
- HumanInteractionRequest validates that `question` set for clarify, `action_description` for approve, `fields` for collect
- RunState transitions tested

---

## HITL-2: Event Types

**Modify** `src/deep_agent/models/events.py`:
- Add `InteractionRequiredEvent` (type="interaction_required", run_id, skill_id, interaction: HumanInteractionRequest)
- Add `InteractionResponseEvent` (type="interaction_response", run_id, response: InteractionResponse)
- Add both to the `AgentEvent` discriminated union

Ensure backward compatibility — existing tests must still pass.

---

## HITL-3: Skill Frontmatter

**Modify** `src/deep_agent/models/skills.py`:
- Add `requires_approval: bool = False` to `SkillContent`
- Add `clarification_hints: dict[str, str] = {}` to `SkillContent`
- Add `hitl_timeout: int = 300` and `hitl_fallback: Literal["abort","default","skip"] = "abort"` to `SkillQuality` (using aliases `hitl-timeout`, `hitl-fallback`)

**Modify** `src/deep_agent/skills/parser.py`:
- Parse `requires-approval`, `clarification-hints`, `quality.hitl-timeout`, `quality.hitl-fallback` from frontmatter
- All fields optional with defaults (backward compatible)

---

## Validation (run after all three tasks)

```bash
cd /home/ubuntu/deep-agent && source .venv/bin/activate
ruff check src/ tests/
mypy src/
pytest tests/ -x -q
```

All must pass with 0 errors. Do NOT proceed if any check fails — fix errors first.

## Output

When done, write a summary to `docs/tasks/HITL-BATCH1-REVIEW.md`:
- List all files created/modified
- Confirm ruff, mypy, pytest results
- Note any design decisions or deviations from spec
- Give READY_FOR_REVIEW as the final line
