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
