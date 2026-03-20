"""Unit tests for the human_interaction tool."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from deep_agent.models.hitl import HumanInteractionRequest
from deep_agent.tools import HumanInteractionTool, create_human_interaction_tool


def test_human_interaction_tool_name_and_schema() -> None:
    tool = create_human_interaction_tool()

    assert isinstance(tool, HumanInteractionTool)
    assert tool.name == "human_interaction"
    assert tool.args_schema is HumanInteractionRequest


def test_human_interaction_tool_appears_in_tools_list_with_schema() -> None:
    tool = create_human_interaction_tool()
    tools = [tool]

    assert any(t.name == "human_interaction" for t in tools)
    schema = tool.get_input_schema()
    assert issubclass(schema, BaseModel)
    assert "kind" in schema.model_fields


def test_human_interaction_tool_run_raises_not_implemented() -> None:
    tool = create_human_interaction_tool()

    with pytest.raises(NotImplementedError, match="intercepted by the orchestrator"):
        tool._run(kind="clarify", question="Which?")


@pytest.mark.asyncio
async def test_human_interaction_tool_arun_raises_not_implemented() -> None:
    tool = create_human_interaction_tool()

    with pytest.raises(NotImplementedError, match="intercepted by the orchestrator"):
        await tool._arun(kind="clarify", question="Which?")
