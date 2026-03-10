"""Skill-related data models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SkillSummary(BaseModel):
    """Public summary of a skill used for discovery in prompts."""

    skill_id: str
    name: str
    description: str
    tags: list[str]


class SkillMetadata(SkillSummary):
    """Skill metadata used to authorize tool usage and tenant visibility."""

    model_config = ConfigDict(populate_by_name=True)

    version: str
    allowed_tools: list[str]
    tenant: str


class SkillContent(SkillMetadata):
    """Full skill definition including markdown instruction body."""

    body: str
