"""Runtime protocol abstractions."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from deep_agent.models import AgentEvent, TenantContext

Agent = Any


class AgentResponse(BaseModel):
    """Synchronous response from an agent invocation."""

    content: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    tokens_used: int = 0


@runtime_checkable
class RuntimeAdapter(Protocol):
    """Protocol for runtime backends that execute agent loops."""

    def create_agent(
        self,
        model: str,
        tools: list[Any],
        system_prompt: str,
        **kwargs: Any,
    ) -> Agent:
        """Build a compiled agent with the provided model, tools, and prompt."""
        ...

    async def invoke(
        self,
        agent: Agent,
        message: str,
        context: TenantContext,
    ) -> AgentResponse:
        """Run the agent to completion and return structured output."""
        ...

    def stream(
        self,
        agent: Agent,
        message: str,
        context: TenantContext,
    ) -> AsyncIterator[AgentEvent]:
        """Stream runtime events for a single request."""
        ...
