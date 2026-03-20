"""In-memory session management for Phase 1."""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from deep_agent.models.context import TenantContext
from deep_agent.models.skills import AgentSkillBindings


@dataclass
class Session:
    """A single user session with conversation state."""

    session_id: str
    tenant: TenantContext
    bindings: AgentSkillBindings
    messages: list[Any] = field(default_factory=list)  # list[BaseMessage]
    active_run_id: str | None = None
    resume_queue: asyncio.Queue[Any] = field(default_factory=asyncio.Queue)
    created_at: float = field(default_factory=time.time)


class SessionManager:
    """Thread-safe in-memory session store.

    Phase 1 only — sessions are lost on restart.
    Phase 2 replaces this with Redis + PostgreSQL.
    """

    def __init__(self, max_sessions: int = 1000) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        self._max_sessions = max_sessions

    def create(
        self,
        tenant: TenantContext,
        bindings: AgentSkillBindings,
    ) -> Session:
        """Create a new session and return it."""
        session_id = uuid.uuid4().hex
        session = Session(
            session_id=session_id,
            tenant=tenant,
            bindings=bindings,
        )
        with self._lock:
            self._sessions[session_id] = session
            self._evict_oldest()
        return session

    def get(self, session_id: str) -> Session | None:
        """Return session by ID, or None if not found."""
        with self._lock:
            return self._sessions.get(session_id)

    def delete(self, session_id: str) -> None:
        """Remove a session."""
        with self._lock:
            self._sessions.pop(session_id, None)

    def _evict_oldest(self) -> None:
        """Evict oldest sessions if over capacity."""
        while len(self._sessions) > self._max_sessions:
            oldest_id = min(self._sessions, key=lambda k: self._sessions[k].created_at)
            self._sessions.pop(oldest_id, None)
