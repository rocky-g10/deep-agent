"""Unit tests for shared models and configuration."""

from __future__ import annotations

from typing import Any

from pydantic import SecretStr, TypeAdapter

from deep_agent.config import AppSettings
from deep_agent.models import (
    AgentEvent,
    ExecuteResult,
    LLMConfig,
    ResourceLimits,
    TenantContext,
)
from deep_agent.models.skills import AgentSkillBindings, SkillInput, SkillQuality


def _roundtrip(model: Any) -> Any:
    """Round-trip a Pydantic model through model_dump/model_validate."""
    model_type = type(model)
    return model_type.model_validate(model.model_dump())


def test_tenant_context_default_returns_neutral_values() -> None:
    """TenantContext.default should return a generic neutral context."""
    ctx = TenantContext.default()

    assert ctx.tenant_id == "default"
    assert ctx.user_id == "anonymous"
    assert ctx.resource_env == {}
    assert ctx.mcp_config_path == ""


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


def test_agent_event_discriminator_deserializes_all_event_types() -> None:
    """AgentEvent discriminated union should deserialize each event payload shape."""
    adapter: TypeAdapter[AgentEvent] = TypeAdapter(AgentEvent)

    payloads: list[dict[str, Any]] = [
        {"type": "agent_chunk", "content": "hello"},
        {"type": "tool_call", "tool": "execute_code", "input": {"code": "print(1)"}},
        {"type": "tool_result", "tool": "execute_code", "output": "1", "files": {}},
        {"type": "skill_match", "skill_id": "equities/zscore-monitor", "confidence": 0.9},
        {"type": "agent_complete", "summary": "Done", "tokens_used": 42},
        {"type": "error", "code": "SANDBOX_TIMEOUT", "message": "Timed out"},
        {
            "type": "interaction_required",
            "run_id": "run-1",
            "skill_id": "risk/portfolio-var",
            "interaction": {"kind": "clarify", "question": "Which portfolio?"},
        },
        {
            "type": "interaction_response",
            "run_id": "run-1",
            "response": {"kind": "clarify", "value": "EQ-MACRO-1"},
        },
    ]

    event_types = [adapter.validate_python(payload).type for payload in payloads]
    assert event_types == [
        "agent_chunk",
        "tool_call",
        "tool_result",
        "skill_match",
        "agent_complete",
        "error",
        "interaction_required",
        "interaction_response",
    ]


def test_app_settings_loads_defaults(monkeypatch: Any) -> None:
    """AppSettings should load defaults when optional env vars are absent."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("SKILLS_ROOT", raising=False)

    settings = AppSettings(OPENAI_API_KEY=SecretStr("test-key"))

    assert settings.openai_model == "gpt-5"
    assert str(settings.skills_root) == "skills"


def test_agent_skill_bindings() -> None:
    """AgentSkillBindings should hold agent_id and bound_skill_ids."""
    bindings = AgentSkillBindings(
        agent_id="equities-agent",
        bound_skill_ids=("common/db-query", "equities/zscore-monitor"),
    )

    assert bindings.agent_id == "equities-agent"
    assert "common/db-query" in bindings.bound_skill_ids
    assert "equities/zscore-monitor" in bindings.bound_skill_ids
    assert len(bindings.bound_skill_ids) == 2


def test_skill_input_defaults() -> None:
    inp = SkillInput(name="x")
    assert inp.type == "string"
    assert inp.required is True
    assert inp.description == ""


def test_skill_quality_defaults() -> None:
    q = SkillQuality()
    assert q.timeout == 60
    assert q.max_retries == 0
    assert q.validation == ""
    assert q.hitl_timeout == 300
    assert q.hitl_fallback == "abort"


def test_skill_quality_alias() -> None:
    q = SkillQuality(**{"max-retries": 3, "hitl-timeout": 900, "hitl-fallback": "skip"})
    assert q.max_retries == 3
    assert q.hitl_timeout == 900
    assert q.hitl_fallback == "skip"
