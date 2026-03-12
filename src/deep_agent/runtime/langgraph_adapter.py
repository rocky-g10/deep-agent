"""LangGraph runtime adapter with deepagents-first fallback behavior."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from deep_agent.models import (
    AgentChunkEvent,
    AgentCompleteEvent,
    AgentEvent,
    ErrorEvent,
    TenantContext,
    ToolCallEvent,
    ToolResultEvent,
)
from deep_agent.runtime.protocol import Agent, AgentResponse, RuntimeAdapter

logger = logging.getLogger(__name__)

try:
    from deepagents import create_deep_agent

    USING_DEEPAGENTS: bool = True
except ImportError:  # pragma: no cover - depends on environment.
    USING_DEEPAGENTS = False


class LangGraphAdapter(RuntimeAdapter):
    """Runtime adapter backed by deepagents with langgraph fallback."""

    def create_agent(
        self,
        model: str,
        tools: list[Any],
        system_prompt: str,
        **kwargs: Any,
    ) -> Agent:
        """Build a compiled agent graph for execution."""
        temperature = float(kwargs.get("temperature", 0.0))
        max_tokens = kwargs.get("max_tokens")
        llm_kwargs: dict[str, Any] = {"model": model, "temperature": temperature}
        if max_tokens is not None:
            llm_kwargs["max_tokens"] = int(max_tokens)
        llm = ChatOpenAI(**llm_kwargs)

        if USING_DEEPAGENTS:
            try:
                logger.info("Creating agent with deepagents backend")
                return create_deep_agent(model=llm, tools=tools, system_prompt=system_prompt)
            except Exception as exc:  # pragma: no cover - defensive fallback.
                logger.warning("deepagents backend failed, falling back to langgraph: %s", exc)

        logger.info("Creating agent with langgraph prebuilt backend")
        return create_react_agent(llm, tools, prompt=system_prompt)

    async def invoke(
        self,
        agent: Agent,
        message: str,
        context: TenantContext,
    ) -> AgentResponse:
        """Run the agent and return a normalized response."""
        _ = context
        payload = {"messages": [HumanMessage(content=message)]}
        try:
            result = await agent.ainvoke(payload)
        except Exception as exc:
            logger.exception("Agent invocation failed")
            return AgentResponse(content=f"Error: {exc}", tool_calls=[], tokens_used=0)

        messages = _extract_messages(result)
        final_message = messages[-1] if messages else AIMessage(content="")

        usage_metadata = getattr(final_message, "usage_metadata", None)
        tokens_used = int(usage_metadata.get("total_tokens", 0)) if usage_metadata else 0
        tool_calls = [dict(call) for call in (getattr(final_message, "tool_calls", None) or [])]

        return AgentResponse(
            content=_content_to_text(getattr(final_message, "content", "")),
            tool_calls=tool_calls,
            tokens_used=tokens_used,
        )

    async def stream(
        self,
        agent: Agent,
        message: str,
        context: TenantContext,
    ) -> AsyncIterator[AgentEvent]:
        """Stream execution as normalized AgentEvent objects."""
        _ = context
        payload = {"messages": [HumanMessage(content=message)]}
        summary_parts: list[str] = []
        tokens_used = 0
        pending_tool_calls: dict[int, dict[str, str]] = {}

        try:
            async for message_chunk, metadata in agent.astream(payload, stream_mode="messages"):
                tokens_used = max(tokens_used, _extract_total_tokens(metadata))

                if isinstance(message_chunk, AIMessageChunk):
                    content = _content_to_text(message_chunk.content)
                    if content and not getattr(message_chunk, "tool_call_chunks", None):
                        summary_parts.append(content)
                        yield AgentChunkEvent(content=content)

                    completed_tool_calls = getattr(message_chunk, "tool_calls", None) or []
                    for tool_call in completed_tool_calls:
                        tool_name = str(tool_call.get("name", "unknown"))
                        tool_args = _coerce_tool_args(tool_call.get("args", {}))
                        yield ToolCallEvent(tool=tool_name, input=tool_args)

                    for tool_chunk in getattr(message_chunk, "tool_call_chunks", None) or []:
                        chunk_dict = dict(tool_chunk)
                        index = int(chunk_dict.get("index", 0))
                        entry = pending_tool_calls.setdefault(index, {"name": "", "args": ""})
                        if chunk_dict.get("name"):
                            entry["name"] += str(chunk_dict["name"])
                        if chunk_dict.get("args"):
                            entry["args"] += str(chunk_dict["args"])

                elif isinstance(message_chunk, ToolMessage):
                    for _, pending in sorted(pending_tool_calls.items()):
                        if pending["name"]:
                            yield ToolCallEvent(
                                tool=pending["name"],
                                input=_parse_json_args(pending["args"]),
                            )
                    pending_tool_calls.clear()

                    tool_name = getattr(message_chunk, "name", "unknown") or "unknown"
                    yield ToolResultEvent(
                        tool=str(tool_name),
                        output=_content_to_text(message_chunk.content),
                        files={},
                    )

            for _, pending in sorted(pending_tool_calls.items()):
                if pending["name"]:
                    yield ToolCallEvent(
                        tool=pending["name"],
                        input=_parse_json_args(pending["args"]),
                    )

            yield AgentCompleteEvent(summary="".join(summary_parts), tokens_used=tokens_used)
        except Exception as exc:
            yield ErrorEvent(code="RUNTIME_ERROR", message=str(exc))


def _extract_messages(result: Any) -> list[Any]:
    if isinstance(result, dict):
        messages = result.get("messages")
        if isinstance(messages, list):
            return messages
    return []


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return str(content) if content is not None else ""


def _coerce_tool_args(args: Any) -> dict[str, Any]:
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        return _parse_json_args(args)
    return {}


def _parse_json_args(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _extract_total_tokens(metadata: Any) -> int:
    if not isinstance(metadata, dict):
        return 0
    for key in ("usage_metadata", "token_usage"):
        usage = metadata.get(key)
        if isinstance(usage, dict):
            total = usage.get("total_tokens")
            if isinstance(total, int):
                return total
    return 0
