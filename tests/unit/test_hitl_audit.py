"""Unit tests for HITL audit logging."""

from __future__ import annotations

import json

from deep_agent.hitl.audit import HITLAuditEvent, emit_hitl_audit


def test_emit_hitl_audit_logs_structured_json(caplog: object) -> None:
    with caplog.at_level("INFO", logger="deep_agent.hitl.audit"):
        emit_hitl_audit(
            HITLAuditEvent(
                timestamp="2026-03-20T00:00:00Z",
                trace_id="run-1",
                session_id="session-1",
                user_id="u-1",
                tenant_id="risk",
                action="interaction_requested",
                interaction_kind="approve",
                question_or_action="Execute hedge?",
                risk_level="high",
            )
        )

    record = json.loads(caplog.records[-1].message)
    assert record["category"] == "hitl_interaction"
    assert record["trace_id"] == "run-1"
    assert record["action"] == "interaction_requested"
    assert record["interaction_kind"] == "approve"
    assert record["question_or_action"] == "Execute hedge?"
    assert record["risk_level"] == "high"


def test_emit_hitl_audit_fields_for_response_and_timeout(caplog: object) -> None:
    latency_ms = int((11.5 - 10.0) * 1000)
    with caplog.at_level("INFO", logger="deep_agent.hitl.audit"):
        emit_hitl_audit(
            HITLAuditEvent(
                timestamp="2026-03-20T00:00:01Z",
                trace_id="run-2",
                session_id="session-2",
                user_id="u-2",
                tenant_id="equities",
                action="response_submitted",
                interaction_kind="approve",
                question_or_action="Execute hedge?",
                response='{"kind":"approve","approved":true}',
                responder_id="u-2",
                latency_ms=latency_ms,
                outcome="approved",
            )
        )
        emit_hitl_audit(
            HITLAuditEvent(
                timestamp="2026-03-20T00:00:02Z",
                trace_id="run-3",
                session_id="session-3",
                user_id="u-3",
                tenant_id="equities",
                action="interaction_timed_out",
                interaction_kind="clarify",
                question_or_action="Which portfolio?",
                outcome="timed_out",
            )
        )
        emit_hitl_audit(
            HITLAuditEvent(
                timestamp="2026-03-20T00:00:03Z",
                trace_id="run-4",
                session_id="session-4",
                user_id="u-4",
                tenant_id="equities",
                action="interaction_timed_out",
                interaction_kind="collect",
                question_or_action="collect_fields",
                outcome="skipped",
            )
        )

    response_record = json.loads(caplog.records[-3].message)
    timeout_record = json.loads(caplog.records[-2].message)
    skip_record = json.loads(caplog.records[-1].message)

    assert response_record["latency_ms"] == latency_ms
    assert response_record["outcome"] == "approved"
    assert timeout_record["outcome"] == "timed_out"
    assert skip_record["outcome"] == "skipped"
