# CC Review Request — HITL Batch 6 (HITL-14, HITL-15) — FINAL BATCH

Review Codex's final HITL batch. Full summary in `docs/tasks/HITL-BATCH6-REVIEW.md`.

This is the last review before HITL is complete. Be thorough.

Key files to examine:
- `scripts/invoke_agent.py` (--interactive flag, HITL-14)
- `tests/unit/test_hitl_prompt.py` (new)
- `tests/integration/test_hitl_orchestrator.py` (extended)
- `tests/integration/test_hitl_ws.py` (extended)
- `tests/integration/test_hitl_timeout.py` (extended)

Review for:
1. HITL-14: CLI interactive mode — clarify/approve/collect prompts correct, timeout handling present, non-interactive fallback (print JSON + exit) unchanged
2. HITL-15: Test coverage completeness vs HITL-TASKS.md §15 spec — especially the full lifecycle test and the deferred items from previous reviews
3. Overall regression check — does the full suite still pass?

Run validation:
```bash
cd /home/ubuntu/deep-agent && source .venv/bin/activate
ruff check src/ tests/ && mypy src/ && pytest tests/ -q --tb=short
```

Write verdict to `docs/tasks/CC-REVIEW-BATCH6-RESULT.md` with ACCEPT or REVISE at the end.
