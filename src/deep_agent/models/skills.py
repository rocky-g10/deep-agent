"""Skill-related data models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SkillInput(BaseModel):
    """Declared input parameter for a skill."""

    name: str
    type: str = "string"
    description: str = ""
    required: bool = True


class SkillQuality(BaseModel):
    """Quality constraints for a skill execution."""

    timeout: int = 60
    max_retries: int = Field(default=0, alias="max-retries")
    validation: str = ""
    hitl_timeout: int = Field(default=300, alias="hitl-timeout")
    hitl_fallback: Literal["abort", "default", "skip"] = Field(
        default="abort", alias="hitl-fallback"
    )

    model_config = ConfigDict(populate_by_name=True)


class SkillMCPServer(BaseModel):
    """MCP server declared in a skill's SKILL.md frontmatter."""

    name: str
    transport: Literal["stdio", "sse"]
    command: list[str] | None = Field(default=None)
    url: str | None = Field(default=None)
    env: dict[str, str] = Field(default_factory=dict)


@dataclass(frozen=True)
class MCPToolBinding:
    """Explicit binding of a tool name to a specific MCP server."""

    tool_name: str
    server_name: str


class SkillSummary(BaseModel):
    """Public summary of a skill used for discovery in prompts."""

    skill_id: str
    name: str
    description: str
    tags: list[str]
    score: float = 0.0


class SkillMetadata(SkillSummary):
    """Skill metadata used to authorize tool usage."""

    model_config = ConfigDict(populate_by_name=True)

    version: str
    allowed_tools: list[str]


class SkillContent(SkillMetadata):
    """Full skill definition including markdown instruction body."""

    body: str
    scripts_path: str = ""
    requires_approval: bool = False
    clarification_hints: dict[str, str] = Field(default_factory=dict)
    inputs: list[SkillInput] = Field(default_factory=list)
    quality: SkillQuality = Field(default_factory=SkillQuality)
    mcp_servers: list[SkillMCPServer] = Field(default_factory=list)
    mcp_tool_bindings: list[MCPToolBinding] = Field(default_factory=list)


@dataclass(frozen=True)
class AgentSkillBindings:
    """Maps an agent to the skills it may use."""

    agent_id: str
    bound_skill_ids: tuple[str, ...]
