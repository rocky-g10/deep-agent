# Full Project Audit — deep-agent

## Context
We just completed a major codebase refactor (resource-agnostic architecture). Codex caught issues that should have been caught earlier. Rio wants a thorough end-to-end review of the ENTIRE project.

## Your Task
Do a comprehensive audit of the entire deep-agent codebase against our PRD and design decisions. This is a READ-ONLY analysis — no code changes.

## What to Review

### 1. PRD Alignment
- Read `docs/PRD.md` thoroughly
- Compare every PRD requirement against actual implementation
- Flag any PRD features that are missing, incomplete, or diverge from spec
- Flag any implemented features NOT in the PRD (scope creep)

### 2. Architecture & Design
- Read `docs/implementation-plan.md` and any architecture docs
- Verify the implementation matches our design decisions
- Check module boundaries, dependency flow, separation of concerns
- Verify the resource-agnostic refactor is truly complete (no remaining hardcoded equity/finance references in core)

### 3. Skill System Integrity
- For EVERY skill in `skills/` (recursively):
  - Does it have the files it references (scripts/, templates, etc.)?
  - Do its SKILL.md instructions actually work with the current codebase?
  - Are tool references valid (no references to removed tools)?
  - Does the sandbox execution path work (PYTHONPATH, imports, etc.)?
- List any broken/orphaned skills

### 4. Test Coverage
- Are all core modules tested?
- Are there any obvious gaps (untested functions, untested error paths)?
- Do the tests actually test meaningful behavior or just mock everything?
- Are integration/e2e paths covered or only unit tests?

### 5. Code Quality
- Dead code, unused imports, stale TODOs
- Error handling gaps (bare excepts, swallowed errors)
- Type hints consistency
- Config/model validation completeness

### 6. Runtime Correctness
- Run the example (`examples/run_example.py`) and verify output makes sense
- Run `pytest tests/` and report results
- Check for any obvious runtime issues (missing env vars, hardcoded paths, etc.)

## Output
Write your findings to `docs/full-project-audit.md` with:
- **Summary** (1 paragraph overall assessment)
- **Critical Issues** (would break at runtime)
- **Important Issues** (design/correctness concerns)
- **Minor Issues** (cleanup, style, nice-to-haves)
- **PRD Gap Analysis** (table: PRD requirement → status → notes)
- **Recommendation** (what to prioritize next)

Use AskUserQuestion if you need clarification on any design intent or PRD interpretation.
