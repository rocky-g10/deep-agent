"""ScriptedRuntime — mock RuntimeAdapter that replays predetermined code blocks.

Each call to ``stream()`` executes the next script in the list via the real
``execute_code`` tool, exercising the full sandbox pipeline without an LLM.

Pattern derived from ``tests/e2e/test_pipeline_e2e.DeterministicRuntime``.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from deep_agent.models import (
    AgentChunkEvent,
    AgentCompleteEvent,
    AgentEvent,
    TenantContext,
    ToolCallEvent,
    ToolResultEvent,
)
from deep_agent.runtime.protocol import AgentResponse


class ScriptedRuntime:
    """Runtime adapter that replays predetermined code blocks turn by turn.

    Implements the same ``RuntimeAdapter`` protocol as ``LangGraphAdapter``:
        - ``create_agent()`` — stores tools for later use
        - ``invoke()``       — runs to completion
        - ``stream()``       — yields AgentEvent objects

    On each ``stream()`` call, selects the next script from the list,
    executes it via the real ``execute_code`` tool (sandbox subprocess),
    and yields standard events.
    """

    def __init__(self, scripts: list[str]) -> None:
        self._scripts = scripts
        self._turn = 0

    def create_agent(
        self,
        model: str,
        tools: list[Any],
        system_prompt: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Store tools for use during streaming."""
        return {"tools": tools}

    async def invoke(
        self,
        agent: dict[str, Any],
        message: str,
        context: TenantContext,
        history: list[Any] | None = None,
    ) -> AgentResponse:
        """Run to completion (collects stream events)."""
        summary = ""
        async for event in self.stream(agent, message, context, history):
            if hasattr(event, "summary"):
                summary = event.summary
        return AgentResponse(content=summary)

    async def stream(
        self,
        agent: dict[str, Any],
        message: str,
        context: TenantContext,
        history: list[Any] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Yield events for one turn, executing the next scripted code block."""
        _ = message, context, history
        code = self._scripts[self._turn % len(self._scripts)]

        tool = next(
            (t for t in agent["tools"] if getattr(t, "name", "") == "execute_code"),
            None,
        )
        assert tool is not None, "execute_code tool missing from agent tools"

        yield ToolCallEvent(tool="execute_code", input={"code": code})

        raw_result = await tool.ainvoke({"code": code})
        parsed = json.loads(raw_result)
        output = parsed.get("stdout") or parsed.get("stderr") or ""
        yield ToolResultEvent(
            tool="execute_code",
            output=output,
            files=parsed.get("output_files", {}),
        )

        summary = f"Turn {self._turn + 1} complete."
        yield AgentChunkEvent(content=summary)
        yield AgentCompleteEvent(summary=summary, tokens_used=0)

        self._turn += 1
