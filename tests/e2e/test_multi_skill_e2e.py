"""E2E test for multi-skill composition through the full pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import WebSocketDisconnect

from deep_agent.api.app import create_app
from deep_agent.api.config_loader import build_tenant_context, load_agent_bindings
from deep_agent.api.ws_chat import _handle_client_message
from deep_agent.config import AppSettings
from deep_agent.models.events import AgentCompleteEvent, ToolCallEvent, ToolResultEvent

MULTI_SKILL_CODE = """
from risk_calc import calculate_var
from firm_stats import zscore

var_value = calculate_var([1.0, -0.5, 0.25])
z_value = zscore([100.0, 101.0, 99.5, 100.5], 100.2)
print(f"var={var_value:.2f}")
print(f"zscore={z_value:.2f}")
"""


class FakeWebSocket:
    """Minimal websocket test double for ws_chat handlers."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.sent_texts: list[str] = []

    async def send_text(self, text: str) -> None:
        self.sent_texts.append(text)

    async def accept(self) -> None:
        return None

    async def receive_text(self) -> str:
        raise WebSocketDisconnect()


class DeterministicRuntime:
    """Runtime fallback that executes tools without calling an LLM."""

    def create_agent(
        self, model: str, tools: list[Any], system_prompt: str, **kwargs: Any,
    ) -> dict[str, Any]:
        _ = model, system_prompt, kwargs
        return {"tools": tools}

    async def stream(
        self,
        agent: dict[str, Any],
        message: str,
        context: Any,
        history: list[Any] | None = None,
    ):
        _ = message, context, history
        tool = next((t for t in agent["tools"] if getattr(t, "name", "") == "execute_code"), None)
        assert tool is not None, "execute_code tool missing"

        yield ToolCallEvent(tool="execute_code", input={"code": MULTI_SKILL_CODE})
        raw_result = await tool.ainvoke({"code": MULTI_SKILL_CODE})
        parsed = json.loads(raw_result)
        output = parsed.get("stdout") or parsed.get("stderr") or ""
        yield ToolResultEvent(
            tool="execute_code",
            output=output,
            files=parsed.get("output_files", {}),
        )
        yield AgentCompleteEvent(summary="Completed multi-skill pipeline", tokens_used=0)


@pytest.fixture
def multi_skill_components(tmp_path: Path) -> tuple[Any, Any, str]:
    """Create app with two skills that should match and compose."""
    skills_root = tmp_path / "skills"

    var_skill_dir = skills_root / "risk" / "portfolio-var"
    var_skill_dir.mkdir(parents=True)
    (var_skill_dir / "SKILL.md").write_text(
        '---\nname: portfolio-var\ndescription: Compute portfolio VaR\nversion: "1.0"\n'
        "tags: [risk, var, portfolio]\nallowed-tools: [execute_code]\n---\n"
        "Compute portfolio VaR.\n",
        encoding="utf-8",
    )
    var_scripts_dir = var_skill_dir / "scripts"
    var_scripts_dir.mkdir()
    (var_scripts_dir / "risk_calc.py").write_text(
        "def calculate_var(returns):\n    return abs(min(returns))\n",
        encoding="utf-8",
    )

    zscore_skill_dir = skills_root / "equities" / "zscore-monitor"
    zscore_skill_dir.mkdir(parents=True)
    (zscore_skill_dir / "SKILL.md").write_text(
        '---\nname: zscore-monitor\ndescription: Flag z-score outliers\nversion: "1.0"\n'
        "tags: [equities, zscore, outlier]\nallowed-tools: [execute_code]\n---\n"
        "Flag z-score outliers.\n",
        encoding="utf-8",
    )
    zscore_scripts_dir = zscore_skill_dir / "scripts"
    zscore_scripts_dir.mkdir()
    (zscore_scripts_dir / "firm_stats.py").write_text(
        (
            "def zscore(series, current):\n"
            "    mean = sum(series) / len(series)\n"
            "    variance = sum((x - mean) ** 2 for x in series) / len(series)\n"
            "    std = variance ** 0.5\n"
            "    return 0.0 if std == 0 else (current - mean) / std\n"
        ),
        encoding="utf-8",
    )

    config_root = tmp_path / "config"
    tenant_dir = config_root / "tenants" / "test"
    tenant_dir.mkdir(parents=True)
    (tenant_dir / "resources.yaml").write_text("resource_aliases: {}\n", encoding="utf-8")

    agents_dir = config_root / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "test-agent.yaml").write_text(
        (
            'agent_id: "test-agent"\n'
            "bound_skill_ids:\n"
            '  - "risk/portfolio-var"\n'
            '  - "equities/zscore-monitor"\n'
        ),
        encoding="utf-8",
    )

    settings = AppSettings(
        OPENAI_API_KEY="sk-fake",  # type: ignore[arg-type]
        SKILLS_ROOT=skills_root,
    )
    app = create_app(
        settings=settings,
        config_root=config_root,
        runtime=DeterministicRuntime(),
    )

    tenant = build_tenant_context("test", config_root=config_root)
    bindings = load_agent_bindings("test-agent", config_root=config_root)
    assert bindings is not None

    session = app.state.session_manager.create(tenant=tenant, bindings=bindings)
    websocket = FakeWebSocket(app)
    return app, websocket, session.session_id


@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_multi_skill_full_pipeline(multi_skill_components: tuple[Any, Any, str]) -> None:
    """Full pipeline should match two skills and execute one composed script."""
    app, websocket, session_id = multi_skill_components

    await _handle_client_message(
        raw=json.dumps(
            {
                "type": "user_message",
                "content": "Compute portfolio VaR and zscore outlier flags",
                "session_id": session_id,
            }
        ),
        websocket=websocket,
        orchestrator=app.state.orchestrator,
        session_manager=app.state.session_manager,
        session_id=session_id,
    )

    events = [json.loads(text) for text in websocket.sent_texts]
    skill_matches = [e for e in events if e["type"] == "skill_match"]
    tool_calls = [e for e in events if e["type"] == "tool_call"]
    tool_results = [e for e in events if e["type"] == "tool_result"]
    errors = [e for e in events if e["type"] == "error"]

    assert len(skill_matches) == 2
    matched_ids = {e["skill_id"] for e in skill_matches}
    assert matched_ids == {"risk/portfolio-var", "equities/zscore-monitor"}
    assert len(tool_calls) == 1
    assert tool_calls[0]["tool"] == "execute_code"
    assert len(tool_results) == 1
    assert "var=" in tool_results[0]["output"]
    assert "zscore=" in tool_results[0]["output"]
    assert events[-1]["type"] == "agent_complete"
    assert errors == []
