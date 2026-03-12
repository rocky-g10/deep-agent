"""Python subprocess-based sandbox backend."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import shutil
import tempfile
import threading
import time
import uuid
from asyncio.subprocess import PIPE
from pathlib import Path

from deep_agent.models import ExecuteResult, ResourceLimits

logger = logging.getLogger(__name__)

_SANDBOX_ENV_ALLOWLIST = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TMPDIR",
        "TMP",
        "TEMP",
        "TERM",
    }
)
_ALLOWED_ENV_PREFIXES = ("DB_", "CH_", "PG_", "REDIS_", "MONGO_", "RESOURCE_", "KDB_", "API_")


class PythonSubprocessSandbox:
    """SandboxManager implementation using Python subprocesses."""

    def __init__(self, max_tracked: int = 100) -> None:
        """Initialize sandbox execution backend."""
        self._max_tracked = max_tracked
        self._executions: dict[str, Path] = {}
        self._lock = threading.Lock()

    async def execute(
        self,
        code: str,
        timeout: int = 60,
        resource_limits: ResourceLimits | None = None,
        env: dict[str, str] | None = None,
        files_in: dict[str, bytes] | None = None,
    ) -> ExecuteResult:
        """Execute code in a temporary subprocess sandbox."""
        execution_id = uuid.uuid4().hex
        temp_dir = Path(tempfile.mkdtemp(prefix=f"sandbox-{execution_id[:8]}-"))
        output_dir = temp_dir / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        if files_in:
            for rel_path, file_bytes in files_in.items():
                target = (temp_dir / rel_path).resolve()
                if not target.is_relative_to(temp_dir.resolve()):
                    raise ValueError(
                        f"Path traversal detected: '{rel_path}' escapes sandbox directory"
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(file_bytes)

        code_path = temp_dir / "code.py"
        preamble = _build_resource_preamble(resource_limits)
        code_path.write_text(f"{preamble}{code}", encoding="utf-8")

        process_env = self._build_process_env(env)
        max_output_bytes = (
            resource_limits.max_output_bytes if resource_limits is not None else 10_000_000
        )

        start = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            "python3",
            "code.py",
            cwd=str(temp_dir),
            env=process_env,
            stdout=PIPE,
            stderr=PIPE,
        )

        timeout_message = f"Execution timed out after {timeout} seconds"
        timed_out = False
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            exit_code = proc.returncode if proc.returncode is not None else 1
        except TimeoutError:
            timed_out = True
            proc.kill()
            stdout_bytes, stderr_bytes = await proc.communicate()
            exit_code = -1

        stdout_decoded = stdout_bytes.decode("utf-8", errors="replace")
        stderr_decoded = stderr_bytes.decode("utf-8", errors="replace")
        stdout_text = _truncate_text(stdout_decoded, max_output_bytes)
        stderr_text = _truncate_text(stderr_decoded, max_output_bytes)
        if timed_out:
            stderr_text = _truncate_text(
                f"{stderr_text}\n{timeout_message}" if stderr_text else timeout_message,
                max_output_bytes,
            )

        output_files = _collect_output_files(output_dir)
        duration_ms = int((time.monotonic() - start) * 1000)

        with self._lock:
            self._executions[execution_id] = temp_dir
            self._evict_if_needed()

        return ExecuteResult(
            execution_id=execution_id,
            exit_code=exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
            output_files=output_files,
            duration_ms=duration_ms,
        )

    async def cleanup(self, execution_id: str) -> None:
        """Delete execution artifacts for a completed run."""
        with self._lock:
            path = self._executions.pop(execution_id, None)

        if path is not None and path.exists():
            shutil.rmtree(path)

    def _build_process_env(self, env_overrides: dict[str, str] | None) -> dict[str, str]:
        process_env = {
            key: val
            for key, val in os.environ.items()
            if key in _SANDBOX_ENV_ALLOWLIST
        }

        if env_overrides:
            for key, val in env_overrides.items():
                if any(key.startswith(prefix) for prefix in _ALLOWED_ENV_PREFIXES):
                    process_env[key] = val
                else:
                    # Warning for visibility when a caller attempts unsafe overrides.
                    logger.warning("Blocked disallowed env override: %s", key)

        return process_env

    def _evict_if_needed(self) -> None:
        while len(self._executions) > self._max_tracked:
            oldest_id = next(iter(self._executions))
            oldest_path = self._executions.pop(oldest_id)
            if oldest_path.exists():
                shutil.rmtree(oldest_path)


def _build_resource_preamble(resource_limits: ResourceLimits | None) -> str:
    if resource_limits is None:
        return ""
    memory_mb = resource_limits.memory_mb
    return (
        "import resource as _resource\n"
        f"_mem_bytes = {memory_mb} * 1024 * 1024\n"
        "_resource.setrlimit(_resource.RLIMIT_AS, (_mem_bytes, _mem_bytes))\n"
        "del _resource, _mem_bytes\n"
    )


def _truncate_text(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value

    truncated = encoded[:max_bytes]
    return truncated.decode("utf-8", errors="ignore")


def _collect_output_files(output_dir: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    if not output_dir.exists():
        return files

    resolved_output = output_dir.resolve()
    for file_path in sorted(output_dir.rglob("*")):
        if not file_path.is_file():
            continue
        if file_path.is_symlink():
            continue
        if not file_path.resolve().is_relative_to(resolved_output):
            continue
        rel = file_path.relative_to(output_dir).as_posix()
        files[rel] = base64.b64encode(file_path.read_bytes()).decode("utf-8")
    return files
