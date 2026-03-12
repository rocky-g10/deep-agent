# Final Verdict: REVISE

Most of the requested fixes are implemented correctly:
- `skill_bindings` is now required in orchestrator.
- `query_database` was removed from core skill allowlists/instructions.
- Resource env collision behavior was improved (prefixed-only for multi-alias).
- `mcp_config_path` is now consulted by `load_mcp_config`.
- New tests were added for these areas.

However, there are still **blocking completeness issues**:

## Remaining Issues

1. **Core zscore skill still not runnable with `firm_stats` import**
- `skills/equities/zscore-monitor/SKILL.md` still instructs `from firm_stats import zscore`.
- But that core skill has no local `scripts/` directory, so parser yields empty `scripts_path`, and no `PYTHONPATH` gets injected for this skill path.
- Verified behavior: sandbox execution still fails with `ModuleNotFoundError: No module named 'firm_stats'` when using default/core skill flow.
- References:
  - [skills/equities/zscore-monitor/SKILL.md](/home/ubuntu/deep-agent/skills/equities/zscore-monitor/SKILL.md#L33)
  - [src/deep_agent/skills/parser.py](/home/ubuntu/deep-agent/src/deep_agent/skills/parser.py#L61)
  - [src/deep_agent/orchestrator/agent_orchestrator.py](/home/ubuntu/deep-agent/src/deep_agent/orchestrator/agent_orchestrator.py#L79)

2. **`mcp_config_path` path semantics are inconsistent with `TenantContext.stub()`**
- Loader now resolves custom path as `config_root / tenant.mcp_config_path`.
- `TenantContext.stub()` sets `mcp_config_path="config/tenants/equities/mcp.json"`.
- With default `config_root="config"`, this resolves to `config/config/tenants/equities/mcp.json` (double-prefixed).
- This makes the default stub path incorrect under the new behavior.
- References:
  - [src/deep_agent/models/context.py](/home/ubuntu/deep-agent/src/deep_agent/models/context.py#L23)
  - [src/deep_agent/mcp/config.py](/home/ubuntu/deep-agent/src/deep_agent/mcp/config.py#L47)

## Suggested Minimal Fixes
1. Either add `skills/equities/zscore-monitor/scripts/firm_stats.py` (or equivalent packaging) under core `skills/`, or remove `firm_stats` dependency from core skill instructions.
2. Normalize `mcp_config_path` contract to be relative to `config_root` (and update `TenantContext.stub()` to `tenants/equities/mcp.json`), or detect/handle already-rooted `config/...` paths consistently.
