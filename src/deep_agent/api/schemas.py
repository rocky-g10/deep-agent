"""WebSocket message schemas for client-server communication."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from deep_agent.models.hitl import InteractionResponse


class UserMessage(BaseModel):
    """Client → Server: user sends a chat message."""

    type: Literal["user_message"] = "user_message"
    content: str
    session_id: str = ""


class SessionStartedMessage(BaseModel):
    """Server → Client: sent immediately after WebSocket connection is accepted."""

    type: Literal["session_started"] = "session_started"
    session_id: str


class RunRespondRequest(BaseModel):
    """REST payload for submitting human response to a suspended run."""

    response: InteractionResponse


class RunRespondResult(BaseModel):
    """REST response for accepted run resume request."""

    run_id: str
    status: str
