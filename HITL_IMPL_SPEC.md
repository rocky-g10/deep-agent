# HITL Implementation Spec Request

## Context
The HITL (Human-in-the-Loop) framework has been fully spec'd in `docs/PRD.md` §11.4 and referenced in `docs/DEVELOPER_GUIDE.md`. The spec defines 3 interaction patterns:
1. **Clarify** — binary/multiple-choice confirmation from the human
2. **Approve** — human approval gate before proceeding with a risky action
3. **Collect** — structured multi-field input collection (form-like)

Currently this is **docs-only** (commit 595cd89). No runtime code exists in `src/`.

## Your Task
Read the HITL spec in `docs/PRD.md` §11.4 (starts around line 1542) and the relevant developer guide sections, then produce a **detailed implementation plan** broken into discrete, Codex-implementable tasks.

For each task, specify:
- **Task ID** (e.g., HITL-1, HITL-2, ...)
- **Title** — one-line summary
- **Files to create/modify** — exact paths
- **What to build** — specific classes, functions, protocols
- **Dependencies** — which tasks must complete first
- **Acceptance criteria** — what tests/validations prove it works
- **Estimated complexity** (S/M/L)

## Key Design Constraints
1. **Skill authors write zero HITL code** — the LLM invokes `HumanInteraction` tool naturally based on prompt guidance
2. Must integrate with the existing `RuntimeAdapter` protocol (`src/deep_agent/runtime/protocol.py`)
3. Must work with the existing event streaming model (`src/deep_agent/models/events.py`)
4. HITL interactions must be audit-logged (PRD §11.4.10)
5. Must support both WebSocket (real-time) and REST (polling) delivery via the API layer (`src/deep_agent/api/`)
6. Multi-skill composition must handle HITL correctly (PRD §11.4.8)

## Existing Architecture
- **Models:** `src/deep_agent/models/` — events.py, context.py, skills.py, etc.
- **Runtime:** `src/deep_agent/runtime/` — protocol.py, langgraph_adapter.py, llm_router.py
- **Orchestrator:** `src/deep_agent/orchestrator/agent_orchestrator.py`
- **API:** `src/deep_agent/api/` — app.py, ws_chat.py, schemas.py, session.py
- **Tools:** `src/deep_agent/tools/` — execute_code.py
- **Tests:** `tests/` directory

## Output
Write the implementation plan to `docs/tasks/HITL-TASKS.md`. Make the tasks granular enough for Codex to implement one at a time (one concern per task). Order them by dependency so they can be executed sequentially.

Do NOT implement anything — spec only.
