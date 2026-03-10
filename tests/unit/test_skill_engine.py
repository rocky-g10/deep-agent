"""Unit tests for skill discovery, matching, and loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from deep_agent.models import TenantContext
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
    tenant: str,
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
                f"tenant: {tenant}",
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
def tenant_equities() -> TenantContext:
    """Return a tenant context for equities tests."""
    return TenantContext(
        tenant_id="equities",
        user_id="test-user",
        skills_dirs=["skills/common", "skills/equities"],
        db_aliases=["ch-equities"],
    )


@pytest.fixture
def tenant_risk() -> TenantContext:
    """Return a tenant context for risk tests."""
    return TenantContext(
        tenant_id="risk",
        user_id="test-user",
        skills_dirs=["skills/common", "skills/risk"],
        db_aliases=["ch-risk"],
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
        tenant="common",
    )
    _write_skill(
        root=root,
        tenant_dir="equities",
        skill_dir="zscore-monitor",
        name="zscore-monitor",
        description="Monitor z-scores for equities",
        tags=["equities", "zscore", "volume", "monitor"],
        tenant="equities",
    )
    _write_skill(
        root=root,
        tenant_dir="risk",
        skill_dir="var-report",
        name="var-report",
        description="Run risk VaR report",
        tags=["risk", "var", "report"],
        tenant="risk",
    )
    return root


def test_discover_returns_common_and_tenant_skills(
    temp_skills_root: Path, tenant_equities: TenantContext
) -> None:
    """Discover should include common and tenant-local skills only."""
    engine = SkillEngine(skills_root=temp_skills_root)

    discovered = engine.discover(tenant_equities)
    ids = [skill.skill_id for skill in discovered]

    assert "common/db-query" in ids
    assert "equities/zscore-monitor" in ids
    assert len(discovered) == 2


def test_discover_excludes_other_tenants(
    temp_skills_root: Path, tenant_equities: TenantContext
) -> None:
    """Discover should not leak skills from other tenants."""
    engine = SkillEngine(skills_root=temp_skills_root)

    discovered = engine.discover(tenant_equities)
    ids = [skill.skill_id for skill in discovered]

    assert "risk/var-report" not in ids


def test_match_zscore_query_ranks_zscore_first(
    temp_skills_root: Path, tenant_equities: TenantContext
) -> None:
    """Tag-overlap scoring should prioritize zscore skill for zscore query."""
    engine = SkillEngine(skills_root=temp_skills_root)

    matched = engine.match("z-scores for AAPL volume", tenant_equities, top_k=2)

    assert matched[0].skill_id == "equities/zscore-monitor"


def test_match_query_database_ranks_db_query_first(
    temp_skills_root: Path, tenant_equities: TenantContext
) -> None:
    """Tag-overlap scoring should prioritize db-query for database query text."""
    engine = SkillEngine(skills_root=temp_skills_root)

    matched = engine.match("query database", tenant_equities, top_k=2)

    assert matched[0].skill_id == "common/db-query"


def test_load_returns_full_skill_content(
    temp_skills_root: Path, tenant_equities: TenantContext
) -> None:
    """Load should return full parsed content including markdown body."""
    engine = SkillEngine(skills_root=temp_skills_root)

    skill = engine.load("equities/zscore-monitor", tenant_equities)

    assert skill.skill_id == "equities/zscore-monitor"
    assert "## Instructions" in skill.body


def test_load_missing_skill_raises_not_found(
    temp_skills_root: Path, tenant_equities: TenantContext
) -> None:
    """Load should raise when skill_id does not exist."""
    engine = SkillEngine(skills_root=temp_skills_root)

    with pytest.raises(SkillNotFoundError):
        engine.load("equities/not-real", tenant_equities)


def test_load_wrong_tenant_raises_not_found(
    temp_skills_root: Path, tenant_equities: TenantContext
) -> None:
    """Load should raise when tenant attempts to access another tenant's skill."""
    engine = SkillEngine(skills_root=temp_skills_root)

    with pytest.raises(SkillNotFoundError):
        engine.load("risk/var-report", tenant_equities)


def test_cache_invalidation_picks_up_filesystem_changes(
    tenant_equities: TenantContext, tmp_path: Path
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
        tenant="common",
    )
    _write_skill(
        root=skills_root,
        tenant_dir="equities",
        skill_dir="zscore-monitor",
        name="zscore-monitor",
        description="Monitor z-scores for equities",
        tags=["equities", "zscore", "volume", "monitor"],
        tenant="equities",
    )

    fake_clock = FakeClock(now=10.0)
    engine = SkillEngine(skills_root=skills_root, cache_ttl=5, clock=fake_clock)

    baseline = {skill.skill_id for skill in engine.discover(tenant_equities)}
    assert baseline == {"common/db-query", "equities/zscore-monitor"}

    _write_skill(
        root=skills_root,
        tenant_dir="equities",
        skill_dir="momentum-watch",
        name="momentum-watch",
        description="Monitor momentum",
        tags=["equities", "momentum"],
        tenant="equities",
    )

    pre_ttl = {skill.skill_id for skill in engine.discover(tenant_equities)}
    assert pre_ttl == baseline

    fake_clock.advance(6.0)
    post_ttl = {skill.skill_id for skill in engine.discover(tenant_equities)}

    assert "equities/momentum-watch" in post_ttl
