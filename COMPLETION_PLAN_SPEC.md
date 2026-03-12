# deep-agent Phase 1 Completion — Design & Plan

## Context
The full project audit (docs/full-project-audit.md) identified what's done and what's missing.
We need to COMPLETE Phase 1 per the PRD (docs/PRD.md) and Implementation Plan (docs/implementation-plan.md).

## Your Task
Design a comprehensive, detailed implementation plan to complete ALL remaining Phase 1 work.
This is a DESIGN task — you are NOT implementing. Write the spec so that Codex can implement it without ambiguity.

## What Needs to Be Done (from audit)

### Priority 1: WebSocket Chat API (T4.1)
Design the complete API layer:
- `src/deep_agent/api/app.py` — FastAPI app with health endpoint, CORS, lifespan
- `src/deep_agent/api/ws_chat.py` — WebSocket handler for `/ws/chat`
- `src/deep_agent/api/schemas.py` — Request/response Pydantic models
- `src/deep_agent/api/session.py` — In-memory session management (dict-based for Phase 1)
- Streaming event protocol (the event models exist in models/ — wire them to WS)
- Authentication placeholder (API key header for Phase 1)

### Priority 2: Parse `inputs` and `quality` Fields (C4)
- Add `inputs` and `quality` to `SkillContent` model
- Update parser to extract them from YAML frontmatter
- Wire `quality.timeout` to sandbox execution
- Include `inputs` schema in system prompt

### Priority 3: Fix `db-query` Skill (C3)
- Add `scripts/requirements.txt` with `clickhouse-connect`
- Or redesign for generic DB access if appropriate per PRD

### Priority 4: Config Tests
- Test `AppSettings` defaults, env overrides, missing fields
- Test `get_settings()` caching behavior

### Priority 5: WebSocket Integration Tests (T4.3)
- Test WS connect/disconnect
- Test message flow (send query → receive streaming events → final response)
- Test session management
- Test error handling (invalid message, unauthorized)

### Priority 6: E2E Test (T4.4)
- Full Z-Score query via WebSocket
- Verify response contains expected data
- Run against SQLite example DB (not ClickHouse)

### Priority 7: Dev Run Script (T4.5)
- `scripts/run_dev.py` — starts API server with example config
- Seeds DB, starts MCP test server if needed
- README update with quickstart

### Priority 8: Minor Fixes
- Fix f-string lint issue (M1)
- Deduplicate firm_stats.py (M4)
- Move TenantContext.stub() to examples/ (I1)
- Add config.py tests

## Output Requirements

Write to `docs/COMPLETION_SPEC.md` with:

### For EACH task:
1. **Exact file paths** to create/modify
2. **Module structure** — classes, functions, imports
3. **Interface contracts** — function signatures with type hints, Pydantic model schemas
4. **Behavior spec** — what each function does, edge cases, error handling
5. **Test specifications** — what to test, expected assertions
6. **Dependencies** — what must be done before this task

### Architecture Decisions to Make:
- WebSocket message format (align with existing event models in `models/events.py`)
- Session lifecycle (connect → authenticate → query → stream → disconnect)
- How the API wires to AgentOrchestrator
- Error handling strategy (WebSocket error frames vs event-based errors)
- Graceful shutdown (in-flight requests)

### Ordering:
- Provide a clear implementation order (tasks with dependencies listed)
- Each task should be independently testable after completion
- Break large tasks into sub-tasks if needed

## Constraints
- Must align with PRD §4.5 and §10
- Must work with the existing architecture (no redesign of core)
- Phase 1 only — don't design Phase 2/3 features
- Must be implementable by Codex with zero ambiguity
- Include exact Pydantic model definitions, not just descriptions
- Use existing patterns from the codebase (check how other modules are structured)

## Use AskUserQuestion for:
- Any PRD ambiguity about WebSocket protocol details
- Any design tradeoffs where you need Rio's input
- Anything where two reasonable approaches exist and context is needed to choose
