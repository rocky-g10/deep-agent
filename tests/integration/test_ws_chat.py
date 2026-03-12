"""Integration tests for WebSocket chat endpoint (in-process, no real sockets)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import WebSocketDisconnect

from deep_agent.api.app import create_app
from deep_agent.api.ws_chat import _handle_client_message, ws_chat
from deep_agent.config import AppSettings
from deep_agent.models import TenantContext
from deep_agent.models.skills import AgentSkillBindings


class FakeWebSocket:
    """Minimal websocket test double for ws_chat handlers."""

    def __init__(self, app: Any, incoming: list[Any] | None = None) -> None:
        self.app = app
        self._incoming = list(incoming or [])
        self.sent_texts: list[str] = []
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self) -> str:
        if not self._incoming:
            raise WebSocketDisconnect()
        next_item = self._incoming.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return str(next_item)

    async def send_text(self, text: str) -> None:
        self.sent_texts.append(text)


def _test_settings(tmp_path: Path) -> AppSettings:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    return AppSettings(
        OPENAI_API_KEY="sk-fake",  # type: ignore[arg-type]
        SKILLS_ROOT=skills_dir,
    )


def _write_test_skill(skills_root: Path) -> None:
    skill_dir = skills_root / "test" / "hello"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        '---\nname: hello\ndescription: Test skill\nversion: "1.0"\n'
        "tags: [test]\nallowed-tools: [execute_code]\n---\nSay hello.\n",
        encoding="utf-8",
    )


def _fake_runtime() -> MagicMock:
    runtime = MagicMock()
    runtime.create_agent.return_value = MagicMock()

    async def fake_stream(*args: Any, **kwargs: Any):
        _ = args, kwargs
        from deep_agent.models.events import AgentChunkEvent, AgentCompleteEvent

        yield AgentChunkEvent(content="Hello!")
        yield AgentCompleteEvent(summary="Hello!", tokens_used=5)

    runtime.stream = fake_stream
    return runtime


def _build_app(tmp_path: Path) -> Any:
    settings = _test_settings(tmp_path)
    _write_test_skill(settings.skills_root)
    return create_app(
        settings=settings,
        config_root=tmp_path / "config",
        runtime=_fake_runtime(),
    )


@pytest.mark.asyncio
async def test_health_route_registered(tmp_path: Path) -> None:
    app = _build_app(tmp_path)
    paths = {route.path for route in app.routes}
    assert "/health" in paths


@pytest.mark.asyncio
async def test_ws_connect_receives_session_started(tmp_path: Path) -> None:
    app = _build_app(tmp_path)
    websocket = FakeWebSocket(app=app, incoming=[WebSocketDisconnect()])

    await ws_chat(websocket)

    assert websocket.accepted is True
    assert websocket.sent_texts
    started = json.loads(websocket.sent_texts[0])
    assert started["type"] == "session_started"
    assert "session_id" in started


@pytest.mark.asyncio
async def test_ws_user_message_streams_events(tmp_path: Path) -> None:
    app = _build_app(tmp_path)
    incoming = [
        json.dumps({"type": "user_message", "content": "hello", "session_id": ""}),
        WebSocketDisconnect(),
    ]
    websocket = FakeWebSocket(app=app, incoming=incoming)

    await ws_chat(websocket)

    events = [json.loads(t) for t in websocket.sent_texts]
    types = [e["type"] for e in events]
    assert "session_started" in types
    assert "agent_chunk" in types
    assert "agent_complete" in types


@pytest.mark.asyncio
async def test_ws_invalid_json_returns_error(tmp_path: Path) -> None:
    app = _build_app(tmp_path)
    sm = app.state.session_manager
    session = sm.create(
        tenant=TenantContext.default(),
        bindings=AgentSkillBindings(agent_id="default", bound_skill_ids=("test/hello",)),
    )
    websocket = FakeWebSocket(app=app)

    await _handle_client_message(
        raw="not valid json {{{",
        websocket=websocket,
        orchestrator=app.state.orchestrator,
        session_manager=sm,
        session_id=session.session_id,
    )

    data = json.loads(websocket.sent_texts[-1])
    assert data["type"] == "error"
    assert data["code"] == "INVALID_JSON"


@pytest.mark.asyncio
async def test_ws_unknown_message_type_returns_error(tmp_path: Path) -> None:
    app = _build_app(tmp_path)
    sm = app.state.session_manager
    session = sm.create(
        tenant=TenantContext.default(),
        bindings=AgentSkillBindings(agent_id="default", bound_skill_ids=("test/hello",)),
    )
    websocket = FakeWebSocket(app=app)

    await _handle_client_message(
        raw=json.dumps({"type": "unknown_type"}),
        websocket=websocket,
        orchestrator=app.state.orchestrator,
        session_manager=sm,
        session_id=session.session_id,
    )

    data = json.loads(websocket.sent_texts[-1])
    assert data["type"] == "error"
    assert data["code"] == "UNKNOWN_MESSAGE_TYPE"


@pytest.mark.asyncio
async def test_ws_tenant_and_agent_resolution(tmp_path: Path) -> None:
    app = _build_app(tmp_path)

    config_root = tmp_path / "config"
    agents_dir = config_root / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "my-agent.yaml").write_text(
        'agent_id: "my-agent"\nbound_skill_ids:\n  - "test/hello"\n',
        encoding="utf-8",
    )

    app.state.config_root = config_root
    websocket = FakeWebSocket(app=app, incoming=[WebSocketDisconnect()])

    await ws_chat(websocket, tenant_id="risk", agent_id="my-agent")

    started = json.loads(websocket.sent_texts[0])
    assert started["type"] == "session_started"


@pytest.mark.asyncio
async def test_ws_multi_turn_session(tmp_path: Path) -> None:
    app = _build_app(tmp_path)
    incoming = [
        json.dumps({"type": "user_message", "content": "first", "session_id": ""}),
        json.dumps({"type": "user_message", "content": "second", "session_id": ""}),
        json.dumps({"type": "user_message", "content": "third", "session_id": ""}),
        WebSocketDisconnect(),
    ]
    websocket = FakeWebSocket(app=app, incoming=incoming)

    await ws_chat(websocket)

    events = [json.loads(t) for t in websocket.sent_texts]
    complete_count = sum(1 for e in events if e["type"] == "agent_complete")
    assert complete_count == 3
