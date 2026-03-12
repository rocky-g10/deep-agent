# Week 1 Batch 2: T1.4 + T1.5 + T1.6

> **Reference:** `docs/IMPLEMENTATION_PLAN.md` — read Weeks 1 sections for T1.4, T1.5, T1.6.
> **Depends on:** T1.1–T1.3 (already implemented — scaffolding, models, parser all in place)
> **Scope:** SkillEngine, reference SKILL.md files, unit tests for the skills layer.

---

## T1.4 — SkillEngine

Implement `src/deep_agent/skills/engine.py` — the core skill management class.

### Interface

```python
class SkillEngine:
    def __init__(self, skills_root: Path, cache_ttl: int = 300) -> None:
        """Initialize with skills directory and cache TTL in seconds."""

    def discover(self, tenant: TenantContext, skill_bindings: list[str] | None = None) -> list[SkillSummary]:
        """Return SkillSummary objects for all indexed skills, optionally filtered by agent skill bindings.
        When skill_bindings is provided, only skills whose skill_id is in the bindings are returned."""

    def match(self, query: str, tenant: TenantContext, top_k: int = 5, skill_bindings: list[str] | None = None) -> list[SkillSummary]:
        """Return skills ranked by tag overlap with query tokens, scoped to agent skill bindings."""

    def load(self, skill_id: str, tenant: TenantContext) -> SkillContent:
        """Return full SkillContent including body.
        Raises SkillNotFoundError if skill doesn't exist or tenant lacks access."""
```

### Requirements

1. **Discovery:** Scans filesystem for `SKILL.md` files on first call. Indexes them by skill_id.
2. **Scoped discovery:** `discover()` returns all indexed skills by default. When `skill_bindings` is provided, only bound skills are returned. Skills are tenant-unaware — there is no tenant-based filtering of skills.
3. **Matching algorithm (tag-based):**
   ```
   score(skill, query) = |skill.tags ∩ query_tokens| / |skill.tags|
   ```
   Where `query_tokens` = set of lowercase words from the query. Return top_k sorted descending by score.
4. **Loading:** `load(skill_id, tenant)` returns full `SkillContent`. Raises `SkillNotFoundError` if skill doesn't exist or tenant doesn't have access.
5. **Cache with TTL:** After `cache_ttl` seconds, next call re-scans filesystem (hot reload).
6. **Thread-safe:** Cache guarded by a threading.Lock.
7. **Custom exceptions:** `SkillNotFoundError` — define in this module or a shared exceptions file.

### Implementation Notes

- Use the parser from `skills/parser.py` (already implemented)
- Import models from `deep_agent.models`
- `SkillSummary` should be created from `SkillContent` metadata (skill_id, name, description, tags)

---

## T1.5 — Reference SKILL.md Files

Create the two reference skill files from the PRD.

### Files

**`skills/data-query/db-query/SKILL.md`** (example skill):
```yaml
---
name: db-query
description: Query any database using natural language. Translates user intent into SQL, executes via sandbox, and returns formatted results.
version: "1.0.0"
tags:
  - database
  - query
  - sql
  - data
allowed-tools:
  - execute_code
inputs:
  - name: question
    type: string
    description: Natural language question about data
quality:
  accuracy: "Validated against standard SQL syntax"
---

## Instructions

You are a database query assistant. When the user asks about data:

1. Identify the relevant database from resource env vars available in the sandbox.
2. Write Python code that connects using `os.environ` (e.g., `DB_HOST`, `DB_PORT`) and runs the appropriate SQL query.
3. Use `execute_code` to run the query and format results as a table.
4. If the user asks for a chart, generate it with matplotlib and save to `/output/chart.png`.

Always explain the SQL query you're running and summarize the results.
```

**`skills/data-query/db-query/scripts/requirements.txt`:**
```
# Skill-specific dependencies — installed in sandbox at runtime
clickhouse-connect>=0.7
pandas>=2.2
```

**`skills/equities/zscore-monitor/SKILL.md`** (example skill):
```yaml
---
name: zscore-monitor
description: Monitor z-scores for equity metrics (volume, price, PE ratio). Identifies statistical outliers using rolling window calculations.
version: "1.0.0"
tags:
  - equities
  - zscore
  - volume
  - monitor
  - statistics
  - outlier
allowed-tools:
  - execute_code
inputs:
  - name: symbol
    type: string
    description: Stock ticker symbol (e.g. AAPL)
  - name: metric
    type: string
    description: Metric to monitor (volume, close, pe_ratio)
  - name: window
    type: integer
    description: Rolling window size in days (default 20)
quality:
  accuracy: "Z-scores validated against pandas rolling calculations"
---

## Instructions

You are a statistical monitoring agent for equities. When asked about z-scores:

1. Write Python code that connects to the database using env vars (`DB_HOST`, `DB_PORT`, etc.).
2. Use `from firm_stats import zscore, moving_avg` (bundled in `scripts/firm_stats.py`).
3. Use `execute_code` to run the analysis.
4. Flag any data points where |z-score| > 2 as outliers.
5. Generate a chart with matplotlib showing the metric and z-score over time. Save to `/output/chart.png`.

Example query structure:
```python
import os
import clickhouse_connect
import pandas as pd
from firm_stats import zscore

client = clickhouse_connect.get_client(
    host=os.environ["DB_HOST"],
    port=int(os.environ["DB_PORT"]),
)
df = pd.DataFrame(
    client.query("SELECT date, volume FROM fundamentals_daily WHERE symbol='AAPL' ORDER BY date").result_rows,
    columns=["date", "volume"],
)
df["zscore"] = zscore(df["volume"], window=20)
outliers = df[df["zscore"].abs() > 2]
```
```

**`skills/equities/zscore-monitor/scripts/requirements.txt`:**
```
# Skill-specific dependencies
clickhouse-connect>=0.7
pandas>=2.2
numpy>=1.26
matplotlib>=3.9
```

**`skills/equities/zscore-monitor/scripts/firm_stats.py`:**
```
# Bundled inside the skill, not a top-level stubs/ package
# See T2.5 for implementation
```

---

## T1.6 — Unit Tests for Skills Layer

Write comprehensive unit tests covering parser, engine discovery, matching, and loading.

### Files

**`tests/unit/test_skill_parser.py`:**
- Test valid SKILL.md parsing (use reference files from T1.5)
- Test missing required fields raises `SkillParseError`
- Test malformed frontmatter raises `SkillParseError`
- Test empty body (valid — body can be empty)
- Test extra frontmatter fields are ignored
- Test skill_id derivation from paths

**`tests/unit/test_skill_engine.py`:**
- Test `discover()` returns all indexed skills when no skill_bindings provided
- Test `discover()` with skill_bindings returns only bound skills
- Test `match("z-scores for AAPL volume", ...)` ranks zscore-monitor first
- Test `match("query database", ...)` ranks db-query first
- Test `load()` returns full SkillContent with body
- Test `load()` raises SkillNotFoundError for missing skill
- Test `load()` raises SkillNotFoundError for non-existent skill_id
- Test cache invalidation: after TTL, filesystem changes are picked up (mock time or use short TTL)

### Test Fixtures (in conftest.py or local conftest)

Create a temporary skills directory with the reference SKILL.md files for isolated testing. Use `tmp_path` fixture.

### Acceptance Criteria
1. All tests pass with `pytest tests/unit/ -v`
2. At least 12 test cases across both files
3. Tests are independent (no shared mutable state)
4. Good coverage of error paths, not just happy paths

---

## Design Principles (same as Batch 1)

1. Protocol-based interfaces where applicable
2. Zero circular imports
3. Type annotations on ALL functions/methods
4. Docstrings on all public classes/methods
5. One concern per file

## Validation

After implementation:
```bash
source .venv/bin/activate
ruff check src/ tests/
mypy src/
pytest tests/unit/ -v
```

All must pass cleanly.
