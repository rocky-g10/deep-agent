"""Unit tests for PythonSubprocessSandbox."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from deep_agent.sandbox import PythonSubprocessSandbox


@pytest.mark.timeout(10)
async def test_execute_simple_print() -> None:
    """Simple print should produce stdout and zero exit code."""
    sandbox = PythonSubprocessSandbox()

    result = await sandbox.execute("print('hello')")

    assert result.exit_code == 0
    assert result.stdout == "hello\n"
    assert result.stderr == ""
    await sandbox.cleanup(result.execution_id)


@pytest.mark.timeout(10)
async def test_execute_output_file() -> None:
    """Files written to output/ should be returned in output_files."""
    sandbox = PythonSubprocessSandbox()
    code = """
from pathlib import Path
Path('output/chart.png').write_bytes(b'PNGDATA')
print('done')
"""

    result = await sandbox.execute(code)

    assert result.exit_code == 0
    assert "chart.png" in result.output_files
    decoded = base64.b64decode(result.output_files["chart.png"])
    assert decoded == b"PNGDATA"
    await sandbox.cleanup(result.execution_id)


@pytest.mark.timeout(15)
async def test_execute_timeout() -> None:
    """Timeout should kill the process and return timeout info in stderr."""
    sandbox = PythonSubprocessSandbox()
    code = """
import time
time.sleep(100)
"""

    result = await sandbox.execute(code, timeout=1)

    assert result.exit_code != 0
    assert "timed out" in result.stderr.lower()
    await sandbox.cleanup(result.execution_id)


@pytest.mark.timeout(10)
async def test_execute_syntax_error() -> None:
    """Invalid syntax should produce non-zero exit and SyntaxError in stderr."""
    sandbox = PythonSubprocessSandbox()

    result = await sandbox.execute("def broken(:\n    pass")

    assert result.exit_code != 0
    assert "SyntaxError" in result.stderr
    await sandbox.cleanup(result.execution_id)


@pytest.mark.timeout(10)
async def test_execute_env_var_injection() -> None:
    """Environment overrides should be visible inside sandbox code."""
    sandbox = PythonSubprocessSandbox()
    code = """
import os
print(os.environ['DB_TEST_VAR'])
"""

    result = await sandbox.execute(code, env={"DB_TEST_VAR": "VALUE123"})

    assert result.exit_code == 0
    assert result.stdout.strip() == "VALUE123"
    await sandbox.cleanup(result.execution_id)


@pytest.mark.timeout(10)
async def test_execute_files_in() -> None:
    """files_in payload should be written before execution."""
    sandbox = PythonSubprocessSandbox()
    code = """
from pathlib import Path
print(Path('data.csv').read_text())
"""

    result = await sandbox.execute(code, files_in={"data.csv": b"a,b\n1,2\n"})

    assert result.exit_code == 0
    assert "a,b" in result.stdout
    assert "1,2" in result.stdout
    await sandbox.cleanup(result.execution_id)


@pytest.mark.timeout(10)
async def test_cleanup_removes_directory() -> None:
    """cleanup should delete tracked temporary execution directory."""
    sandbox = PythonSubprocessSandbox()

    result = await sandbox.execute("print('x')")
    exec_path = sandbox._executions[result.execution_id]
    assert exec_path.exists()

    await sandbox.cleanup(result.execution_id)

    assert not exec_path.exists()


async def test_cleanup_nonexistent_id_is_noop() -> None:
    """cleanup on unknown execution id should not raise."""
    sandbox = PythonSubprocessSandbox()

    await sandbox.cleanup("missing-id")


@pytest.mark.timeout(10)
async def test_files_in_path_traversal_blocked() -> None:
    """files_in entries must not escape the sandbox directory."""
    sandbox = PythonSubprocessSandbox()

    with pytest.raises(ValueError, match="Path traversal"):
        await sandbox.execute("", files_in={"../../etc/evil": b"x"})

    with pytest.raises(ValueError, match="Path traversal"):
        await sandbox.execute("", files_in={"/tmp/evil": b"x"})


@pytest.mark.timeout(10)
async def test_output_files_symlinks_skipped() -> None:
    """Symlinked files in output/ should be skipped for security."""
    sandbox = PythonSubprocessSandbox()
    code = """
import os
from pathlib import Path

Path('output/real.txt').write_text('real')
os.symlink('/etc/passwd', 'output/leaked')
"""

    result = await sandbox.execute(code)

    assert "real.txt" in result.output_files
    assert "leaked" not in result.output_files
    await sandbox.cleanup(result.execution_id)


@pytest.mark.timeout(10)
async def test_sandbox_env_does_not_leak_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Host secret env vars should not leak into sandbox subprocess env."""
    monkeypatch.setenv("SECRET_TOKEN", "hunter2")
    sandbox = PythonSubprocessSandbox()
    code = """
import os
print(os.environ.get('SECRET_TOKEN', 'ABSENT'))
"""

    result = await sandbox.execute(code)

    assert result.exit_code == 0
    assert result.stdout.strip() == "ABSENT"
    await sandbox.cleanup(result.execution_id)


@pytest.mark.timeout(10)
async def test_env_overrides_blocks_dangerous_keys() -> None:
    """Only allowlisted env prefixes should be applied to sandbox process env."""
    sandbox = PythonSubprocessSandbox()
    code = """
import os
print(os.environ.get('LD_PRELOAD', 'MISSING'))
print(os.environ.get('PATH', 'MISSING'))
print(os.environ.get('CH_EQUITIES_HOST', 'MISSING'))
"""

    result = await sandbox.execute(
        code,
        env={
            "LD_PRELOAD": "/evil.so",
            "PATH": "/evil",
            "CH_EQUITIES_HOST": "safe-host",
        },
    )

    lines = result.stdout.strip().splitlines()
    assert lines[0] == "MISSING"
    assert lines[1] != "/evil"
    assert lines[2] == "safe-host"
    await sandbox.cleanup(result.execution_id)


@pytest.mark.timeout(10)
async def test_resource_prefix_env_var_injection() -> None:
    """RESOURCE_ prefixed env vars should be allowed into sandbox."""
    sandbox = PythonSubprocessSandbox()
    code = """
import os
print(os.environ.get('RESOURCE_API_KEY', 'MISSING'))
print(os.environ.get('KDB_HOST', 'MISSING'))
print(os.environ.get('API_TOKEN', 'MISSING'))
"""

    result = await sandbox.execute(
        code,
        env={
            "RESOURCE_API_KEY": "res-key-123",
            "KDB_HOST": "kdb-host.local",
            "API_TOKEN": "api-tok-456",
        },
    )

    lines = result.stdout.strip().splitlines()
    assert lines[0] == "res-key-123"
    assert lines[1] == "kdb-host.local"
    assert lines[2] == "api-tok-456"
    await sandbox.cleanup(result.execution_id)


@pytest.mark.timeout(10)
async def test_pythonpath_env_enables_skill_script_imports(tmp_path: Path) -> None:
    """PYTHONPATH override should allow sandbox to import skill helper modules."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "helper.py").write_text("VALUE = 42\n", encoding="utf-8")

    sandbox = PythonSubprocessSandbox()
    code = """
from helper import VALUE
print(VALUE)
"""

    result = await sandbox.execute(
        code, env={"PYTHONPATH": str(scripts_dir)}
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == "42"
    await sandbox.cleanup(result.execution_id)
