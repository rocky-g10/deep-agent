"""Unit tests for skill discovery, matching, and loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from deep_agent.models.skills import AgentSkillBindings
from deep_agent.skills.engine import SkillEngine, SkillNotFoundError


class FakeClock:
    """Mutable clock used for deterministic cache TTL tests."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _write_skill(
    root: Path,
    tenant_dir: str,
    skill_dir: str,
    name: str,
    description: str,
    tags: list[str],
) -> None:
    skill_path = root / tenant_dir / skill_dir / "SKILL.md"
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    tags_yaml = "\n".join(f"  - {tag}" for tag in tags)
    skill_path.write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: {description}",
                'version: "1.0.0"',
                "tags:",
                tags_yaml,
                f"tenant: {tenant_dir}",
                "allowed-tools:",
                "  - query_database",
                "  - execute_code",
                "---",
                "",
                "## Instructions",
                "",
                f"Skill {name}",
                "",
            ]
        ),
        encoding="utf-8",
    )


@pytest.fixture
def temp_skills_root(tmp_path: Path) -> Path:
    """Create an isolated skills tree for engine tests."""
    root = tmp_path / "skills"
    _write_skill(
        root=root,
        tenant_dir="common",
        skill_dir="db-query",
        name="db-query",
        description="Query databases",
        tags=["database", "query", "sql", "data"],
    )
    _write_skill(
        root=root,
        tenant_dir="equities",
        skill_dir="zscore-monitor",
        name="zscore-monitor",
        description="Monitor z-scores for equities",
        tags=["equities", "zscore", "volume", "monitor"],
    )
    _write_skill(
        root=root,
        tenant_dir="risk",
        skill_dir="var-report",
        name="var-report",
        description="Run risk VaR report",
        tags=["risk", "var", "report"],
    )
    return root


def test_discover_returns_bound_skills(
    temp_skills_root: Path, skill_bindings: AgentSkillBindings
) -> None:
    """Discover should return only the skills bound to the agent."""
    engine = SkillEngine(skills_root=temp_skills_root)

    discovered = engine.discover(skill_bindings)
    ids = [skill.skill_id for skill in discovered]

    assert "common/db-query" in ids
    assert "equities/zscore-monitor" in ids
    assert len(discovered) == 2


def test_discover_excludes_unbound_skills(
    temp_skills_root: Path, skill_bindings: AgentSkillBindings
) -> None:
    """Discover should not include skills not in the agent's bound_skill_ids."""
    engine = SkillEngine(skills_root=temp_skills_root)

    discovered = engine.discover(skill_bindings)
    ids = [skill.skill_id for skill in discovered]

    assert "risk/var-report" not in ids


def test_match_zscore_query_ranks_zscore_first(
    temp_skills_root: Path, skill_bindings: AgentSkillBindings
) -> None:
    """Tag-overlap scoring should prioritize zscore skill for zscore query."""
    engine = SkillEngine(skills_root=temp_skills_root)

    matched = engine.match("z-scores for AAPL volume", skill_bindings, top_k=2)

    assert matched[0].skill_id == "equities/zscore-monitor"


def test_match_query_database_ranks_db_query_first(
    temp_skills_root: Path, skill_bindings: AgentSkillBindings
) -> None:
    """Tag-overlap scoring should prioritize db-query for database query text."""
    engine = SkillEngine(skills_root=temp_skills_root)

    matched = engine.match("query database", skill_bindings, top_k=2)

    assert matched[0].skill_id == "common/db-query"


def test_min_score_filters_low_scoring(
    temp_skills_root: Path, skill_bindings: AgentSkillBindings
) -> None:
    """min_score should drop low-scoring matches from the result set."""
    engine = SkillEngine(skills_root=temp_skills_root)

    matched = engine.match("equities zscore volume", skill_bindings, top_k=3, min_score=0.4)

    assert len(matched) == 1
    assert matched[0].skill_id == "equities/zscore-monitor"
    assert matched[0].score >= 0.4


def test_min_score_zero_returns_all(
    temp_skills_root: Path, skill_bindings: AgentSkillBindings
) -> None:
    """min_score=0 should preserve current behavior and return top_k results."""
    engine = SkillEngine(skills_root=temp_skills_root)

    matched = engine.match("query database", skill_bindings, top_k=2, min_score=0.0)

    assert len(matched) == 2
    assert matched[0].skill_id == "common/db-query"


def test_min_score_filters_all_when_none_match(
    temp_skills_root: Path, skill_bindings: AgentSkillBindings
) -> None:
    """When no match clears the threshold, an empty list should be returned."""
    engine = SkillEngine(skills_root=temp_skills_root)

    matched = engine.match("totally unrelated tokens", skill_bindings, top_k=2, min_score=0.01)

    assert matched == []


def test_load_returns_full_skill_content(
    temp_skills_root: Path, skill_bindings: AgentSkillBindings
) -> None:
    """Load should return full parsed content including markdown body."""
    engine = SkillEngine(skills_root=temp_skills_root)

    skill = engine.load("equities/zscore-monitor", skill_bindings)

    assert skill.skill_id == "equities/zscore-monitor"
    assert "## Instructions" in skill.body


def test_load_missing_skill_raises_not_found(
    temp_skills_root: Path, skill_bindings: AgentSkillBindings
) -> None:
    """Load should raise when skill_id does not exist."""
    engine = SkillEngine(skills_root=temp_skills_root)

    with pytest.raises(SkillNotFoundError):
        engine.load("equities/not-real", skill_bindings)


def test_load_unbound_skill_raises_not_found(
    temp_skills_root: Path, skill_bindings: AgentSkillBindings
) -> None:
    """Load should raise when skill is not bound to the agent."""
    engine = SkillEngine(skills_root=temp_skills_root)

    with pytest.raises(SkillNotFoundError):
        engine.load("risk/var-report", skill_bindings)


def test_cache_invalidation_picks_up_filesystem_changes(
    skill_bindings: AgentSkillBindings, tmp_path: Path
) -> None:
    """Engine should rescan after TTL and include newly added skills."""
    skills_root = tmp_path / "skills"
    _write_skill(
        root=skills_root,
        tenant_dir="common",
        skill_dir="db-query",
        name="db-query",
        description="Query databases",
        tags=["database", "query", "sql", "data"],
    )
    _write_skill(
        root=skills_root,
        tenant_dir="equities",
        skill_dir="zscore-monitor",
        name="zscore-monitor",
        description="Monitor z-scores for equities",
        tags=["equities", "zscore", "volume", "monitor"],
    )

    fake_clock = FakeClock(now=10.0)
    engine = SkillEngine(skills_root=skills_root, cache_ttl=5, clock=fake_clock)

    baseline = {skill.skill_id for skill in engine.discover(skill_bindings)}
    assert baseline == {"common/db-query", "equities/zscore-monitor"}

    _write_skill(
        root=skills_root,
        tenant_dir="equities",
        skill_dir="momentum-watch",
        name="momentum-watch",
        description="Monitor momentum",
        tags=["equities", "momentum"],
    )

    pre_ttl = {skill.skill_id for skill in engine.discover(skill_bindings)}
    assert pre_ttl == baseline

    fake_clock.advance(6.0)

    # Need bindings that include the new skill to see it after cache refresh
    expanded_bindings = AgentSkillBindings(
        agent_id="equities-agent",
        bound_skill_ids=(
            "common/db-query",
            "equities/zscore-monitor",
            "equities/momentum-watch",
        ),
    )
    post_ttl = {skill.skill_id for skill in engine.discover(expanded_bindings)}

    assert "equities/momentum-watch" in post_ttl


def test_discover_skips_malformed_skill_file(
    tmp_path: Path,
    skill_bindings: AgentSkillBindings,
) -> None:
    """Malformed skill files should be skipped without failing discovery."""
    skills_root = tmp_path / "skills"
    _write_skill(
        root=skills_root,
        tenant_dir="common",
        skill_dir="db-query",
        name="db-query",
        description="Query databases",
        tags=["database"],
    )
    bad_skill = skills_root / "equities" / "broken" / "SKILL.md"
    bad_skill.parent.mkdir(parents=True, exist_ok=True)
    bad_skill.write_text(
        """---
name: broken
description: malformed
version: "1.0.0"
tags: [equities
tenant: equities
allowed-tools: [query_database]
---
bad
""",
        encoding="utf-8",
    )

    engine = SkillEngine(skills_root=skills_root)
    discovered = engine.discover(skill_bindings)

    assert len(discovered) == 1
    assert discovered[0].skill_id == "common/db-query"
