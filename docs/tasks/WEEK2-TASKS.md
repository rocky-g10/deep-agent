# Week 2: LLM Router, RuntimeAdapter, and Sandbox — T2.1–T2.6

> **Reference:** `docs/IMPLEMENTATION_PLAN.md` — Week 2 section
> **Depends on:** T1.1–T1.6 (complete — scaffolding, models, skills engine all in place)
> **Scope:** LLM routing, runtime adapter protocol, LangGraph integration, sandbox execution, firm.stats stubs, unit tests

---

## Batch Layout

| Batch | Tasks | Parallelizable? | Rationale |
|-------|-------|-----------------|-----------|
| **1** | T2.1, T2.2, T2.4, T2.5 | Yes — all four | Each depends only on T1.2 (models) or nothing |
| **2** | T2.3 | No — sequential | Depends on T2.1 (LLMRouter) + T2.2 (RuntimeAdapter protocol) |
| **3** | T2.6 | No — sequential | Tests exercise T2.1, T2.3, T2.4, T2.5 |

---

## T2.1 — LLMRouter

Single-provider router that resolves `LLMConfig` from `AppSettings`. Phase 1 = OpenAI GPT-5 only; `task_hint` accepted but ignored.

### Files

| File | Action | Purpose |
|------|--------|---------|
| `src/deep_agent/runtime/__init__.py` | Modify | Add exports: `LLMRouter` |
| `src/deep_agent/runtime/llm_router.py` | Create | `LLMRouter` class |

### Interface

```python
# src/deep_agent/runtime/llm_router.py
from __future__ import annotations

from deep_agent.config import AppSettings
from deep_agent.models import LLMConfig, TenantContext


class LLMRouter:
    """Resolves LLM configuration from app settings.

    Phase 1: single-provider (OpenAI), no per-tenant overrides.
    """

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings

    def resolve(
        self,
        tenant: TenantContext,
        task_hint: str | None = None,
    ) -> LLMConfig:
        """Return LLMConfig for the given tenant.

        Args:
            tenant: Current tenant context (unused in Phase 1).
            task_hint: Optional hint like "summarize" or "code_gen" (ignored in Phase 1).

        Returns:
            LLMConfig with provider, model, temperature, max_tokens from settings.
        """
```

### Implementation Details

- Read `openai_model`, `openai_temperature`, `openai_max_tokens` from `self._settings`
- Return `LLMConfig(provider="openai", model=..., temperature=..., max_tokens=...)`
- `tenant` and `task_hint` are accepted but unused — placeholder for Phase 2 per-tenant routing

### Connections to Week 1

- Imports `LLMConfig` from `deep_agent.models.llm` (T1.2)
- Imports `TenantContext` from `deep_agent.models.context` (T1.2)
- Imports `AppSettings` from `deep_agent.config` (T1.1)

### Acceptance Criteria

1. `LLMRouter(settings).resolve(tenant)` returns `LLMConfig` with `model="gpt-5"`, `provider="openai"`
2. Model name and provider configurable via `AppSettings` / environment variables
3. `task_hint` parameter accepted but ignored in Phase 1
4. Returns consistent `LLMConfig` with all four fields populated

### Edge Cases

- `AppSettings` with non-default model (e.g., `"gpt-4o"`) — router must reflect it
- `task_hint=None` vs `task_hint="summarize"` — both return identical config in Phase 1

---

## T2.2 — RuntimeAdapter Protocol

Define the `RuntimeAdapter` protocol, `Agent` type alias, and `AgentResponse` model.

### Files

| File | Action | Purpose |
|------|--------|---------|
| `src/deep_agent/runtime/protocol.py` | Create | Protocol + types |
| `src/deep_agent/runtime/__init__.py` | Modify | Add exports: `RuntimeAdapter`, `Agent`, `AgentResponse` |

### Interface

```python
# src/deep_agent/runtime/protocol.py
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from deep_agent.models import AgentEvent, TenantContext


# Opaque agent handle — CompiledStateGraph for LangGraph, Any for protocol decoupling
Agent = Any


class AgentResponse(BaseModel):
    """Synchronous response from an agent invocation."""

    content: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    tokens_used: int = 0


@runtime_checkable
class RuntimeAdapter(Protocol):
    """Protocol for LLM runtime backends (PRD §3.2)."""

    def create_agent(
        self,
        model: str,
        tools: list[Any],
        system_prompt: str,
        **kwargs: Any,
    ) -> Agent:
        """Build a compiled agent graph with the given model, tools, and prompt."""
        ...

    async def invoke(
        self,
        agent: Agent,
        message: str,
        context: TenantContext,
    ) -> AgentResponse:
        """Run the agent synchronously and return the final response."""
        ...

    async def stream(
        self,
        agent: Agent,
        message: str,
        context: TenantContext,
    ) -> AsyncIterator[AgentEvent]:
        """Stream agent execution as AgentEvent objects."""
        ...
```

### Implementation Details

- `Agent = Any` — keeps protocol decoupled from LangGraph; concrete adapters internally cast to `CompiledStateGraph`
- `AgentResponse` is Pydantic for JSON serialization; `tool_calls` uses `dict[str, Any]` (not LangChain's `ToolCall` TypedDict) to stay framework-agnostic
- `@runtime_checkable` enables `isinstance()` checks in tests
- `tools: list[Any]` — will be `list[BaseTool]` in practice but protocol shouldn't import LangChain

### Connections to Week 1

- Imports `AgentEvent` from `deep_agent.models.events` (T1.2)
- Imports `TenantContext` from `deep_agent.models.context` (T1.2)

### Acceptance Criteria

1. `RuntimeAdapter` is a `typing.Protocol` with `create_agent`, `invoke`, `stream` methods
2. `Agent` defined as `Any` type alias
3. `AgentResponse` has `content: str`, `tool_calls: list[dict[str, Any]]`, `tokens_used: int`
4. Protocol passes `mypy --strict` checking
5. `@runtime_checkable` allows `isinstance(adapter, RuntimeAdapter)` in tests

### Edge Cases

- `AgentResponse` with empty `tool_calls` list — default factory handles it
- `tokens_used=0` default — backends that don't report usage still work

---

## T2.3 — LangGraphAdapter (deepagents + langgraph fallback)

Implement `LangGraphAdapter` conforming to `RuntimeAdapter`. Primary: `deepagents.create_deep_agent()`. Fallback: `langgraph.prebuilt.create_react_agent`.

### Files

| File | Action | Purpose |
|------|--------|---------|
| `src/deep_agent/runtime/langgraph_adapter.py` | Create | `LangGraphAdapter` class |
| `src/deep_agent/runtime/__init__.py` | Modify | Add export: `LangGraphAdapter` |

### Interface

```python
# src/deep_agent/runtime/langgraph_adapter.py
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from deep_agent.models import (
    AgentChunkEvent,
    AgentCompleteEvent,
    AgentEvent,
    ErrorEvent,
    TenantContext,
    ToolCallEvent,
    ToolResultEvent,
)
from deep_agent.runtime.protocol import Agent, AgentResponse, RuntimeAdapter

logger = logging.getLogger(__name__)

# --- Backend detection ---
try:
    from deepagents import create_deep_agent

    USING_DEEPAGENTS: bool = True
except ImportError:
    USING_DEEPAGENTS = False

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent


class LangGraphAdapter:
    """RuntimeAdapter implementation using deepagents/langgraph.

    Tries deepagents.create_deep_agent() first; falls back to
    langgraph.prebuilt.create_react_agent if unavailable or on error.
    """

    def create_agent(
        self,
        model: str,
        tools: list[Any],
        system_prompt: str,
        **kwargs: Any,
    ) -> Agent:
        """Build a compiled agent graph."""
        ...

    async def invoke(
        self,
        agent: Agent,
        message: str,
        context: TenantContext,
    ) -> AgentResponse:
        """Run agent to completion, return structured response."""
        ...

    async def stream(
        self,
        agent: Agent,
        message: str,
        context: TenantContext,
    ) -> AsyncIterator[AgentEvent]:
        """Yield AgentEvent objects from the agent's execution stream."""
        ...
```

### Implementation Details

**`create_agent()`:**
1. Instantiate `ChatOpenAI(model=model, temperature=kwargs.get("temperature", 0.0))`
2. If `USING_DEEPAGENTS`, try `create_deep_agent(model=llm, tools=tools, system_prompt=system_prompt)`
3. On failure (any `Exception`), log warning and fall through
4. Fallback: `create_react_agent(llm, tools, prompt=system_prompt)`
5. Log which backend was used at INFO level

**`invoke()`:**
1. Build input: `{"messages": [HumanMessage(content=message)]}`
2. Call `result = await agent.ainvoke(input)`
3. Extract final `AIMessage` from `result["messages"][-1]`
4. Build `AgentResponse(content=msg.content, tool_calls=[tc for tc in msg.tool_calls], tokens_used=msg.usage_metadata.get("total_tokens", 0) if msg.usage_metadata else 0)`

**`stream()` — event translation from LangGraph `astream(stream_mode="messages")`:**
1. Use `agent.astream(input, stream_mode="messages")`
2. Each yielded item is a tuple `(message_chunk, metadata)` where `message_chunk` is an `AIMessageChunk` or `ToolMessage`
3. Translation rules:
   - `AIMessageChunk` with non-empty `content` and no `tool_call_chunks` → yield `AgentChunkEvent(content=chunk.content)`
   - `AIMessageChunk` with `tool_call_chunks` → accumulate chunks; when complete tool call assembled, yield `ToolCallEvent(tool=name, input=args)`
   - `ToolMessage` → yield `ToolResultEvent(tool=msg.name, output=msg.content, files={})`
4. After stream exhaustion → yield `AgentCompleteEvent(summary=accumulated_content, tokens_used=total_tokens)`
5. Wrap entire stream in try/except → on error yield `ErrorEvent(code="RUNTIME_ERROR", message=str(e))`

**Tool call chunk accumulation:**
- LangGraph streams tool calls as multiple `AIMessageChunk` objects with partial `tool_call_chunks`
- Track by `index` field: buffer partial name/args until a complete tool call is detected
- A tool call is complete when the next chunk has a different `index` or the stream transitions to a `ToolMessage`

### Connections to Week 1

- Imports all `AgentEvent` subtypes from `deep_agent.models.events` (T1.2)
- Imports `TenantContext` from `deep_agent.models.context` (T1.2)

### Connections to Week 2

- Implements `RuntimeAdapter` from `deep_agent.runtime.protocol` (T2.2)
- Used by future `AgentOrchestrator` (T3.4) which passes `LLMConfig` from `LLMRouter` (T2.1)

### Acceptance Criteria

1. `create_agent()` tries `deepagents` first, falls back to `create_react_agent` on failure
2. `invoke()` runs graph, returns `AgentResponse` with content and token count
3. `stream()` yields `AgentChunkEvent` per LLM token, `ToolCallEvent` on tool invocation, `ToolResultEvent` on tool return, `AgentCompleteEvent` at end
4. Errors caught and yielded as `ErrorEvent`
5. Adapter is stateless — all state lives in the graph instance
6. Module-level `USING_DEEPAGENTS: bool` flag logged on import

### Edge Cases

- `deepagents` not installed → `USING_DEEPAGENTS=False`, uses `create_react_agent` directly
- `create_deep_agent()` raises at runtime → falls back to `create_react_agent`
- LLM returns empty content → `AgentChunkEvent` not yielded, `AgentCompleteEvent.summary=""`
- Graph runs with no tool calls → stream yields only chunk events + complete event
- `usage_metadata` is `None` → `tokens_used=0`

---

## T2.4 — SandboxManager Protocol + PythonSubprocessSandbox

Define `SandboxManager` protocol and implement `PythonSubprocessSandbox` for safe code execution.

### Files

| File | Action | Purpose |
|------|--------|---------|
| `src/deep_agent/sandbox/protocol.py` | Create | `SandboxManager` protocol |
| `src/deep_agent/sandbox/subprocess_sandbox.py` | Create | `PythonSubprocessSandbox` class |
| `src/deep_agent/sandbox/__init__.py` | Modify | Add exports: `SandboxManager`, `PythonSubprocessSandbox` |

### Protocol Interface

```python
# src/deep_agent/sandbox/protocol.py
from __future__ import annotations

from typing import Protocol, runtime_checkable

from deep_agent.models import ExecuteResult, ResourceLimits


@runtime_checkable
class SandboxManager(Protocol):
    """Protocol for sandboxed code execution (PRD §4.2)."""

    async def execute(
        self,
        code: str,
        timeout: int = 60,
        resource_limits: ResourceLimits | None = None,
        env: dict[str, str] | None = None,
        files_in: dict[str, bytes] | None = None,
    ) -> ExecuteResult:
        """Execute Python code in isolation.

        Args:
            code: Python source code to execute.
            timeout: Max execution time in seconds.
            resource_limits: Optional CPU/memory/output constraints.
            env: Additional environment variables for the subprocess.
            files_in: Files to write into the working directory before execution.

        Returns:
            ExecuteResult with stdout, stderr, exit_code, output_files.
        """
        ...

    async def cleanup(self, execution_id: str) -> None:
        """Remove the temp directory for a completed execution."""
        ...
```

### Implementation Interface

```python
# src/deep_agent/sandbox/subprocess_sandbox.py
from __future__ import annotations

import asyncio
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from deep_agent.models import ExecuteResult, ResourceLimits


class PythonSubprocessSandbox:
    """SandboxManager implementation using Python subprocesses.

    Spawns `python3 code.py` in a temp directory with resource limits,
    timeout enforcement, and output file collection.
    """

    def __init__(
        self,
        stubs_path: Path | None = None,
        max_tracked: int = 100,
    ) -> None:
        """Initialize sandbox.

        Args:
            stubs_path: Path to stubs/ directory for PYTHONPATH injection.
            max_tracked: Maximum number of tracked executions before auto-eviction.
        """
        self._stubs_path = stubs_path
        self._max_tracked = max_tracked
        self._executions: dict[str, Path] = {}
        self._lock = threading.Lock()

    async def execute(
        self,
        code: str,
        timeout: int = 60,
        resource_limits: ResourceLimits | None = None,
        env: dict[str, str] | None = None,
        files_in: dict[str, bytes] | None = None,
    ) -> ExecuteResult:
        """Execute Python code in a subprocess sandbox."""
        ...

    async def cleanup(self, execution_id: str) -> None:
        """Remove temp directory for the given execution."""
        ...
```

### Implementation Details

**`execute()` flow:**
1. Generate `execution_id = uuid.uuid4().hex`
2. Create temp dir: `tempfile.mkdtemp(prefix=f"sandbox-{execution_id[:8]}-")`
3. Create `output/` subdirectory inside temp dir
4. If `files_in` provided, write each file into temp dir
5. Build `code.py` content:
   - If `resource_limits` provided, prepend resource-limiting preamble:
     ```python
     import resource as _resource
     _mem_bytes = {resource_limits.memory_mb} * 1024 * 1024
     _resource.setrlimit(_resource.RLIMIT_AS, (_mem_bytes, _mem_bytes))
     del _resource, _mem_bytes
     ```
   - Append the user's code
6. Write `code.py` to temp dir
7. Build subprocess environment:
   - Start with `os.environ.copy()` (inherit base env)
   - If `self._stubs_path`, prepend to `PYTHONPATH`
   - Merge in `env` dict (user-provided vars override)
8. Record start time
9. Spawn: `asyncio.create_subprocess_exec("python3", "code.py", cwd=tmp_dir, env=sub_env, stdout=PIPE, stderr=PIPE)`
10. Apply timeout: `asyncio.wait_for(proc.communicate(), timeout=timeout)`
11. On `asyncio.TimeoutError`: kill process, set `exit_code=-1`, append timeout message to stderr
12. Truncate stdout/stderr to `max_output_bytes` (from `resource_limits` or default 10MB)
13. Collect output files: walk `output/` dir, read each file, base64-encode into `output_files` dict
14. Compute `duration_ms = int((time.monotonic() - start) * 1000)`
15. Track execution: `self._executions[execution_id] = tmp_dir_path`
16. If `len(self._executions) > self._max_tracked`, evict oldest entries
17. Return `ExecuteResult(execution_id=execution_id, exit_code=..., stdout=..., stderr=..., output_files=..., duration_ms=...)`

**`cleanup()` flow:**
1. Pop `execution_id` from `self._executions` under lock
2. If found and path exists, `shutil.rmtree(path)`
3. If not found, no-op (idempotent)

**Resource limit preamble approach:**
- `resource.RLIMIT_AS` is injected as a Python preamble in `code.py` rather than via `preexec_fn`
- This works with `asyncio.create_subprocess_exec` which doesn't support `preexec_fn`
- The preamble uses `import resource` and sets limits before user code runs
- Variables are deleted after use to avoid polluting user namespace

### Connections to Week 1

- Imports `ExecuteResult` from `deep_agent.models.sandbox` (T1.2)
- Imports `ResourceLimits` from `deep_agent.models.sandbox` (T1.2)

### Acceptance Criteria

1. `SandboxManager` protocol has `execute()` and `cleanup()` matching PRD §4.2
2. `execute(code)` creates temp dir, spawns subprocess, captures output, returns `ExecuteResult`
3. `cleanup(execution_id)` removes the temp directory
4. Timeout kills the process and returns non-zero exit code with timeout info in stderr
5. Memory limit is enforced via `resource.RLIMIT_AS` preamble
6. Files written to `output/` appear in `ExecuteResult.output_files` (base64-encoded)
7. `stubs/` directory added to `PYTHONPATH` so sandbox code can `import firm.stats`
8. `files_in` content is written to temp dir before execution

### Edge Cases

- **Timeout**: `asyncio.TimeoutError` → kill process, report in stderr
- **Syntax error**: subprocess exits non-zero, error in stderr
- **No output files**: `output_files` is empty dict
- **Large stdout**: truncated to `max_output_bytes`
- **cleanup non-existent ID**: no-op, no exception
- **Concurrent executions**: `_lock` guards `_executions` dict
- **Binary output files** (e.g., PNG): read as bytes, base64-encode to string for `output_files`

---

## T2.5 — firm.stats Stubs

Stub implementation of `firm.stats` with real math using pandas. Sandbox code can `import firm.stats` when `stubs/` is on `PYTHONPATH`.

### Files

| File | Action | Purpose |
|------|--------|---------|
| `stubs/firm/__init__.py` | Create | Package marker |
| `stubs/firm/stats.py` | Create | `zscore()`, `moving_avg()` implementations |

### Interface

```python
# stubs/firm/stats.py
"""Stub implementation of firm.stats with real math.

Provides rolling statistical functions for financial data analysis.
Usage: Add stubs/ to PYTHONPATH, then `from firm.stats import zscore, moving_avg`.
"""
from __future__ import annotations

import pandas as pd


def moving_avg(series: pd.Series, window: int) -> pd.Series:
    """Compute rolling mean over the given window.

    Args:
        series: Input time series.
        window: Rolling window size.

    Returns:
        Series with rolling mean. NaN for positions before window is full.
    """
    ...


def zscore(series: pd.Series, window: int) -> pd.Series:
    """Compute rolling z-score: (x - rolling_mean) / rolling_std.

    Args:
        series: Input time series.
        window: Rolling window size.

    Returns:
        Series with rolling z-scores. NaN where window is incomplete or std is zero.
    """
    ...
```

### Implementation Details

```python
def moving_avg(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window).mean()


def zscore(series: pd.Series, window: int) -> pd.Series:
    roll = series.rolling(window=window)
    mean = roll.mean()
    std = roll.std()  # ddof=1 (Bessel's correction) — standard for sample z-scores
    return (series - mean) / std
```

- `rolling().std()` uses `ddof=1` by default — correct for sample statistics in finance
- Division by zero (when `std=0`) produces `NaN` automatically via pandas
- Window larger than series length → all `NaN` (native pandas behavior with `min_periods=window`)
- Empty series → empty series returned

### `stubs/firm/__init__.py`

```python
"""Stub implementation of the firm internal library."""
```

### Connections to Week 2

- Used by `PythonSubprocessSandbox` (T2.4) via `PYTHONPATH` injection
- Referenced in `skills/equities/zscore-monitor/SKILL.md` instructions (T1.5)

### Acceptance Criteria

1. `from firm.stats import zscore, moving_avg` works when `stubs/` is on `PYTHONPATH`
2. `moving_avg(series, window)` computes rolling mean via `pandas.Series.rolling().mean()`
3. `zscore(series, window)` computes `(x - rolling_mean) / rolling_std`
4. Both accept `pandas.Series` and return `pandas.Series`
5. Window larger than series → NaN for early values
6. Empty series → empty series

### Edge Cases

- Empty `pd.Series()` → returns empty `pd.Series()`
- `window > len(series)` → all NaN values
- `window=1` for zscore → all NaN (std of single element is NaN with ddof=1)
- NaN values in input → NaN propagates through rolling calculations
- Single-element series → NaN for any `window >= 1` in zscore

---

## T2.6 — Unit Tests for Runtime and Sandbox

Comprehensive tests for LLMRouter, LangGraphAdapter (mocked), PythonSubprocessSandbox, and firm.stats.

### Files

| File | Action | Purpose |
|------|--------|---------|
| `tests/unit/test_llm_router.py` | Create | LLMRouter tests |
| `tests/unit/test_sandbox.py` | Create | PythonSubprocessSandbox tests |
| `tests/unit/test_langgraph_adapter.py` | Create | LangGraphAdapter tests (mocked LLM) |
| `tests/unit/test_firm_stats.py` | Create | firm.stats stub tests |

### test_llm_router.py

```python
# Tests for LLMRouter
# Fixtures: use monkeypatch to set OPENAI_API_KEY env var, construct AppSettings

def test_resolve_returns_default_config() -> None:
    """LLMRouter with default settings returns gpt-5 / openai."""

def test_resolve_with_custom_model(monkeypatch) -> None:
    """Override OPENAI_MODEL env var → resolve reflects custom model."""

def test_resolve_ignores_task_hint() -> None:
    """task_hint='summarize' returns same config as task_hint=None."""

def test_resolve_uses_custom_temperature(monkeypatch) -> None:
    """Override OPENAI_TEMPERATURE → resolve reflects it."""
```

**Patterns:** Use `monkeypatch.setenv()` to configure `AppSettings`, same as `test_models.py` pattern. Clear `get_settings` cache between tests.

### test_sandbox.py

```python
# Tests for PythonSubprocessSandbox
# All tests are async (asyncio_mode="auto")

import pytest

@pytest.mark.timeout(10)
async def test_execute_simple_print() -> None:
    """print('hello') → stdout='hello\\n', exit_code=0."""

@pytest.mark.timeout(10)
async def test_execute_output_file(tmp_path: Path) -> None:
    """Code writes to output/chart.png → appears in output_files."""

@pytest.mark.timeout(15)
async def test_execute_timeout() -> None:
    """time.sleep(100) with timeout=2 → exit_code!=0, stderr mentions timeout."""

@pytest.mark.timeout(10)
async def test_execute_syntax_error() -> None:
    """Malformed Python → exit_code!=0, stderr has SyntaxError."""

@pytest.mark.timeout(10)
async def test_execute_env_var_injection() -> None:
    """Code reads os.environ['TEST_VAR'] → value matches injected env."""

@pytest.mark.timeout(10)
async def test_execute_files_in() -> None:
    """files_in={'data.csv': b'a,b\\n1,2'} → code reads file successfully."""

@pytest.mark.timeout(10)
async def test_cleanup_removes_directory() -> None:
    """After execute + cleanup, temp dir no longer exists."""

async def test_cleanup_nonexistent_id_is_noop() -> None:
    """cleanup('nonexistent') does not raise."""

@pytest.mark.timeout(10)
async def test_execute_stubs_pythonpath() -> None:
    """Code does 'from firm.stats import zscore' with stubs_path set → succeeds."""
```

**Patterns:** Use `pytest.mark.timeout()` to prevent hanging. Use real subprocess execution (not mocked). Construct `PythonSubprocessSandbox(stubs_path=Path("stubs/"))` with real stubs path.

### test_langgraph_adapter.py

```python
# Tests for LangGraphAdapter — ALL use mocked LLM (no real OpenAI calls)

from unittest.mock import AsyncMock, MagicMock, patch

def test_create_agent_returns_agent() -> None:
    """create_agent() with mocked ChatOpenAI returns a compiled graph."""

def test_using_deepagents_flag_logged() -> None:
    """Module-level USING_DEEPAGENTS flag is a bool."""

async def test_invoke_returns_agent_response() -> None:
    """Mocked graph.ainvoke() → AgentResponse with content and tokens."""

async def test_stream_yields_chunk_events() -> None:
    """Mocked graph.astream() with AIMessageChunks → AgentChunkEvent objects."""

async def test_stream_yields_tool_events() -> None:
    """Mocked tool call + result → ToolCallEvent + ToolResultEvent."""

async def test_stream_ends_with_complete_event() -> None:
    """Stream terminates with AgentCompleteEvent."""

async def test_stream_error_yields_error_event() -> None:
    """Exception during streaming → ErrorEvent yielded."""

def test_fallback_to_create_react_agent() -> None:
    """When create_deep_agent raises, falls back to create_react_agent."""
```

**Patterns:** Use `unittest.mock.patch` to mock `ChatOpenAI`, `create_react_agent`, `create_deep_agent`. Use `AsyncMock` for async graph methods. Build fake `AIMessage` / `AIMessageChunk` objects to drive the stream.

### test_firm_stats.py

```python
# Tests for stubs/firm/stats.py
# Note: add stubs/ to sys.path in conftest or at module level

import pandas as pd

def test_moving_avg_basic() -> None:
    """Known input → rolling mean matches expected values."""

def test_moving_avg_empty_series() -> None:
    """Empty Series → empty Series returned."""

def test_moving_avg_window_larger_than_series() -> None:
    """Window=10 on 3-element series → all NaN."""

def test_zscore_basic() -> None:
    """Known input → z-scores match manual calculation."""

def test_zscore_empty_series() -> None:
    """Empty Series → empty Series returned."""

def test_zscore_window_1_returns_nan() -> None:
    """Window=1 → all NaN (std is NaN with ddof=1)."""

def test_zscore_nan_propagation() -> None:
    """Series with NaN → NaN propagates in rolling window."""
```

**Patterns:** Use `pd.testing.assert_series_equal()` for floating-point comparisons. Add `stubs/` to `sys.path` at test module level or via conftest fixture.

### conftest.py Updates

Add to `tests/conftest.py`:

```python
import sys
from pathlib import Path

# Make stubs/ importable for firm.stats tests
_stubs_dir = Path(__file__).resolve().parent.parent / "stubs"
if str(_stubs_dir) not in sys.path:
    sys.path.insert(0, str(_stubs_dir))
```

### Acceptance Criteria

1. All tests pass with `pytest tests/unit/ -v`
2. At least 25 test cases across all four files
3. LLMRouter: resolve correct model, config override, task_hint ignored
4. Sandbox: simple execution, file output, timeout, error handling, env vars, files_in, cleanup, stubs PYTHONPATH
5. LangGraphAdapter: mocked LLM — no real OpenAI calls; correct event types
6. firm.stats: rolling mean, z-score, edge cases (empty, window, NaN)
7. Tests are independent (no shared mutable state)

### Edge Cases Tested

- Sandbox timeout with `pytest.mark.timeout` safety net
- Concurrent sandbox executions (covered by thread-safe `_lock`)
- Empty/NaN series in firm.stats
- Missing `deepagents` package → fallback path in adapter

---

## Design Principles (apply to ALL code)

1. **Protocol-based interfaces** — `RuntimeAdapter` and `SandboxManager` are `typing.Protocol`
2. **Zero circular imports** — `models/` has no internal deps; `runtime/` and `sandbox/` import only from `models/`
3. **Type annotations** on ALL functions and methods
4. **Docstrings** on all public classes and methods
5. **One concern per file** — protocol separate from implementation
6. **Async-first** — `invoke()`, `stream()`, `execute()`, `cleanup()` are all async
7. **Dependency injection** — `LLMRouter` takes `AppSettings`; `PythonSubprocessSandbox` takes `stubs_path`

---

## Validation

After all implementation, run:
```bash
source .venv/bin/activate
ruff check src/ tests/ stubs/
mypy src/
pytest tests/unit/ -v
python -c "from deep_agent.runtime import LLMRouter, RuntimeAdapter, LangGraphAdapter; print('runtime OK')"
python -c "from deep_agent.sandbox import SandboxManager, PythonSubprocessSandbox; print('sandbox OK')"
PYTHONPATH=stubs python -c "from firm.stats import zscore, moving_avg; print('stubs OK')"
```

All must pass cleanly.
