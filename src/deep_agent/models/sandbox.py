"""Sandbox execution models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ResourceLimits(BaseModel):
    """Resource constraints applied to sandboxed code execution."""

    cpu_cores: float = 2.0
    memory_mb: int = 4096
    max_output_bytes: int = 10_000_000


class ExecuteResult(BaseModel):
    """Result payload for sandbox code execution."""

    execution_id: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    output_files: dict[str, str] = Field(default_factory=dict)
    duration_ms: int
