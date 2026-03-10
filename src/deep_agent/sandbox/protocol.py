"""Sandbox protocol abstractions."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from deep_agent.models import ExecuteResult, ResourceLimits


@runtime_checkable
class SandboxManager(Protocol):
    """Protocol for isolated code execution backends."""

    async def execute(
        self,
        code: str,
        timeout: int = 60,
        resource_limits: ResourceLimits | None = None,
        env: dict[str, str] | None = None,
        files_in: dict[str, bytes] | None = None,
    ) -> ExecuteResult:
        """Execute source code in isolation and return execution output."""
        ...

    async def cleanup(self, execution_id: str) -> None:
        """Remove temporary artifacts associated with an execution ID."""
        ...
