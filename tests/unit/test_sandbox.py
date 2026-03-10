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
print(os.environ['TEST_VAR'])
"""

    result = await sandbox.execute(code, env={"TEST_VAR": "VALUE123"})

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
async def test_execute_stubs_pythonpath() -> None:
    """stubs_path should allow importing firm.stats inside sandbox."""
    sandbox = PythonSubprocessSandbox(stubs_path=Path("stubs").resolve())
    code = """
from firm.stats import zscore, moving_avg
print(callable(zscore), callable(moving_avg))
"""

    result = await sandbox.execute(code)

    assert result.exit_code == 0
    assert "True True" in result.stdout
    await sandbox.cleanup(result.execution_id)
