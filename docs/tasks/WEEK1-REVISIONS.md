# Week 1 Code Review: REVISIONS REQUIRED

Claude Code reviewed T1.1-T1.6 and issued **REVISE**. Fix ALL items below.

---

## Bugs / Spec Violations (MUST FIX)

### 1. `src/deep_agent/models/sandbox.py:23` — bytes field breaks JSON serialization
`output_files: dict[str, bytes]` fails Pydantic JSON round-trip. `bytes` values can't serialize via `.model_dump()` / `.model_validate()`.
**Fix:** Change to `dict[str, str]` and use base64 encoding, OR add a custom Pydantic serializer for bytes values.

### 2. `src/deep_agent/skills/engine.py:129-134` — Scoring algorithm mismatch
The spec says: `score(skill, query) = |tags ∩ query_tokens| / |skill.tags|`

Problem: `_score_skill` lowercases tags (`tag.lower()`) but `_tokenize` uses regex `[a-z0-9_]+` which strips hyphens. A tag like `"z-score"` becomes `{"z-score"}` in tag_tokens but `_tokenize("z-scores")` produces `{"z", "scores"}` — they'll never match.

**Fix:** Both tags and query should be tokenized the same way — run both through `_tokenize` (or an equivalent splitting strategy that handles hyphens consistently).

### 3. `src/deep_agent/skills/engine.py:103-111` — Lock held during I/O
`_ensure_cache` holds `self._lock` during the full filesystem scan (`rglob` + file reads). This blocks ALL concurrent callers.

**Fix:** Build the index outside the lock, then swap the reference under the lock:
```python
def _ensure_cache(self) -> None:
    if not self._needs_refresh():
        return
    # Build outside lock
    new_index = self._scan_filesystem()
    # Swap under lock
    with self._lock:
        self._skills = new_index
        self._last_scan = time.monotonic()
```

### 4. `pyproject.toml:12` — Empty dependencies list
`dependencies = []` means `pip install deep-agent` installs a broken package (no runtime deps). Dependencies are only in `requirements.txt`.

**Fix:** Mirror runtime dependencies in `[project].dependencies` in pyproject.toml. Dev deps stay in requirements-dev.txt only.

## Missing Test Coverage (MUST FIX)

### 5. No unit tests for models or config
Zero tests exist for: `AppSettings`, `LLMConfig`, `ResourceLimits`, `ExecuteResult`, `AgentEvent` discriminated union deserialization, `DatabaseAlias`, `TenantContext.stub()`, or `ConnectionConfig`.

**Fix:** Create `tests/unit/test_models.py` with tests for:
- All Pydantic models instantiate and round-trip JSON (`.model_dump()` → `.model_validate()`)
- `TenantContext.stub()` returns correct equities context
- `AgentEvent` discriminated union deserializes each event type correctly
- `ExecuteResult` with output_files serializes correctly (after fix #1)
- `AppSettings` loads with defaults

### 6. Missing test for frontmatter delimiter edge case
`test_malformed_frontmatter_raises_skill_parse_error` tests broken YAML, not a file with NO `---` delimiters at all.

**Fix:** Add a test case with a plain markdown file (no frontmatter delimiters) and verify it raises `SkillParseError`.

## Minor (Fix if easy, otherwise note for later)

### 7. Sort tiebreaker is reverse alphabetical
`sorted(..., key=lambda: (score, skill_id), reverse=True)` breaks ties by skill_id in reverse alpha order. Consider lexicographic ascending for consistency.

### 8. Dead code: `SkillParser` Protocol
`src/deep_agent/skills/parser.py:28-31` — `SkillParser` Protocol is defined but never used. Remove it or use it.

---

## Validation

After all fixes:
```bash
source .venv/bin/activate
ruff check src/ tests/
mypy src/
pytest tests/unit/ -v
```

All must pass. Ensure the new model tests and the frontmatter delimiter test are included.
