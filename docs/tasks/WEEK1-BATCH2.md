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

    def discover(self, tenant: TenantContext) -> list[SkillSummary]:
        """Return SkillSummary objects for skills in common/ and tenant's dir.
        Skills from other tenants are excluded."""

    def match(self, query: str, tenant: TenantContext, top_k: int = 5) -> list[SkillSummary]:
        """Return skills ranked by tag overlap with query tokens."""

    def load(self, skill_id: str, tenant: TenantContext) -> SkillContent:
        """Return full SkillContent including body.
        Raises SkillNotFoundError if skill doesn't exist or tenant lacks access."""
```

### Requirements

1. **Discovery:** Scans filesystem for `SKILL.md` files on first call. Indexes them by skill_id.
2. **Tenant filtering:** `discover()` returns skills from `common/` plus the tenant's directory. Other tenants' skills are excluded.
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
- `SkillSummary` should be created from `SkillContent` metadata (skill_id, name, description, tags, tenant)

---

## T1.5 — Reference SKILL.md Files

Create the two reference skill files from the PRD.

### Files

**`skills/common/db-query/SKILL.md`:**
```yaml
---
name: db-query
description: Query any registered database using natural language. Translates user intent into SQL, executes via sandbox, and returns formatted results.
version: "1.0.0"
tags:
  - database
  - query
  - sql
  - data
tenant: common
allowed-tools:
  - query_database
  - execute_code
inputs:
  - name: question
    type: string
    description: Natural language question about data
quality:
  accuracy: "Validated against ClickHouse SQL syntax"
---

## Instructions

You are a database query assistant. When the user asks about data:

1. Use `query_database` with `action="list_aliases"` to find available databases.
2. Use `query_database` with `action="get_schema"` to understand table structures.
3. Write Python code that connects to the database and runs the appropriate SQL query.
4. Use `execute_code` to run the query and format results as a table.
5. If the user asks for a chart, generate it with matplotlib and save to `/output/chart.png`.

Always explain the SQL query you're running and summarize the results.
```

**`skills/equities/zscore-monitor/SKILL.md`:**
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
tenant: equities
allowed-tools:
  - query_database
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

1. Use `query_database` to discover the `ch-equities` database schema.
2. Write Python code using `firm.stats.zscore()` to compute rolling z-scores.
3. Use `execute_code` to run the analysis.
4. Flag any data points where |z-score| > 2 as outliers.
5. Generate a chart with matplotlib showing the metric and z-score over time. Save to `/output/chart.png`.

Example query structure:
```python
import os
import clickhouse_connect
import pandas as pd
from firm.stats import zscore

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
- Test `discover()` returns skills for correct tenant (equities gets common + equities skills)
- Test `discover()` excludes other tenants' skills
- Test `match("z-scores for AAPL volume", ...)` ranks zscore-monitor first
- Test `match("query database", ...)` ranks db-query first
- Test `load()` returns full SkillContent with body
- Test `load()` raises SkillNotFoundError for missing skill
- Test `load()` raises SkillNotFoundError for wrong tenant
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
