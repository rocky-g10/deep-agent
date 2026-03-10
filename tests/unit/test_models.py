"""Unit tests for shared models and configuration."""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter

from deep_agent.config import AppSettings
from deep_agent.models import (
    AgentEvent,
    ConnectionConfig,
    DatabaseAlias,
    ExecuteResult,
    LLMConfig,
    ResourceLimits,
    TenantContext,
)


def _roundtrip(model: Any) -> Any:
    """Round-trip a Pydantic model through model_dump/model_validate."""
    model_type = type(model)
    return model_type.model_validate(model.model_dump())


def test_tenant_context_stub_returns_expected_equities_values() -> None:
    """TenantContext.stub should return the hardcoded equities context."""
    stub = TenantContext.stub()

    assert stub.tenant_id == "equities"
    assert stub.user_id == "dev-user"
    assert stub.skills_dirs == ["skills/common", "skills/equities"]
    assert stub.db_aliases == ["ch-equities"]


def test_llm_config_roundtrip() -> None:
    """LLMConfig should instantiate and round-trip via model_dump/model_validate."""
    config = LLMConfig(provider="openai", model="gpt-5", temperature=0.2, max_tokens=1024)

    loaded = _roundtrip(config)
    assert loaded == config


def test_resource_limits_roundtrip() -> None:
    """ResourceLimits should instantiate and round-trip cleanly."""
    limits = ResourceLimits(cpu_cores=1.5, memory_mb=2048, max_output_bytes=1024)

    loaded = _roundtrip(limits)
    assert loaded == limits


def test_execute_result_output_files_json_roundtrip() -> None:
    """ExecuteResult output_files should serialize and deserialize as JSON-safe strings."""
    result = ExecuteResult(
        execution_id="exec-1",
        exit_code=0,
        stdout="ok",
        stderr="",
        output_files={"chart.png": "YmFzZTY0LWJ5dGVz"},
        duration_ms=12,
    )

    loaded = _roundtrip(result)
    assert loaded == result


def test_database_alias_roundtrip() -> None:
    """DatabaseAlias should instantiate and round-trip cleanly."""
    alias = DatabaseAlias(alias="ch-equities", engine="clickhouse", description="Equities data")

    loaded = _roundtrip(alias)
    assert loaded == alias


def test_connection_config_roundtrip() -> None:
    """ConnectionConfig should instantiate and round-trip cleanly."""
    config = ConnectionConfig(
        engine="clickhouse",
        host="localhost",
        port=8123,
        database="default",
        credentials_ref="secret://clickhouse/default",
    )

    loaded = _roundtrip(config)
    assert loaded == config


def test_agent_event_discriminator_deserializes_all_event_types() -> None:
    """AgentEvent discriminated union should deserialize each event payload shape."""
    adapter = TypeAdapter(AgentEvent)

    payloads: list[dict[str, Any]] = [
        {"type": "agent_chunk", "content": "hello"},
        {"type": "tool_call", "tool": "execute_code", "input": {"code": "print(1)"}},
        {"type": "tool_result", "tool": "execute_code", "output": "1", "files": {}},
        {"type": "skill_match", "skill_id": "equities/zscore-monitor", "confidence": 0.9},
        {"type": "agent_complete", "summary": "Done", "tokens_used": 42},
        {"type": "error", "code": "SANDBOX_TIMEOUT", "message": "Timed out"},
    ]

    event_types = [adapter.validate_python(payload).type for payload in payloads]
    assert event_types == [
        "agent_chunk",
        "tool_call",
        "tool_result",
        "skill_match",
        "agent_complete",
        "error",
    ]


def test_app_settings_loads_defaults(monkeypatch: Any) -> None:
    """AppSettings should load defaults when optional env vars are absent."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("CLICKHOUSE_HOST", raising=False)
    monkeypatch.delenv("SKILLS_ROOT", raising=False)

    settings = AppSettings()

    assert settings.openai_model == "gpt-5"
    assert settings.clickhouse_host == "localhost"
    assert str(settings.skills_root) == "skills"
