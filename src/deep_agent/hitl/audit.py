"""Audit helpers for HITL interaction lifecycle events."""

from __future__ import annotations

import dataclasses
import json
import logging
from dataclasses import dataclass

logger = logging.getLogger("deep_agent.hitl.audit")


@dataclass
class HITLAuditEvent:
    """Structured audit event for HITL interactions."""

    timestamp: str
    trace_id: str
    session_id: str
    user_id: str
    tenant_id: str
    category: str = "hitl_interaction"
    action: str = ""
    interaction_kind: str = ""
    question_or_action: str = ""
    response: str | None = None
    responder_id: str | None = None
    latency_ms: int | None = None
    risk_level: str | None = None
    outcome: str | None = None


def emit_hitl_audit(event: HITLAuditEvent) -> None:
    """Emit structured HITL audit event as a JSON log line."""
    logger.info(json.dumps(dataclasses.asdict(event), sort_keys=True))
