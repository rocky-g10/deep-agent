# Code Review: Resource-Agnostic Refactor (`git diff HEAD~1`)

## Findings (ordered by severity)

### 1) Critical: skill script imports are broken in sandbox (runtime regression)
- **What changed:** `PythonSubprocessSandbox` no longer supports injecting a stubs/scripts path into `PYTHONPATH`.
- **Why this breaks:** Skills/docs now instruct importing helper modules like `firm_stats`, but those modules are not available in sandbox executions by default.
- **Evidence:**
  - `PythonSubprocessSandbox.__init__` dropped `stubs_path` and `_build_process_env` removed `PYTHONPATH` injection logic: [src/deep_agent/sandbox/subprocess_sandbox.py](/home/ubuntu/deep-agent/src/deep_agent/sandbox/subprocess_sandbox.py#L41), [src/deep_agent/sandbox/subprocess_sandbox.py](/home/ubuntu/deep-agent/src/deep_agent/sandbox/subprocess_sandbox.py#L135)
  - Skill now instructs `from firm_stats import zscore`: [skills/equities/zscore-monitor/SKILL.md](/home/ubuntu/deep-agent/skills/equities/zscore-monitor/SKILL.md#L41)
  - Direct check shows `ModuleNotFoundError: No module named 'firm_stats'` when executing in sandbox.
- **Impact:** Any skill depending on local helper modules fails at execution time.

### 2) High: default orchestrator path silently disables all skills
- **What changed:** `handle_message()` now accepts optional `skill_bindings`; when omitted, it defaults to an empty binding set.
- **Why this is breaking:** Existing callers that still pass only `(message, context)` now discover/match zero skills, causing behavior regression without explicit errors.
- **Evidence:** [src/deep_agent/orchestrator/agent_orchestrator.py](/home/ubuntu/deep-agent/src/deep_agent/orchestrator/agent_orchestrator.py#L53), [src/deep_agent/orchestrator/agent_orchestrator.py](/home/ubuntu/deep-agent/src/deep_agent/orchestrator/agent_orchestrator.py#L57)
- **Impact:** Skill selection and skill-scoped tool filtering effectively stop working unless every caller is updated.

### 3) High: core skills still depend on `query_database`, but core tool was removed
- **What changed:** `query_database` tool factory was removed from core exports and orchestrator built-ins.
- **Why this regresses behavior:** Existing skills still allow and instruct `query_database`, but orchestrator now only injects `execute_code` unless callers manually provide extra tools.
- **Evidence:**
  - Tool removal: [src/deep_agent/tools/__init__.py](/home/ubuntu/deep-agent/src/deep_agent/tools/__init__.py#L1)
  - Built-in tool list now only includes `execute_code`: [src/deep_agent/orchestrator/agent_orchestrator.py](/home/ubuntu/deep-agent/src/deep_agent/orchestrator/agent_orchestrator.py#L101)
  - Skills still require `query_database`: [skills/common/db-query/SKILL.md](/home/ubuntu/deep-agent/skills/common/db-query/SKILL.md#L10), [skills/equities/zscore-monitor/SKILL.md](/home/ubuntu/deep-agent/skills/equities/zscore-monitor/SKILL.md#L12)
- **Impact:** Skill instructions and runtime tool availability are out of sync; user flows relying on schema-discovery tool calls degrade.

### 4) Medium (Security/Design): tool injection model is name-based and can be spoofed
- **What changed:** Arbitrary `extra_tools` are appended and then filtered only by tool name.
- **Risk:** A malicious/untrusted injected tool can adopt an allowlisted name (e.g. `execute_code`) and pass `_filter_tools`, effectively bypassing intended capability boundaries.
- **Evidence:** [src/deep_agent/orchestrator/agent_orchestrator.py](/home/ubuntu/deep-agent/src/deep_agent/orchestrator/agent_orchestrator.py#L39), [src/deep_agent/orchestrator/agent_orchestrator.py](/home/ubuntu/deep-agent/src/deep_agent/orchestrator/agent_orchestrator.py#L77), [src/deep_agent/orchestrator/agent_orchestrator.py](/home/ubuntu/deep-agent/src/deep_agent/orchestrator/agent_orchestrator.py#L166)
- **Impact:** Security boundary is weaker than it appears unless tool registration source is fully trusted.

### 5) Medium: resource env flattening creates collision/override hazards
- **What changed:** `_build_resource_env()` merges all alias variables into one flat dict and also adds prefixed variants.
- **Risk:** Unprefixed keys (`DB_HOST`, `DB_PASS`, etc.) from later aliases overwrite earlier aliases silently.
- **Evidence:** [src/deep_agent/tools/execute_code.py](/home/ubuntu/deep-agent/src/deep_agent/tools/execute_code.py#L53)
- **Impact:** Multi-resource tenants can get nondeterministic or wrong default connection target; subtle data correctness issues.

### 6) Low/Medium: abstraction boundary inconsistency (`mcp_config_path` is modeled but unused)
- **What changed:** `TenantContext` now carries `mcp_config_path`, but MCP config loader still derives path strictly from `tenant_id`.
- **Evidence:** [src/deep_agent/models/context.py](/home/ubuntu/deep-agent/src/deep_agent/models/context.py#L14), [src/deep_agent/mcp/config.py](/home/ubuntu/deep-agent/src/deep_agent/mcp/config.py#L44)
- **Impact:** The model implies per-context MCP path control, but runtime ignores it. This can confuse integrators and weakens boundary clarity.

## Code Quality and Pattern Notes
- Positive: removing hardcoded DB config from `AppSettings` is aligned with resource-agnostic goals.
- Concern: `TenantContext` is `frozen=True` but contains mutable nested dicts (`resource_env`), which weakens immutability guarantees and makes accidental cross-request mutation possible.

## Test Coverage Gaps
1. Missing regression test for sandbox importability of skill helper modules (e.g. `firm_stats`) via orchestrator/`execute_code` path.
2. Missing orchestrator test for omitted `skill_bindings` (current default behavior should be explicitly asserted as intended or corrected).
3. Missing integration test that validates skill allowlisted tools are actually present after assembly/filtering (e.g. `query_database` contract).
4. Missing test for resource env collision behavior across multiple aliases (`DB_*` overwrite semantics).
5. Missing security test for duplicate tool names in `extra_tools`/MCP tools and allowlist spoofing behavior.
6. Missing test asserting `mcp_config_path` is either honored or intentionally ignored.

## Security Notes on New Tool Injection
- The move to injection is directionally good, but current enforcement is **name-based**, not **identity/capability-based**.
- If tool sources are not strongly trusted, add provenance checks (signed registry/explicit source allowlist), and enforce unique tool names before filtering.
- Consider scoping secret env vars per execution/tool and minimizing broad prefixes (`API_`) unless necessary.
