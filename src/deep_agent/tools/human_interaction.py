"""Built-in human_interaction tool definition."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel

from deep_agent.models.hitl import HumanInteractionRequest


class HumanInteractionTool(BaseTool):
    """Tool the LLM can call to request human input during a run."""

    name: str = "human_interaction"
    description: str = (
        "Request input from the human user. Use this tool when you need "
        "clarification, approval for a risky action, or structured input. "
        "Specify 'kind' as 'clarify', 'approve', or 'collect'."
    )
    args_schema: type[BaseModel] = HumanInteractionRequest

    def _run(self, **kwargs: Any) -> str:
        raise NotImplementedError("human_interaction is intercepted by the orchestrator")

    async def _arun(self, **kwargs: Any) -> str:
        raise NotImplementedError("human_interaction is intercepted by the orchestrator")


def create_human_interaction_tool() -> HumanInteractionTool:
    """Factory returning the human_interaction tool instance."""
    return HumanInteractionTool()
