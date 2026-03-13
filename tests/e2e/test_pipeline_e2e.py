"""End-to-end pipeline test with mock runtime + real sandbox SQLite execution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import WebSocketDisconnect

from deep_agent.api.app import create_app
from deep_agent.api.config_loader import build_tenant_context, load_agent_bindings
from deep_agent.api.ws_chat import _handle_client_message
from deep_agent.config import AppSettings
from deep_agent.models.events import AgentCompleteEvent, ToolCallEvent, ToolResultEvent

QUERY_CODE = """
import sqlite3, os
conn = sqlite3.connect(os.environ.get("DB_PATH", "/tmp/portfolio.db"))
rows = conn.execute("SELECT sym, qty, avg_cost FROM positions").fetchall()
conn.close()
for sym, qty, cost in rows:
    print(f"{sym}: qty={qty}, avg_cost={cost}")
"""


class FakeWebSocket:
    """Minimal websocket test double for ws_chat handlers."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.sent_texts: list[str] = []

    async def send_text(self, text: str) -> None:
        self.sent_texts.append(text)

    async def accept(self) -> None:
        return None

    async def receive_text(self) -> str:
        raise WebSocketDisconnect()


class DeterministicRuntime:
    """Runtime fallback that executes real tools without invoking an LLM."""

    def create_agent(
        self, model: str, tools: list[Any], system_prompt: str, **kwargs: Any,
    ) -> dict[str, Any]:
        _ = model, system_prompt, kwargs
        return {"tools": tools}

    async def stream(
        self,
        agent: dict[str, Any],
        message: str,
        context: Any,
        history: list[Any] | None = None,
    ):
        _ = message, context, history
        tool = next((t for t in agent["tools"] if getattr(t, "name", "") == "execute_code"), None)
        assert tool is not None, "execute_code tool missing"

        yield ToolCallEvent(tool="execute_code", input={"code": QUERY_CODE})
        raw_result = await tool.ainvoke({"code": QUERY_CODE})
        parsed = json.loads(raw_result)
        output = parsed.get("stdout") or parsed.get("stderr") or ""
        yield ToolResultEvent(
            tool="execute_code", output=output, files=parsed.get("output_files", {}),
        )
        yield AgentCompleteEvent(summary="Completed deterministic pipeline", tokens_used=0)


@pytest.fixture(autouse=True)
def seed_db() -> None:
    """Seed SQLite with example portfolio data."""
    from tests.support.seed_data import seed

    seed()


@pytest.fixture
def e2e_components(tmp_path: Path) -> tuple[Any, Any, str]:
    """Create full app components with real SkillEngine + Sandbox and deterministic runtime."""
    skills_root = tmp_path / "skills" / "test" / "query-db"
    skills_root.mkdir(parents=True)
    (skills_root / "SKILL.md").write_text(
        '---\nname: query-db\ndescription: Query database\nversion: "1.0"\n'
        'tags: [database, query, sql]\nallowed-tools: [execute_code]\n---\n'
        'Query the portfolio database and return results.\n',
        encoding="utf-8",
    )

    config_root = tmp_path / "config"
    tenant_dir = config_root / "tenants" / "test"
    tenant_dir.mkdir(parents=True)
    (tenant_dir / "resources.yaml").write_text(
        'resource_aliases:\n  portfolio-db:\n    DB_PATH: "/tmp/portfolio.db"\n'
        '    DB_ENGINE: "sqlite"\n',
        encoding="utf-8",
    )

    agents_dir = config_root / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "test-agent.yaml").write_text(
        'agent_id: "test-agent"\nbound_skill_ids:\n  - "test/query-db"\n',
        encoding="utf-8",
    )

    settings = AppSettings(
        OPENAI_API_KEY="sk-fake",  # type: ignore[arg-type]
        SKILLS_ROOT=tmp_path / "skills",
    )

    app = create_app(
        settings=settings,
        config_root=config_root,
        runtime=DeterministicRuntime(),
    )

    tenant = build_tenant_context("test", config_root=config_root)
    bindings = load_agent_bindings("test-agent", config_root=config_root)
    assert bindings is not None

    session = app.state.session_manager.create(tenant=tenant, bindings=bindings)
    websocket = FakeWebSocket(app)
    return app, websocket, session.session_id


@pytest.mark.timeout(30)
@pytest.mark.asyncio
async def test_full_pipeline_ws_to_sandbox(e2e_components: tuple[Any, Any, str]) -> None:
    """Full pipeline: WS handler → Orchestrator → SkillEngine → Sandbox → SQLite → events."""
    app, websocket, session_id = e2e_components

    await _handle_client_message(
        raw=json.dumps(
            {
                "type": "user_message",
                "content": "Show me portfolio positions from the database",
                "session_id": session_id,
            }
        ),
        websocket=websocket,
        orchestrator=app.state.orchestrator,
        session_manager=app.state.session_manager,
        session_id=session_id,
    )

    events = [json.loads(text) for text in websocket.sent_texts]
    event_types = [e["type"] for e in events]

    assert "skill_match" in event_types, f"Expected skill_match in {event_types}"

    tool_calls = [e for e in events if e["type"] == "tool_call"]
    assert len(tool_calls) >= 1
    assert tool_calls[0]["tool"] == "execute_code"

    tool_results = [e for e in events if e["type"] == "tool_result"]
    assert len(tool_results) >= 1
    result_output = tool_results[0]["output"]
    assert "AAPL" in result_output or "aapl" in result_output.lower(), (
        f"Expected AAPL in tool result, got: {result_output[:500]}"
    )

    assert events[-1]["type"] == "agent_complete"

    errors = [e for e in events if e["type"] == "error"]
    assert errors == [], f"Unexpected errors: {errors}"
