# Phase 1 Completion — Implementation Specification

> **Date:** 2026-03-12
> **Status:** Approved design — ready for implementation
> **Prerequisite reading:** `docs/PRD.md` §4.5, §5.1, §10; `docs/full-project-audit.md`

---

## Design Decisions (Settled)

| Decision | Choice | Rationale |
|---|---|---|
| WS tenant/agent resolution | Client-specified via query params (`?tenant_id=X&agent_id=Y`), fallback to defaults | Enables E2E testing with different agents; forward-compatible with auth |
| E2E test scope | Mock LLM + SQLite — fully self-contained, no API key needed | Runs in CI; tests full pipeline except actual LLM inference |
| Session model | Multi-turn with conversation history | Matches PRD §4.5; enables follow-up questions |

---

## Task Overview & Dependency Graph

```
Phase A (no dependencies — can run in parallel):
  A1  Add SkillInput + SkillQuality models, update parser
  A2  Fix db-query skill (add scripts/requirements.txt)
  A3  Add config.py unit tests
  A4  Minor fixes (lint, dedup, stub rename, remove clickhouse from core deps)

Phase B (depends on A1 for inputs/quality; A4 for stub rename):
  B1  Session management module                ← A4
  B2  WebSocket request/response schemas       ← (none)
  B3  Agent + tenant config loaders            ← A4
  B4  Extend RuntimeAdapter + Orchestrator for history  ← (none)
  B5  FastAPI app + WebSocket handler          ← B1, B2, B3, B4
  B6  Wire quality.timeout to orchestrator     ← A1

Phase C (depends on B5):
  C1  WebSocket integration tests              ← B5
  C2  E2E test (mock LLM + SQLite)             ← B5

Phase D (depends on all):
  D1  Dev run script (scripts/run_dev.py)      ← B5
  D2  README update                            ← D1
```

---

## Phase A — Foundation

### Task A1: Add `SkillInput` + `SkillQuality` Models

**Goal:** Parse the `inputs` and `quality` YAML frontmatter fields defined in PRD §5.1 into typed models, and make them available on `SkillContent`.

#### A1.1 — Modify `src/deep_agent/models/skills.py`

Add two new Pydantic models **before** `SkillSummary`. Update `SkillContent` to include them.

```python
class SkillInput(BaseModel):
    """Declared input parameter for a skill."""

    name: str
    type: str = "string"
    description: str = ""
    required: bool = True


class SkillQuality(BaseModel):
    """Quality constraints for a skill execution."""

    timeout: int = 60
    max_retries: int = Field(default=0, alias="max-retries")
    validation: str = ""

    model_config = ConfigDict(populate_by_name=True)
```

Modify `SkillContent` — add two fields after `scripts_path`:

```python
class SkillContent(SkillMetadata):
    """Full skill definition including markdown instruction body."""

    body: str
    scripts_path: str = ""
    inputs: list[SkillInput] = Field(default_factory=list)
    quality: SkillQuality = Field(default_factory=SkillQuality)
```

#### A1.2 — Modify `src/deep_agent/models/__init__.py`

Add to imports and `__all__`:

```python
from deep_agent.models.skills import (
    AgentSkillBindings, SkillContent, SkillInput, SkillMetadata, SkillQuality, SkillSummary,
)
```

Add `"SkillInput"` and `"SkillQuality"` to the `__all__` list (alphabetical order).

#### A1.3 — Modify `src/deep_agent/skills/parser.py`

In `parse_skill_file()`, after extracting `allowed_tools` (line 58) and before the `return SkillContent(...)` call, add extraction of optional fields:

```python
from deep_agent.models.skills import SkillInput, SkillQuality

# ... inside parse_skill_file, after allowed_tools extraction:

raw_inputs = metadata.get("inputs", [])
inputs: list[SkillInput] = []
if isinstance(raw_inputs, list):
    for item in raw_inputs:
        if isinstance(item, dict) and "name" in item:
            inputs.append(SkillInput(**{k: v for k, v in item.items() if k in SkillInput.model_fields}))

raw_quality = metadata.get("quality", {})
quality = SkillQuality()
if isinstance(raw_quality, dict):
    quality = SkillQuality(**{k: v for k, v in raw_quality.items() if k in SkillQuality.model_fields or k in ("max-retries",)})
```

Add `inputs=inputs` and `quality=quality` to the `SkillContent(...)` constructor call.

**Key behavior:**
- `inputs` and `quality` are OPTIONAL — missing fields produce empty list / defaults.
- Malformed `inputs` entries (missing `name`) are silently skipped.
- Unknown keys inside `inputs` items or `quality` are silently ignored.
- This is NOT a breaking change — existing SKILL.md files without these fields continue to parse.

#### A1.4 — Tests for `inputs` / `quality`

**File:** `tests/unit/test_skill_parser.py` — add these tests:

```python
def test_parse_skill_with_inputs_and_quality(tmp_path: Path) -> None:
    """Parser should extract inputs and quality from frontmatter."""
    skill_path = tmp_path / "skills" / "risk" / "var" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("""---
name: var-report
description: VaR report
version: "1.0.0"
tags: [risk]
allowed-tools: [execute_code]
inputs:
  - name: portfolio_id
    type: string
    description: Portfolio ID
    required: true
  - name: confidence
    type: number
    description: Confidence level
    required: false
quality:
  timeout: 90
  max-retries: 2
  validation: "Must include VaR number"
---
Body
""", encoding="utf-8")

    skill = parse_skill_file(skill_path)

    assert len(skill.inputs) == 2
    assert skill.inputs[0].name == "portfolio_id"
    assert skill.inputs[0].type == "string"
    assert skill.inputs[0].required is True
    assert skill.inputs[1].name == "confidence"
    assert skill.inputs[1].required is False
    assert skill.quality.timeout == 90
    assert skill.quality.max_retries == 2
    assert skill.quality.validation == "Must include VaR number"


def test_parse_skill_without_inputs_quality_uses_defaults(tmp_path: Path) -> None:
    """Skills without inputs/quality should get empty list and default quality."""
    skill_path = tmp_path / "skills" / "common" / "basic" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("""---
name: basic
description: basic skill
version: "1.0.0"
tags: [general]
allowed-tools: [execute_code]
---
Body
""", encoding="utf-8")

    skill = parse_skill_file(skill_path)

    assert skill.inputs == []
    assert skill.quality.timeout == 60
    assert skill.quality.max_retries == 0
    assert skill.quality.validation == ""


def test_parse_reference_skills_have_inputs_and_quality() -> None:
    """The reference zscore-monitor skill should have inputs and quality parsed."""
    skill = parse_skill_file(Path("skills/equities/zscore-monitor/SKILL.md"))

    assert len(skill.inputs) >= 1
    assert any(i.name == "symbol" for i in skill.inputs)
    assert skill.quality.accuracy is not None or skill.quality.timeout == 60  # has quality block
```

**File:** `tests/unit/test_models.py` — add:

```python
def test_skill_input_defaults() -> None:
    inp = SkillInput(name="x")
    assert inp.type == "string"
    assert inp.required is True
    assert inp.description == ""


def test_skill_quality_defaults() -> None:
    q = SkillQuality()
    assert q.timeout == 60
    assert q.max_retries == 0
    assert q.validation == ""


def test_skill_quality_alias() -> None:
    q = SkillQuality(**{"max-retries": 3})
    assert q.max_retries == 3
```

---

### Task A2: Fix `db-query` Skill

**Goal:** Add missing `scripts/requirements.txt` so sandbox can install dependencies.

**Create:** `skills/common/db-query/scripts/requirements.txt`

```
clickhouse-connect>=0.7
```

That's it. One file, one line. The skill instructions reference ClickHouse SQL syntax (validated in the quality block), so `clickhouse-connect` is the correct dependency.

---

### Task A3: Config Unit Tests

**Goal:** Test `AppSettings` defaults, env overrides, and `get_settings()` caching.

**Create:** `tests/unit/test_config.py`

```python
"""Unit tests for application configuration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import SecretStr

from deep_agent.config import AppSettings, EnvironmentSettingsProvider, get_settings


def test_app_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """AppSettings should apply default values for optional fields."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    settings = AppSettings()  # type: ignore[call-arg]

    assert settings.openai_model == "gpt-5"
    assert settings.openai_temperature == 0.0
    assert settings.openai_max_tokens == 4096
    assert settings.skills_root == Path("skills/")
    assert settings.cache_ttl_seconds == 300
    assert settings.log_level == "INFO"


def test_app_settings_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment variables should override defaults."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-override")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1")
    monkeypatch.setenv("OPENAI_TEMPERATURE", "0.7")
    monkeypatch.setenv("OPENAI_MAX_TOKENS", "2048")
    monkeypatch.setenv("SKILLS_ROOT", "/custom/skills")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    settings = AppSettings()  # type: ignore[call-arg]

    assert settings.openai_model == "gpt-4.1"
    assert settings.openai_temperature == 0.7
    assert settings.openai_max_tokens == 2048
    assert settings.skills_root == Path("/custom/skills")
    assert settings.log_level == "DEBUG"


def test_app_settings_api_key_is_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """OPENAI_API_KEY should be stored as SecretStr."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-123")
    settings = AppSettings()  # type: ignore[call-arg]

    assert isinstance(settings.openai_api_key, SecretStr)
    assert settings.openai_api_key.get_secret_value() == "sk-secret-123"
    assert "sk-secret-123" not in str(settings.openai_api_key)


def test_environment_settings_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """EnvironmentSettingsProvider.load() should return an AppSettings instance."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    provider = EnvironmentSettingsProvider()
    settings = provider.load()

    assert isinstance(settings, AppSettings)
    assert settings.openai_api_key.get_secret_value() == "sk-test"
```

**Note:** `get_settings()` uses `@lru_cache` which makes it hard to test in isolation. Do NOT test `get_settings()` caching behavior — it's a known limitation (see audit M2). Testing the provider directly is sufficient.

---

### Task A4: Minor Fixes

#### A4.1 — Fix f-string lint (M1)

**File:** `src/deep_agent/mcp/config.py` line 54

```python
# BEFORE:
f"MCP config path escapes config root: path traversal detected"

# AFTER:
"MCP config path escapes config root: path traversal detected"
```

Remove the `f` prefix. Nothing else changes.

#### A4.2 — Deduplicate `firm_stats.py` (M4)

The file `examples/skills/equities/zscore-monitor/scripts/firm_stats.py` is an identical copy of `skills/equities/zscore-monitor/scripts/firm_stats.py`.

**Action:** Delete `examples/skills/equities/zscore-monitor/scripts/firm_stats.py`.

**Modify:** `tests/unit/test_firm_stats.py` — change the `_scripts_dir` path to point to the canonical location:

```python
# BEFORE:
_scripts_dir = str(
    Path(__file__).resolve().parent.parent.parent
    / "examples"
    / "skills"
    / "equities"
    / "zscore-monitor"
    / "scripts"
)

# AFTER:
_scripts_dir = str(
    Path(__file__).resolve().parent.parent.parent
    / "skills"
    / "equities"
    / "zscore-monitor"
    / "scripts"
)
```

If `examples/skills/equities/zscore-monitor/scripts/requirements.txt` exists and contains only dependencies, keep it (it may be referenced by the example). If the entire `examples/skills/equities/zscore-monitor/scripts/` directory becomes empty after removing `firm_stats.py`, delete the directory but keep `requirements.txt` if present.

#### A4.3 — Rename `TenantContext.stub()` → `TenantContext.default()` (I1)

**File:** `src/deep_agent/models/context.py`

Replace the `stub` classmethod with a domain-neutral `default`:

```python
@classmethod
def default(cls) -> TenantContext:
    """Return a generic default context for local development."""
    return cls(
        tenant_id="default",
        user_id="anonymous",
    )
```

**Files to update (references to `.stub()`):**

1. `tests/unit/test_models.py` — rename test `test_tenant_context_stub_returns_expected_equities_values` to `test_tenant_context_default_returns_neutral_values`. Update assertions:
   ```python
   def test_tenant_context_default_returns_neutral_values() -> None:
       ctx = TenantContext.default()
       assert ctx.tenant_id == "default"
       assert ctx.user_id == "anonymous"
       assert ctx.resource_env == {}
       assert ctx.mcp_config_path == ""
   ```

2. Search the entire codebase for `TenantContext.stub()` and replace with `TenantContext.default()`. As of the audit, it only appears in `context.py` and `test_models.py`.

#### A4.4 — Remove `clickhouse-connect` from core dependencies

**File:** `pyproject.toml` — remove `"clickhouse-connect>=0.7",` from the `dependencies` list (line 21). This dependency belongs in skill-level `scripts/requirements.txt` (added in Task A2), not in the core framework.

**File:** `requirements.txt` — if `clickhouse-connect` appears here, remove it as well.

**Verify:** Run `pip install -e .` and `pytest tests/` to confirm nothing in core depends on it.

---

## Phase B — API Layer

### Task B1: Session Management Module

**Create:** `src/deep_agent/api/session.py`

```python
"""In-memory session management for Phase 1."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from deep_agent.models.context import TenantContext
from deep_agent.models.skills import AgentSkillBindings


@dataclass
class Session:
    """A single user session with conversation state."""

    session_id: str
    tenant: TenantContext
    bindings: AgentSkillBindings
    messages: list[Any] = field(default_factory=list)  # list[BaseMessage]
    created_at: float = field(default_factory=time.time)


class SessionManager:
    """Thread-safe in-memory session store.

    Phase 1 only — sessions are lost on restart.
    Phase 2 replaces this with Redis + PostgreSQL.
    """

    def __init__(self, max_sessions: int = 1000) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        self._max_sessions = max_sessions

    def create(
        self,
        tenant: TenantContext,
        bindings: AgentSkillBindings,
    ) -> Session:
        """Create a new session and return it."""
        session_id = uuid.uuid4().hex
        session = Session(
            session_id=session_id,
            tenant=tenant,
            bindings=bindings,
        )
        with self._lock:
            self._sessions[session_id] = session
            self._evict_oldest()
        return session

    def get(self, session_id: str) -> Session | None:
        """Return session by ID, or None if not found."""
        with self._lock:
            return self._sessions.get(session_id)

    def delete(self, session_id: str) -> None:
        """Remove a session."""
        with self._lock:
            self._sessions.pop(session_id, None)

    def _evict_oldest(self) -> None:
        """Evict oldest sessions if over capacity."""
        while len(self._sessions) > self._max_sessions:
            oldest_id = min(self._sessions, key=lambda k: self._sessions[k].created_at)
            self._sessions.pop(oldest_id, None)
```

**Behavior:**
- Thread-safe via `threading.Lock` (matches sandbox/engine patterns).
- `max_sessions=1000` default prevents unbounded memory growth.
- `messages` stores LangChain `BaseMessage` objects (typed as `list[Any]` to avoid hard dependency on langchain_core in the models layer).
- `create()` generates a UUID hex session ID.
- `get()` returns `None` for unknown IDs (caller handles the error).

---

### Task B2: WebSocket Request/Response Schemas

**Create:** `src/deep_agent/api/schemas.py`

```python
"""WebSocket message schemas for client-server communication."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class UserMessage(BaseModel):
    """Client → Server: user sends a chat message."""

    type: Literal["user_message"] = "user_message"
    content: str
    session_id: str = ""


class SessionStartedMessage(BaseModel):
    """Server → Client: sent immediately after WebSocket connection is accepted."""

    type: Literal["session_started"] = "session_started"
    session_id: str
```

**Notes:**
- Server → Client streaming events (`agent_chunk`, `tool_call`, `tool_result`, `skill_match`, `agent_complete`, `error`) already exist in `deep_agent.models.events` and are used directly — do NOT duplicate them.
- `UserMessage.session_id` defaults to `""`. If empty on first message, the server uses the session created at connect time. If non-empty, the server looks up that session (enables reconnection in future phases).
- `SessionStartedMessage` is a new event type sent once on connection.

---

### Task B3: Agent + Tenant Config Loaders

**Create:** `src/deep_agent/api/config_loader.py`

```python
"""Load agent bindings and tenant resource config from YAML files."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from deep_agent.models.context import TenantContext
from deep_agent.models.skills import AgentSkillBindings

logger = logging.getLogger(__name__)


class ConfigLoadError(ValueError):
    """Raised when a config file is malformed."""


def load_agent_bindings(
    agent_id: str,
    config_root: Path = Path("config"),
) -> AgentSkillBindings | None:
    """Load agent skill bindings from config/agents/{agent_id}.yaml.

    Returns None if the file does not exist (caller should apply a default).
    Raises ConfigLoadError if the file exists but is malformed.
    """
    config_path = (config_root / "agents" / f"{agent_id}.yaml").resolve()
    safe_root = config_root.resolve()
    if not config_path.is_relative_to(safe_root):
        raise ConfigLoadError("Agent config path escapes config root: path traversal detected")

    if not config_path.is_file():
        logger.debug("No agent config at %s — returning None", config_path)
        return None

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ConfigLoadError(f"Failed to parse agent config {config_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigLoadError(f"Agent config {config_path} must be a YAML mapping")

    agent_id_from_file = raw.get("agent_id", agent_id)
    bound_ids = raw.get("bound_skill_ids", [])
    if not isinstance(bound_ids, list):
        raise ConfigLoadError(f"Agent config {config_path}: bound_skill_ids must be a list")

    return AgentSkillBindings(
        agent_id=str(agent_id_from_file),
        bound_skill_ids=tuple(str(s) for s in bound_ids),
    )


def load_resource_env(
    tenant_id: str,
    config_root: Path = Path("config"),
) -> dict[str, dict[str, str]]:
    """Load resource aliases from config/tenants/{tenant_id}/resources.yaml.

    Returns empty dict if the file does not exist.
    Raises ConfigLoadError if the file exists but is malformed.
    """
    config_path = (config_root / "tenants" / tenant_id / "resources.yaml").resolve()
    safe_root = config_root.resolve()
    if not config_path.is_relative_to(safe_root):
        raise ConfigLoadError("Resource config path escapes config root: path traversal detected")

    if not config_path.is_file():
        logger.debug("No resource config at %s — returning empty", config_path)
        return {}

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ConfigLoadError(f"Failed to parse resource config {config_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigLoadError(f"Resource config {config_path} must be a YAML mapping")

    aliases = raw.get("resource_aliases", {})
    if not isinstance(aliases, dict):
        raise ConfigLoadError(f"Resource config {config_path}: resource_aliases must be a mapping")

    result: dict[str, dict[str, str]] = {}
    for alias_name, env_vars in aliases.items():
        if isinstance(env_vars, dict):
            result[str(alias_name)] = {str(k): str(v) for k, v in env_vars.items()}

    return result


def build_tenant_context(
    tenant_id: str,
    config_root: Path = Path("config"),
    user_id: str = "anonymous",
) -> TenantContext:
    """Build a TenantContext from config files.

    Loads resource env from config/tenants/{tenant_id}/resources.yaml.
    Sets mcp_config_path to tenants/{tenant_id}/mcp.json (relative to config_root).
    """
    resource_env = load_resource_env(tenant_id, config_root)
    mcp_config_path = f"tenants/{tenant_id}/mcp.json"
    return TenantContext(
        tenant_id=tenant_id,
        user_id=user_id,
        mcp_config_path=mcp_config_path,
        resource_env=resource_env,
    )
```

**Dependency:** Add `pyyaml>=6.0` to `requirements.txt` and `pyproject.toml` dependencies (if not already present — check first; `python-frontmatter` may pull it in transitively, but it should be an explicit dependency).

**Tests:** `tests/unit/test_config_loader.py`

```python
def test_load_agent_bindings_from_yaml(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "test-agent.yaml").write_text(
        'agent_id: "test-agent"\nbound_skill_ids:\n  - "risk/var"\n  - "common/db-query"\n'
    )
    bindings = load_agent_bindings("test-agent", config_root=tmp_path)
    assert bindings is not None
    assert bindings.agent_id == "test-agent"
    assert bindings.bound_skill_ids == ("risk/var", "common/db-query")


def test_load_agent_bindings_missing_file(tmp_path: Path) -> None:
    result = load_agent_bindings("nonexistent", config_root=tmp_path)
    assert result is None


def test_load_resource_env_from_yaml(tmp_path: Path) -> None:
    tenant_dir = tmp_path / "tenants" / "risk"
    tenant_dir.mkdir(parents=True)
    (tenant_dir / "resources.yaml").write_text(
        'resource_aliases:\n  my-db:\n    DB_HOST: "localhost"\n    DB_PORT: "5432"\n'
    )
    env = load_resource_env("risk", config_root=tmp_path)
    assert env == {"my-db": {"DB_HOST": "localhost", "DB_PORT": "5432"}}


def test_load_resource_env_missing_file(tmp_path: Path) -> None:
    env = load_resource_env("missing", config_root=tmp_path)
    assert env == {}


def test_build_tenant_context(tmp_path: Path) -> None:
    tenant_dir = tmp_path / "tenants" / "risk"
    tenant_dir.mkdir(parents=True)
    (tenant_dir / "resources.yaml").write_text(
        'resource_aliases:\n  db:\n    DB_HOST: "host"\n'
    )
    ctx = build_tenant_context("risk", config_root=tmp_path, user_id="user1")
    assert ctx.tenant_id == "risk"
    assert ctx.user_id == "user1"
    assert ctx.resource_env == {"db": {"DB_HOST": "host"}}
    assert ctx.mcp_config_path == "tenants/risk/mcp.json"


def test_path_traversal_blocked(tmp_path: Path) -> None:
    with pytest.raises(ConfigLoadError):
        load_agent_bindings("../../etc/passwd", config_root=tmp_path)
    with pytest.raises(ConfigLoadError):
        load_resource_env("../../etc", config_root=tmp_path)
```

---

### Task B4: Extend RuntimeAdapter + Orchestrator for Multi-Turn History

**Goal:** Enable multi-turn conversations by passing message history through the orchestrator to the runtime adapter. This is a backward-compatible extension — all new parameters have defaults.

#### B4.1 — Modify `src/deep_agent/runtime/protocol.py`

Add optional `history` parameter to both `invoke()` and `stream()`:

```python
from typing import Any  # already imported

# In RuntimeAdapter protocol:

async def invoke(
    self,
    agent: Agent,
    message: str,
    context: TenantContext,
    history: list[Any] | None = None,
) -> AgentResponse:
    """Run the agent to completion and return structured output."""
    ...

def stream(
    self,
    agent: Agent,
    message: str,
    context: TenantContext,
    history: list[Any] | None = None,
) -> AsyncIterator[AgentEvent]:
    """Stream runtime events for a single request."""
    ...
```

#### B4.2 — Modify `src/deep_agent/runtime/langgraph_adapter.py`

Update `invoke()` and `stream()` to accept and use `history`:

```python
async def invoke(
    self,
    agent: Agent,
    message: str,
    context: TenantContext,
    history: list[Any] | None = None,
) -> AgentResponse:
    _ = context
    messages: list[Any] = list(history or [])
    messages.append(HumanMessage(content=message))
    payload = {"messages": messages}
    # ... rest unchanged
```

```python
async def stream(
    self,
    agent: Agent,
    message: str,
    context: TenantContext,
    history: list[Any] | None = None,
) -> AsyncIterator[AgentEvent]:
    _ = context
    messages: list[Any] = list(history or [])
    messages.append(HumanMessage(content=message))
    payload = {"messages": messages}
    # ... rest unchanged (replace the existing single-line payload construction)
```

**Key behavior:**
- If `history` is `None` or `[]`, behavior is identical to current (single-turn).
- `history` contains LangChain `BaseMessage` objects (HumanMessage, AIMessage, ToolMessage).
- The adapter prepends history before the new HumanMessage.

#### B4.3 — Modify `src/deep_agent/orchestrator/agent_orchestrator.py`

Add `history` parameter to `handle_message()` and pass it through:

```python
async def handle_message(
    self,
    message: str,
    context: TenantContext,
    skill_bindings: AgentSkillBindings,
    history: list[Any] | None = None,
) -> AsyncIterator[AgentEvent]:
```

In the body, change the `self._runtime.stream()` call:

```python
# BEFORE:
async for event in self._runtime.stream(agent, message, context):

# AFTER:
async for event in self._runtime.stream(agent, message, context, history=history):
```

**Import addition:** Add `Any` to the typing imports if not already present.

#### B4.4 — Update existing tests

The existing tests pass `handle_message(msg, ctx, skill_bindings=bindings)` — this continues to work because `history` defaults to `None`. No test changes are needed for backward compatibility.

Add ONE new test in `tests/unit/test_orchestrator.py`:

```python
@pytest.mark.asyncio
async def test_handle_message_passes_history_to_runtime(
    tenant_equities: TenantContext,
    skill_bindings: AgentSkillBindings,
) -> None:
    """History should be forwarded to runtime.stream()."""
    engine = _mock_skill_engine([])
    runtime = MagicMock()
    runtime.create_agent.return_value = MagicMock()
    runtime.stream = _fake_stream

    orchestrator = AgentOrchestrator(
        skill_engine=engine,
        llm_router=MagicMock(resolve=MagicMock(return_value=LLMConfig())),
        runtime=runtime,
        sandbox=AsyncMock(),
    )

    fake_history = [MagicMock(), MagicMock()]
    # Wrap _fake_stream to capture call args
    calls = []
    async def capturing_stream(*args, **kwargs):
        calls.append((args, kwargs))
        async for event in _fake_stream(*args, **kwargs):
            yield event

    runtime.stream = capturing_stream

    _ = [
        event
        async for event in orchestrator.handle_message(
            "follow-up", tenant_equities, skill_bindings=skill_bindings, history=fake_history
        )
    ]

    assert len(calls) == 1
    _, kwargs = calls[0]
    assert kwargs.get("history") is fake_history
```

Add ONE new test in `tests/unit/test_langgraph_adapter.py`:

```python
@pytest.mark.asyncio
async def test_stream_with_history_prepends_messages(tenant_equities: TenantContext) -> None:
    """History messages should be prepended before the new HumanMessage."""
    from langchain_core.messages import AIMessage

    captured_payloads = []
    original_message = AIMessage(content="previous response")

    async def fake_astream(payload, **kwargs):
        captured_payloads.append(payload)
        return
        yield  # make it an async generator

    fake_agent = MagicMock()
    fake_agent.astream = fake_astream

    adapter = LangGraphAdapter()
    _ = [event async for event in adapter.stream(
        fake_agent, "new question", tenant_equities, history=[original_message]
    )]

    assert len(captured_payloads) == 1
    msgs = captured_payloads[0]["messages"]
    assert len(msgs) == 2
    assert msgs[0] is original_message
    assert msgs[1].content == "new question"
```

---

### Task B5: FastAPI App + WebSocket Handler

**This is the largest task.** It creates 3 files and modifies 1.

#### B5.1 — Modify `src/deep_agent/api/__init__.py`

Replace the empty file with:

```python
"""Deep Agent API package."""
```

(Just add a docstring — no functional change.)

#### B5.2 — Create `src/deep_agent/api/app.py`

```python
"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI

from deep_agent.api.session import SessionManager
from deep_agent.config import AppSettings, get_settings
from deep_agent.mcp.manager import MCPManager
from deep_agent.orchestrator.agent_orchestrator import AgentOrchestrator
from deep_agent.runtime.langgraph_adapter import LangGraphAdapter
from deep_agent.runtime.llm_router import LLMRouter
from deep_agent.runtime.protocol import RuntimeAdapter
from deep_agent.sandbox.subprocess_sandbox import PythonSubprocessSandbox
from deep_agent.skills.engine import SkillEngine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup and shutdown lifecycle for the FastAPI app."""
    logger.info("Deep Agent API starting up")
    yield
    logger.info("Deep Agent API shutting down")
    # Cleanup MCP manager if attached
    mcp: MCPManager | None = getattr(app.state, "mcp_manager", None)
    if mcp is not None:
        await mcp.disconnect()


def create_app(
    settings: AppSettings | None = None,
    config_root: Path | None = None,
    runtime: RuntimeAdapter | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        settings: Override application settings (default: from environment).
        config_root: Root directory for agent/tenant configs (default: "config/").
        runtime: Override the runtime adapter (useful for testing with fake LLMs).
    """
    resolved_settings = settings or get_settings()
    resolved_config_root = config_root or Path("config/")
    resolved_runtime = runtime or LangGraphAdapter()

    app = FastAPI(title="Deep Agent", version="0.1.0", lifespan=_lifespan)

    # Initialize subsystems
    skill_engine = SkillEngine(
        skills_root=resolved_settings.skills_root,
        cache_ttl=resolved_settings.cache_ttl_seconds,
    )
    llm_router = LLMRouter(resolved_settings)
    sandbox = PythonSubprocessSandbox()
    session_manager = SessionManager()

    orchestrator = AgentOrchestrator(
        skill_engine=skill_engine,
        llm_router=llm_router,
        runtime=resolved_runtime,
        sandbox=sandbox,
    )

    # Store on app.state for access in route handlers
    app.state.orchestrator = orchestrator
    app.state.skill_engine = skill_engine
    app.state.session_manager = session_manager
    app.state.config_root = resolved_config_root
    app.state.settings = resolved_settings

    # Health endpoint
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # Register WebSocket route
    from deep_agent.api.ws_chat import router as ws_router

    app.include_router(ws_router)

    return app
```

**Key design choices:**
- `create_app()` is a factory — used with `uvicorn deep_agent.api.app:create_app --factory`.
- `runtime` parameter allows tests to inject a `LangGraphAdapter` backed by a fake LLM.
- `config_root` parameter allows tests to use a temp directory with test fixtures.
- Subsystems are stored on `app.state` (FastAPI's standard dependency pattern).
- No `MCPManager` is created at startup — it's created per-session in the WS handler when needed (because MCP config is tenant-specific).
- The `_lifespan` context manager handles cleanup.

#### B5.3 — Create `src/deep_agent/api/ws_chat.py`

```python
"""WebSocket chat endpoint handler."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import ValidationError

from deep_agent.api.config_loader import build_tenant_context, load_agent_bindings
from deep_agent.api.schemas import SessionStartedMessage, UserMessage
from deep_agent.api.session import SessionManager
from deep_agent.models.context import TenantContext
from deep_agent.models.events import ErrorEvent
from deep_agent.models.skills import AgentSkillBindings
from deep_agent.orchestrator.agent_orchestrator import AgentOrchestrator
from deep_agent.skills.engine import SkillEngine

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/chat")
async def ws_chat(
    websocket: WebSocket,
    tenant_id: str = Query(default="default"),
    agent_id: str = Query(default=""),
) -> None:
    """Handle a WebSocket chat connection.

    Query params:
        tenant_id: Tenant identifier (default: "default").
        agent_id: Agent identifier for skill bindings (default: "" → bind all skills).
    """
    await websocket.accept()

    orchestrator: AgentOrchestrator = websocket.app.state.orchestrator
    session_manager: SessionManager = websocket.app.state.session_manager
    skill_engine: SkillEngine = websocket.app.state.skill_engine
    config_root: Path = websocket.app.state.config_root

    # Resolve tenant context
    try:
        tenant = build_tenant_context(
            tenant_id=tenant_id,
            config_root=config_root,
        )
    except Exception as exc:
        logger.warning("Failed to build tenant context for '%s': %s", tenant_id, exc)
        tenant = TenantContext.default()

    # Resolve agent skill bindings
    bindings = _resolve_bindings(agent_id, config_root, skill_engine)

    # Create session
    session = session_manager.create(tenant=tenant, bindings=bindings)

    # Send session_started
    started = SessionStartedMessage(session_id=session.session_id)
    await websocket.send_text(started.model_dump_json())

    try:
        while True:
            raw = await websocket.receive_text()
            await _handle_client_message(
                raw=raw,
                websocket=websocket,
                orchestrator=orchestrator,
                session_manager=session_manager,
                session_id=session.session_id,
            )
    except WebSocketDisconnect:
        logger.debug("Client disconnected (session %s)", session.session_id)
    except Exception as exc:
        logger.exception("WebSocket error (session %s)", session.session_id)
        try:
            error = ErrorEvent(code="WS_ERROR", message=str(exc))
            await websocket.send_text(error.model_dump_json())
        except Exception:
            pass
    finally:
        session_manager.delete(session.session_id)


async def _handle_client_message(
    raw: str,
    websocket: WebSocket,
    orchestrator: AgentOrchestrator,
    session_manager: SessionManager,
    session_id: str,
) -> None:
    """Parse and process a single client message."""
    # Parse JSON
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        error = ErrorEvent(code="INVALID_JSON", message=f"Malformed JSON: {exc}")
        await websocket.send_text(error.model_dump_json())
        return

    # Validate message type
    msg_type = data.get("type")
    if msg_type != "user_message":
        error = ErrorEvent(code="UNKNOWN_MESSAGE_TYPE", message=f"Unknown type: {msg_type}")
        await websocket.send_text(error.model_dump_json())
        return

    # Validate schema
    try:
        user_msg = UserMessage.model_validate(data)
    except ValidationError as exc:
        error = ErrorEvent(code="VALIDATION_ERROR", message=str(exc))
        await websocket.send_text(error.model_dump_json())
        return

    # Look up session
    effective_session_id = user_msg.session_id or session_id
    session = session_manager.get(effective_session_id)
    if session is None:
        error = ErrorEvent(code="SESSION_NOT_FOUND", message=f"Unknown session: {effective_session_id}")
        await websocket.send_text(error.model_dump_json())
        return

    # Add user message to history
    session.messages.append(HumanMessage(content=user_msg.content))

    # Stream orchestrator events
    summary_parts: list[str] = []
    async for event in orchestrator.handle_message(
        message=user_msg.content,
        context=session.tenant,
        skill_bindings=session.bindings,
        history=session.messages[:-1] if len(session.messages) > 1 else None,
    ):
        await websocket.send_text(event.model_dump_json())
        # Capture AI content for history
        if event.type == "agent_chunk":
            summary_parts.append(event.content)

    # Add AI response to history
    if summary_parts:
        session.messages.append(AIMessage(content="".join(summary_parts)))


def _resolve_bindings(
    agent_id: str,
    config_root: Path,
    skill_engine: SkillEngine,
) -> AgentSkillBindings:
    """Resolve agent skill bindings from config or default to all skills."""
    if agent_id:
        try:
            bindings = load_agent_bindings(agent_id, config_root)
            if bindings is not None:
                return bindings
        except Exception as exc:
            logger.warning("Failed to load agent bindings for '%s': %s", agent_id, exc)

    # Default: bind all discovered skills
    all_skills = skill_engine._scan_filesystem()
    return AgentSkillBindings(
        agent_id=agent_id or "default",
        bound_skill_ids=tuple(all_skills.keys()),
    )
```

**Key behavior:**

1. **Connection:** Accept WebSocket, resolve tenant + agent from query params, create session, send `session_started`.
2. **Message loop:** Receive JSON, validate as `user_message`, look up session, stream orchestrator events.
3. **Multi-turn:** Conversation history (`session.messages`) is passed to the orchestrator as `history`. History includes all prior `HumanMessage` and `AIMessage` objects. The current message is NOT included in `history` (it's passed separately as `message`).
4. **Error handling:** Invalid JSON, unknown message types, validation errors, and session-not-found all produce `error` events without closing the connection. Only unrecoverable errors close the connection.
5. **Cleanup:** Session is deleted when the WebSocket disconnects.
6. **Default bindings:** If no agent_id is provided (or the config file doesn't exist), ALL discovered skills are bound. This ensures the API works out-of-the-box without any config files.

---

### Task B6: Wire `quality.timeout` to Orchestrator

**Goal:** When a skill is matched and loaded, use its `quality.timeout` value as the sandbox timeout instead of the default 60 seconds.

**Modify:** `src/deep_agent/orchestrator/agent_orchestrator.py`

In the `_build_builtin_tools()` method, accept an optional `timeout` parameter:

```python
def _build_builtin_tools(
    self,
    context: TenantContext,
    scripts_dirs: list[str] | None = None,
    timeout: int | None = None,
) -> list[BaseTool]:
    """Create built-in tools bound to tenant-scoped dependencies."""
    tools: list[BaseTool] = []
    tools.append(
        create_execute_code_tool(
            sandbox=self._sandbox,
            tenant=context,
            scripts_dirs=scripts_dirs,
            timeout=timeout,
        )
    )
    return tools
```

In `handle_message()`, extract timeout from the matched skill's quality and pass it:

```python
# After skill_content is loaded (line ~74), extract timeout:
skill_timeout: int | None = None
if skill_content is not None and skill_content.quality.timeout != 60:
    skill_timeout = skill_content.quality.timeout

# Pass to _build_builtin_tools:
builtin_tools = self._build_builtin_tools(
    context, scripts_dirs=scripts_dirs, timeout=skill_timeout
)
```

**Modify:** `src/deep_agent/tools/execute_code.py`

Add `timeout` parameter to `create_execute_code_tool`:

```python
def create_execute_code_tool(
    sandbox: SandboxManager,
    tenant: TenantContext,
    scripts_dirs: list[str] | None = None,
    timeout: int | None = None,
) -> BaseTool:
```

Inside the inner `execute_code` function, use the skill timeout as default:

```python
@tool
async def execute_code(code: str, timeout: int = 60) -> str:
    """Execute Python code in a sandboxed environment."""
    effective_timeout = timeout if timeout != 60 else (skill_timeout or timeout)
    # ...use effective_timeout instead of timeout in sandbox.execute()
```

Wait — this is tricky because the LLM controls the `timeout` argument. A cleaner approach: capture the skill timeout in the closure and use it as the default:

```python
def create_execute_code_tool(
    sandbox: SandboxManager,
    tenant: TenantContext,
    scripts_dirs: list[str] | None = None,
    default_timeout: int | None = None,
) -> BaseTool:
    resource_env = _build_resource_env(tenant)
    if scripts_dirs:
        resource_env["PYTHONPATH"] = os.pathsep.join(scripts_dirs)

    effective_default = default_timeout or 60

    @tool
    async def execute_code(code: str, timeout: int = effective_default) -> str:
        # ... rest unchanged, uses `timeout` parameter
```

Actually, `@tool` reads the default from the function signature at decoration time. The default must be a literal or a constant — it can't be a closure variable used as a default argument in a way that `@tool` can introspect.

**Simpler approach:** Just cap the timeout in the function body:

```python
def create_execute_code_tool(
    sandbox: SandboxManager,
    tenant: TenantContext,
    scripts_dirs: list[str] | None = None,
    max_timeout: int = 60,
) -> BaseTool:
    resource_env = _build_resource_env(tenant)
    if scripts_dirs:
        resource_env["PYTHONPATH"] = os.pathsep.join(scripts_dirs)

    @tool
    async def execute_code(code: str, timeout: int = 60) -> str:
        """Execute Python code in a sandboxed environment."""
        capped_timeout = min(timeout, max_timeout) if max_timeout else timeout
        try:
            result = await sandbox.execute(code=code, timeout=capped_timeout, env=resource_env)
            # ... rest unchanged
```

This uses `max_timeout` from the skill's `quality.timeout` as an upper bound. The LLM can request a shorter timeout but not exceed the skill's limit.

**Test:** Add to `tests/unit/test_tools.py`:

```python
@pytest.mark.asyncio
async def test_execute_code_respects_max_timeout() -> None:
    """max_timeout should cap the sandbox timeout."""
    tenant = TenantContext(tenant_id="t", user_id="u")
    sandbox = AsyncMock()
    sandbox.execute.return_value = ExecuteResult(
        execution_id="e", exit_code=0, stdout="", stderr="", output_files={}, duration_ms=1
    )

    tool = create_execute_code_tool(sandbox, tenant, max_timeout=30)
    await tool.ainvoke({"code": "pass", "timeout": 90})

    _, kwargs = sandbox.execute.call_args
    assert kwargs["timeout"] <= 30
```

---

## Phase C — Testing

### Task C1: WebSocket Integration Tests

**Create:** `tests/integration/test_ws_chat.py`

```python
"""Integration tests for WebSocket chat endpoint."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from deep_agent.api.app import create_app
from deep_agent.config import AppSettings
from deep_agent.models.events import (
    AgentChunkEvent,
    AgentCompleteEvent,
    ErrorEvent,
    SkillMatchEvent,
)


def _test_settings(tmp_path: Path) -> AppSettings:
    """Create AppSettings pointing to a temp skills directory."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    return AppSettings(
        openai_api_key="sk-fake",  # type: ignore[arg-type]
        skills_root=skills_dir,
    )


def _write_test_skill(skills_root: Path) -> None:
    """Write a minimal test skill."""
    skill_dir = skills_root / "test" / "hello"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        '---\nname: hello\ndescription: Test skill\nversion: "1.0"\n'
        "tags: [test]\nallowed-tools: [execute_code]\n---\nSay hello.\n",
        encoding="utf-8",
    )


def _fake_runtime() -> MagicMock:
    """Runtime that yields a chunk + complete without calling an LLM."""
    runtime = MagicMock()
    runtime.create_agent.return_value = MagicMock()

    async def fake_stream(*args: Any, **kwargs: Any):
        yield AgentChunkEvent(content="Hello!")
        yield AgentCompleteEvent(summary="Hello!", tokens_used=5)

    runtime.stream = fake_stream
    return runtime


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = _test_settings(tmp_path)
    _write_test_skill(settings.skills_root)
    app = create_app(
        settings=settings,
        config_root=tmp_path / "config",
        runtime=_fake_runtime(),
    )
    return TestClient(app)


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ws_connect_receives_session_started(client: TestClient) -> None:
    with client.websocket_connect("/ws/chat") as ws:
        data = json.loads(ws.receive_text())
        assert data["type"] == "session_started"
        assert "session_id" in data


def test_ws_user_message_streams_events(client: TestClient) -> None:
    with client.websocket_connect("/ws/chat") as ws:
        started = json.loads(ws.receive_text())
        session_id = started["session_id"]

        ws.send_text(json.dumps({
            "type": "user_message",
            "content": "hello",
            "session_id": session_id,
        }))

        events = []
        while True:
            raw = ws.receive_text()
            event = json.loads(raw)
            events.append(event)
            if event["type"] in ("agent_complete", "error"):
                break

        types = [e["type"] for e in events]
        assert "agent_chunk" in types
        assert "agent_complete" in types


def test_ws_invalid_json_returns_error(client: TestClient) -> None:
    with client.websocket_connect("/ws/chat") as ws:
        _ = ws.receive_text()  # session_started
        ws.send_text("not valid json {{{")

        data = json.loads(ws.receive_text())
        assert data["type"] == "error"
        assert data["code"] == "INVALID_JSON"


def test_ws_unknown_message_type_returns_error(client: TestClient) -> None:
    with client.websocket_connect("/ws/chat") as ws:
        _ = ws.receive_text()  # session_started
        ws.send_text(json.dumps({"type": "unknown_type"}))

        data = json.loads(ws.receive_text())
        assert data["type"] == "error"
        assert data["code"] == "UNKNOWN_MESSAGE_TYPE"


def test_ws_tenant_and_agent_query_params(tmp_path: Path) -> None:
    settings = _test_settings(tmp_path)
    _write_test_skill(settings.skills_root)

    # Create agent config
    config_root = tmp_path / "config"
    agents_dir = config_root / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "my-agent.yaml").write_text(
        'agent_id: "my-agent"\nbound_skill_ids:\n  - "test/hello"\n'
    )

    app = create_app(settings=settings, config_root=config_root, runtime=_fake_runtime())
    client = TestClient(app)

    with client.websocket_connect("/ws/chat?tenant_id=risk&agent_id=my-agent") as ws:
        data = json.loads(ws.receive_text())
        assert data["type"] == "session_started"


def test_ws_multi_turn_session(client: TestClient) -> None:
    """Multiple messages in same session should not error."""
    with client.websocket_connect("/ws/chat") as ws:
        started = json.loads(ws.receive_text())
        session_id = started["session_id"]

        for content in ["first", "second", "third"]:
            ws.send_text(json.dumps({
                "type": "user_message",
                "content": content,
                "session_id": session_id,
            }))

            # Drain events until agent_complete
            while True:
                event = json.loads(ws.receive_text())
                if event["type"] in ("agent_complete", "error"):
                    break

            assert event["type"] == "agent_complete"
```

**Notes:**
- Uses `FastAPI.TestClient` with `websocket_connect()` — synchronous test wrapper for async WS.
- The `_fake_runtime()` returns a mock that yields predetermined events without calling any LLM.
- Tests are self-contained — each creates its own temp skills directory.
- All tests should pass with `pytest tests/integration/test_ws_chat.py`.

---

### Task C2: E2E Test (Mock LLM + SQLite)

**Create:** `tests/e2e/test_pipeline_e2e.py`

This test exercises the **full pipeline**: WebSocket → Orchestrator → SkillEngine → Sandbox → SQLite → events back over WebSocket. The only mock is the LLM.

#### Test fixture setup:

1. Create a temp skills directory with a test skill that queries SQLite.
2. Create a tenant config with resource env pointing to `/tmp/portfolio.db`.
3. Seed the SQLite database (reuse `examples/seed_data.py`).
4. Create a `LangGraphAdapter` with a patched `ChatOpenAI` replaced by a `FakeListChatModel`.
5. Create the FastAPI app with these fixtures.
6. Connect via WebSocket and send a query.

#### Fake LLM strategy:

Use `unittest.mock.patch` to replace `ChatOpenAI` at `deep_agent.runtime.langgraph_adapter.ChatOpenAI`. The replacement is a `FakeListChatModel` (from `langchain_core.language_models.fake_chat_models`) pre-loaded with two responses:

1. **Response 1:** `AIMessage` with a `tool_calls` entry for `execute_code` containing Python code that queries the SQLite DB.
2. **Response 2:** `AIMessage` with text content summarizing the results.

```python
"""End-to-end pipeline test with mock LLM + SQLite."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from deep_agent.api.app import create_app
from deep_agent.config import AppSettings


QUERY_CODE = """
import sqlite3, os
conn = sqlite3.connect(os.environ.get("DB_PATH", "/tmp/portfolio.db"))
rows = conn.execute("SELECT sym, qty, avg_cost FROM positions").fetchall()
conn.close()
for sym, qty, cost in rows:
    print(f"{sym}: qty={qty}, avg_cost={cost}")
"""


@pytest.fixture(autouse=True)
def seed_db() -> None:
    """Seed SQLite with example portfolio data."""
    # Add examples to path so we can import seed_data
    project_root = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(project_root))
    from examples.seed_data import seed
    seed()


@pytest.fixture
def e2e_app(tmp_path: Path) -> TestClient:
    """Create a full app with real SkillEngine + Sandbox but fake LLM."""
    # Write a test skill
    skills_root = tmp_path / "skills" / "test" / "query-db"
    skills_root.mkdir(parents=True)
    (skills_root / "SKILL.md").write_text(
        '---\nname: query-db\ndescription: Query database\nversion: "1.0"\n'
        'tags: [database, query, sql]\nallowed-tools: [execute_code]\n---\n'
        'Query the portfolio database and return results.\n',
        encoding="utf-8",
    )

    # Write tenant config with SQLite resource env
    config_root = tmp_path / "config"
    tenant_dir = config_root / "tenants" / "test"
    tenant_dir.mkdir(parents=True)
    (tenant_dir / "resources.yaml").write_text(
        'resource_aliases:\n  portfolio-db:\n    DB_PATH: "/tmp/portfolio.db"\n'
        '    DB_ENGINE: "sqlite"\n',
        encoding="utf-8",
    )

    # Write agent config binding to the test skill
    agents_dir = config_root / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "test-agent.yaml").write_text(
        'agent_id: "test-agent"\nbound_skill_ids:\n  - "test/query-db"\n',
        encoding="utf-8",
    )

    settings = AppSettings(
        openai_api_key="sk-fake",  # type: ignore[arg-type]
        skills_root=tmp_path / "skills",
    )

    # Fake LLM responses
    tool_call_response = AIMessage(
        content="",
        tool_calls=[{
            "name": "execute_code",
            "args": {"code": QUERY_CODE},
            "id": "call_1",
            "type": "tool_call",
        }],
    )
    final_response = AIMessage(content="Here are the portfolio positions from the database.")

    fake_responses = [tool_call_response, final_response]

    # Patch ChatOpenAI to return a fake model
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    fake_llm = FakeListChatModel(responses=[r.content or "" for r in fake_responses])
    # FakeListChatModel doesn't handle tool_calls properly, so we use a
    # different approach: patch the ChatOpenAI constructor to return a mock
    # that returns our pre-defined messages.
    from langchain_core.language_models import BaseChatModel
    from unittest.mock import MagicMock, AsyncMock

    class DeterministicChatModel(BaseChatModel):
        """A chat model that returns pre-determined responses."""
        responses: list[AIMessage]
        call_count: int = 0

        @property
        def _llm_type(self) -> str:
            return "fake"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            from langchain_core.outputs import ChatResult, ChatGeneration
            idx = min(self.call_count, len(self.responses) - 1)
            self.call_count += 1
            return ChatResult(generations=[ChatGeneration(message=self.responses[idx])])

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            return self._generate(messages, stop, run_manager, **kwargs)

    fake_model = DeterministicChatModel(responses=fake_responses)

    with patch("deep_agent.runtime.langgraph_adapter.ChatOpenAI", return_value=fake_model):
        from deep_agent.runtime.langgraph_adapter import LangGraphAdapter
        runtime = LangGraphAdapter()
        app = create_app(
            settings=settings,
            config_root=config_root,
            runtime=runtime,
        )
        yield TestClient(app)


@pytest.mark.timeout(30)
def test_full_pipeline_ws_to_sandbox(e2e_app: TestClient) -> None:
    """Full pipeline: WS → Orchestrator → SkillEngine → Sandbox → SQLite → events."""
    with e2e_app.websocket_connect("/ws/chat?tenant_id=test&agent_id=test-agent") as ws:
        # 1. Receive session_started
        started = json.loads(ws.receive_text())
        assert started["type"] == "session_started"
        session_id = started["session_id"]

        # 2. Send user message
        ws.send_text(json.dumps({
            "type": "user_message",
            "content": "Show me portfolio positions from the database",
            "session_id": session_id,
        }))

        # 3. Collect all events
        events: list[dict[str, Any]] = []
        while True:
            raw = ws.receive_text()
            event = json.loads(raw)
            events.append(event)
            if event["type"] in ("agent_complete", "error"):
                break

        event_types = [e["type"] for e in events]

        # 4. Assertions
        # Should have a skill_match (the test skill matches "database")
        assert "skill_match" in event_types, f"Expected skill_match in {event_types}"

        # Should have tool_call for execute_code
        tool_calls = [e for e in events if e["type"] == "tool_call"]
        assert len(tool_calls) >= 1
        assert tool_calls[0]["tool"] == "execute_code"

        # Should have tool_result with actual SQLite data
        tool_results = [e for e in events if e["type"] == "tool_result"]
        assert len(tool_results) >= 1
        result_output = tool_results[0]["output"]
        # The seeded data has AAPL, MSFT, GOOG
        assert "AAPL" in result_output or "aapl" in result_output.lower(), (
            f"Expected AAPL in tool result, got: {result_output[:500]}"
        )

        # Should end with agent_complete (no error)
        assert events[-1]["type"] == "agent_complete"

        # No error events
        errors = [e for e in events if e["type"] == "error"]
        assert errors == [], f"Unexpected errors: {errors}"
```

**Important implementation notes:**

1. The `DeterministicChatModel` is defined inline in the test. It subclasses `BaseChatModel` to be compatible with `create_react_agent`. The `_generate` method returns pre-determined `AIMessage` objects in sequence.

2. The `QUERY_CODE` uses `os.environ.get("DB_PATH")` to read the SQLite path from the resource env vars injected by the sandbox. The resource config sets `DB_PATH: "/tmp/portfolio.db"`.

3. The `DB_PATH` env var has the prefix `DB_` which is in `_ALLOWED_ENV_PREFIXES` in the sandbox, so it will be passed through.

4. The test seeds the DB using `examples/seed_data.seed()` which creates 3 positions (AAPL, MSFT, GOOG).

5. The `@pytest.mark.timeout(30)` prevents the test from hanging if something goes wrong.

6. **If `DeterministicChatModel` doesn't work cleanly with `create_react_agent`** (because LangGraph has specific expectations about message types during tool use), the implementer should fall back to mocking at the `RuntimeAdapter` level instead:
   - Create a `FakeRuntimeAdapter` that calls the REAL sandbox but returns predetermined tool calls.
   - This still tests SkillEngine matching + sandbox execution + WS streaming.
   - Use this as Plan B; attempt the `DeterministicChatModel` approach first.

---

## Phase D — Polish

### Task D1: Dev Run Script

**Create:** `scripts/run_dev.py`

```python
#!/usr/bin/env python3
"""Start the Deep Agent development server.

Usage:
    python scripts/run_dev.py

Requires:
    OPENAI_API_KEY environment variable (or .env file)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    # Ensure project root is on path
    project_root = Path(__file__).resolve().parent.parent
    os.chdir(project_root)

    # Check for API key
    if not os.environ.get("OPENAI_API_KEY"):
        env_file = project_root / ".env"
        if env_file.exists():
            print(f"Loading environment from {env_file}")
        else:
            print("WARNING: OPENAI_API_KEY not set and no .env file found.")
            print("The server will start but LLM calls will fail.")
            print("Set OPENAI_API_KEY or create a .env file.")
            print()

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))

    print(f"Starting Deep Agent dev server...")
    print(f"  Health: http://{host}:{port}/health")
    print(f"  WebSocket: ws://{host}:{port}/ws/chat")
    print(f"  Skills root: {os.environ.get('SKILLS_ROOT', 'skills/')}")
    print()

    import uvicorn

    uvicorn.run(
        "deep_agent.api.app:create_app",
        host=host,
        port=port,
        reload=True,
        factory=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
```

Make the file executable: `chmod +x scripts/run_dev.py`.

---

### Task D2: README Update

**Modify:** `README.md`

Replace the current minimal content with:

```markdown
# Deep Agent

Enterprise-grade AI agent framework with skills-driven architecture. Business desks author plain-language skill files (`SKILL.md`) — the framework handles discovery, matching, sandboxed execution, and streaming responses.

## Quick Start

```bash
# Prerequisites: Python 3.12+
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pip install -e .

# Set your OpenAI API key
export OPENAI_API_KEY="sk-..."

# Start the dev server
python scripts/run_dev.py
```

The server starts at `ws://localhost:8000/ws/chat`. Health check: `GET http://localhost:8000/health`.

## Run Tests

```bash
# Unit tests (no API key needed)
pytest tests/unit/

# Integration tests (no API key needed)
pytest tests/integration/

# E2E tests (no API key needed — uses mock LLM)
pytest tests/e2e/

# All tests
pytest tests/

# MCP integration tests (requires MCP server)
RUN_MCP_INTEGRATION=1 pytest tests/integration/test_mcp_manager.py
```

## Run the Example

```bash
# Portfolio VaR example (no API key needed)
python -m examples.run_example
```

## Architecture

See [docs/PRD.md](docs/PRD.md) for the full product specification and [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md) for skill authoring.

```
src/deep_agent/
├── api/           # FastAPI + WebSocket (this layer)
├── orchestrator/  # Agent orchestration flow
├── skills/        # Skill discovery, matching, loading
├── runtime/       # LLM routing + LangGraph adapter
├── sandbox/       # Sandboxed code execution
├── mcp/           # MCP server integration
├── tools/         # LangChain tool factories
└── models/        # Shared Pydantic models
```
```

---

## Implementation Checklist

| # | Task | Files | Effort | Dependencies |
|---|---|---|---|---|
| A1 | SkillInput + SkillQuality models | `models/skills.py`, `models/__init__.py`, `skills/parser.py`, tests | S | None |
| A2 | Fix db-query skill | `skills/common/db-query/scripts/requirements.txt` | XS | None |
| A3 | Config unit tests | `tests/unit/test_config.py` | S | None |
| A4 | Minor fixes (lint, dedup, stub, deps) | `mcp/config.py`, `models/context.py`, `pyproject.toml`, `requirements.txt`, tests | S | None |
| B1 | Session management | `api/session.py` | S | A4 |
| B2 | WebSocket schemas | `api/schemas.py` | XS | None |
| B3 | Config loaders | `api/config_loader.py`, tests | S | A4 |
| B4 | Multi-turn history | `runtime/protocol.py`, `runtime/langgraph_adapter.py`, `orchestrator/agent_orchestrator.py`, tests | M | None |
| B5 | FastAPI app + WS handler | `api/app.py`, `api/ws_chat.py`, `api/__init__.py` | L | B1, B2, B3, B4 |
| B6 | Wire quality.timeout | `orchestrator/agent_orchestrator.py`, `tools/execute_code.py`, tests | S | A1 |
| C1 | WebSocket integration tests | `tests/integration/test_ws_chat.py` | M | B5 |
| C2 | E2E test | `tests/e2e/test_pipeline_e2e.py` | L | B5 |
| D1 | Dev run script | `scripts/run_dev.py` | S | B5 |
| D2 | README update | `README.md` | XS | D1 |

**Total new files:** 7 (`session.py`, `schemas.py`, `config_loader.py`, `app.py`, `ws_chat.py`, `run_dev.py`, `test_pipeline_e2e.py`)
**Total modified files:** ~12
**Estimated effort:** ~2-3 days for an experienced developer, parallelizable across Phase A/B.

---

## Verification Criteria

After ALL tasks are complete, the following must pass:

```bash
# 1. All tests pass
pytest tests/ -v
# Expected: all pass, 0 failures, MCP integration tests may skip

# 2. Lint clean
ruff check src/ tests/

# 3. Type check clean
mypy src/

# 4. Health endpoint works
python scripts/run_dev.py &
curl http://localhost:8000/health
# Expected: {"status": "ok"}

# 5. WebSocket connects and responds
python -c "
import asyncio, json, websockets
async def test():
    async with websockets.connect('ws://localhost:8000/ws/chat') as ws:
        msg = await ws.recv()
        print(json.loads(msg))  # session_started
asyncio.run(test())
"

# 6. Example still runs
python -m examples.run_example
```
