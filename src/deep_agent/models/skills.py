"""Skill-related data models."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict


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


@dataclass(frozen=True)
class AgentSkillBindings:
    """Maps an agent to the skills it may use."""

    agent_id: str
    bound_skill_ids: tuple[str, ...]
