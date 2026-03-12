# Codebase Refactoring Audit

## Objective
Audit the entire codebase against the updated PRD (docs/PRD.md) and task files (docs/tasks/). Produce a precise, actionable refactoring plan.

## What I Need From You

### 1. File-by-File Audit
For EVERY file under `src/deep_agent/`, determine:
- **KEEP** — file aligns with the updated PRD, no changes needed
- **MODIFY** — file needs specific changes (list them)
- **MOVE** — file should relocate (e.g., core → examples/) with exact source → destination paths
- **DELETE** — file is dead/stale and serves no purpose under the new architecture

### 2. New Files Needed
List any new modules that need to be created per the updated PRD that don't exist yet:
- Agent Skill Bindings config loader
- Generic resource env-var injection (replacing DatabaseRegistry)
- Anything else the PRD specifies that's missing

### 3. Test Impact
For every file change above, list which test files need updating:
- Tests that reference moved/deleted modules
- Tests that need new assertions for the refactored behavior
- Tests that should be moved to examples/ alongside example code

### 4. Example Skills Directory
Specify the exact structure for `examples/` where example-specific code (DatabaseRegistry, query_database tool, firm.stats, docker-compose, etc.) should live.

### 5. Dependency Changes
- What to remove from `requirements.txt` (e.g., `clickhouse-connect` if it's no longer core)
- What to add (if anything)
- Changes to the sandbox base image spec

## Rules
- **Zero feature regression** — every capability must be preserved, just reorganized
- **Simplicity** — the framework core should be as lean as possible
- **Readability** — a new developer should understand the codebase structure in 5 minutes
- **No guessing** — read every file before classifying it. Use `cat` or `Read` to inspect contents.
- **Use AskUserQuestion for any ambiguity** — if you're unsure whether something is core vs example, ASK.

## Output Format
Write the complete refactoring plan to `docs/REFACTOR_PLAN.md` with:
1. Summary table (file → action → reason)
2. Detailed changes per file
3. New files to create
4. Test migration plan
5. examples/ directory structure
6. Dependency changes
7. Execution order (what to do first, what depends on what)

## Important
This is PLAN ONLY — do NOT make any code changes. Just produce the plan document.
