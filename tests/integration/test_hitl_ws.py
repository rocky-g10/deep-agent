"""Integration tests for HITL WebSocket + REST resume bridging."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from starlette.websockets import WebSocketDisconnect

from deep_agent.api.app import create_app
from deep_agent.api.runs import respond_to_run
from deep_agent.api.schemas import RunRespondRequest
from deep_agent.api.ws_chat import ws_chat
from deep_agent.config import AppSettings
from deep_agent.models.events import AgentChunkEvent, AgentCompleteEvent, ToolCallEvent
from deep_agent.models.hitl import InteractionResponse
from tests.integration.test_hitl_orchestrator import MockRuntime


class _FakeRequest:
    def __init__(self, app: Any) -> None:
        self.app = app


class _AsyncFakeWebSocket:
    """Async websocket test double that allows pushing inbound messages."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self._incoming: asyncio.Queue[Any] = asyncio.Queue()
        self.sent_texts: list[str] = []
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self) -> str:
        item = await self._incoming.get()
        if isinstance(item, Exception):
            raise item
        return str(item)

    async def send_text(self, text: str) -> None:
        self.sent_texts.append(text)

    async def push_text(self, text: str) -> None:
        await self._incoming.put(text)

    async def disconnect(self) -> None:
        await self._incoming.put(WebSocketDisconnect())


def _build_app(tmp_path: Path):
    settings = AppSettings(
        OPENAI_API_KEY="sk-fake",  # type: ignore[arg-type]
        SKILLS_ROOT=tmp_path / "skills",
    )
    settings.skills_root.mkdir(parents=True, exist_ok=True)
    runtime = MockRuntime(
        stream_sequences=[
            [
                ToolCallEvent(
                    tool="human_interaction",
                    input={"kind": "clarify", "question": "Which portfolio?"},
                    tool_call_id="tc-1",
                )
            ],
            [
                AgentChunkEvent(content="Resumed output"),
                AgentCompleteEvent(summary="Done", tokens_used=1),
            ],
        ]
    )
    return create_app(settings=settings, config_root=tmp_path / "config", runtime=runtime)


async def _wait_for_event(
    sent_texts: list[str], event_type: str, timeout_s: float = 2.0
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        for raw in sent_texts:
            data = json.loads(raw)
            if data.get("type") == event_type:
                return data
        await asyncio.sleep(0.01)
    raise AssertionError(f"Timed out waiting for event type '{event_type}'")


@pytest.mark.asyncio
async def test_hitl_ws_suspend_and_resume_flow(tmp_path: Path) -> None:
    app = _build_app(tmp_path)
    ws = _AsyncFakeWebSocket(app=app)

    task = asyncio.create_task(ws_chat(ws, tenant_id="default", agent_id=""))
    try:
        started = await _wait_for_event(ws.sent_texts, "session_started")
        session_id = started["session_id"]

        await ws.push_text(
            json.dumps(
                {
                    "type": "user_message",
                    "content": "Need clarification",
                    "session_id": session_id,
                }
            )
        )
        interaction = await _wait_for_event(ws.sent_texts, "interaction_required")
        run_id = interaction["run_id"]

        result = await respond_to_run(
            run_id=run_id,
            body=RunRespondRequest(
                response=InteractionResponse(kind="clarify", value="EQ-MACRO-1")
            ),
            request=_FakeRequest(app),  # type: ignore[arg-type]
        )
        assert result.status == "resumed"

        resumed_chunk = await _wait_for_event(ws.sent_texts, "agent_chunk")
        assert resumed_chunk["content"] == "Resumed output"
        resumed_complete = await _wait_for_event(ws.sent_texts, "agent_complete")
        assert resumed_complete["summary"] == "Done"
    finally:
        await ws.disconnect()
        await task


@pytest.mark.asyncio
async def test_hitl_respond_unknown_run_returns_404(tmp_path: Path) -> None:
    app = _build_app(tmp_path)
    with pytest.raises(HTTPException) as exc:
        await respond_to_run(
            run_id="unknown-id",
            body=RunRespondRequest(response=InteractionResponse(kind="clarify", value="EQ")),
            request=_FakeRequest(app),  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_hitl_respond_non_suspended_run_returns_409(tmp_path: Path) -> None:
    app = _build_app(tmp_path)
    run = app.state.orchestrator.run_state_manager.create_run(session_id="session-x")

    with pytest.raises(HTTPException) as exc:
        await respond_to_run(
            run_id=run.run_id,
            body=RunRespondRequest(response=InteractionResponse(kind="clarify", value="EQ")),
            request=_FakeRequest(app),  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 409
