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
    assert skill.allowed_tools == ["execute_code"]
    assert "## Instructions" in skill.body


def test_parse_reference_zscore_skill() -> None:
    """Parser should extract metadata and body from the reference equities skill."""
    skill_path = Path("skills/equities/zscore-monitor/SKILL.md")
    skill = parse_skill_file(skill_path)

    assert skill.skill_id == "equities/zscore-monitor"
    assert skill.name == "zscore-monitor"
    assert "z-scores" in skill.description
    assert "volume" in skill.tags


def test_parse_skill_with_inputs_and_quality(tmp_path: Path) -> None:
    """Parser should extract inputs and quality from frontmatter."""
    skill_path = tmp_path / "skills" / "risk" / "var" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        """---
name: var-report
description: VaR report
version: "1.0.0"
tags: [risk]
allowed-tools: [execute_code]
inputs:
  - name: portfolio_id
    type: string
    description: Portfolio ID
    required: true
  - name: confidence
    type: number
    description: Confidence level
    required: false
quality:
  timeout: 90
  max-retries: 2
  validation: "Must include VaR number"
---
Body
""",
        encoding="utf-8",
    )

    skill = parse_skill_file(skill_path)

    assert len(skill.inputs) == 2
    assert skill.inputs[0].name == "portfolio_id"
    assert skill.inputs[0].type == "string"
    assert skill.inputs[0].required is True
    assert skill.inputs[1].name == "confidence"
    assert skill.inputs[1].required is False
    assert skill.quality.timeout == 90
    assert skill.quality.max_retries == 2
    assert skill.quality.validation == "Must include VaR number"


def test_quality_timeout_parsed(tmp_path: Path) -> None:
    """Parser should map quality.timeout from frontmatter."""
    skill_path = tmp_path / "skills" / "risk" / "quality-timeout" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        """---
name: quality-timeout
description: quality timeout parsing
version: "1.0.0"
tags: [risk]
allowed-tools: [execute_code]
quality:
  timeout: 90
---
Body
""",
        encoding="utf-8",
    )

    skill = parse_skill_file(skill_path)

    assert skill.quality.timeout == 90


def test_quality_defaults_when_omitted(tmp_path: Path) -> None:
    """Parser should use default quality values when quality is omitted."""
    skill_path = tmp_path / "skills" / "risk" / "quality-defaults" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        """---
name: quality-defaults
description: quality defaults
version: "1.0.0"
tags: [risk]
allowed-tools: [execute_code]
---
Body
""",
        encoding="utf-8",
    )

    skill = parse_skill_file(skill_path)

    assert skill.quality.timeout == 60


def test_inputs_parsed(tmp_path: Path) -> None:
    """Parser should populate SkillContent.inputs from frontmatter."""
    skill_path = tmp_path / "skills" / "risk" / "inputs-parsed" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        """---
name: inputs-parsed
description: inputs parsing
version: "1.0.0"
tags: [risk]
allowed-tools: [execute_code]
inputs:
  - name: portfolio_id
    type: string
    description: Portfolio identifier
    required: true
  - name: confidence
    type: number
    description: Confidence level
    required: false
---
Body
""",
        encoding="utf-8",
    )

    skill = parse_skill_file(skill_path)

    assert len(skill.inputs) == 2
    assert [item.name for item in skill.inputs] == ["portfolio_id", "confidence"]


def test_parse_skill_without_inputs_quality_uses_defaults(tmp_path: Path) -> None:
    """Skills without inputs/quality should get empty list and default quality."""
    skill_path = tmp_path / "skills" / "common" / "basic" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        """---
name: basic
description: basic skill
version: "1.0.0"
tags: [general]
allowed-tools: [execute_code]
---
Body
""",
        encoding="utf-8",
    )

    skill = parse_skill_file(skill_path)

    assert skill.inputs == []
    assert skill.quality.timeout == 60
    assert skill.quality.max_retries == 0
    assert skill.quality.validation == ""


def test_parse_reference_skills_have_inputs_and_quality() -> None:
    """The reference zscore-monitor skill should have inputs and quality parsed."""
    skill = parse_skill_file(Path("skills/equities/zscore-monitor/SKILL.md"))

    assert len(skill.inputs) >= 1
    assert any(i.name == "symbol" for i in skill.inputs)
    assert skill.quality.timeout == 60


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
    """Parser should ignore unknown frontmatter fields (including tenant)."""
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
    assert "tenant" not in dumped


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


def test_derive_skill_id_nested_skills_dir(tmp_path: Path) -> None:
    """Parser should derive ID from the last 'skills' directory in path."""
    skill_path = (
        tmp_path / "a" / "skills" / "archive" / "skills" / "equities" / "nested" / "SKILL.md"
    )
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        """---
name: nested
description: nested path
version: "1.0.0"
tags: [equities]
tenant: equities
allowed-tools: [query_database]
---
Body
""",
        encoding="utf-8",
    )

    skill = parse_skill_file(skill_path)
    assert skill.skill_id == "equities/nested"
