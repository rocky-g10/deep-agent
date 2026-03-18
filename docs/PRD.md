# Deep Agent — Product Requirements Document

> **Version:** 0.1.0-draft
> **Last Updated:** 2026-03-09
> **Status:** Draft
> **Author:** Rio (stakeholder), Engineering

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Architecture Overview](#3-architecture-overview)
4. [Core Components](#4-core-components)
5. [Skills Specification](#5-skills-specification)
6. [Security & Sandboxing](#6-security--sandboxing)
7. [Multi-Tenancy](#7-multi-tenancy)
8. [Deployment Model](#8-deployment-model)
9. [Technology Stack](#9-technology-stack)
10. [MVP Scope & Phasing](#10-mvp-scope--phasing)
11. [Future Roadmap](#11-future-roadmap)

---

## 1. Executive Summary

Deep Agent is an enterprise-grade, reusable AI agent framework designed for a large financial institution. It enables business desks — Equities, Fixed Income, Risk, Compliance, and others — to build custom AI agents by authoring plain-language skill files (`SKILL.md`) rather than writing code. The framework is built on LangChain's `deepagents` library (`pip install deepagents`) and abstracts the underlying runtime behind a `RuntimeAdapter` protocol, allowing the orchestration engine to be swapped (e.g., from LangGraph to Claude Agent SDK) without modifying any skills.

**Key differentiators:**

- **Skills-driven architecture** — domain experts express business logic in Markdown; no Python or framework knowledge required.
- **Swappable runtime** — the `RuntimeAdapter` protocol decouples skill definitions from execution engines, future-proofing the platform.
- **Provider-agnostic LLM routing** — ships with OpenAI GPT-5 / GPT-4.1 as the default provider, with a routing layer designed for zero-downtime swap to Claude, Gemini, or any future model.
- **On-premise deployment** — runs on self-hosted Kubernetes or OpenShift clusters behind the firm's network perimeter, meeting regulatory and data-residency requirements.
- **Resource-agnostic** — the framework does not bake in any specific database or data source. Skills define their own data sources; the platform provides secure sandbox execution and generic resource env-var injection.
- **Self-contained skills (Anthropic AgentSkills spec)** — each skill is a self-contained directory with `scripts/`, `references/`, and `assets/` folders. Skills bundle their own code and declare their own dependencies via `scripts/requirements.txt`.
- **Scoped skill discovery** — a simplified two-layer model (Global Skill Registry → Agent Skill Bindings) replaces tenant-scoped skill directories. Skills are tenant-unaware and agent-unaware; access control is purely at the agent level.

**MVP priority order:**

1. Skills engine (discovery, matching, loading)
2. Secure code sandbox — skills execute Python against any data source they define
3. MCP tool integrations

---

## 2. Problem Statement

### 2.1 Current State

Business desks across the firm perform repetitive analytical workflows daily — pulling data from multiple databases, running statistical computations (z-scores, moving averages, WAM, PCA), generating reports, and visualizing results. These workflows are:

- **Manual and time-consuming.** Analysts context-switch between SQL clients, Python notebooks, Excel, and internal tools to answer a single question.
- **Siloed by desk.** Each desk has built bespoke scripts and one-off chatbot prototypes. There is no shared infrastructure, no reuse of common patterns, and no institutional knowledge capture.
- **Inaccessible to non-developers.** Domain experts (traders, risk managers, portfolio analysts) possess deep business knowledge but cannot express it in a form that AI systems can consume without developer intermediation.

### 2.2 Failed Prior Approaches

Previous AI initiatives produced isolated chatbots tightly coupled to a single desk, a single LLM provider, and hardcoded tool integrations. These could not be extended, governed, or reused. When the LLM provider changed pricing or capabilities, the entire integration had to be rewritten.

### 2.3 Gaps

| Gap | Impact |
|---|---|
| No reusable agent framework | Every desk rebuilds from scratch; 3-6 month lead time per integration |
| No shared skill format | Domain knowledge locked in individual scripts and tribal memory |
| No sandboxed execution | Ad-hoc code execution creates security and compliance risk |
| No audit trail | Regulators require full provenance of AI-assisted decisions; current tools provide none |
| LLM vendor lock-in | Single-provider dependencies create cost, availability, and regulatory risk |
| No multi-tenancy | Cross-desk data leakage risk; no resource isolation or access control |

### 2.4 Desired Outcome

A single platform where:

1. Business experts author skills in plain language.
2. Any desk user can invoke an agent that discovers relevant skills, queries databases, executes code in a secure sandbox, and returns answers with visualizations — all within a chat interface.
3. Every action is audit-logged with user identity, tenant context, and full provenance.
4. The LLM provider and runtime engine can be swapped without touching skills or business logic.

---

## 3. Architecture Overview

### 3.1 Layer Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                      CHAT INTERFACE LAYER                          │
│  React Web Portal  ◄──WebSocket──►  Streaming API  ◄──►  Session  │
│                                      (FastAPI)           Manager   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                      ORCHESTRATION LAYER                           │
│  ┌──────────┐  ┌───────────────┐  ┌──────────────┐  ┌───────────┐ │
│  │  Agent    │  │  Tenant       │  │  Skill       │  │  Agent    │ │
│  │  Router   │──│  Context      │──│  Matcher     │──│  Loop     │ │
│  └──────────┘  └───────────────┘  └──────────────┘  └───────────┘ │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                        SKILLS LAYER                                │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  SkillEngine (runtime-agnostic)                             │   │
│  │  discover() → match() → load() → inject into system prompt  │   │
│  └─────────────────────────────────────────────────────────────┘   │
│  skills/common/   skills/equities/   skills/risk/   skills/...    │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                       RUNTIME LAYER                                │
│  ┌──────────────────────────────────────────────────────┐          │
│  │  RuntimeAdapter Protocol                              │          │
│  │  create_agent()  │  invoke()  │  stream()             │          │
│  ├──────────────────┴────────────┴───────────────────────┤          │
│  │  LangGraphAdapter (deepagents)    ← current           │          │
│  │  ClaudeAgentAdapter               ← future            │          │
│  └──────────────────────────────────────────────────────┘          │
│                                                                     │
│  ┌──────────────────────────────────────────────────────┐          │
│  │  LLM Router                                           │          │
│  │  OpenAI GPT-5/4.1 (default) │ Claude │ Gemini         │          │
│  └──────────────────────────────────────────────────────┘          │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                     INTEGRATION LAYER                              │
│  ┌──────────────────────────┐  ┌──────────────┐                   │
│  │ Skill-Defined Data       │  │ MCP Adapters │                   │
│  │ Sources (any DB, API,    │  │ (per-tenant  │                   │
│  │ file system — skill-     │  │  JSON config)│                   │
│  │ managed)                 │  │              │                   │
│  └──────────────────────────┘  └──────────────┘                   │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Skill-Bundled Scripts (per Anthropic AgentSkills spec)       │  │
│  └──────────────────────────────────────────────────────────────┘  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                      EXECUTION LAYER                               │
│  ┌──────────────────────────────────────────────────────┐          │
│  │  SandboxManager (pluggable)                           │          │
│  │  PythonSubprocessSandbox   ← dev / MVP                │          │
│  │  OpenShiftPodSandbox       ← production               │          │
│  └──────────────────────────────────────────────────────┘          │
│  matplotlib / plotly → rendered images returned to chat            │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                    INFRASTRUCTURE LAYER                             │
│  Self-hosted K8s / OpenShift  │  PostgreSQL  │  Redis  │  S3/Minio │
│  OAuth/OIDC (pluggable)       │  Vault       │  ELK/Loki           │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 Key Design Principles

#### RuntimeAdapter Protocol

The `RuntimeAdapter` is the central abstraction that makes the framework runtime-agnostic. It exposes three methods:

```python
class RuntimeAdapter(Protocol):
    def create_agent(
        self,
        model: str,
        tools: list[Tool],
        system_prompt: str,
        **kwargs,
    ) -> Agent: ...

    async def invoke(
        self,
        agent: Agent,
        message: str,
        context: TenantContext,
    ) -> AgentResponse: ...

    async def stream(
        self,
        agent: Agent,
        message: str,
        context: TenantContext,
    ) -> AsyncIterator[AgentEvent]: ...
```

The `LangGraphAdapter` (backed by `deepagents`) is the only implementation at MVP. The `SkillEngine` has **zero dependency** on any runtime — it produces metadata and prompt content that the orchestration layer injects into whichever runtime is active.

#### LLM Router

The LLM Router sits within the Runtime Layer and abstracts model selection:

```python
class LLMRouter:
    def resolve(self, tenant: TenantContext, task_hint: str | None = None) -> LLMConfig:
        """Return model config based on tenant settings, cost policy, and availability."""
```

Default configuration ships with **OpenAI GPT-5** as the primary model and **GPT-4.1** as the cost-optimized fallback. The router is provider-agnostic — adding Claude or Gemini requires only a new provider config entry; no code changes.

#### Pluggable Sandboxing

The `SandboxManager` abstracts code execution behind a pluggable interface:

| Environment | Backend | Use Case |
|---|---|---|
| Local dev | `PythonSubprocessSandbox` | Fast iteration, no container runtime needed |
| Production | `OpenShiftPodSandbox` | Full isolation, resource limits, network policies |

Both backends implement the same `execute(code, timeout, resource_limits) -> ExecuteResult` interface, where `ExecuteResult` carries `stdout`, `stderr`, `exit_code`, and `output_files` (for charts/images).

#### Skill-Runtime Separation

```
SKILL.md (plain language, runtime-agnostic)
    │
    ▼
SkillEngine.match(user_query) → SkillMetadata
    │
    ▼
Orchestrator injects skill content into system prompt
    │
    ▼
RuntimeAdapter.stream(agent, message, context)
    │
    ▼
Agent loop: LLM ↔ tools ↔ sandbox ↔ DB
```

Skills never import framework code. They are pure Markdown documents describing *what* the agent should do, *which tools* it may use, and *what quality standards* apply. This means:

- Swapping from LangGraph to Claude Agent SDK requires a new `RuntimeAdapter` — zero skill changes.
- Business experts author skills without knowing which runtime executes them.
- Skills are testable, reviewable, and version-controlled as plain text.

### 3.3 Data Flow — Typical Query

```
User (React portal)
  │
  ├─ WebSocket ──► Streaming API (FastAPI)
  │                  │
  │                  ├─ Authenticate (OAuth/OIDC token validation)
  │                  ├─ Resolve tenant context from token claims
  │                  ├─ SkillEngine.discover(tenant) → skill summaries
  │                  ├─ Build system prompt (base + tenant + skill summaries)
  │                  ├─ RuntimeAdapter.stream(agent, user_message, ctx)
  │                  │     │
  │                  │     ├─ LLM call (GPT-5 via LLM Router)
  │                  │     ├─ Tool call: execute_code(python_code)
  │                  │     │     └─ Sandbox injects tenant resource env vars
  │                  │     │     └─ SandboxManager.execute(python_code)
  │                  │     │     └─ Returns DataFrame / chart image
  │                  │     ├─ LLM call (interpret results)
  │                  │     └─ AgentComplete
  │                  │
  │                  ├─ Stream events back over WebSocket
  │                  └─ Audit logger writes every event
  │
  ◄─ agent_chunk, tool_call, tool_result, agent_complete
```

---

## 4. Core Components

### 4.1 SkillEngine (Global Skill Registry + Scoped Discovery)

The SkillEngine is the central component of the Skills Layer. It functions as a **Global Skill Registry**, indexing all skill folders by YAML frontmatter. It has **zero dependency** on any runtime or LLM provider. Skills are **tenant-unaware** and **agent-unaware** — access control is purely at the agent level through skill bindings.

#### Discovery Pipeline (Two Layers)

```
SkillRegistry.index_all()          ← Layer 1: Global index of all skills
    │
    ▼
Agent Skill Bindings filter        ← Layer 2: Agent config binds specific skill_ids
    │
    ▼
match(query) against bound skills  ← Runtime: tag/keyword matching on the filtered set
```

There is **no tenant-level skill allowlist**. All skills in the global registry are available to any tenant. The agent configuration determines which skills are accessible.

#### Interface

```python
class SkillEngine:
    def __init__(self, skills_root: Path, cache_ttl: int = 300): ...

    def discover(self, skill_bindings: list[str] | None = None) -> list[SkillSummary]:
        """Return name + description for all skills, optionally filtered by agent skill bindings.
        Results are injected into the system prompt so the LLM knows what's available."""

    def match(self, query: str, skill_bindings: list[str] | None = None, min_score: float = 0.0) -> list[SkillMetadata]:
        """Rank skills by relevance to the user query, scoped to bound skills.
        All bound skills scoring at or above min_score are returned — there is no artificial cap.
        MVP: tag + keyword matching. Future: embedding-based similarity."""

    def load(self, skill_id: str) -> SkillContent:
        """Return full SKILL.md content for system-prompt injection.
        No tenant check — skills are globally accessible."""
```

#### Agent Skill Bindings

Each agent configuration specifies a list of `skill_id`s that the agent may use. This is the **only** access-control mechanism for skills:

```python
@dataclass
class AgentSkillBindings:
    agent_id: str
    bound_skill_ids: list[str]   # e.g. ["data-query/db-query", "equities/zscore-monitor"]
```

The orchestrator receives agent-scoped skill bindings and passes them to `discover()` and `match()`.

#### Data Types

```python
@dataclass
class SkillSummary:
    skill_id: str          # e.g. "equities/zscore-monitor"
    name: str              # human-readable name from frontmatter
    description: str       # one-line description
    tags: list[str]        # e.g. ["database", "equities", "fundamentals"]

@dataclass
class SkillMetadata(SkillSummary):
    allowed_tools: list[str]   # e.g. ["execute_code"]

@dataclass
class SkillContent(SkillMetadata):
    body: str              # full Markdown body (instructions, examples, quality standards)
```

Note: The `tenant` field is **removed** from all skill data types. Skills are tenant-unaware.

#### Progressive Disclosure

Skills are exposed to the LLM in three tiers to minimize prompt bloat:

| Tier | What the LLM sees | When |
|---|---|---|
| **Discovery** | `SkillSummary` list (names + one-line descriptions) | Every turn — always in system prompt |
| **Read** | Full `SkillContent` body | When `match()` ranks a skill as relevant to the current query |
| **Execute** | Tool calls permitted by `allowed_tools` | During agent loop, gated by the skill's tool allowlist |

#### File Layout

Skills are organized by domain, not tenant ownership:

```
skills/
├── data-query/                    # general data querying skills
│   ├── db-query/
│   │   ├── SKILL.md
│   │   ├── scripts/
│   │   │   └── requirements.txt
│   │   ├── references/
│   │   └── assets/
│   └── visualization/
│       ├── SKILL.md
│       └── scripts/
├── equities/                      # equities domain skills
│   ├── zscore-monitor/
│   │   ├── SKILL.md
│   │   ├── scripts/
│   │   │   ├── requirements.txt
│   │   │   └── firm_stats.py
│   │   ├── references/
│   │   └── assets/
│   └── query-fundamentals/
│       └── SKILL.md
├── fixed-income/
│   └── swap-notional-calc/
│       └── SKILL.md
├── risk/
│   └── var-report/
│       └── SKILL.md
└── compliance/
    └── trade-surveillance/
        └── SKILL.md
```

All skills are globally visible. Agent configurations bind specific skills to specific agents.

---

### 4.2 SandboxManager

The SandboxManager provides secure, isolated Python execution. It is pluggable — the backend can be swapped without changing any calling code.

#### Interface

```python
class SandboxManager(Protocol):
    async def execute(
        self,
        code: str,
        timeout: int = 60,
        resource_limits: ResourceLimits | None = None,
        env: dict[str, str] | None = None,
        files_in: dict[str, bytes] | None = None,
    ) -> ExecuteResult: ...

    async def cleanup(self, execution_id: str) -> None: ...

@dataclass
class ResourceLimits:
    cpu_cores: float = 2.0
    memory_mb: int = 4096
    max_output_bytes: int = 10_000_000   # 10 MB

@dataclass
class ExecuteResult:
    execution_id: str
    exit_code: int
    stdout: str
    stderr: str
    output_files: dict[str, bytes]   # e.g. {"chart.png": b"..."}
    duration_ms: int
```

#### Backends

| Backend | Class | When Used | How It Works |
|---|---|---|---|
| Subprocess | `PythonSubprocessSandbox` | Local dev, MVP | Spawns a Python subprocess with `resource` limits, temp directory for output files. No container runtime required. |
| OpenShift Pod | `OpenShiftPodSandbox` | Production | Creates an ephemeral Pod via K8s API. Non-root user, read-only rootfs, CPU/memory limits, network policy restricts egress to approved DB endpoints only. Pod is destroyed after execution. |

#### Sandbox Image

The sandbox provides a minimal **Python 3.12-slim + pip** base image. Skills declare their dependencies in `scripts/requirements.txt`; the sandbox installs them at execution time (with per-skill caching). No analytics libraries, database drivers, or internal firm libraries are pre-installed in the base image — all dependencies come from the skill's own requirements.

#### Visualization Pipeline

1. Agent generates Python code that uses `matplotlib` or `plotly` (installed from the skill's `scripts/requirements.txt`).
2. Code writes output to `/output/` inside the sandbox.
3. `ExecuteResult.output_files` returns the rendered images (PNG/SVG) or interactive HTML.
4. The Chat API encodes images as base64 data URIs and streams them to the React portal in a `tool_result` event.

---

### 4.3 Resource Configuration

The framework is **resource-agnostic** — it does not bake in any specific database engine, client library, or data-source connector. Instead, tenants configure **generic resource aliases** as key-value environment variable sets in their tenant configuration.

#### How It Works

1. **Tenant config** defines named resource aliases with key-value env var pairs:

```python
# In tenant config (PostgreSQL / admin API)
resource_aliases:
  ch-equities:
    DB_HOST: "clickhouse.equities.internal"
    DB_PORT: "8123"
    DB_NAME: "equities_db"
    DB_USER: "reader"
    DB_PASS_REF: "vault:clickhouse/equities/password"
  redis-pricing:
    REDIS_URL: "redis://pricing-cache.internal:6379/0"
```

2. **SandboxManager** injects these env vars into the sandbox process at execution time.
3. **Skill code** references resources via `os.environ` — e.g., `os.environ["DB_HOST"]`.
4. **No built-in database drivers, no engine-specific logic** in the framework core.

#### Credential Flow (preserved, but generic)

```
Secret Store (Vault / K8s Secrets)
    │
    ▼
Tenant resource config  →  env var references resolved at runtime
    │
    ▼
SandboxManager injects env vars into sandbox process
    │
    ▼
Skill code uses os.environ["DB_HOST"] etc. — never sees raw credentials
```

The agent's LLM prompt receives only resource alias names and descriptions (not credentials). When the agent generates Python code, the `SandboxManager` injects credentials as environment variables. The agent-generated code references `os.environ` — the LLM never sees the actual values.

---

### 4.4 MCP Adapters

MCP (Model Context Protocol) adapters expose external tools to the agent via the `langchain-mcp-adapters` library. MCP servers can be configured at **two levels**: directly in a skill's `SKILL.md` frontmatter (self-contained, simple) or in per-tenant `mcp.json` (centralized, recommended for production). Both approaches are fully supported; tenant config takes precedence when server names conflict.

#### Configuration Sources (Priority Order)

1. **Tenant-level** (`config/tenants/{tenant_id}/mcp.json`) — recommended for production. Provides centralized control, secrets management, and environment separation. Overrides skill-level declarations on name conflicts.

```json
{
  "servers": [
    {
      "name": "bloomberg-mcp",
      "transport": "stdio",
      "command": ["python", "-m", "mcp_bloomberg"],
      "env": {"BLOOMBERG_API_KEY_REF": "vault:bloomberg/api-key"}
    },
    {
      "name": "risk-engine-mcp",
      "transport": "sse",
      "url": "http://risk-engine-mcp.deep-agent-mcp.svc:8080/sse"
    }
  ]
}
```

2. **Skill-level** (`mcp-servers` in SKILL.md frontmatter) — enables self-contained skills that bundle their own MCP dependency. No tenant config required.

```yaml
# In SKILL.md frontmatter
mcp-servers:
  - name: market-data
    transport: sse
    url: http://localhost:8080/sse
```

#### Skill-Level MCP: Two Modes

Skills can use MCP servers in two ways:

**Mode 1 — Server only (discover all tools):** The skill declares a server and the orchestrator discovers all tools it exposes at runtime. The agent uses whichever tools are appropriate. Good for general-purpose servers.

```yaml
mcp-servers:
  - name: market-data
    transport: sse
    url: http://localhost:8080/sse
```

**Mode 2 — Server + specific tool binding:** The skill declares servers AND explicitly binds specific steps to specific tools on specific servers. This is the most precise and self-documenting approach. Good for multi-server skills where each step uses a different data source.

```yaml
allowed-tools:
  - execute_code
  - get_market_data
  - get_fx_rates
mcp-servers:
  - name: market-data
    transport: sse
    url: http://localhost:8080/sse
  - name: fx-service
    transport: sse
    url: http://localhost:9090/sse
mcp-tool-bindings:
  - tool: get_market_data
    server: market-data
  - tool: get_fx_rates
    server: fx-service
```

In Mode 2, bindings are declared in frontmatter via `mcp-tool-bindings` and enforced by the orchestrator.

#### Merge Rules

| Scenario | Result |
|----------|--------|
| Skill has `mcp-servers`, no tenant `mcp.json` | Skill's URLs used directly — fully self-contained |
| Tenant has `mcp.json`, skill has no `mcp-servers` | Tenant config used |
| Both exist, same server name | **Tenant wins** — ops can redirect without modifying the skill |
| Both exist, different server names | Both available — merged |

#### Lifecycle

1. On session start, the orchestrator reads the tenant's `mcp.json` (if present) and the matched skill's `mcp-servers` (if declared).
2. Server configs are merged (tenant takes precedence on name conflicts).
3. `langchain-mcp-adapters` connects to each MCP server and discovers available tools.
4. In Mode 2, explicit tool→server bindings from `mcp-tool-bindings` are enforced; in Mode 1, all discovered tools from the named server are available.
5. Discovered tools are merged with skill-defined `allowed_tools` — a tool is only available to the agent if the matched skill permits it.
6. Tools are passed to `RuntimeAdapter.create_agent()` alongside built-in tools (sandbox, DB query).

#### Skill-Bundled Scripts

Skills bundle their own code in `scripts/` per the **Anthropic AgentSkills spec**. There is no centralized Internal Library Registry. Each skill's `scripts/` directory contains the Python modules the skill needs, and `scripts/requirements.txt` declares third-party dependencies.

For example, the `zscore-monitor` skill bundles `scripts/firm_stats.py` directly — the sandbox code does `from firm_stats import zscore, moving_avg` rather than importing from a pre-installed `firm.*` package.

---

### 4.5 Chat API (WebSocket)

The Chat API is a WebSocket endpoint that the React portal connects to for real-time, streaming agent interactions.

#### Connection

```
wss://{host}/ws/chat?token={oauth_access_token}
```

On connect, the server validates the OAuth/OIDC token, extracts tenant membership and roles, and establishes a session.

#### Message Protocol

All messages are JSON with a `type` discriminator:

**Client → Server:**

```json
{"type": "user_message", "content": "Show me AAPL fundamentals for last quarter", "session_id": "..."}
```

**Server → Client:**

| Event Type | Payload | Description |
|---|---|---|
| `agent_chunk` | `{"content": "Let me query..."}` | Streaming text token from the LLM |
| `tool_call` | `{"tool": "execute_code", "input": {"code": "..."}}` | Agent is invoking a tool (shown in UI as a collapsible block) |
| `tool_result` | `{"tool": "execute_code", "output": "...", "files": {"chart.png": "<base64>"}}` | Tool execution result, may include images |
| `skill_match` | `{"skill_id": "equities/query-fundamentals", "confidence": 0.92}` | Informational — which skill was selected |
| `agent_complete` | `{"summary": "...", "tokens_used": 1847}` | Agent has finished responding |
| `error` | `{"code": "SANDBOX_TIMEOUT", "message": "..."}` | Error during processing |

#### Session Management

- Sessions are stored in **Redis** with a configurable TTL (default: 4 hours).
- Each session holds: conversation history, tenant context, matched skills, active sandbox references.
- Sessions are scoped to a single user within a single tenant. A user with access to multiple desks selects the active desk on session creation.
- **Persistence:** Completed conversations are flushed to **PostgreSQL** for long-term storage, search, and audit correlation.

---

## 5. Skills Specification

### 5.1 SKILL.md Format

Every skill is a single Markdown file with YAML frontmatter. This is the **only** authoring format — no Python, no JSON schemas, no framework imports.

```yaml
---
name: "<Human-readable skill name>"
description: "<One-line summary — used in discovery tier>"
version: "1.0"
tags: [<keyword>, ...]
allowed-tools:
  - <tool_name>
  - ...
inputs:
  - name: "<parameter>"
    description: "<what this input represents>"
    required: true | false
quality:
  timeout: <seconds>
  max-retries: <int>
  validation: "<natural-language acceptance criteria>"
---

# <Skill Name>

## Purpose
<What this skill does and when the agent should use it.>

## Instructions
<Step-by-step directions for the agent — written in plain language.>

## Examples
<Worked input/output examples the LLM can use as few-shot demonstrations.>

## Quality Standards
<Constraints, edge cases, output format requirements.>
```

#### Skill Directory Structure (Anthropic AgentSkills Spec)

Each skill is a self-contained directory following the Anthropic AgentSkills specification:

```
skill-name/
├── SKILL.md                  # Skill definition (max 5,000 words; overflow → references/)
├── scripts/
│   ├── requirements.txt      # Skill-specific Python dependencies
│   └── *.py                  # Bundled Python scripts used by the skill
├── references/
│   └── *.md                  # Extended documentation, data dictionaries, etc.
└── assets/
    └── *                     # Static assets (templates, sample data, configs)
```

- **SKILL.md** is limited to 5,000 words. Longer content goes in `references/`.
- **`scripts/requirements.txt`** declares the skill's Python dependencies. The sandbox installs these at execution time (with per-skill caching).
- **`scripts/*.py`** contains Python modules the skill's sandbox code can import directly.

#### Frontmatter Field Reference

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Human-readable name shown in discovery |
| `description` | string | yes | One-line summary for system prompt injection |
| `version` | string | yes | Semver — used for changelog and rollback |
| `tags` | list[string] | yes | Keywords for matching (e.g., `database`, `equities`, `statistics`) |
| `allowed-tools` | list[string] | yes | Whitelist of tools the agent may invoke when executing this skill |
| `inputs` | list[object] | no | Named parameters the user should provide |
| `quality.timeout` | int | no | Max execution time in seconds (default: 60) |
| `quality.max-retries` | int | no | Auto-retry on sandbox failure (default: 1) |
| `mcp-servers` | list[object] | no | MCP servers the skill needs (see §4.4). Each entry: `name`, `transport`, `url` (or `command` for stdio). Enables self-contained skills without tenant config. |
| `mcp-tool-bindings` | list[object] | no | Explicit tool→server routing (see §4.4 Mode 2). Each entry: `tool` (tool name), `server` (server name from `mcp-servers`). Enforced by the orchestrator. |
| `quality.validation` | string | no | Natural-language acceptance criteria the agent self-checks |

### 5.2 Authoring Guidelines for Business Desks

Skills are written by domain experts — traders, risk managers, analysts — not engineers. The following guidelines ensure skills are effective:

1. **Write for an intelligent colleague, not a machine.** Describe the task as if briefing a new analyst who is technically capable but unfamiliar with your desk's conventions.
2. **Be explicit about data sources.** Name the database alias (`ch-equities`), table (`fundamentals_daily`), and relevant columns. The agent cannot guess schema.
3. **Include at least one worked example.** Show a concrete user question, the expected SQL/Python, and the expected output shape. This serves as a few-shot prompt.
4. **State what "good" looks like.** Under Quality Standards, specify: output format (table, chart, number), precision requirements, edge cases to handle (missing data, weekends, holidays).
5. **Keep skills focused.** One skill = one workflow. If a workflow has independent sub-tasks, split into separate skills that compose naturally.
6. **Use `allowed-tools` as a guardrail.** Only list the tools this skill actually needs. A skill that queries a database but never plots should not include `plot_chart`.

### 5.3 Worked Examples

#### 5.3.1 `common/db-query/SKILL.md` — General Database Query

```yaml
---
name: "Database Query"
description: "Query any registered database using natural language. Translates user questions into SQL/Python, executes in sandbox, and returns results."
version: "1.0"
tags: [database, query, sql, general]
allowed-tools:
  - query_database
  - execute_code
inputs:
  - name: question
    description: "The user's natural-language data question"
    required: true
  - name: database_alias
    description: "Target database alias (optional — agent infers from context if omitted)"
    required: false
quality:
  timeout: 60
  max-retries: 1
  validation: "Result must include row count. If query returns 0 rows, confirm with user that filters are correct before retrying."
---

# Database Query

## Purpose
Use this skill when the user asks a data question that requires querying a registered database. You have access to ClickHouse, Redis, MongoDB, and MySQL via tenant-scoped aliases.

## Instructions
1. Identify which database alias is relevant from the available aliases in your context.
2. Use `query_database` to retrieve the schema (tables, columns, types) for that alias.
3. Write Python code that connects using environment variables (`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASS`) and executes the appropriate query.
4. Execute the code in the sandbox via `execute_code`.
5. Present results as a formatted table. If more than 20 rows, summarize and offer to show full results.

## Examples

**User:** "What were the top 10 stocks by volume on 2026-03-07?"

**Agent approach:**
- Alias: `ch-equities`
- Query: `SELECT symbol, volume, close FROM fundamentals_daily WHERE date = '2026-03-07' ORDER BY volume DESC LIMIT 10`
- Present as a table with columns: Symbol, Volume, Close Price

## Quality Standards
- Always use parameterized queries or proper escaping — never interpolate user strings into SQL.
- Include the row count in the response.
- If a query takes longer than 30 seconds, add a `LIMIT 1000` and inform the user.
```

#### 5.3.2 `common/visualization/SKILL.md` — Chart Generation

```yaml
---
name: "Visualization"
description: "Generate charts and plots from data using matplotlib or plotly. Returns rendered images in chat."
version: "1.0"
tags: [visualization, chart, plot, matplotlib, plotly]
allowed-tools:
  - execute_code
  - query_database
inputs:
  - name: data_description
    description: "What data to visualize and how"
    required: true
quality:
  timeout: 60
  validation: "Chart must have a title, labeled axes, and a legend if multiple series."
---

# Visualization

## Purpose
Use this skill when the user asks for a chart, plot, graph, or visual representation of data.

## Instructions
1. If data is not already in memory, query it first using the appropriate database alias.
2. Write Python code using `matplotlib` or `plotly`:
   - Use `matplotlib` for static charts (line, bar, scatter, histogram).
   - Use `plotly` for interactive charts (write to HTML) — prefer when the user asks to "explore" or "interact with" data.
3. Always save output to `/output/`:
   - `plt.savefig("/output/chart.png", dpi=150, bbox_inches="tight")` for matplotlib.
   - `fig.write_html("/output/chart.html")` or `fig.write_image("/output/chart.png")` for plotly.
4. Present the chart with a brief description of what it shows.

## Examples

**User:** "Plot AAPL closing price for the last 90 days"

**Agent approach:**
```python
import os
import clickhouse_connect
import matplotlib.pyplot as plt

client = clickhouse_connect.get_client(
    host=os.environ["DB_HOST"],
    port=int(os.environ["DB_PORT"]),
    username=os.environ["DB_USER"],
    password=os.environ["DB_PASS"],
)
df = client.query_df(
    "SELECT date, close FROM fundamentals_daily WHERE symbol='AAPL' "
    "AND date >= today() - 90 ORDER BY date"
)
fig, ax = plt.subplots(figsize=(10, 5))
ax.plot(df["date"], df["close"])
ax.set_title("AAPL Closing Price — Last 90 Days")
ax.set_xlabel("Date")
ax.set_ylabel("Close ($)")
ax.grid(True, alpha=0.3)
fig.savefig("/output/chart.png", dpi=150, bbox_inches="tight")
```

## Quality Standards
- Every chart must have: title, axis labels, grid.
- Use a legend when plotting multiple series.
- Default figure size: 10×5 inches, 150 DPI.
- For time series, format x-axis dates readably (no overlapping labels).
```

### 5.4 Reference Example — Z-Score Monitor with Moving Average

This is the **reference skill** that demonstrates a self-contained skill with bundled scripts (`scripts/firm_stats.py`) combined with ClickHouse querying. It lives at `skills/equities/zscore-monitor/SKILL.md`.

```yaml
---
name: "Z-Score & Moving Average Monitor"
description: "Compute z-scores and moving averages for equity metrics using bundled firm_stats scripts, with data sourced from ClickHouse. Flags statistical outliers and generates overlay charts."
version: "1.0"
tags: [statistics, z-score, moving-average, equities, monitor, clickhouse]
allowed-tools:
  - query_database
  - execute_code
inputs:
  - name: symbol
    description: "Ticker symbol (e.g., AAPL, MSFT)"
    required: true
  - name: metric
    description: "Column to analyze (e.g., close, volume, pe_ratio)"
    required: false
  - name: window
    description: "Lookback window in trading days (default: 60)"
    required: false
  - name: z_threshold
    description: "Z-score threshold for outlier flagging (default: 2.0)"
    required: false
quality:
  timeout: 90
  max-retries: 1
  validation: >
    Output must include: (1) a summary table with current value, moving average,
    z-score, and outlier flag; (2) a dual-axis chart with the raw metric,
    moving average overlay, and z-score bands highlighted.
---

# Z-Score & Moving Average Monitor

## Purpose
Use this skill when the user wants to:
- Detect statistical outliers in equity time-series data.
- Compute rolling z-scores or moving averages for any numeric metric.
- Visualize a metric against its statistical norms.

This skill uses bundled **`scripts/firm_stats.py`** for z-score and moving average computation, and queries **ClickHouse** (`ch-equities`) for raw data.

## Instructions
1. Query ClickHouse alias `ch-equities`, table `fundamentals_daily`, for the requested symbol and metric over a sufficient history (at least 2× the lookback window).
2. Use `firm_stats.moving_avg(series, window)` (from bundled `scripts/firm_stats.py`) to compute the rolling mean.
3. Use `firm_stats.zscore(series, window)` to compute the rolling z-score.
4. Flag rows where `abs(z_score) >= z_threshold` as outliers.
5. Generate a dual-panel chart:
   - **Top panel:** raw metric line + moving average line + shaded z-score bands (±threshold × std around the MA).
   - **Bottom panel:** z-score line with horizontal threshold lines at ±threshold.
6. Return a summary table: date, current value, moving average, z-score, outlier flag.

## Examples

**User:** "Show me z-scores for AAPL volume over the last 60 days, flag anything above 2 sigma"

**Agent generates:**
```python
import os
import clickhouse_connect
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from firm_stats import zscore, moving_avg

# --- 1. Query data ---
client = clickhouse_connect.get_client(
    host=os.environ["DB_HOST"],
    port=int(os.environ["DB_PORT"]),
    username=os.environ["DB_USER"],
    password=os.environ["DB_PASS"],
)
df = client.query_df(
    "SELECT date, volume FROM fundamentals_daily "
    "WHERE symbol = 'AAPL' AND date >= today() - 180 "
    "ORDER BY date"
)

# --- 2. Compute statistics using firm_stats (bundled in scripts/) ---
window = 60
threshold = 2.0
df["ma"] = moving_avg(df["volume"], window)
df["z"] = zscore(df["volume"], window)
df["outlier"] = df["z"].abs() >= threshold

# Trim to display window (last 60 trading days)
df_display = df.tail(window).copy()

# --- 3. Summary table ---
latest = df_display.iloc[-1]
print(f"Symbol:         AAPL")
print(f"Metric:         volume")
print(f"Current Value:  {latest['volume']:,.0f}")
print(f"Moving Avg:     {latest['ma']:,.0f}")
print(f"Z-Score:        {latest['z']:.2f}")
print(f"Outlier:        {'YES' if latest['outlier'] else 'no'}")
print(f"\nOutlier days in window: {df_display['outlier'].sum()}")
print(df_display[df_display["outlier"]][["date", "volume", "ma", "z"]].to_string(index=False))

# --- 4. Dual-panel chart ---
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), sharex=True,
                                gridspec_kw={"height_ratios": [2, 1]})

# Top panel: metric + MA + bands
ax1.plot(df_display["date"], df_display["volume"], label="Volume", linewidth=1.2)
ax1.plot(df_display["date"], df_display["ma"], label=f"{window}-day MA",
         linewidth=1.5, linestyle="--")
std = df_display["volume"].rolling(window, min_periods=1).std()
ax1.fill_between(df_display["date"],
                 df_display["ma"] - threshold * std,
                 df_display["ma"] + threshold * std,
                 alpha=0.15, color="orange", label=f"±{threshold}σ band")
outliers = df_display[df_display["outlier"]]
ax1.scatter(outliers["date"], outliers["volume"], color="red", zorder=5,
            label="Outlier", s=40)
ax1.set_ylabel("Volume")
ax1.set_title(f"AAPL Volume — Z-Score Monitor ({window}-day window)")
ax1.legend(loc="upper left", fontsize=8)
ax1.grid(True, alpha=0.3)

# Bottom panel: z-score
ax2.plot(df_display["date"], df_display["z"], color="steelblue", linewidth=1.2)
ax2.axhline(y=threshold, color="red", linestyle="--", linewidth=0.8, label=f"+{threshold}")
ax2.axhline(y=-threshold, color="red", linestyle="--", linewidth=0.8, label=f"-{threshold}")
ax2.axhline(y=0, color="gray", linestyle="-", linewidth=0.5)
ax2.fill_between(df_display["date"], threshold, df_display["z"],
                 where=df_display["z"] >= threshold, alpha=0.3, color="red")
ax2.fill_between(df_display["date"], -threshold, df_display["z"],
                 where=df_display["z"] <= -threshold, alpha=0.3, color="red")
ax2.set_ylabel("Z-Score")
ax2.set_xlabel("Date")
ax2.legend(loc="upper left", fontsize=8)
ax2.grid(True, alpha=0.3)
ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))

plt.tight_layout()
fig.savefig("/output/chart.png", dpi=150, bbox_inches="tight")
```

**Agent responds with:**
- The summary table (current value, MA, z-score, outlier flag).
- The dual-panel chart image.
- A plain-language interpretation: *"AAPL volume is currently 1.8σ above the 60-day moving average. 3 outlier days were detected in the window, most recently on Mar 5 when volume spiked to 2.4σ following the earnings announcement."*

## Quality Standards
- Always fetch at least 2× the window length of history to ensure the moving average and z-score are stable from day one of the display range.
- Use `firm_stats.zscore` and `firm_stats.moving_avg` (bundled in `scripts/`) — do not re-implement these from scratch.
- Chart must have: title, axis labels, legend, grid, date formatting.
- The summary must include the plain-language interpretation — do not just dump numbers.
- If the requested metric column does not exist in the schema, list available columns and ask the user to choose.

### 5.5 Multi-Skill Composition

A single user query may span multiple domains — for example, computing VaR for a portfolio (risk skill) while simultaneously flagging z-score outliers in the positions (monitoring skill). Multi-skill composition allows the orchestrator to activate **multiple skills** for a single message so the LLM can generate a unified response that draws on all of them.

#### Matching: `min_score` threshold

`SkillEngine.match()` accepts a `min_score` parameter as the sole relevance filter. The orchestrator calls `match(message, bindings, min_score=0.01)`. All bound skills scoring at or above `min_score` are activated — there is no artificial cap on the number of active skills. The candidate set is already scoped by the agent's `bound_skill_ids` (typically 3–8 skills). One `SkillMatchEvent` is emitted per activated skill, in descending score order. The event schema (`skill_id`, `confidence`) is unchanged — only the cardinality changes.

#### Merge strategies

| Field | Strategy | Detail |
|-------|----------|--------|
| `allowed-tools` | **Union** (sorted) | All activated skills' tools are combined. `None` if no skills match (preserves no-filtering behavior). |
| `scripts/` dirs | **Collect** non-empty paths | Ordered by score (highest first). All directories are joined onto `PYTHONPATH`, so sandbox code can `import` modules from any activated skill. |
| `quality.timeout` | **max()** across skills | Highest timeout wins. Falls back to the default (60s) if no skill exceeds it. |
| `mcp-servers` | **Concatenate**, deduplicate by name | First-seen (highest-scored) server definition wins on name collision. |
| `mcp-tool-bindings` | **Concatenate**, deduplicate by tool name | Higher-scored skill's binding wins on conflict; the lower-scored duplicate is silently dropped with a debug log. |

#### System prompt format

- **0 skills matched:** No active skills section (unchanged).
- **1 skill matched:** `## Active Skill: {name}` + body (unchanged — full backward compatibility).
- **2+ skills matched:** `## Active Skills` header, a composition instruction, then `### Skill: {name}` + body for each activated skill.

The composition instruction tells the LLM:

> You may combine functionality from multiple active skills in a single `execute_code` call. Each skill's `scripts/` directory is on PYTHONPATH.

#### Conflict resolution

| Scenario | Resolution |
|----------|------------|
| Two skills share a script filename (e.g., `utils.py`) | Warning logged. Python uses the first `PYTHONPATH` entry, so the higher-scored skill's version wins. |
| Skill A allows `[execute_code]`, Skill B allows `[execute_code, get_data]` | Union: both tools available. |
| MCP tool binding conflict (same tool name, different servers) | Higher-scored skill's binding wins. |
| Skill load fails for one of two matches | Failed skill is skipped (warning logged); the other proceeds as sole active skill. |

#### Backward compatibility

Single-skill queries produce identical results to the pre-composition behavior: same event count, same prompt format (`## Active Skill:` singular), same tool filtering. The `min_score=0.01` threshold ensures zero-scoring skills are excluded while keeping the activation bar low for legitimate cross-skill queries.

#### Demo & validation

- **`scripts/demo_equities_agent.py`** includes a cross-domain skill matching demo: a single query triggers both equities and risk skills simultaneously, exercising the full multi-skill composition pipeline.
- A multi-skill banner is displayed when 2+ skills activate, making it easy to visually confirm composition is working.
- `DEMO_QUESTIONS` includes a dedicated multi-skill cross-domain query for quick smoke-testing.
- **`scripts/demo_risk_agent.py`** provides a standalone risk-domain demo for single-skill baseline comparison.
- `test_multi_skill_cross_domain_query` provides automated coverage for the cross-domain matching path.

---

## 6. Security & Sandboxing

### 6.1 Threat Model

Deep Agent operates in a financial institution where data sensitivity is high, regulatory scrutiny is constant, and the blast radius of a breach extends to client assets and market operations. The primary threat vectors are:

| Threat | Vector | Mitigation Section |
|---|---|---|
| **LLM prompt injection** | Malicious user input causes the agent to bypass controls | §6.3 Input Sanitization |
| **Sandbox escape** | Agent-generated code breaks out of execution boundary | §6.2 Sandbox Hardening |
| **Credential exfiltration** | Code attempts to read/leak database credentials | §6.4 Credential Management |
| **Cross-tenant data access** | User in Desk A accesses Desk B's data | §7 Multi-Tenancy |
| **Audit evasion** | Actions occur without logging | §6.5 Audit Trail |
| **Denial of service** | Runaway code consumes cluster resources | §6.2 Resource Limits |

### 6.2 Sandbox Hardening

#### PythonSubprocessSandbox (Dev / MVP)

- Runs under a dedicated OS user with no shell access beyond the subprocess.
- `resource` module limits: CPU time, memory, file descriptors.
- Writable only to `/tmp/sandbox-{execution_id}/output/`.
- Network access restricted to loopback + approved DB endpoints via `iptables` rules.
- Process killed after `timeout` seconds (default: 60).

#### OpenShiftPodSandbox (Production)

| Control | Setting |
|---|---|
| User | `runAsNonRoot: true`, `runAsUser: 65534` (nobody) |
| Filesystem | `readOnlyRootFilesystem: true`; writable `emptyDir` mounted at `/output/` |
| CPU | `limits.cpu: "2"` |
| Memory | `limits.memory: "4Gi"` |
| Timeout | Pod-level `activeDeadlineSeconds: 90` |
| Network | `NetworkPolicy`: egress allowed only to DB service endpoints in `deep-agent-platform` namespace; all other egress denied |
| Capabilities | `drop: [ALL]` — no Linux capabilities |
| Privilege escalation | `allowPrivilegeEscalation: false` |
| Service account | No-token SA — no K8s API access from sandbox |
| Image | Minimal base: `python:3.12-slim` + pinned analytics libraries; no shell utilities beyond Python |

#### Pod Lifecycle

```
execute() called
    │
    ├─ Create Pod from template (inject code as ConfigMap volume)
    ├─ Inject env vars (DB credentials from Secret Store)
    ├─ Wait for Pod completion or timeout
    ├─ Copy /output/ files from Pod
    ├─ Record exit code, stdout, stderr
    └─ Delete Pod (immediate; no lingering resources)
```

### 6.3 Input Sanitization

All user input passes through a sanitization pipeline before reaching the LLM:

1. **Character filtering.** Strip null bytes, control characters (except newlines), and Unicode homoglyph sequences.
2. **Prompt injection detection.** A lightweight classifier (rule-based at MVP, ML-based post-MVP) scans for common injection patterns:
   - Role override attempts ("ignore previous instructions", "you are now...")
   - Tool-forcing patterns ("call execute_code with the following...")
   - Encoded payloads (base64, hex, Unicode escapes embedding instructions)
3. **Length limits.** User messages capped at 32,000 characters. Messages exceeding the limit are rejected with an error event.
4. **Flagging, not silent dropping.** Suspicious inputs are flagged in the audit log (`category: input_sanitization`, `action: flagged`) and optionally escalated to `desk_admin`. The agent still processes the query unless the risk score exceeds a configurable threshold.

### 6.4 Credential Management

Credentials are **never** exposed to the LLM, the user, or the agent-generated code as literal values.

```
┌──────────────────────┐       ┌──────────────────────┐
│  Secret Store        │       │  K8s Secret          │
│  (Vault / External   │──────►│  (synced by          │
│   Secrets Operator)  │       │   ExternalSecret)    │
└──────────────────────┘       └─────────┬────────────┘
                                         │
                               ┌─────────▼────────────┐
                               │  SandboxManager       │
                               │  injects as env vars  │
                               │  into Pod spec        │
                               └─────────┬────────────┘
                                         │
                               ┌─────────▼────────────┐
                               │  Sandbox code uses    │
                               │  os.environ["DB_*"]   │
                               └──────────────────────┘
```

**Controls:**

- Secret Store (HashiCorp Vault or equivalent) is the single source of truth.
- K8s `ExternalSecret` resources sync secrets into the platform namespace — never into the sandbox namespace.
- The `SandboxManager` injects only the secrets required by the resolved `DatabaseAlias` into the Pod's environment.
- Env var names are generic (`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASS`) — the LLM is instructed to reference them by these names, never to output their values.

#### Output Scanning

Every `ExecuteResult.stdout` and `ExecuteResult.stderr` is scanned before being returned to the LLM or user:

- Regex patterns for common credential formats (API keys, connection strings with passwords, JWT tokens).
- Matches are redacted (`[REDACTED]`) and flagged in the audit log.

### 6.5 Audit Trail

Every action in the system is logged as a structured JSON event. This is non-negotiable — audit logging cannot be disabled per tenant or per user.

#### Event Schema

```json
{
  "timestamp": "2026-03-09T14:32:07.123Z",
  "trace_id": "abc123",
  "session_id": "sess-789",
  "user_id": "jane.doe@firm.com",
  "tenant_id": "equities",
  "category": "code_execution",
  "action": "sandbox_execute",
  "detail": {
    "code_hash": "sha256:...",
    "exit_code": 0,
    "duration_ms": 2340,
    "output_files": ["chart.png"],
    "db_aliases_accessed": ["ch-equities"]
  },
  "risk_level": "standard"
}
```

#### Event Categories

| Category | Logged Events |
|---|---|
| `llm_call` | Every LLM invocation: model, token count, latency, truncated prompt hash |
| `tool_call` | Every tool invocation: tool name, input summary, output summary |
| `code_execution` | Every sandbox run: code hash, exit code, duration, output files |
| `data_access` | Every database query: alias, query hash, row count, duration |
| `skill_match` | Every skill match: skill ID, confidence score, matched tags |
| `auth` | Login, logout, token refresh, permission denied events |
| `input_sanitization` | Flagged inputs: pattern matched, risk score, action taken |
| `error` | All errors: category, message, stack trace hash |

#### Storage & Retention

| Store | Purpose | Retention |
|---|---|---|
| **Deployer-configured analytics backend** | Analytics queries on audit data (dashboards, anomaly detection) | 1 year rolling |
| **S3 / Minio** | Immutable, compressed archive (compliance) | 7 years (regulatory requirement) |
| **PostgreSQL** | Session & conversation persistence, correlated with audit `trace_id` | 1 year |

All audit writes are **asynchronous** (queued via Redis) to avoid impacting agent response latency. The audit pipeline guarantees at-least-once delivery — if ClickHouse is temporarily unavailable, events are buffered in Redis and flushed on recovery.

#### Audit Query API

Platform admins can query audit logs via a read-only API:

```
GET /api/v1/audit?tenant=equities&user=jane.doe&category=data_access&from=2026-03-01&to=2026-03-09
```

This powers the admin dashboard for compliance reviews, incident investigation, and usage analytics.

---

## 7. Multi-Tenancy

### 7.1 Tenant Model

The primary tenant boundary is the **business desk** (Equities, Fixed Income, Risk, Compliance, etc.). Within a desk, an optional **team** sub-tenant can further segment access for large desks with distinct groups.

```
Firm
├── Equities (tenant)
│   ├── Cash Equities (team, optional)
│   └── Derivatives (team, optional)
├── Fixed Income (tenant)
├── Risk (tenant)
└── Compliance (tenant)
```

Each tenant is a self-contained configuration unit that owns:

| Resource | Tenant-Scoped? | Description |
|---|---|---|
| Skills | No (agent-scoped) | All skills are in the global registry. Access control is at the agent level via `AgentSkillBindings`, not tenant-scoped directories. |
| Database aliases | Yes | Each tenant sees only its registered aliases in `DatabaseRegistry` |
| MCP config | Yes | `config/tenants/{tenant_id}/mcp.json` — independent tool sets |
| Resource quotas | Yes | Max concurrent sandboxes, LLM token budget per day/month |
| User membership | Yes | Derived from OAuth/OIDC group claims |
| Audit logs | Yes | Logs are tagged with `tenant_id`; query API filters by tenant |
| Conversation history | Yes | Sessions and persisted conversations belong to one tenant |
| LLM config | Yes | Tenant can override default model, temperature, max tokens |

### 7.2 Tenant Configuration

Tenant configuration is stored in PostgreSQL and cached in Redis. Schema:

```python
@dataclass
class TenantConfig:
    tenant_id: str                    # "equities"
    display_name: str                 # "Equities Desk"
    skills_dirs: list[str]            # ["skills/common", "skills/equities"]
    db_aliases: list[str]             # ["ch-equities", "redis-pricing"]
    mcp_config_path: str              # "config/tenants/equities/mcp.json"
    llm_overrides: LLMConfig | None   # optional model/temperature override
    quotas: TenantQuotas              # resource limits
    teams: list[TeamConfig]           # optional sub-tenants

@dataclass
class TenantQuotas:
    max_concurrent_sandboxes: int = 10
    max_daily_llm_tokens: int = 5_000_000
    max_monthly_llm_tokens: int = 100_000_000
    max_session_duration_hours: int = 8
    max_code_execution_seconds: int = 90
```

### 7.3 Tenant Isolation

Every layer enforces tenant boundaries:

| Layer | Isolation Mechanism |
|---|---|
| **Auth** | OAuth/OIDC token claims include group membership → mapped to `tenant_id` at session creation |
| **Orchestration** | `TenantContext` is threaded through every call; `AgentRouter` refuses cross-tenant requests |
| **Skills** | All skills in the global registry are available to any tenant. Access control is at the agent level — each agent config binds specific skills via `AgentSkillBindings`. |
| **Database** | `DatabaseRegistry.list_aliases(tenant)` returns only that tenant's aliases; connection configs are tenant-scoped in the secret store |
| **Sandbox** | Pod labels include `tenant_id`; `NetworkPolicy` selectors scope egress per tenant |
| **MCP** | MCP server connections are established per-tenant per-session; no shared tool state |
| **Audit** | Every audit event carries `tenant_id`; query API enforces tenant filter for non-platform-admin roles |
| **LLM Context** | System prompt includes tenant name, skill set, and DB metadata — never cross-tenant information |

### 7.4 Roles & Permissions

Deep Agent defines four roles. Roles are hierarchical — each level inherits permissions from below.

| Role | Scope | Permissions |
|---|---|---|
| `agent_user` | Tenant | Chat with agent, view own conversation history |
| `skill_author` | Tenant | All of `agent_user` + create/edit/delete skills in their tenant directory, view skill usage metrics |
| `desk_admin` | Tenant | All of `skill_author` + manage tenant config (DB aliases, MCP, quotas, team membership), view tenant audit logs, manage team sub-tenants |
| `platform_admin` | Global | All of `desk_admin` across all tenants + manage tenants, view global audit, manage LLM router config, manage platform deployment |

#### Role Resolution

```
OAuth/OIDC token
    │
    ├─ Extract group claims (e.g., "equities-users", "equities-admins", "platform-admins")
    │
    ▼
Role Mapper (configurable mapping table)
    │
    ├─ "equities-users"    → tenant=equities, role=agent_user
    ├─ "equities-authors"  → tenant=equities, role=skill_author
    ├─ "equities-admins"   → tenant=equities, role=desk_admin
    └─ "platform-admins"   → tenant=*, role=platform_admin
```

The mapping table is stored in PostgreSQL and editable by `platform_admin` via the Admin API. This keeps role logic out of the identity provider, allowing any OAuth/OIDC-compliant IdP (Okta, Azure AD, Keycloak, PingFederate) to work without custom claim configuration.

### 7.5 Team Sub-Tenants

For large desks, an optional team layer provides finer-grained segmentation:

- A team inherits its parent tenant's DB aliases, MCP config, and quotas by default.
- Teams can define **additional** skills (in `skills/{tenant}/{team}/`), but cannot remove parent skills.
- Teams can have **reduced** quotas (subset of parent), but not increased.
- Team membership is resolved from OAuth/OIDC group claims, nested under the parent tenant group.
- Audit logs carry both `tenant_id` and `team_id` for drill-down.

Teams are optional — a tenant with no teams configured behaves identically to the base model.

---

## 8. Deployment Model

### 8.1 Target Infrastructure

Deep Agent is deployed on **self-hosted Kubernetes** (vanilla K8s or OpenShift) within the firm's private network. There is no dependency on any public cloud managed service — all components run on-premise.

### 8.2 Namespace Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  Cluster                                                        │
│                                                                  │
│  ┌──────────────────────────────────┐                           │
│  │  deep-agent-platform             │                           │
│  │  ├─ api (FastAPI, WebSocket)     │  Deployments              │
│  │  ├─ worker (async task runner)   │                           │
│  │  ├─ postgresql                   │  StatefulSets             │
│  │  ├─ redis                        │                           │
│  └──────────────────────────────────┘                           │
│                                                                  │
│  ┌──────────────────────────────────┐                           │
│  │  deep-agent-sandboxes            │                           │
│  │  ├─ (ephemeral Pods, created     │  Jobs / Pods              │
│  │  │   on demand by SandboxManager)│                           │
│  │  └─ NetworkPolicy: egress only   │                           │
│  │     to deep-agent-platform DBs   │                           │
│  └──────────────────────────────────┘                           │
│                                                                  │
│  ┌──────────────────────────────────┐                           │
│  │  deep-agent-mcp                  │                           │
│  │  ├─ bloomberg-mcp                │  Deployments              │
│  │  ├─ risk-engine-mcp             │  (one per MCP server)     │
│  │  └─ ...                          │                           │
│  └──────────────────────────────────┘                           │
└─────────────────────────────────────────────────────────────────┘
```

### 8.3 Container Images

| Image | Base | Contents | Registry |
|---|---|---|---|
| `deep-agent-api` | `python:3.12-slim` | FastAPI app, WebSocket handler, SkillEngine, orchestrator | Internal registry |
| `deep-agent-worker` | `python:3.12-slim` | Async worker (audit flush, session cleanup, skill index rebuild) | Internal registry |
| `deep-agent-sandbox` | `python:3.12-slim` | Python 3.12-slim + pip. Skill dependencies installed at runtime from `scripts/requirements.txt` (with per-skill caching). | Internal registry |
| `deep-agent-mcp-*` | Varies per MCP server | MCP server process + dependencies | Internal registry |

All images are built in CI, scanned for vulnerabilities (Trivy or equivalent), signed, and pushed to the firm's internal container registry. No public registry pulls at runtime.

### 8.4 Autoscaling

| Component | Scaling Metric | Strategy |
|---|---|---|
| `api` | Active WebSocket connections | HPA, target 200 connections/pod |
| `worker` | Redis queue depth | HPA, target 50 pending tasks/pod |
| Sandbox Pods | Execution demand (concurrent Pods) | Controlled by `SandboxManager` pool; capped by `TenantQuotas.max_concurrent_sandboxes` cluster-wide |
| MCP servers | Request rate | HPA per MCP deployment, tuned per server |

Minimum replicas for `api` and `worker`: 2 (high availability). Sandbox Pods scale to zero when idle — no standing pool in production.

### 8.5 Skills CI/CD Pipeline

Skills are version-controlled in a Git repository (separate from the platform code). The pipeline:

```
skill author pushes to skills repo
    │
    ├─ CI: validate YAML frontmatter (schema check)
    ├─ CI: lint Markdown body (heading structure, required sections)
    ├─ CI: tenant authorization (author must be member of target tenant)
    ├─ CI: diff review (PR required; approved by desk_admin or skill_author peer)
    │
    ▼
merge to main
    │
    ├─ CD: sync skills directory to PersistentVolume (or ConfigMap) in deep-agent-platform
    └─ CD: trigger SkillEngine index rebuild (hot reload, no API restart)
```

### 8.6 Persistent Storage

| Volume | Type | Mounted By | Purpose |
|---|---|---|---|
| `skills-volume` | PVC (ReadOnlyMany) | `api`, `worker` | SKILL.md files synced from Git |
| `pg-data` | PVC (ReadWriteOnce) | `postgresql` | Tenant config, sessions, conversations |
| `redis-data` | PVC (ReadWriteOnce) | `redis` | Session cache, task queue, audit buffer |
| `audit-archive` | S3/Minio bucket | `worker` | 7-year immutable audit archive; audit analytics via deployer-configured backend |

### 8.7 High Availability & Disaster Recovery

- **API/Worker:** Multi-replica Deployments behind a Service; rolling updates with zero downtime.
- **PostgreSQL:** Primary-replica with streaming replication; automatic failover via Patroni or equivalent operator.
- **Redis:** Sentinel or Redis Cluster mode for HA.
- **Audit store:** Deployer-configured backend (e.g., ClickHouse, Elasticsearch, or cloud analytics service) with appropriate HA configuration.
- **Backup:** Nightly PostgreSQL pg_dump to S3/Minio; audit backend backup to S3/Minio. RPO: 24 hours. RTO: 1 hour.
- **Skills:** Git repo is the source of truth; PVC is rebuilt from Git on any failure.

---

## 9. Technology Stack

| Layer | Technology | Version | Justification |
|---|---|---|---|
| **Agent Framework** | `deepagents` (LangChain) | latest stable | Provides LangGraph-based agent loop, tool binding, streaming; abstracted behind `RuntimeAdapter` |
| **LLM (primary)** | OpenAI GPT-5 | — | Best-in-class reasoning for complex financial queries; code generation quality |
| **LLM (fallback)** | OpenAI GPT-4.1 | — | Cost-optimized for simpler queries; automatic fallback via LLM Router |
| **LLM (future)** | Claude, Gemini | — | Provider-agnostic router enables zero-code swap when models are approved |
| **API Framework** | FastAPI | 0.115+ | Async-native, WebSocket support, OpenAPI docs, Pydantic validation |
| **Streaming** | WebSocket (RFC 6455) | — | Real-time bidirectional streaming; native browser support |
| **Primary Database** | PostgreSQL | 16+ | Tenant config, session persistence, conversation history; ACID, mature ecosystem |
| **Cache / Queue** | Redis | 7+ | Session cache, async task queue (audit flush, cleanup), pub/sub for events |
| **Analytics DB** | ClickHouse (example) | 24+ | Example skill dependency for analytics; not a core framework requirement. Skills define their own data sources. |
| **Object Storage** | S3 / Minio | — | Audit archive (7-year), chart image storage, backup target |
| **Secret Management** | HashiCorp Vault | 1.15+ | Central credential store; dynamic secrets for DB access; K8s auth backend |
| **Auth** | OAuth 2.0 / OIDC | — | Pluggable identity provider (Okta, Azure AD, Keycloak, PingFederate) |
| **Container Orchestration** | Kubernetes / OpenShift | 1.28+ / 4.14+ | On-premise deployment; namespace isolation; NetworkPolicy; Pod security |
| **Sandbox Runtime** | Python subprocess / K8s Pod | 3.12 | Pluggable execution backend; subprocess for dev, Pod for production |
| **MCP Integration** | `langchain-mcp-adapters` | latest stable | Connects LangChain tools to MCP servers; per-tenant config |
| **Visualization** | matplotlib, plotly | 3.9+, 5.22+ | Static and interactive charts; rendered in sandbox, returned as images/HTML |
| **Internal Libraries** | Skills bundle own code | — | Skills bundle their own scripts in `scripts/` per the Anthropic AgentSkills spec. No centralized library registry. |
| **Observability** | LangSmith / OpenTelemetry | — | LLM call tracing (LangSmith); distributed tracing and metrics (OTel) |
| **Log Aggregation** | ELK Stack or Loki+Grafana | — | Platform logs (not audit — audit goes to ClickHouse/S3) |
| **CI/CD** | Jenkins / GitLab CI / Tekton | — | Firm-standard pipeline; builds images, validates skills, deploys via Helm/Kustomize |
| **Infrastructure as Code** | Helm / Kustomize | — | Templated K8s manifests for all components |

---

## 10. MVP Scope & Phasing

### 10.1 Phase 1 — Foundation (Weeks 1–4)

**Goal:** End-to-end agent loop — a single user on a single tenant can ask a natural-language question, the agent matches a skill, executes Python in a sandbox, and streams the answer back.

| Deliverable | Details |
|---|---|
| `RuntimeAdapter` protocol | Interface definition + `LangGraphAdapter` implementation using `deepagents` |
| `LLMRouter` | OpenAI GPT-5 integration; single-provider (no fallback yet) |
| `SkillEngine` | Discover, match (tag-based), load; hot reload from filesystem |
| WebSocket API | FastAPI app with `user_message` → `agent_chunk` / `tool_call` / `tool_result` / `agent_complete` streaming |
| `SandboxManager` | `PythonSubprocessSandbox` backend with resource limits |
| Resource Configuration | Generic resource env-var injection via tenant config |
| Example skills | `data-query/db-query`, `equities/zscore-monitor` — self-contained with scripts (ClickHouse z-score demo) |
| `scripts/invoke_agent.py` | CLI script for invoking the agent in isolation — no API server required. Useful for skill development and debugging. |
| End-to-end test | User asks "Show me z-scores for AAPL volume" → skill executes Python in sandbox → gets table + chart |

**Not in Phase 1:** Auth, multi-tenancy, persistence, audit logging, visualization skill (charts work via zscore-monitor, but no standalone viz skill yet).

### 10.2 Phase 2 — Enterprise Hardening (Weeks 5–8)

**Goal:** Production-grade security, multi-tenancy, and persistence. Two desks onboarded.

| Deliverable | Details |
|---|---|
| OAuth/OIDC auth | Token validation, tenant resolution from group claims, role mapping |
| Multi-tenancy | `TenantContext` threading, tenant-scoped skills/DB/MCP, 2 tenants (Equities + Risk) |
| PostgreSQL persistence | Tenant config, session storage, conversation history |
| Audit logging | Full audit pipeline: structured events → Redis queue → pluggable backend + S3 |
| Additional resource templates | Example resource configs for Redis, MongoDB, MySQL added to examples |
| LLM fallback | GPT-4.1 fallback in `LLMRouter`; tenant-level model override |
| Visualization skill | `common/visualization` SKILL.md; matplotlib + plotly support |
| Additional skills | 3–5 skills per onboarded desk |
| Output scanning | Credential pattern redaction in sandbox stdout/stderr |

### 10.3 Phase 3 — Scale & Integration (Weeks 9–12)

**Goal:** MCP integrations, production deployment on K8s/OpenShift, load tested and security reviewed.

| Deliverable | Details |
|---|---|
| MCP integration | `langchain-mcp-adapters` wired into orchestrator; per-tenant `mcp.json` config; 1–2 MCP servers deployed |
| `OpenShiftPodSandbox` | Production sandbox backend with full Pod security (§6.2) |
| Subagent support | Agent can spawn child agents for multi-step workflows (via `deepagents` subgraph) |
| Admin API | CRUD for tenants, DB aliases, quotas, role mappings; read-only audit query endpoint |
| K8s deployment | Helm charts for all components; namespace layout per §8.2 |
| Example skill libraries | Skills bundle `firm_stats.py` etc. in their own `scripts/` directories; documented in example skills |
| Skills CI/CD | Git-based pipeline per §8.5; PR review flow for skill authors |
| Load testing | Target: 50 concurrent sessions, 10 concurrent sandbox executions, p95 latency < 5s for text response |
| Security review | Penetration test of sandbox escape, prompt injection, cross-tenant access |
| Desk onboarding | 2 additional desks (Fixed Income + Compliance) — total 4 tenants |

### 10.4 Success Criteria

The MVP is considered successful when:

1. **Functional:** An Equities desk user can ask "Show me z-scores for AAPL volume over the last 60 days, flag anything above 2 sigma" and receive a summary table + dual-panel chart within **30 seconds**, entirely through the chat UI.
2. **Secure:** The full interaction (LLM calls, tool invocations, sandbox execution, DB access) is captured in the audit trail with user identity and tenant context.
3. **Multi-tenant:** A Risk desk user in the same cluster sees only Risk skills and Risk DB aliases — zero visibility into Equities data.
4. **Resilient:** Sandbox timeout, LLM error, and DB connection failure all produce graceful error messages (not stack traces) and are audit-logged.
5. **Extensible:** Adding a new skill requires only a `SKILL.md` file merged to the skills repo — no platform code change, no redeployment.

---

## 11. Future Roadmap

The following capabilities are planned for post-MVP phases. They are listed in approximate priority order, subject to revision based on desk feedback and organizational priorities.

### 11.1 Runtime Swap — Claude Agent SDK

Implement a `ClaudeAgentAdapter` conforming to the `RuntimeAdapter` protocol. This enables:

- Switching a tenant (or the entire platform) from LangGraph to Claude's native agent loop.
- A/B testing between runtimes on the same skill set.
- **Zero skill changes required** — the `SkillEngine` and all `SKILL.md` files remain untouched.

### 11.2 Embedding-Based Skill Matching

Replace tag-based `SkillEngine.match()` with a vector-similarity approach:

- Embed all skill descriptions and bodies using a sentence-transformer model.
- On each user query, compute embedding and retrieve top-k skills by cosine similarity.
- Enables scaling to **100+ skills** without degradation in match quality.
- Hybrid approach: embedding score combined with tag overlap for ranking.

### 11.3 Scheduled Agent Runs

Allow `desk_admin` to configure cron-scheduled agent executions:

- Define a schedule, a prompt template, and a delivery target (email, Slack, S3 report bucket).
- Example: "Every weekday at 7:00 AM, run the z-score monitor for our top 20 holdings and email the report to the desk."
- Reuses the same skills, sandbox, and audit pipeline — no separate execution path.

### 11.4 Human-in-the-Loop for High-Risk Operations

For sensitive workflows (trade booking, large data exports, compliance-flagged queries):

- Agent pauses and emits an `approval_required` WebSocket event.
- The UI presents the proposed action to the user (or a designated approver).
- Execution proceeds only after explicit approval; denial is audit-logged.
- Configurable per-skill via a `requires-approval: true` frontmatter field.

### 11.5 Advanced Integrations

| Integration | Description |
|---|---|
| **Trade booking** | Agent can submit trade orders via internal OMS API (behind human-in-the-loop approval) |
| **Market data streaming** | Real-time price feeds via WebSocket; agent can subscribe and react to events |
| **Bloomberg Terminal** | Bloomberg MCP server for BQL queries, reference data, news |
| **Compliance screening** | Pre-trade compliance checks invoked as a tool before any trade-related action |
| **Email / Slack** | Agent can send structured reports to email or Slack channels on behalf of the user |

### 11.6 Skill Governance & Analytics

As the skill library grows, governance becomes critical:

- **PR-based review:** All skill changes require approval from `desk_admin` or peer `skill_author` (enforced in CI).
- **Quality scoring:** Automated scoring based on: completeness (all required sections present), example coverage, validation criteria specificity.
- **Usage analytics:** Track per-skill: invocation count, success rate, average latency, user satisfaction (thumbs up/down).
- **Cost attribution:** LLM token usage and sandbox compute time attributed to the skill that triggered them, aggregated by tenant.
- **Deprecation workflow:** Skills below a usage threshold are flagged for review; deprecated skills are hidden from discovery but retained for audit history.

### 11.7 Multi-Region / DR

For global desks operating across time zones:

- Active-passive deployment across two data centers.
- PostgreSQL cross-region replication; Redis Cluster with geo-distributed replicas.
- Skills Git repo mirrored to both regions.
- RPO < 1 hour, RTO < 15 minutes for region failover.

---

*End of document.*
