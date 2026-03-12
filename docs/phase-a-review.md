# Phase A Review — ACCEPT

> **Reviewer:** Claude (Opus 4.6)
> **Date:** 2026-03-12
> **Commit:** 3a69ee7
> **Test results:** 98 passed, 9 skipped (integration tests gated on `RUN_MCP_INTEGRATION=1`)
> **Linting:** ruff — all checks passed, mypy — clean

---

## Verdict: ACCEPT

All four Phase A tasks (A1–A4) are implemented correctly and match the COMPLETION_SPEC.md design. Tests are comprehensive, no regressions, clean linting.

---

## Task-by-Task Assessment

### A1: SkillInput + SkillQuality Models — PASS

| Spec Requirement | Status | Notes |
|---|---|---|
| `SkillInput` model with name/type/description/required | Done | Exact match to spec |
| `SkillQuality` model with timeout/max-retries/validation | Done | Alias `max-retries` works via `populate_by_name=True` |
| `SkillContent` gains `scripts_path`, `inputs`, `quality` fields | Done | Fields added with correct defaults |
| `__init__.py` re-exports `SkillInput`, `SkillQuality` | Done | Added to imports and `__all__` |
| Parser extracts `inputs` from frontmatter | Done | Handles missing, malformed, and valid entries |
| Parser extracts `quality` from frontmatter | Done | Handles alias (`max-retries`) and missing fields |
| Parser auto-discovers `scripts/` directory | Done | `scripts_path` populated when `scripts/` exists |
| Tests: `test_parse_skill_with_inputs_and_quality` | Done | Full assertion coverage |
| Tests: `test_parse_skill_without_inputs_quality_uses_defaults` | Done | |
| Tests: `test_parse_reference_skills_have_inputs_and_quality` | Done | Adapted from spec (removed nonexistent `accuracy` field reference) |
| Tests: `test_skill_input_defaults`, `test_skill_quality_defaults`, `test_skill_quality_alias` | Done | |

**Minor spec deviation (acceptable):** The spec's `test_parse_reference_skills_have_inputs_and_quality` asserted `skill.quality.accuracy is not None or skill.quality.timeout == 60`. Since `SkillQuality` has no `accuracy` field, Codex correctly simplified to `skill.quality.timeout == 60`. This is the right call.

### A2: Fix db-query Skill — PASS

| Spec Requirement | Status | Notes |
|---|---|---|
| Create `skills/common/db-query/scripts/requirements.txt` | Done | Contains `clickhouse-connect>=0.7` |
| Remove `query_database` from `allowed-tools` | Done | Only `execute_code` remains |
| Update instructions to use env vars | Done | Steps rewritten for resource-agnostic flow |

**Beyond spec (good):** Codex also removed `query_database` from `zscore-monitor/SKILL.md` allowed-tools and updated its instructions. This was the right call — the tool doesn't exist in core anymore.

### A3: Config Unit Tests — PASS

| Spec Requirement | Status | Notes |
|---|---|---|
| Create `tests/unit/test_config.py` | Done | 4 tests |
| Test `AppSettings` defaults | Done | |
| Test env var overrides | Done | |
| Test `SecretStr` behavior | Done | |
| Test `EnvironmentSettingsProvider.load()` | Done | |

Exact match to spec. No `get_settings()` caching test (intentionally excluded per spec note).

### A4: Minor Fixes — PASS

| Spec Requirement | Status | Notes |
|---|---|---|
| A4.1: Fix f-string lint in `mcp/config.py` | Done | `f"..."` → `"..."` on line 53 |
| A4.2: Dedup `firm_stats.py` | Done | Canonical copy at `skills/equities/zscore-monitor/scripts/firm_stats.py`; example copy deleted; `test_firm_stats.py` path updated |
| A4.3: Rename `TenantContext.stub()` → `.default()` | Done | Returns `tenant_id="default"`, `user_id="anonymous"`, empty resource_env |
| A4.3: Update all `.stub()` references | Done | Zero remaining `grep -r "\.stub()"` hits |
| A4.4: Remove `clickhouse-connect` from `pyproject.toml` | Done | |
| A4.4: Remove from `requirements.txt` | Done | No `clickhouse` references in core deps |

---

## Additional Work (Beyond Spec — All Good)

Codex made several additional improvements that were raised in the prior code review but not explicitly in the Phase A spec:

1. **`skill_bindings` is now required** in `handle_message()` (was optional with silent fallback). Good — prevents silent "no skills matched" bugs.
2. **`_build_resource_env()` rewritten** for multi-alias safety: prefixed keys always emitted, unprefixed only for single-alias tenants, collision warning for multi-alias. Addresses the audit's resource env collision concern.
3. **`PYTHONPATH` injection pipeline**: `parser.py` resolves `scripts_path` → `orchestrator` passes to `create_execute_code_tool` → tool sets `PYTHONPATH` → sandbox allowlists `PYTHONPATH` via `_SANDBOX_ENV_OVERRIDE_EXACT`. End-to-end working.
4. **`load_mcp_config()` now honors `mcp_config_path`** with path traversal protection. Resolves the audit finding about the field being modeled but unused.
5. **MCP config path traversal test coverage** expanded: 3 new tests (custom path, fallback to tenant_id, traversal via mcp_config_path).

---

## Observations (Non-blocking)

1. **`query_database` still referenced in test fixtures**: `test_skill_parser.py`, `test_orchestrator.py`, and `test_skill_engine.py` use `query_database` in test SKILL.md fixtures and mock tool names. This is fine — these are isolated test data, not production code, and the tests pass. No action needed.

2. **`db-query` quality block has `accuracy` field**: `skills/common/db-query/SKILL.md` line 17 has `accuracy: "Validated against ClickHouse SQL syntax"`. This is silently ignored by the parser (filtered out by the `if k in SkillQuality.model_fields` check), which is the correct behavior per spec. If a future `accuracy` field is added to `SkillQuality`, it will be picked up automatically.

3. **Three new docs added**: `docs/code-review-refactor.md`, `docs/codex-final-verdict.md`, `docs/codex-final-verdict-r2.md` document the Codex review/fix cycle. Consider cleaning these up before Phase B — they served their purpose.

---

## Verification Checklist

- [x] 98 tests pass, 9 skipped
- [x] `ruff check src/ tests/` — all checks passed
- [x] `mypy src/deep_agent` — clean
- [x] Zero `.stub()` references remain
- [x] Zero `clickhouse` in core deps
- [x] `firm_stats.py` canonical copy exists, example duplicate deleted
- [x] `db-query/scripts/requirements.txt` exists
- [x] `SkillInput` and `SkillQuality` models match spec exactly
- [x] Parser handles missing/malformed inputs gracefully
- [x] PYTHONPATH injection works end-to-end (sandbox test confirms import)
- [x] `TenantContext.default()` returns neutral values
