"""Checkpoint store abstractions for paused HITL runs."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from langchain_core.messages import BaseMessage, messages_from_dict, messages_to_dict
from pydantic import BaseModel, Field

from deep_agent.models.hitl import HumanInteractionRequest


class Checkpoint(BaseModel):
    """Serialized agent state for suspend/resume."""

    run_id: str
    session_id: str
    conversation_history: list[dict[str, Any]]
    pending_interaction: HumanInteractionRequest
    skill_id: str | None = None
    tool_call_id: str | None = None
    env_snapshot: dict[str, str] = Field(default_factory=dict)
    scripts_dirs: list[str] = Field(default_factory=list)
    tenant_context: dict[str, Any] = Field(default_factory=dict)
    skill_bindings: dict[str, Any] = Field(default_factory=dict)
    original_message: str = ""
    created_at: float

    @classmethod
    def from_messages(
        cls,
        *,
        run_id: str,
        session_id: str,
        messages: Sequence[BaseMessage],
        pending_interaction: HumanInteractionRequest,
        created_at: float,
        skill_id: str | None = None,
        tool_call_id: str | None = None,
        env_snapshot: dict[str, str] | None = None,
        scripts_dirs: list[str] | None = None,
    ) -> Checkpoint:
        """Build a checkpoint using LangChain message objects."""
        return cls(
            run_id=run_id,
            session_id=session_id,
            conversation_history=messages_to_dict(list(messages)),
            pending_interaction=pending_interaction,
            skill_id=skill_id,
            tool_call_id=tool_call_id,
            env_snapshot=env_snapshot or {},
            scripts_dirs=scripts_dirs or [],
            created_at=created_at,
        )

    def to_messages(self) -> list[BaseMessage]:
        """Rehydrate LangChain messages from serialized history."""
        return list(messages_from_dict(self.conversation_history))


@runtime_checkable
class CheckpointStore(Protocol):
    """Storage protocol for run checkpoints."""

    async def save(self, checkpoint: Checkpoint) -> None: ...

    async def load(self, run_id: str) -> Checkpoint | None: ...

    async def delete(self, run_id: str) -> None: ...


class InMemoryCheckpointStore:
    """MVP in-memory implementation. Redis/PostgreSQL backends are post-MVP."""

    def __init__(self) -> None:
        self._store: dict[str, Checkpoint] = {}
        self._lock = asyncio.Lock()

    async def save(self, checkpoint: Checkpoint) -> None:
        async with self._lock:
            self._store[checkpoint.run_id] = checkpoint

    async def load(self, run_id: str) -> Checkpoint | None:
        async with self._lock:
            return self._store.get(run_id)

    async def delete(self, run_id: str) -> None:
        async with self._lock:
            self._store.pop(run_id, None)
