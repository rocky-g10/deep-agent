"""Unit tests for skill file parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from deep_agent.skills import SkillParseError, parse_skill_file


def test_parse_reference_db_query_skill() -> None:
    """Parser should extract metadata and body from the reference common skill."""
    skill_path = Path("skills/common/db-query/SKILL.md")
    skill = parse_skill_file(skill_path)

    assert skill.skill_id == "common/db-query"
    assert skill.name == "db-query"
    assert skill.tenant == "common"
    assert skill.allowed_tools == ["query_database", "execute_code"]
    assert "## Instructions" in skill.body


def test_parse_reference_zscore_skill() -> None:
    """Parser should extract metadata and body from the reference equities skill."""
    skill_path = Path("skills/equities/zscore-monitor/SKILL.md")
    skill = parse_skill_file(skill_path)

    assert skill.skill_id == "equities/zscore-monitor"
    assert skill.name == "zscore-monitor"
    assert "z-scores" in skill.description
    assert "volume" in skill.tags


def test_missing_required_field_raises_skill_parse_error(tmp_path: Path) -> None:
    """Parser should reject frontmatter missing required keys."""
    skill_path = tmp_path / "skills" / "equities" / "missing" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        """---
name: missing
description: Missing required fields
version: "1.0.0"
tags: [equities]
tenant: equities
---
Body
""",
        encoding="utf-8",
    )

    with pytest.raises(SkillParseError):
        parse_skill_file(skill_path)


def test_malformed_frontmatter_raises_skill_parse_error(tmp_path: Path) -> None:
    """Parser should normalize YAML parse failures to SkillParseError."""
    skill_path = tmp_path / "skills" / "equities" / "malformed" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        """---
name: malformed
description: bad yaml
version: "1.0.0"
tags: [equities
tenant: equities
allowed-tools: [query_database]
---
Body
""",
        encoding="utf-8",
    )

    with pytest.raises(SkillParseError):
        parse_skill_file(skill_path)


def test_empty_body_is_valid(tmp_path: Path) -> None:
    """Parser should allow skills that contain only frontmatter."""
    skill_path = tmp_path / "skills" / "common" / "empty" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        """---
name: empty
description: no body
version: "1.0.0"
tags: [database]
tenant: common
allowed-tools: [query_database]
---
""",
        encoding="utf-8",
    )

    skill = parse_skill_file(skill_path)
    assert skill.body == ""


def test_extra_frontmatter_fields_are_ignored(tmp_path: Path) -> None:
    """Parser should ignore unknown frontmatter fields."""
    skill_path = tmp_path / "skills" / "common" / "extra" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        """---
name: extra
description: includes extra fields
version: "1.0.0"
tags: [database]
tenant: common
allowed-tools: [query_database]
custom_field: value
---
Body
""",
        encoding="utf-8",
    )

    skill = parse_skill_file(skill_path)
    dumped = skill.model_dump()

    assert dumped["name"] == "extra"
    assert "custom_field" not in dumped


def test_skill_id_derives_from_relative_path(tmp_path: Path) -> None:
    """Parser should derive skill_id from the path under the skills directory."""
    skill_path = tmp_path / "skills" / "risk" / "var-report" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        """---
name: var-report
description: risk report
version: "1.0.0"
tags: [risk]
tenant: risk
allowed-tools: [query_database]
---
Body
""",
        encoding="utf-8",
    )

    skill = parse_skill_file(skill_path)
    assert skill.skill_id == "risk/var-report"


def test_missing_frontmatter_delimiters_raise_skill_parse_error(tmp_path: Path) -> None:
    """Parser should fail when markdown has no YAML frontmatter delimiters."""
    skill_path = tmp_path / "skills" / "common" / "no-frontmatter" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        """# Plain Markdown

This file has no frontmatter delimiters.
""",
        encoding="utf-8",
    )

    with pytest.raises(SkillParseError):
        parse_skill_file(skill_path)
