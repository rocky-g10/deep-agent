"""Unit tests for LangGraphAdapter."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from deep_agent.models import (
    AgentChunkEvent,
    AgentCompleteEvent,
    ErrorEvent,
    TenantContext,
    ToolCallEvent,
    ToolResultEvent,
)
from deep_agent.runtime.langgraph_adapter import USING_DEEPAGENTS, LangGraphAdapter


async def _iterate(
    items: list[tuple[Any, dict[str, Any]]],
) -> AsyncIterator[tuple[Any, dict[str, Any]]]:
    for item in items:
        yield item


def test_create_agent_returns_agent() -> None:
    """create_agent should return backend-compiled agent object."""
    adapter = LangGraphAdapter()
    fake_agent = object()

    with (
        patch("deep_agent.runtime.langgraph_adapter.ChatOpenAI") as chat_cls,
        patch("deep_agent.runtime.langgraph_adapter.create_react_agent", return_value=fake_agent),
        patch("deep_agent.runtime.langgraph_adapter.USING_DEEPAGENTS", False),
    ):
        chat_cls.return_value = MagicMock()
        created = adapter.create_agent("gpt-5", tools=[], system_prompt="system")

    assert created is fake_agent


def test_using_deepagents_flag_logged() -> None:
    """USING_DEEPAGENTS should always be defined as bool."""
    assert isinstance(USING_DEEPAGENTS, bool)


def test_create_agent_forwards_max_tokens() -> None:
    """max_tokens should be passed through to ChatOpenAI constructor."""
    adapter = LangGraphAdapter()

    with (
        patch("deep_agent.runtime.langgraph_adapter.ChatOpenAI") as chat_cls,
        patch("deep_agent.runtime.langgraph_adapter.create_react_agent", return_value=object()),
        patch("deep_agent.runtime.langgraph_adapter.USING_DEEPAGENTS", False),
    ):
        chat_cls.return_value = MagicMock()
        _ = adapter.create_agent(
            "gpt-5",
            tools=[],
            system_prompt="sys",
            temperature=0.2,
            max_tokens=222,
        )

    kwargs = chat_cls.call_args.kwargs
    assert kwargs["max_tokens"] == 222


@pytest.mark.asyncio
async def test_invoke_returns_agent_response(tenant_equities: TenantContext) -> None:
    """invoke should map final AI message to AgentResponse fields."""
    adapter = LangGraphAdapter()
    fake_msg = AIMessage(
        content="answer",
        tool_calls=[{"id": "call-1", "name": "t", "args": {}}],
        usage_metadata={"input_tokens": 23, "output_tokens": 100, "total_tokens": 123},
    )
    fake_agent = MagicMock()
    fake_agent.ainvoke = AsyncMock(return_value={"messages": [fake_msg]})

    response = await adapter.invoke(fake_agent, "hello", tenant_equities)

    assert response.content == "answer"
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0]["id"] == "call-1"
    assert response.tool_calls[0]["name"] == "t"
    assert response.tool_calls[0]["args"] == {}
    assert response.tokens_used == 123


@pytest.mark.asyncio
async def test_stream_yields_chunk_events(tenant_equities: TenantContext) -> None:
    """AI message chunks should emit AgentChunkEvent tokens."""
    adapter = LangGraphAdapter()
    chunk = AIMessageChunk(content="Hello")
    fake_agent = MagicMock()
    fake_agent.astream = lambda *_args, **_kwargs: _iterate([(chunk, {})])

    events = [event async for event in adapter.stream(fake_agent, "msg", tenant_equities)]

    assert isinstance(events[0], AgentChunkEvent)
    assert events[0].content == "Hello"


@pytest.mark.asyncio
async def test_stream_yields_tool_events(tenant_equities: TenantContext) -> None:
    """Tool call chunks and ToolMessage should emit tool call/result events."""
    adapter = LangGraphAdapter()
    tool_chunk = AIMessageChunk(content="")
    tool_chunk.tool_call_chunks = [
        {"index": 0, "id": "call_1", "name": "execute_code", "args": '{"code": "print(1)"}'}
    ]
    tool_message = ToolMessage(content="1", name="execute_code", tool_call_id="call-1")

    fake_agent = MagicMock()
    fake_agent.astream = lambda *_args, **_kwargs: _iterate([(tool_chunk, {}), (tool_message, {})])

    events = [event async for event in adapter.stream(fake_agent, "msg", tenant_equities)]

    assert any(isinstance(event, ToolCallEvent) for event in events)
    assert any(isinstance(event, ToolResultEvent) for event in events)


@pytest.mark.asyncio
async def test_stream_ends_with_complete_event(tenant_equities: TenantContext) -> None:
    """Stream should terminate with AgentCompleteEvent."""
    adapter = LangGraphAdapter()
    chunk = AIMessageChunk(content="Summary")
    fake_agent = MagicMock()
    fake_agent.astream = lambda *_args, **_kwargs: _iterate([(chunk, {})])

    events = [event async for event in adapter.stream(fake_agent, "msg", tenant_equities)]

    assert isinstance(events[-1], AgentCompleteEvent)


@pytest.mark.asyncio
async def test_stream_error_yields_error_event(tenant_equities: TenantContext) -> None:
    """Streaming exceptions should be surfaced as ErrorEvent."""
    adapter = LangGraphAdapter()

    async def failing_stream(
        *_args: Any,
        **_kwargs: Any,
    ) -> AsyncIterator[tuple[Any, dict[str, Any]]]:
        raise RuntimeError("boom")
        if False:  # pragma: no cover
            yield AIMessageChunk(content=""), {}

    fake_agent = MagicMock()
    fake_agent.astream = failing_stream

    events = [event async for event in adapter.stream(fake_agent, "msg", tenant_equities)]

    assert isinstance(events[-1], ErrorEvent)
    assert events[-1].code == "RUNTIME_ERROR"


@pytest.mark.asyncio
async def test_invoke_error_returns_error_response(tenant_equities: TenantContext) -> None:
    """invoke failures should return error response payload, not raise."""
    adapter = LangGraphAdapter()
    fake_agent = MagicMock()
    fake_agent.ainvoke = AsyncMock(side_effect=RuntimeError("invoke failed"))

    response = await adapter.invoke(fake_agent, "hello", tenant_equities)

    assert response.tool_calls == []
    assert response.tokens_used == 0
    assert "invoke failed" in response.content


def test_fallback_to_create_react_agent() -> None:
    """If deepagents creation fails, adapter should fallback to create_react_agent."""
    adapter = LangGraphAdapter()
    fallback_agent = object()

    with (
        patch("deep_agent.runtime.langgraph_adapter.ChatOpenAI", return_value=MagicMock()),
        patch("deep_agent.runtime.langgraph_adapter.USING_DEEPAGENTS", True),
        patch(
            "deep_agent.runtime.langgraph_adapter.create_deep_agent",
            side_effect=RuntimeError("deepagents failed"),
        ),
        patch(
            "deep_agent.runtime.langgraph_adapter.create_react_agent",
            return_value=fallback_agent,
        ),
    ):
        created = adapter.create_agent("gpt-5", tools=[], system_prompt="system")

    assert created is fallback_agent
