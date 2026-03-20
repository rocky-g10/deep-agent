# HITL Batch 1 — REVISE

Claude Code reviewed your Batch 1 implementation and found the following issues.
Fix all MUST FIX and SHOULD FIX items, then re-run validation.

---

## #1 — MUST FIX: clarification-hints parser rejects list-of-dicts YAML format

The PRD (§11.4.7 line 1809) and Dev Guide (§11.2 line 674) show `clarification-hints`
as a list-of-dicts format in YAML. Skill authors following the docs will get
`SkillParseError` with the current implementation.

**Fix:** Update `_validate_string_map` (or equivalent) in `src/deep_agent/skills/parser.py`
to accept BOTH formats:
- Dict format: `clarification-hints: {key: value, ...}`
- List-of-dicts format: `clarification-hints: [{key: value}, ...]`

Merge list-of-dicts into a flat dict. Add a parser test for both formats.

---

## #2 — SHOULD FIX: InteractionResponse has no kind-specific validation

`kind="approve"` without `approved` field passes silently, pushing defensive
checks to HITL-8/9 consumers.

**Fix:** Add a `model_validator` to `InteractionResponse` (in `src/deep_agent/models/hitl.py`)
mirroring the existing `HumanInteractionRequest` validation:
- `kind="clarify"` → `value` must be set
- `kind="approve"` → `approved` must be set
- `kind="collect"` → `values` must be set

Add tests for each invalid case to `tests/unit/test_hitl_models.py`.

---

## #3 — SHOULD FIX: Only 1 of 24 invalid state transitions is tested

The `RunState` test suite only covers one invalid transition. Terminal states
and illegal shortcuts need coverage.

**Fix:** Add a parametrized negative test in `tests/unit/test_hitl_models.py` covering:
- All terminal states (`completed`, `failed`, `aborted`) cannot transition to anything
- Illegal shortcuts (e.g., `running→aborted`, `suspended→completed`, `timed_out→running` without fallback)
- At minimum cover 8–10 invalid transitions

---

## Validation (after fixes)

```bash
cd /home/ubuntu/deep-agent && source .venv/bin/activate
ruff check src/ tests/
mypy src/
pytest tests/ -x -q
```

All must pass. Then update `docs/tasks/HITL-BATCH1-REVIEW.md` with the fixes applied
and end with `READY_FOR_REVIEW` on the final line.
