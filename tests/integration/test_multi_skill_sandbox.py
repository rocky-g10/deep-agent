"""Integration tests for multi-skill PYTHONPATH composition in sandbox."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from deep_agent.sandbox.subprocess_sandbox import PythonSubprocessSandbox


@pytest.fixture
def two_skill_scripts(tmp_path: Path) -> tuple[str, str]:
    """Create two temp script directories with unique modules."""
    dir_a = tmp_path / "skill_a"
    dir_b = tmp_path / "skill_b"
    dir_a.mkdir()
    dir_b.mkdir()

    (dir_a / "alpha_mod.py").write_text(
        "def greet():\n    return 'hello from alpha'\n",
        encoding="utf-8",
    )
    (dir_b / "beta_mod.py").write_text(
        "def greet():\n    return 'hello from beta'\n",
        encoding="utf-8",
    )
    return str(dir_a), str(dir_b)


@pytest.mark.asyncio
async def test_two_skills_importable_in_one_execution(two_skill_scripts: tuple[str, str]) -> None:
    """Both skills' modules should import in one sandbox execution."""
    dir_a, dir_b = two_skill_scripts
    sandbox = PythonSubprocessSandbox()
    code = (
        "from alpha_mod import greet as a_greet\n"
        "from beta_mod import greet as b_greet\n"
        "print(a_greet())\n"
        "print(b_greet())\n"
    )
    env = {"PYTHONPATH": os.pathsep.join([dir_a, dir_b])}

    result = await sandbox.execute(code=code, env=env, timeout=15)

    assert result.exit_code == 0, f"stderr: {result.stderr}"
    assert "hello from alpha" in result.stdout
    assert "hello from beta" in result.stdout
    await sandbox.cleanup(result.execution_id)


@pytest.mark.asyncio
async def test_higher_scored_skill_shadows_on_collision(
    two_skill_scripts: tuple[str, str],
) -> None:
    """If module names collide, first path in PYTHONPATH should win."""
    dir_a, dir_b = two_skill_scripts
    (Path(dir_a) / "shared.py").write_text("WHO = 'skill_a'\n", encoding="utf-8")
    (Path(dir_b) / "shared.py").write_text("WHO = 'skill_b'\n", encoding="utf-8")

    sandbox = PythonSubprocessSandbox()
    code = "from shared import WHO\nprint(WHO)\n"
    env = {"PYTHONPATH": os.pathsep.join([dir_a, dir_b])}

    result = await sandbox.execute(code=code, env=env, timeout=15)

    assert result.exit_code == 0
    assert "skill_a" in result.stdout
    await sandbox.cleanup(result.execution_id)
