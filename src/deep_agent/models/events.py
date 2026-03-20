"""Streaming event models for agent WebSocket protocol."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Discriminator, Field

from deep_agent.models.hitl import HumanInteractionRequest, InteractionResponse


class AgentChunkEvent(BaseModel):
    """Streamed text chunk from the running agent."""

    type: Literal["agent_chunk"] = "agent_chunk"
    content: str


class ToolCallEvent(BaseModel):
    """Event describing a tool invocation request."""

    type: Literal["tool_call"] = "tool_call"
    tool: str
    input: dict[str, object] = Field(default_factory=dict)


class ToolResultEvent(BaseModel):
    """Event carrying the result of a tool invocation."""

    type: Literal["tool_result"] = "tool_result"
    tool: str
    output: str
    files: dict[str, str] = Field(default_factory=dict)


class SkillMatchEvent(BaseModel):
    """Informational event indicating selected skill and confidence."""

    type: Literal["skill_match"] = "skill_match"
    skill_id: str
    confidence: float


class AgentCompleteEvent(BaseModel):
    """Terminal success event for an agent response."""

    type: Literal["agent_complete"] = "agent_complete"
    summary: str
    tokens_used: int


class ErrorEvent(BaseModel):
    """Terminal failure event for an agent response."""

    type: Literal["error"] = "error"
    code: str
    message: str


class InteractionRequiredEvent(BaseModel):
    """Event emitted when execution pauses and needs human input."""

    type: Literal["interaction_required"] = "interaction_required"
    run_id: str
    skill_id: str | None = None
    interaction: HumanInteractionRequest


class InteractionResponseEvent(BaseModel):
    """Event carrying a human response that resumes a paused run."""

    type: Literal["interaction_response"] = "interaction_response"
    run_id: str
    response: InteractionResponse


AgentEvent = Annotated[
    AgentChunkEvent
    | ToolCallEvent
    | ToolResultEvent
    | SkillMatchEvent
    | AgentCompleteEvent
    | ErrorEvent
    | InteractionRequiredEvent
    | InteractionResponseEvent,
    Discriminator("type"),
]
