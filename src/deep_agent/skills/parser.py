"""Skill file parsing utilities."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

import frontmatter
from frontmatter import Post

from deep_agent.models import SkillContent

REQUIRED_SKILL_FIELDS: tuple[str, ...] = (
    "name",
    "description",
    "version",
    "tags",
    "allowed-tools",
)


class SkillParseError(ValueError):
    """Raised when a SKILL.md file does not meet required schema constraints."""

class FrontmatterLoader(Protocol):
    """Protocol for loading markdown files with YAML frontmatter."""

    def load(self, path: str, encoding: str = "utf-8") -> Post:
        """Return parsed frontmatter post for the given path."""


class PythonFrontmatterLoader:
    """Adapter around the `python-frontmatter` loader."""

    def load(self, path: str, encoding: str = "utf-8") -> Post:
        """Load and parse a frontmatter post."""
        return frontmatter.load(path, encoding=encoding)


def parse_skill_file(path: Path, loader: FrontmatterLoader | None = None) -> SkillContent:
    """Parse a `SKILL.md` file and return validated skill content."""
    post_loader = loader or PythonFrontmatterLoader()
    try:
        post = post_loader.load(str(path))
    except SkillParseError:
        raise
    except Exception as exc:  # pragma: no cover - upstream library exception shape can vary.
        raise SkillParseError(f"{path}: failed to parse frontmatter: {exc}") from exc

    metadata = dict(post.metadata)
    _validate_required_fields(metadata=metadata, path=path)

    skill_id = _derive_skill_id(path)
    tags = _validate_string_list(metadata["tags"], field_name="tags", path=path)
    allowed_tools = _validate_string_list(
        metadata["allowed-tools"], field_name="allowed-tools", path=path
    )

    body = post.content or ""
    scripts_dir = path.parent / "scripts"
    scripts_path = str(scripts_dir.resolve()) if scripts_dir.is_dir() else ""

    return SkillContent(
        skill_id=skill_id,
        name=_as_string(metadata["name"], field_name="name", path=path),
        description=_as_string(metadata["description"], field_name="description", path=path),
        version=_as_string(metadata["version"], field_name="version", path=path),
        tags=tags,
        allowed_tools=allowed_tools,
        body=body,
        scripts_path=scripts_path,
    )


def _validate_required_fields(metadata: Mapping[str, Any], path: Path) -> None:
    missing_fields = [field for field in REQUIRED_SKILL_FIELDS if field not in metadata]
    if missing_fields:
        missing = ", ".join(missing_fields)
        raise SkillParseError(f"{path}: missing required frontmatter fields: {missing}")


def _derive_skill_id(path: Path) -> str:
    parts = list(path.parts)
    if "skills" in parts:
        skills_index = len(parts) - 1 - parts[::-1].index("skills")
        rel_parts = parts[skills_index + 1 : -1]
        if rel_parts:
            return "/".join(rel_parts)
    if path.parent.name:
        return path.parent.name
    raise SkillParseError(f"{path}: unable to derive skill_id from path")


def _as_string(value: Any, field_name: str, path: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        msg = f"{path}: frontmatter field '{field_name}' must be a non-empty string"
        raise SkillParseError(msg)
    return value


def _validate_string_list(value: Any, field_name: str, path: Path) -> list[str]:
    if not isinstance(value, list) or not value:
        raise SkillParseError(f"{path}: frontmatter field '{field_name}' must be a non-empty list")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise SkillParseError(f"{path}: frontmatter field '{field_name}' must contain strings")
    return [str(item) for item in value]
