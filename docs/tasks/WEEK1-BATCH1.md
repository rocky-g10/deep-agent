# Week 1 Batch 1: T1.1 + T1.2 + T1.3

> **Reference:** `docs/IMPLEMENTATION_PLAN.md` — read it for full context.
> **Scope:** Project scaffolding, shared data models, skill file parser.

---

## T1.1 — Project Scaffolding

Set up the Python project with proper tooling and the full directory skeleton.

### Files to Create

| File | Purpose |
|------|---------|
| `pyproject.toml` | Build metadata, project name `deep-agent`, editable install config |
| `requirements.txt` | Pinned runtime deps (see below) |
| `requirements-dev.txt` | Dev/test deps (see below) |
| `.gitignore` | Standard Python gitignore |
| `.env.example` | All required env vars with placeholder values |
| `src/deep_agent/__init__.py` | Package root with `__version__` |
| `src/deep_agent/py.typed` | PEP 561 marker (empty file) |
| `src/deep_agent/config.py` | `pydantic-settings` config class |
| `tests/conftest.py` | Shared pytest fixtures |

Plus all `__init__.py` files for subpackages:
- `src/deep_agent/models/`
- `src/deep_agent/skills/`
- `src/deep_agent/runtime/`
- `src/deep_agent/sandbox/`
- `src/deep_agent/database/`      # example code, not core framework
- `src/deep_agent/tools/`
- `src/deep_agent/mcp/`
- `src/deep_agent/orchestrator/`
- `src/deep_agent/api/`
- `tests/unit/`, `tests/integration/`, `tests/e2e/`

### Config Fields (`config.py`)

Use `pydantic-settings` `BaseSettings` with env prefix:

```python
class Settings(BaseSettings):
    openai_api_key: str = ""
    openai_model: str = "gpt-5"
    skills_root: str = "skills/"
    sandbox_timeout: int = 60
    sandbox_max_memory_mb: int = 4096

    # Resource env vars are example-specific, not core framework config.
    # Skills define their own data sources. Example skills may use
    # RESOURCE_ENV_* prefixed vars in tenant resource configuration.

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
```

### Dependencies

**requirements.txt:**
```
fastapi>=0.115
uvicorn[standard]>=0.30
websockets>=12.0
deepagents
langgraph>=0.2
langchain-openai>=0.2
langchain-core>=0.3
openai>=1.50
langchain-mcp-adapters>=0.1
mcp>=1.0
pydantic>=2.0
pydantic-settings>=2.0
python-frontmatter>=1.0
matplotlib>=3.9
plotly>=5.22
pandas>=2.2
numpy>=1.26
```

**requirements-dev.txt:**
```
-r requirements.txt
pytest>=8.0
pytest-asyncio>=0.23
pytest-timeout>=2.2
httpx>=0.27
ruff>=0.5
mypy>=1.10
```

### Acceptance Criteria
1. `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt -r requirements-dev.txt` succeeds
2. `pip install -e .` installs `deep_agent` in editable mode
3. `python -c "import deep_agent"` succeeds
4. `ruff check src/ tests/` passes with zero errors
5. `mypy src/` passes with zero errors
6. `pytest` discovers test skeleton and passes (zero tests collected OK)

---

## T1.2 — Shared Data Models

All shared types in `src/deep_agent/models/`. **Zero internal dependencies** — every other module imports from here.

### Files

**`models/context.py`** — TenantContext:
```python
@dataclass
class TenantContext:
    tenant_id: str
    user_id: str
    skills_dirs: list[str]            # Legacy — may be empty when using agent skill bindings
    db_aliases: list[str]             # Legacy — resource env vars configured per-tenant
    resource_env: dict[str, dict[str, str]] | None = None  # Generic resource aliases → env var sets

    @classmethod
    def stub(cls) -> "TenantContext":
        return cls(
            tenant_id="equities",
            user_id="dev-user",
            skills_dirs=["skills/common", "skills/equities"],
            db_aliases=["ch-equities"],
            resource_env={
                "ch-equities": {
                    "DB_HOST": "localhost",
                    "DB_PORT": "8123",
                    "DB_NAME": "default",
                    "DB_USER": "default",
                },
            },
        )
```

**`models/skills.py`** — SkillSummary, SkillMetadata, SkillContent:
- `SkillSummary`: skill_id, name, description, tags (no tenant field — skills are tenant-unaware)
- `SkillMetadata`: all frontmatter fields (name, description, version, tags, tenant, allowed_tools, inputs, quality)
- `SkillContent`: metadata + body (full markdown content)

**`models/sandbox.py`** — ResourceLimits, ExecuteResult:
- `ResourceLimits`: timeout_seconds, max_memory_mb, max_output_bytes
- `ExecuteResult`: execution_id (UUID str), exit_code, stdout, stderr, duration_ms, output_files (dict[str, bytes])

**`models/database.py`** — DatabaseAlias, DatabaseMetadata, TableMeta, ConnectionConfig:
- `DatabaseAlias`: alias, engine, description
- `TableMeta`: table_name, columns (list of dicts with name + type)
- `DatabaseMetadata`: alias + tables list
- `ConnectionConfig`: host, port, database, user, credentials_ref

**`models/llm.py`** — LLMConfig:
- model, provider, temperature, max_tokens

**`models/events.py`** — AgentEvent discriminated union:
```python
# Use Pydantic's Discriminator on the "type" field
# Types: agent_chunk, tool_call, tool_result, skill_match, agent_complete, error
# Each event has a "type" literal + relevant fields
# AgentEvent = Annotated[Union[...], Discriminator("type")]
```

**`models/__init__.py`** — re-export all public models.

### Acceptance Criteria
1. All models instantiate with valid data
2. All Pydantic models serialize to/from JSON (`.model_dump()` / `.model_validate()`)
3. `TenantContext.stub()` returns correct equities context
4. `AgentEvent` is a discriminated union on `type` field
5. `mypy` passes on all model files

---

## T1.3 — Skill File Parser

`src/deep_agent/skills/parser.py` — pure function, no side effects.

### Interface

```python
def parse_skill_file(path: Path, skills_root: Path | None = None) -> SkillContent:
    """Parse a SKILL.md file, extracting YAML frontmatter and markdown body.
    
    Args:
        path: Path to the SKILL.md file
        skills_root: Root directory for skills (used to derive skill_id from relative path)
    
    Returns:
        SkillContent with metadata and body
    
    Raises:
        SkillParseError: If required fields are missing or frontmatter is malformed
    """
```

### Requirements
1. Uses `python-frontmatter` to extract YAML frontmatter
2. Required frontmatter fields: `name`, `description`, `version`, `tags`, `allowed-tools` (note: `tenant` is NOT a required field — skills are tenant-unaware)
3. `skill_id` derived from relative path: `skills/equities/zscore-monitor/SKILL.md` → `equities/zscore-monitor` (domain-based, not tenant-based)
4. `body` = full markdown content after frontmatter
5. `SkillParseError` is a custom exception (define in `skills/parser.py` or a shared `exceptions.py`)
6. Edge cases handled: empty body, missing frontmatter delimiters, extra frontmatter fields (ignored)

---

## Design Principles (apply to ALL code)

1. **Protocol-based interfaces** — use `typing.Protocol` for all abstractions
2. **Zero circular imports** — `models/` has no internal deps; everything imports from `models/`
3. **Type annotations** on ALL functions and methods
4. **Docstrings** on all public classes and methods
5. **One concern per file** — keep modules focused
6. **Pydantic v2** patterns (`model_dump`, `model_validate`, `Discriminator`)

---

## Validation

After all implementation, run:
```bash
ruff check src/ tests/
mypy src/
python -c "import deep_agent; print(deep_agent.__version__)"
pytest --collect-only
```

All must pass cleanly.
