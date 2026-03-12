# PRD Update: Resource-Agnostic Architecture

## Directive from Rio (stakeholder)

The PRD currently enshrines ClickHouse, Redis, MongoDB, and MySQL as "core" database backends. This is WRONG. The framework must be **resource-agnostic** — databases and APIs are whatever skill authors bring, not baked-in components.

## Key Principle

Deep Agent is a **federated execution framework**. Skills define their own data sources — any database, any API, any resource. The framework provides:
1. A secure sandbox for code execution
2. A skill discovery/matching engine
3. A runtime adapter for orchestration

It does NOT prescribe which databases to use. A skill author might use:
- ClickHouse (time-series analytics)
- KDB+ (tick data, quant strategies)
- Snowflake (data warehouse)
- DynamoDB (key-value)
- Any REST/GraphQL API
- Internal firm APIs
- File systems, S3, etc.

## What to Change in docs/PRD.md

1. **Architecture Overview (Section 3)**: Remove ClickHouse/Redis/MongoDB/MySQL from the layer diagram as "core" components. Replace with a generic "Skill-Defined Data Sources" layer that shows these as EXAMPLES, not built-in.

2. **Database/Data Layer references**: Anywhere the PRD says the framework "ships with" or "supports" specific databases, rewrite to say the framework is resource-agnostic — skills define their own dependencies (pip packages, connection strings, etc.). The examples (ClickHouse, Redis, etc.) should be clearly labeled as EXAMPLE skills, not core infrastructure.

3. **docker-compose.yml implications**: The dev docker-compose should NOT spin up ClickHouse/Redis/MongoDB by default. Instead, EXAMPLE skills that use these databases should have their own docker-compose or setup instructions. The core framework's docker-compose should only include what the framework itself needs (if anything).

4. **Tenant database config (Section 4/5)**: The `DatabaseConfig` model with hardcoded engine choices (`clickhouse | redis | mongodb | mysql`) should be replaced with a generic resource registry where skill authors register arbitrary connection configs. The framework doesn't need to know what engine it is — the skill's sandboxed code handles the driver.

5. **Skills Layer**: Update the skill spec to show that skills declare their own dependencies (Python packages, connection requirements) and the sandbox installs/provides them. The framework doesn't need a built-in database abstraction layer.

6. **Example Skills (z-score, database-query)**: Keep these as EXAMPLES but clearly mark them as "example skills that demonstrate ClickHouse usage" — not core framework skills. Any skill author could write equivalent skills for KDB+, Snowflake, etc.

7. **Audit logging**: If audit logs currently assume ClickHouse, make the audit backend pluggable too and just USE the configured platform backend (e.g., ELK, Loki, stdout, whatever the deployer chooses).

8. **Deployment (K8s manifests, Section 8)**: Remove database-specific StatefulSets from the core deployment. Example skills can include their own Helm charts or docker-compose files.

## After PRD Update

Review and update ALL task files in docs/tasks/ to reflect this change:
- Remove any tasks that install/configure specific databases as "core" infrastructure
- Update integration test tasks to use example skills (not assume ClickHouse is running)
- Update the dev setup task (T4.5) to NOT require docker-compose with ClickHouse by default
- The core `run_dev.py` should start the FastAPI server without requiring any database

## ADDITIONAL: Skill Self-Containment (Anthropic AgentSkills Spec)

The PRD currently has `firm.stats` and other stub libraries as top-level framework packages (installed in the sandbox image). This is WRONG. Per the Anthropic AgentSkills specification, **every skill must be self-contained**. Libraries, stubs, and reference implementations belong INSIDE the skill folder.

### Canonical Skill Structure (from Anthropic's official guide):
```
your-skill-name/
├── SKILL.md              # Required - main skill file (< 5000 words)
├── scripts/              # Optional - executable code
│   ├── process_data.py   # Example
│   └── validate.sh       # Example
├── references/           # Optional - documentation
│   ├── api-guide.md      # Example
│   └── examples/         # Example
└── assets/               # Optional - templates, etc.
    └── report-template.md # Example
```

### What This Means for Deep Agent:

1. **`firm.stats` (z-score, moving average, etc.)** → lives inside `skills/equities/zscore-monitor/scripts/firm_stats.py`, NOT as a top-level `src/firm/stats.py` package. Each skill that needs statistical functions bundles its own implementation.

2. **Database drivers** → if a skill needs `clickhouse-connect`, that's declared in the skill's dependency requirements, NOT baked into the core sandbox image. The sandbox should provide a minimal Python environment; skills declare what they need.

3. **Connection configs** → skills reference connection aliases from the tenant's resource registry (generic key-value, not database-specific). The skill's `scripts/` contain the code that knows how to use the driver.

4. **Progressive disclosure** → SKILL.md stays under 5000 words with core instructions. Detailed API patterns, SQL templates, and reference implementations go in `references/`. Scripts go in `scripts/`.

5. **Example skills should follow this structure exactly:**
```
skills/equities/zscore-monitor/
├── SKILL.md                        # Instructions for z-score monitoring
├── scripts/
│   ├── firm_stats.py               # Statistical functions (was firm.stats)
│   ├── compute_zscore.py           # Main computation script
│   └── requirements.txt            # clickhouse-connect, pandas, numpy
├── references/
│   ├── zscore-methodology.md       # Statistical methodology docs
│   └── examples/
│       └── sample-query.sql        # Example ClickHouse queries
└── assets/
    └── chart-template.json         # Plotly chart config
```

6. **The sandbox image** should be minimal: Python 3.12, pip, and basic stdlib. Skills declare their own `requirements.txt` in `scripts/` and the sandbox installs them at runtime (or caches them per-skill).

### Update the PRD to:
- Remove all references to pre-installed firm libraries in the sandbox image
- Remove the "internal library registry" concept — skills bundle their own code
- Update the sandbox spec to show a minimal base image + per-skill dependency installation
- Update ALL example skills to follow the Anthropic AgentSkills directory structure
- Add the skill structure spec to the PRD's Skills Specification section (Section 5)

## ADDITIONAL 2: Skill Discovery is Scoped to Tenant → Agent

The YAML frontmatter in SKILL.md is the universal skill metadata — name, description, tags. But skill DISCOVERY must be scoped at the **agent level** — not the tenant level.

### Simplified model (TWO layers, not three):

```
Global Skill Registry (all registered skills, any tenant can use)
  └─ Agent Skill Bindings (each agent config lists which skills it can discover/load)
      └─ Runtime Skill Matching (agent matches user query against its bound skills' YAML frontmatter)
```

There is NO tenant-level skill allowlist. That's unnecessary complexity. All skills in the global registry are available to any tenant — access control happens at the agent level.

### What this means for the PRD:

1. **Skill Registry** — a catalog service that indexes all skill folders and their YAML frontmatter. This is a FRAMEWORK component (not a skill). It scans `skills/` directories and makes metadata queryable. Any tenant's agents can bind to any skill in the registry.

2. **Agent Skill Bindings** — each agent instance has an explicit list of skill names it can discover. When a user query comes in, the SkillMatcher only evaluates frontmatter from the agent's bound skills — NOT the full catalog. This is the ONLY access control layer for skills.

3. **Skills are tenant-unaware AND agent-unaware** — a skill never references a tenant or agent. It's pure business logic + metadata. The scoping happens entirely in agent configuration.

4. **No tenant-scoped skill assignments** — removed to keep the model simple. If a desk wants all their agents to share skills, they configure each agent the same way (or use agent templates as a future convenience).

## Summary

**Before:** "Deep Agent supports ClickHouse, Redis, MongoDB, MySQL" with pre-installed firm libraries
**After:** "Deep Agent is resource-agnostic. Skills are self-contained per Anthropic's AgentSkills spec. Each skill bundles its own scripts, libraries, references, and dependency declarations. The framework provides a minimal sandbox and a generic resource registry — nothing more."

This is a FOUNDATIONAL change — get it right in the PRD, then cascade to all tasks.
