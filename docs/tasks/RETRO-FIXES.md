# Retroactive Code Review — Fix Specification

> **Created:** 2026-03-12
> **Source:** Full code review of Weeks 1-3 (src/deep_agent/ + tests/)
> **Scope:** 7 CRITICAL + 14 IMPORTANT fixes
> **Target:** All fixes must land before Week 4 (WebSocket API)

---

## Summary Table

| ID | Severity | File | Title | Depends On |
|----|----------|------|-------|------------|
| FIX-1 | CRITICAL | `src/deep_agent/sandbox/subprocess_sandbox.py` | Path traversal in `files_in` | — |
| FIX-2 | CRITICAL | `src/deep_agent/mcp/config.py` | Path traversal in MCP config loader | — |
| FIX-3 | CRITICAL | `src/deep_agent/sandbox/subprocess_sandbox.py` | Environment leakage to sandbox subprocess | — |
| FIX-4 | CRITICAL | `src/deep_agent/tools/execute_code.py` | `_build_db_env` overwrites env vars per alias | — |
| FIX-5 | CRITICAL | `src/deep_agent/tools/execute_code.py` | `DB_PASS` is always empty string | — |
| FIX-6 | CRITICAL | `src/deep_agent/sandbox/subprocess_sandbox.py` | Symlink information disclosure in output collection | — |
| FIX-7 | CRITICAL | `src/deep_agent/sandbox/subprocess_sandbox.py` | `env_overrides` allows injecting dangerous env vars | FIX-3 |
| FIX-8 | IMPORTANT | `src/deep_agent/database/registry.py` | `get_connection` hardcodes `engine="clickhouse"` | — |
| FIX-9 | IMPORTANT | `src/deep_agent/mcp/manager.py` | `disconnect()` never closes underlying client | — |
| FIX-10 | IMPORTANT | `src/deep_agent/mcp/manager.py` | `connect()` not idempotent — leaks clients | FIX-9 |
| FIX-11 | IMPORTANT | `src/deep_agent/skills/engine.py` | `_scan_filesystem` crashes on single malformed file | — |
| FIX-12 | IMPORTANT | `src/deep_agent/models/context.py` | `TenantContext` mutable lists despite `frozen=True` | — |
| FIX-13 | IMPORTANT | `src/deep_agent/orchestrator/agent_orchestrator.py` | `confidence` hardcoded to `1.0` in `SkillMatchEvent` | — |
| FIX-14 | IMPORTANT | `src/deep_agent/runtime/langgraph_adapter.py` | `invoke` vs `stream` inconsistent error handling | — |
| FIX-15 | IMPORTANT | `src/deep_agent/runtime/langgraph_adapter.py` | `max_tokens` not forwarded to `ChatOpenAI` | — |
| FIX-16 | IMPORTANT | Multiple test files | mypy real type errors (18 issues) | — |
| FIX-17 | IMPORTANT | `src/deep_agent/skills/parser.py` | `_derive_skill_id` uses first `"skills"` in path | — |
| FIX-18 | IMPORTANT | `src/deep_agent/mcp/config.py` | TOCTOU race in `load_mcp_config` | — |
| FIX-19 | IMPORTANT | `src/deep_agent/skills/engine.py` | No logging in skills engine | — |
| FIX-20 | IMPORTANT | `tests/conftest.py` | Duplicated `_tenant()` helpers across 6+ test files | — |
| FIX-21 | IMPORTANT | `src/deep_agent/orchestrator/agent_orchestrator.py` | `_build_system_prompt` `all_skills` typed as `list[Any]` | — |

---

## FIX-1: Path traversal in sandbox `files_in`

**Severity:** CRITICAL

**File:** `src/deep_agent/sandbox/subprocess_sandbox.py`

**Problem:** Lines 43-47 — `target = temp_dir / rel_path` does not validate that the resolved path stays within `temp_dir`. If `rel_path` is `"../../etc/crontab"` or an absolute path like `"/tmp/evil.py"`, `Path.__truediv__` resolves outside the sandbox temp directory, allowing arbitrary file writes to the host filesystem.

**Fix:** After computing `target`, resolve both paths and validate containment. Add this validation after line 45:

```python
# Lines 43-47 — replace with:
if files_in:
    for rel_path, file_bytes in files_in.items():
        target = (temp_dir / rel_path).resolve()
        if not target.is_relative_to(temp_dir.resolve()):
            raise ValueError(
                f"Path traversal detected: '{rel_path}' escapes sandbox directory"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(file_bytes)
```

**Acceptance criteria:**
- `await sandbox.execute(code="", files_in={"../../etc/evil": b"x"})` raises `ValueError` with message containing "Path traversal"
- `await sandbox.execute(code="", files_in={"/tmp/evil": b"x"})` raises `ValueError`
- `await sandbox.execute(code="", files_in={"data/input.csv": b"ok"})` still works (nested relative paths)
- Add test `test_files_in_path_traversal_blocked` to `tests/unit/test_sandbox.py`

---

## FIX-2: Path traversal in MCP config loader

**Severity:** CRITICAL

**File:** `src/deep_agent/mcp/config.py`

**Problem:** Line 44 — `config_root / "tenants" / tenant.tenant_id / "mcp.json"` does not sanitize `tenant.tenant_id`. A value like `"../../etc"` escapes the config directory and could read arbitrary JSON files.

**Fix:** Resolve the constructed path and validate it stays under `config_root`:

```python
# Replace lines 44-48 with:
config_path = (config_root / "tenants" / tenant.tenant_id / "mcp.json").resolve()
safe_root = (config_root / "tenants").resolve()
if not config_path.is_relative_to(safe_root):
    raise MCPConfigError(
        f"Invalid tenant_id '{tenant.tenant_id}': path traversal detected"
    )

if not config_path.exists():
    logger.debug("No MCP config found at %s — using empty config", config_path)
    return MCPConfig()
```

**Acceptance criteria:**
- `load_mcp_config(TenantContext(tenant_id="../../etc", ...))` raises `MCPConfigError` with "path traversal"
- Normal tenant IDs like `"equities"` continue to work
- Add test `test_load_mcp_config_path_traversal` to `tests/unit/test_mcp_config.py`

---

## FIX-3: Environment leakage to sandbox subprocess

**Severity:** CRITICAL

**File:** `src/deep_agent/sandbox/subprocess_sandbox.py`

**Problem:** Line 114 — `os.environ.copy()` exposes the full parent process environment (including `OPENAI_API_KEY`, database passwords, AWS credentials, etc.) to executed sandbox code. The PRD (Section 6) explicitly requires that credentials never be visible to executed code beyond injected DB env vars.

**Fix:** Replace the full env copy with a minimal allowlisted base environment:

```python
# Replace line 114 with:
_SANDBOX_ENV_ALLOWLIST = frozenset({
    "PATH", "HOME", "USER", "LANG", "LC_ALL", "LC_CTYPE",
    "TMPDIR", "TMP", "TEMP", "TERM",
})

# In _build_process_env:
process_env = {
    key: val
    for key, val in os.environ.items()
    if key in _SANDBOX_ENV_ALLOWLIST
}
```

Move `_SANDBOX_ENV_ALLOWLIST` to module level (above the class). Keep the rest of `_build_process_env` unchanged — the `PYTHONPATH` injection and `env_overrides` application still happen after.

**Acceptance criteria:**
- A sandbox execution running `import os; print(os.environ.get("OPENAI_API_KEY", "ABSENT"))` prints `ABSENT`
- A sandbox execution running `import os; print(os.environ.get("PATH"))` prints a valid `PATH`
- `PYTHONPATH` injection (stubs) still works
- `env_overrides` (DB env vars) still get applied
- Update existing test `test_execute_env_var_injection` to verify allowlisted vars work
- Add test `test_sandbox_env_does_not_leak_secrets` that sets `os.environ["SECRET_TOKEN"] = "hunter2"` via monkeypatch and verifies the sandbox code cannot read it

---

## FIX-4: `_build_db_env` overwrites env vars per alias

**Severity:** CRITICAL

**File:** `src/deep_agent/tools/execute_code.py`

**Problem:** Lines 58-68 — The `for` loop over `db_registry.list_aliases()` overwrites `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER` on each iteration. For multi-database tenants, only the last alias's connection info survives.

**Fix:** Prefix env vars with the alias name (uppercased, hyphens replaced with underscores):

```python
def _build_db_env(db_registry: DatabaseRegistry, tenant: TenantContext) -> dict[str, str]:
    """Build database-related environment variables from accessible aliases."""
    env: dict[str, str] = {}
    aliases = db_registry.list_aliases(tenant)
    for alias_info in aliases:
        try:
            conn = db_registry.get_connection(alias_info.alias, tenant)
            prefix = alias_info.alias.upper().replace("-", "_")
            env[f"{prefix}_HOST"] = conn.host
            env[f"{prefix}_PORT"] = str(conn.port)
            env[f"{prefix}_NAME"] = conn.database
            env[f"{prefix}_USER"] = _extract_db_user(conn.credentials_ref)
            env[f"{prefix}_PASS"] = _extract_db_pass(conn, db_registry)
        except Exception:
            logger.warning("Failed to resolve connection for alias %s", alias_info.alias)

    # Backwards-compatible: also set unprefixed vars from the first alias
    if aliases:
        first = aliases[0]
        try:
            conn = db_registry.get_connection(first.alias, tenant)
            env["DB_HOST"] = conn.host
            env["DB_PORT"] = str(conn.port)
            env["DB_NAME"] = conn.database
            env["DB_USER"] = _extract_db_user(conn.credentials_ref)
            env["DB_PASS"] = _extract_db_pass(conn, db_registry)
        except Exception:
            pass

    return env
```

Note: `_extract_db_pass` is defined in FIX-5 below — implement both together.

**Acceptance criteria:**
- With one alias `ch-equities`, env contains both `CH_EQUITIES_HOST` and `DB_HOST`
- With two aliases, both get prefixed vars and `DB_*` comes from the first
- Update `test_execute_code_tool_injects_db_env` to verify prefixed vars exist
- Add `test_build_db_env_multiple_aliases` testing two aliases

---

## FIX-5: `DB_PASS` is always empty string

**Severity:** CRITICAL

**File:** `src/deep_agent/tools/execute_code.py`

**Problem:** Line 65 — `env["DB_PASS"] = ""` hardcodes an empty password. `AppSettings.clickhouse_password` is a `SecretStr | None` that is never read. The sandbox code cannot authenticate to any database.

**Fix:** Add a helper function that extracts the password from settings, and use it in `_build_db_env`. This requires `_build_db_env` to accept `AppSettings` or the registry must expose a password getter.

The cleanest approach: pass `AppSettings` to the tool factory and thread it into `_build_db_env`:

```python
# In create_execute_code_tool, add settings parameter:
def create_execute_code_tool(
    sandbox: SandboxManager,
    db_registry: DatabaseRegistry,
    tenant: TenantContext,
    settings: AppSettings,    # <-- add this
) -> BaseTool:
    db_env = _build_db_env(db_registry=db_registry, tenant=tenant, settings=settings)
    ...

# Add helper:
def _extract_db_pass(settings: AppSettings) -> str:
    """Extract database password from settings."""
    if settings.clickhouse_password is not None:
        return settings.clickhouse_password.get_secret_value()
    return ""
```

Then in `_build_db_env`, replace `env["DB_PASS"] = ""` with `env["DB_PASS"] = _extract_db_pass(settings)`.

Update `agent_orchestrator.py` line 94 to pass `settings=self._db_registry._settings` or add a `settings` param to the orchestrator constructor.

**Acceptance criteria:**
- `_build_db_env` output includes a non-empty `DB_PASS` when `clickhouse_password` is set in `AppSettings`
- `DB_PASS` is `""` when `clickhouse_password` is `None`
- Password is never logged (verify no `logger.debug/info` calls print the env dict)
- Existing tests updated to pass the new `settings` argument
- Add test `test_db_pass_populated_from_settings`

---

## FIX-6: Symlink information disclosure in sandbox output collection

**Severity:** CRITICAL

**File:** `src/deep_agent/sandbox/subprocess_sandbox.py`

**Problem:** Lines 158-167 — `_collect_output_files` uses `output_dir.rglob("*")` which follows symlinks by default. Malicious sandbox code can create symlinks pointing to sensitive files (e.g., `ln -s /etc/shadow output/shadow`), which are then base64-encoded and returned to the caller.

**Fix:** Add a symlink check before reading each file:

```python
def _collect_output_files(output_dir: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    if not output_dir.exists():
        return files

    resolved_output = output_dir.resolve()
    for file_path in sorted(output_dir.rglob("*")):
        if not file_path.is_file():
            continue
        # Skip symlinks — prevents information disclosure
        if file_path.is_symlink():
            continue
        # Verify resolved path stays within output directory
        if not file_path.resolve().is_relative_to(resolved_output):
            continue
        rel = file_path.relative_to(output_dir).as_posix()
        files[rel] = base64.b64encode(file_path.read_bytes()).decode("utf-8")
    return files
```

**Acceptance criteria:**
- Sandbox code that runs `import os; os.symlink("/etc/passwd", "output/leaked")` produces an `output_files` dict that does NOT contain `"leaked"`
- Regular files in `output/` are still collected
- Add test `test_output_files_symlinks_skipped` to `tests/unit/test_sandbox.py`

---

## FIX-7: `env_overrides` allows injecting dangerous env vars

**Severity:** CRITICAL

**File:** `src/deep_agent/sandbox/subprocess_sandbox.py`

**Problem:** Lines 124-125 — `process_env.update(env_overrides)` allows overriding any env var including `LD_PRELOAD`, `LD_LIBRARY_PATH`, `PATH`, `HOME`, `PYTHONPATH` (overwriting the stubs injection). A malicious tool call could inject `LD_PRELOAD` to load arbitrary shared libraries.

**Fix:** Allowlist env var prefixes that `env_overrides` may set:

```python
_ALLOWED_ENV_PREFIXES = ("DB_", "CH_", "PG_", "REDIS_", "MONGO_")

# In _build_process_env, replace lines 124-125:
if env_overrides:
    for key, val in env_overrides.items():
        if any(key.startswith(prefix) for prefix in _ALLOWED_ENV_PREFIXES):
            process_env[key] = val
        else:
            logger.warning("Blocked disallowed env override: %s", key)
```

Move `_ALLOWED_ENV_PREFIXES` to module level.

**Acceptance criteria:**
- `env={"DB_HOST": "myhost"}` gets through
- `env={"LD_PRELOAD": "/evil.so"}` is blocked and logged
- `env={"PATH": "/evil"}` is blocked
- `env={"CH_EQUITIES_HOST": "x"}` gets through (the prefix from FIX-4)
- Add test `test_env_overrides_blocks_dangerous_keys`

---

## FIX-8: `get_connection` hardcodes `engine="clickhouse"`

**Severity:** IMPORTANT

**File:** `src/deep_agent/database/registry.py`

**Problem:** Line 78 — `get_connection` always returns `engine="clickhouse"` instead of using `entry.engine` from the looked-up `_ALIASES` dict entry. The result of `_get_accessible_alias` on line 75 is discarded.

**Fix:** Use the alias entry's engine:

```python
def get_connection(self, alias: str, tenant: TenantContext) -> ConnectionConfig:
    """Return connection configuration for an accessible alias."""
    entry = self._get_accessible_alias(alias=alias, tenant=tenant)

    return ConnectionConfig(
        engine=entry.engine,   # <-- was hardcoded "clickhouse"
        host=self._settings.clickhouse_host,
        port=self._settings.clickhouse_port,
        database=self._settings.clickhouse_database,
        credentials_ref=f"env://CLICKHOUSE_USER:{self._settings.clickhouse_user}",
    )
```

**Acceptance criteria:**
- `get_connection("ch-equities", tenant).engine` returns `"clickhouse"` (from alias data, not hardcoded)
- Add test `test_get_connection_engine_from_alias` verifying engine comes from `_ALIASES`

---

## FIX-9: `MCPManager.disconnect()` never closes underlying client

**Severity:** IMPORTANT

**File:** `src/deep_agent/mcp/manager.py`

**Problem:** Lines 76-80 — `disconnect()` sets `self._client = None` but never calls any close/shutdown method on the `MultiServerMCPClient`. Open connections, file descriptors, and subprocesses are leaked.

**Fix:** Call the client's close method if available before nulling the reference:

```python
async def disconnect(self) -> None:
    """Disconnect MCP client and clear discovered tools."""
    if self._client is not None:
        try:
            close = getattr(self._client, "close", None) or getattr(self._client, "aclose", None)
            if close is not None:
                result = close()
                if hasattr(result, "__await__"):
                    await result
        except Exception as exc:
            logger.warning("Error closing MCP client: %s", exc)
    self._client = None
    self._tools = []
    self._connected = False
```

**Acceptance criteria:**
- `disconnect()` calls `close()` or `aclose()` on the client object if the method exists
- Exceptions during close are logged but do not propagate
- `disconnect()` when `self._client is None` is still a no-op
- Update `test_disconnect_cleans_up` to verify close was called (mock client with a `close` method)

---

## FIX-10: `MCPManager.connect()` not idempotent — leaks clients

**Severity:** IMPORTANT

**File:** `src/deep_agent/mcp/manager.py`

**Problem:** Calling `connect()` twice creates a second `MultiServerMCPClient` without closing the first. The old client's connections/subprocesses are leaked.

**Fix:** Disconnect the existing client before creating a new one. Add a guard at the top of `connect()`:

```python
async def connect(self) -> None:
    """Connect to configured MCP servers and discover tools."""
    if self._client is not None:
        await self.disconnect()

    if not _HAS_MCP_ADAPTERS:
        ...  # rest unchanged
```

**Acceptance criteria:**
- Calling `connect()` twice does not leak the first client
- `disconnect()` is called on the old client before creating the new one
- Add test `test_connect_twice_disconnects_first` verifying old client is closed

---

## FIX-11: `_scan_filesystem` crashes on single malformed SKILL.md

**Severity:** IMPORTANT

**File:** `src/deep_agent/skills/engine.py`

**Problem:** Lines 122-127 — If `self._parser(skill_file)` raises for one malformed file, the entire `_scan_filesystem()` call fails, propagating to `discover()` / `match()` / `load()`. A single bad skill file breaks all skill operations for all tenants.

**Fix:** Wrap the per-file parse in a try/except and skip with a warning:

```python
def _scan_filesystem(self) -> dict[str, SkillContent]:
    index: dict[str, SkillContent] = {}
    for skill_file in sorted(self._skills_root.rglob("SKILL.md")):
        try:
            skill = self._parser(skill_file)
            index[skill.skill_id] = skill
        except Exception as exc:
            logger.warning("Skipping malformed skill file %s: %s", skill_file, exc)
    return index
```

This requires adding `import logging` and `logger = logging.getLogger(__name__)` at the top of the file (see FIX-19).

**Acceptance criteria:**
- A directory with 3 SKILL.md files where 1 has invalid YAML still returns 2 valid skills
- The malformed file is logged at WARNING level
- Add test `test_discover_skips_malformed_skill_file` to `tests/unit/test_skill_engine.py`

---

## FIX-12: `TenantContext` mutable lists despite `frozen=True`

**Severity:** IMPORTANT

**File:** `src/deep_agent/models/context.py`

**Problem:** `skills_dirs: list[str]` and `db_aliases: list[str]` are mutable containers. While `frozen=True` prevents attribute reassignment, callers can mutate the lists in-place via `.append()`, `.extend()`, etc., defeating the immutability guarantee.

**Fix:** Change from `list[str]` to `tuple[str, ...]` which is immutable:

```python
@dataclass(frozen=True)
class TenantContext:
    """Tenant and user scope used throughout the orchestration flow."""

    tenant_id: str
    user_id: str
    skills_dirs: tuple[str, ...]
    db_aliases: tuple[str, ...]

    @classmethod
    def stub(cls) -> TenantContext:
        """Return a hardcoded equities context for local development."""
        return cls(
            tenant_id="equities",
            user_id="dev-user",
            skills_dirs=("skills/common", "skills/equities"),
            db_aliases=("ch-equities",),
        )
```

Then update all call sites that construct `TenantContext` with lists to pass tuples instead. Affected files:
- All test files that create `TenantContext` or call `_tenant()` helpers
- `tests/conftest.py` if a shared fixture is added (FIX-20)

**Acceptance criteria:**
- `ctx = TenantContext.stub(); ctx.skills_dirs.append("x")` raises `AttributeError`
- All existing tests still pass after updating list literals to tuples
- `mypy` does not flag type errors on `skills_dirs` or `db_aliases` usage

---

## FIX-13: `confidence` hardcoded to `1.0` in `SkillMatchEvent`

**Severity:** IMPORTANT

**File:** `src/deep_agent/orchestrator/agent_orchestrator.py`

**Problem:** Line 57 — `yield SkillMatchEvent(skill_id=top_match.skill_id, confidence=1.0)` always emits `confidence=1.0` regardless of actual match quality. The PRD's skill matcher implies confidence should reflect actual match scoring.

**Fix:** Propagate the match score from `SkillEngine.match()`. The engine currently returns `SkillSummary` without scores. Two changes needed:

1. In `src/deep_agent/skills/engine.py`, add a `score` field to the returned match results. Simplest approach — add an optional `score` field to `SkillSummary`:

```python
# In src/deep_agent/models/skills.py, add to SkillSummary:
class SkillSummary(BaseModel):
    skill_id: str
    name: str
    description: str
    tags: list[str]
    score: float = 0.0    # <-- add this
```

2. In `engine.py` `match()`, populate the score:

```python
return [
    SkillSummary(
        skill_id=skill.skill_id,
        name=skill.name,
        description=skill.description,
        tags=skill.tags,
        score=score,   # <-- add this
    )
    for score, skill in top
]
```

3. In `agent_orchestrator.py` line 57:

```python
yield SkillMatchEvent(skill_id=top_match.skill_id, confidence=top_match.score)
```

**Acceptance criteria:**
- `SkillMatchEvent.confidence` reflects actual tag-overlap score (0.0-1.0)
- A query that partially matches tags produces `confidence < 1.0`
- Update orchestrator test to verify confidence is not always 1.0

---

## FIX-14: `invoke` vs `stream` inconsistent error handling

**Severity:** IMPORTANT

**File:** `src/deep_agent/runtime/langgraph_adapter.py`

**Problem:** `stream()` (line 145-146) catches all exceptions and yields `ErrorEvent`. `invoke()` (lines 59-81) lets raw LangChain exceptions propagate unwrapped. Callers get different error surfaces depending on the code path.

**Fix:** Wrap `invoke` in the same error-handling pattern:

```python
async def invoke(
    self,
    agent: Agent,
    message: str,
    context: TenantContext,
) -> AgentResponse:
    """Run the agent and return a normalized response."""
    _ = context
    payload = {"messages": [HumanMessage(content=message)]}
    try:
        result = await agent.ainvoke(payload)
    except Exception as exc:
        logger.exception("Agent invocation failed")
        return AgentResponse(
            content=f"Error: {exc}",
            tool_calls=[],
            tokens_used=0,
        )

    messages = _extract_messages(result)
    final_message = messages[-1] if messages else AIMessage(content="")

    usage_metadata = getattr(final_message, "usage_metadata", None)
    tokens_used = int(usage_metadata.get("total_tokens", 0)) if usage_metadata else 0
    tool_calls = [dict(call) for call in (getattr(final_message, "tool_calls", None) or [])]

    return AgentResponse(
        content=_content_to_text(getattr(final_message, "content", "")),
        tool_calls=tool_calls,
        tokens_used=tokens_used,
    )
```

**Acceptance criteria:**
- `invoke` with a failing agent returns `AgentResponse` with error content instead of raising
- The error is logged at exception level
- Add test `test_invoke_error_returns_error_response` to `tests/unit/test_langgraph_adapter.py`

---

## FIX-15: `max_tokens` not forwarded to `ChatOpenAI`

**Severity:** IMPORTANT

**File:** `src/deep_agent/runtime/langgraph_adapter.py`

**Problem:** Line 47 — `ChatOpenAI(model=model, temperature=temperature)` only passes `temperature` from kwargs. `max_tokens` from `LLMConfig` (resolved by `LLMRouter`) is silently ignored.

**Fix:** Extract and forward `max_tokens`:

```python
def create_agent(
    self,
    model: str,
    tools: list[Any],
    system_prompt: str,
    **kwargs: Any,
) -> Agent:
    """Build a compiled agent graph for execution."""
    temperature = float(kwargs.get("temperature", 0.0))
    max_tokens = kwargs.get("max_tokens")
    llm_kwargs: dict[str, Any] = {"model": model, "temperature": temperature}
    if max_tokens is not None:
        llm_kwargs["max_tokens"] = int(max_tokens)
    llm = ChatOpenAI(**llm_kwargs)
    ...
```

Then in `agent_orchestrator.py` line 81, pass `max_tokens`:

```python
agent = self._runtime.create_agent(
    model=llm_config.model,
    tools=all_tools,
    system_prompt=system_prompt,
    temperature=llm_config.temperature,
    max_tokens=llm_config.max_tokens,   # <-- add this
)
```

**Acceptance criteria:**
- `ChatOpenAI` is constructed with `max_tokens` when provided
- `ChatOpenAI` omits `max_tokens` when not provided (no default injection)
- Add test `test_create_agent_forwards_max_tokens`

---

## FIX-16: mypy real type errors (18 issues)

**Severity:** IMPORTANT

**File:** Multiple test files

**Problem:** `mypy src tests --ignore-missing-imports` reports 18 real errors:
1. `tests/unit/test_tools.py` (4 places): `OPENAI_API_KEY` passed as `str` instead of `SecretStr`
2. `tests/unit/test_database_registry.py` (2 places): same
3. `tests/unit/test_llm_router.py` (4 places): same
4. `tests/unit/test_models.py:121`: missing `OPENAI_API_KEY` arg
5. `tests/unit/test_models.py:92`: missing type annotation for `adapter`
6. `tests/unit/test_langgraph_adapter.py` (5 places): `SimpleNamespace` used where `TenantContext` expected
7. `tests/unit/test_langgraph_adapter.py:97`: `ToolCallChunk` dict missing `id` key

**Fix:** Apply these changes:

**A.** In all test files that construct `AppSettings`, wrap the API key:
```python
from pydantic import SecretStr
AppSettings(OPENAI_API_KEY=SecretStr("test-key"), ...)
```
Files: `test_tools.py`, `test_database_registry.py`, `test_llm_router.py`, `test_models.py`.

**B.** In `test_langgraph_adapter.py`, replace all `SimpleNamespace(tenant_id="t1")` with:
```python
from deep_agent.models import TenantContext
TenantContext(tenant_id="t1", user_id="u1", skills_dirs=("common",), db_aliases=())
```
(Use tuples if FIX-12 has landed, otherwise lists.)

**C.** In `test_langgraph_adapter.py:97`, add `"id"` key to the tool call chunk dict:
```python
{"name": "get_data", "args": '{"x":1}', "index": 0, "id": "call_1"}
```

**D.** In `test_models.py:92`, annotate:
```python
adapter: LangGraphAdapter = LangGraphAdapter()
```

**E.** In `test_models.py:121`, add `OPENAI_API_KEY=SecretStr("test")`.

**Acceptance criteria:**
- `mypy src tests --ignore-missing-imports` produces 0 errors (excluding `untyped-decorator` noise)
- All 91+ tests still pass

---

## FIX-17: `_derive_skill_id` uses first `"skills"` in path

**Severity:** IMPORTANT

**File:** `src/deep_agent/skills/parser.py`

**Problem:** Line 84 — `parts.index("skills")` finds the *first* occurrence of `"skills"` in the path components. A path like `/data/skills/archive/skills/equities/SKILL.md` would produce ID `archive/skills/equities` instead of `equities`.

**Fix:** Use `rindex` to find the *last* occurrence:

```python
def _derive_skill_id(path: Path) -> str:
    parts = list(path.parts)
    if "skills" in parts:
        skills_index = len(parts) - 1 - parts[::-1].index("skills")
        rel_parts = parts[skills_index + 1 : -1]
        if rel_parts:
            return "/".join(rel_parts)
    if path.parent.name:
        return path.parent.name
    raise SkillParseError(f"{path}: unable to derive skill_id from path")
```

**Acceptance criteria:**
- Path `/a/skills/b/skills/equities/SKILL.md` produces skill_id `equities`
- Path `/data/skills/equities/SKILL.md` still produces `equities`
- Add test `test_derive_skill_id_nested_skills_dir` to `tests/unit/test_skill_parser.py`

---

## FIX-18: TOCTOU race in `load_mcp_config`

**Severity:** IMPORTANT

**File:** `src/deep_agent/mcp/config.py`

**Problem:** Lines 46-53 — `config_path.exists()` is checked, then `config_path.read_text()` is called separately. The file could be deleted between the two calls (TOCTOU race). The `exists()` check is redundant since `read_text()` raises `FileNotFoundError` which is an `OSError` subclass already caught on line 52.

**Fix:** Remove the `exists()` check and handle `FileNotFoundError` directly:

```python
def load_mcp_config(
    tenant: TenantContext,
    config_root: Path = _DEFAULT_CONFIG_ROOT,
) -> MCPConfig:
    """Load and validate MCP config for a tenant."""
    config_path = (config_root / "tenants" / tenant.tenant_id / "mcp.json").resolve()
    safe_root = (config_root / "tenants").resolve()
    if not config_path.is_relative_to(safe_root):
        raise MCPConfigError(
            f"Invalid tenant_id '{tenant.tenant_id}': path traversal detected"
        )

    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.debug("No MCP config found at %s — using empty config", config_path)
        return MCPConfig()
    except OSError as exc:
        raise MCPConfigError(f"Failed to read MCP config at {config_path}: {exc}") from exc

    # ... rest unchanged (JSON parse, validate, etc.)
```

Note: This fix overlaps with FIX-2 (path traversal check). Implement them together.

**Acceptance criteria:**
- Missing config file returns `MCPConfig()` (empty)
- `exists()` is no longer called on `config_path`
- Existing `test_load_mcp_config_missing_file_returns_empty` still passes

---

## FIX-19: No logging in skills engine

**Severity:** IMPORTANT

**File:** `src/deep_agent/skills/engine.py`

**Problem:** The skills engine has zero logging. Cache refreshes, filesystem scans, parse errors (FIX-11), and tenant access decisions are all silent. This makes debugging production issues impossible, and the PRD mandates audit logging.

**Fix:** Add a module-level logger and log key operations:

```python
import logging

logger = logging.getLogger(__name__)
```

Add log calls at these points:
- `_ensure_cache()` when refreshing: `logger.debug("Refreshing skills cache (%d skills)", len(new_index))`
- `_scan_filesystem()` per-file error (FIX-11): `logger.warning("Skipping malformed skill file %s: %s", ...)`
- `match()`: `logger.debug("Matched %d skills for query (top_k=%d)", len(result), top_k)`
- `load()` on miss: `logger.debug("Skill '%s' not found for tenant '%s'", skill_id, tenant.tenant_id)`

**Acceptance criteria:**
- `logger = logging.getLogger(__name__)` exists in `engine.py`
- Cache refresh, match, and load operations produce DEBUG-level log output
- Parse errors produce WARNING-level log output
- No INFO or higher logs during normal operation (keep it quiet by default)

---

## FIX-20: Duplicated `_tenant()` helpers across 6+ test files

**Severity:** IMPORTANT

**File:** `tests/conftest.py` + 6 test files

**Problem:** At least 6 test files define their own nearly-identical `_tenant()` helper function to create a `TenantContext` for testing. This violates DRY and makes updating the `TenantContext` signature (e.g., FIX-12) painful.

**Fix:** Add a shared pytest fixture to `tests/conftest.py`:

```python
import pytest
from deep_agent.models import TenantContext


@pytest.fixture
def tenant_equities() -> TenantContext:
    """Standard equities tenant for unit tests."""
    return TenantContext(
        tenant_id="equities",
        user_id="test-user",
        skills_dirs=("skills/common", "skills/equities"),
        db_aliases=("ch-equities",),
    )
```

Then update all test files to use `tenant_equities` fixture instead of local `_tenant()`. Remove the now-unnecessary local helpers from:
- `tests/unit/test_tools.py`
- `tests/unit/test_database_registry.py`
- `tests/unit/test_orchestrator.py`
- `tests/unit/test_skill_engine.py` (keep its specialized fixtures but use the shared one where possible)
- `tests/unit/test_langgraph_adapter.py`
- `tests/unit/test_llm_router.py` (if applicable)

Also remove the unused `placeholder_fixture` from `conftest.py`.

**Acceptance criteria:**
- `tests/conftest.py` exports a `tenant_equities` fixture
- No test file defines its own `_tenant()` that duplicates the shared fixture
- `placeholder_fixture` is removed
- All 91+ tests pass

---

## FIX-21: `_build_system_prompt` `all_skills` typed as `list[Any]`

**Severity:** IMPORTANT

**File:** `src/deep_agent/orchestrator/agent_orchestrator.py`

**Problem:** Line 125 — `all_skills: list[Any]` erases type information. The code accesses `.name` and `.description` on line 136, which are `SkillSummary` attributes. This prevents mypy from catching attribute errors.

**Fix:** Change the type annotation:

```python
def _build_system_prompt(
    self,
    context: TenantContext,
    skill_content: SkillContent | None,
    all_skills: list[SkillSummary],   # <-- was list[Any]
) -> str:
```

Add `SkillSummary` to the imports at line 11:

```python
from deep_agent.models import (
    AgentEvent, ErrorEvent, SkillContent, SkillMatchEvent,
    SkillSummary, TenantContext,
)
```

Also fix `_build_builtin_tools` return type (line 90) and `_get_mcp_tools` return type (line 108):
```python
def _build_builtin_tools(self, context: TenantContext) -> list[BaseTool]:
    ...

async def _get_mcp_tools(self) -> list[BaseTool]:
    ...
```

This requires importing `BaseTool` from `langchain_core.tools`.

**Acceptance criteria:**
- `mypy` does not flag `all_skills` attribute accesses
- No `list[Any]` remains in `agent_orchestrator.py` for skills or tools (where a concrete type is available)

---

## Validation Suite

After all fixes are applied, run this full validation:

```bash
# Lint
ruff check src tests

# Type check (ignore missing third-party stubs)
mypy src tests --ignore-missing-imports

# Tests (fail-fast)
python3 -m pytest -x

# Verify new tests exist
python3 -m pytest -x -k "test_files_in_path_traversal or test_sandbox_env_does_not_leak or test_env_overrides_blocks or test_output_files_symlinks or test_load_mcp_config_path_traversal or test_db_pass_populated or test_build_db_env_multiple or test_connect_twice or test_discover_skips_malformed or test_derive_skill_id_nested or test_invoke_error_returns or test_create_agent_forwards_max_tokens" -v
```

All three commands must exit 0. The final `-k` command must find and pass at least 12 new tests.
