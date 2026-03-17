"""Skill discovery, matching, and loading engine."""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from deep_agent.models import SkillContent, SkillSummary
from deep_agent.models.skills import AgentSkillBindings
from deep_agent.skills.parser import parse_skill_file

_TOKEN_PATTERN = re.compile(r"[a-z0-9_]+")
logger = logging.getLogger(__name__)


class Clock(Protocol):
    """Protocol for obtaining current time in seconds."""

    def __call__(self) -> float:
        """Return current monotonic or wall-clock seconds."""


class SkillNotFoundError(KeyError):
    """Raised when a skill is missing or not bound to the requesting agent."""


class SkillEngine:
    """Loads skills from disk and exposes discovery, matching, and retrieval APIs."""

    def __init__(
        self,
        skills_root: Path,
        cache_ttl: int = 300,
        parser: Callable[[Path], SkillContent] = parse_skill_file,
        clock: Clock = time.time,
    ) -> None:
        """Initialize the engine with a skills root and cache TTL in seconds."""
        self._skills_root = skills_root
        self._cache_ttl = cache_ttl
        self._parser = parser
        self._clock = clock
        self._lock = threading.Lock()
        self._last_scan_at = 0.0
        self._skills_index: dict[str, SkillContent] = {}

    def discover(self, bindings: AgentSkillBindings) -> list[SkillSummary]:
        """Return skills bound to the agent."""
        bound = self._bound_skills(bindings)
        return [
            SkillSummary(
                skill_id=skill.skill_id,
                name=skill.name,
                description=skill.description,
                tags=skill.tags,
            )
            for skill in bound
        ]

    def match(
        self,
        query: str,
        bindings: AgentSkillBindings,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> list[SkillSummary]:
        """Return top matching skills ranked by tag overlap with query tokens."""
        bound = self._bound_skills(bindings)
        query_tokens = _tokenize(query)
        scored: list[tuple[float, SkillContent]] = [
            (_score_skill(skill=skill, query_tokens=query_tokens), skill) for skill in bound
        ]
        scored.sort(key=lambda item: (-item[0], item[1].skill_id))
        top = scored[:top_k] if top_k > 0 else []
        if min_score > 0.0:
            top = [(score, skill) for score, skill in top if score >= min_score]

        result = [
            SkillSummary(
                skill_id=skill.skill_id,
                name=skill.name,
                description=skill.description,
                tags=skill.tags,
                score=score,
            )
            for score, skill in top
        ]
        logger.debug("Matched %d skills for query (top_k=%d)", len(result), top_k)
        return result

    def load(self, skill_id: str, bindings: AgentSkillBindings) -> SkillContent:
        """Return full skill content for a bound skill ID."""
        self._ensure_cache()
        with self._lock:
            skill = self._skills_index.get(skill_id)

        if skill is None or not _is_bound_to_agent(skill_id=skill_id, bindings=bindings):
            logger.debug("Skill '%s' not bound to agent '%s'", skill_id, bindings.agent_id)
            raise SkillNotFoundError(
                f"Skill '{skill_id}' not found or not bound to agent '{bindings.agent_id}'"
            )
        return skill

    def _bound_skills(self, bindings: AgentSkillBindings) -> list[SkillContent]:
        self._ensure_cache()
        with self._lock:
            skills = [
                skill
                for skill in self._skills_index.values()
                if _is_bound_to_agent(skill_id=skill.skill_id, bindings=bindings)
            ]
        return sorted(skills, key=lambda skill: skill.skill_id)

    def _ensure_cache(self) -> None:
        if not self._needs_refresh():
            return

        # Build outside lock so concurrent reads are not blocked by filesystem I/O.
        new_index = self._scan_filesystem()

        with self._lock:
            now = self._clock()
            should_refresh = not self._skills_index or (now - self._last_scan_at) >= self._cache_ttl
            if should_refresh:
                self._skills_index = new_index
                self._last_scan_at = now
                logger.debug("Refreshing skills cache (%d skills)", len(new_index))

    def _needs_refresh(self) -> bool:
        now = self._clock()
        with self._lock:
            return not self._skills_index or (now - self._last_scan_at) >= self._cache_ttl

    def _scan_filesystem(self) -> dict[str, SkillContent]:
        index: dict[str, SkillContent] = {}
        for skill_file in sorted(self._skills_root.rglob("SKILL.md")):
            try:
                skill = self._parser(skill_file)
                index[skill.skill_id] = skill
            except Exception as exc:
                logger.warning("Skipping malformed skill file %s: %s", skill_file, exc)
        return index


def _is_bound_to_agent(skill_id: str, bindings: AgentSkillBindings) -> bool:
    return skill_id in bindings.bound_skill_ids


def _tokenize(query: str) -> set[str]:
    return set(_TOKEN_PATTERN.findall(query.lower()))


def _score_skill(skill: SkillContent, query_tokens: set[str]) -> float:
    if not skill.tags:
        return 0.0
    matched_tags = sum(1 for tag in skill.tags if _tokenize(tag).intersection(query_tokens))
    return matched_tags / len(skill.tags)
