"""Unit tests for AgentOrchestrator."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from deep_agent.models import (
    AgentChunkEvent,
    AgentCompleteEvent,
    AgentEvent,
    ErrorEvent,
    LLMConfig,
    SkillSummary,
    TenantContext,
)
from deep_agent.models.skills import (
    AgentSkillBindings,
    MCPToolBinding,
    SkillContent,
    SkillMCPServer,
)
from deep_agent.orchestrator.agent_orchestrator import (
    AgentOrchestrator,
    _filter_tools,
    _merge_skill_contents,
)


def _make_skill_content(skill_match: SkillSummary) -> MagicMock:
    """Build a realistic skill content mock for orchestrator tests."""
    skill_content = MagicMock()
    skill_content.name = skill_match.name
    skill_content.skill_id = skill_match.skill_id
    skill_content.body = "## Instructions\nDo stuff."
    skill_content.allowed_tools = ["execute_code"]
    skill_content.scripts_path = ""
    skill_content.quality.timeout = 60
    skill_content.mcp_servers = []
    skill_content.mcp_tool_bindings = []
    return skill_content


def _skill_content_model(
    *,
    skill_id: str,
    allowed_tools: list[str] | None = None,
    scripts_path: str = "",
    timeout: int = 60,
    mcp_servers: list[SkillMCPServer] | None = None,
    mcp_tool_bindings: list[MCPToolBinding] | None = None,
) -> SkillContent:
    return SkillContent(
        skill_id=skill_id,
        name=skill_id.split("/")[-1],
        description=f"{skill_id} description",
        version="1.0.0",
        tags=["test"],
        allowed_tools=allowed_tools or ["execute_code"],
        body=f"Body for {skill_id}",
        scripts_path=scripts_path,
        mcp_servers=mcp_servers or [],
        mcp_tool_bindings=mcp_tool_bindings or [],
        quality={"timeout": timeout},
    )


def _mock_skill_engine(matches: list[SkillSummary] | None = None) -> MagicMock:
    engine = MagicMock()
    engine.discover.return_value = matches or []
    engine.match.return_value = matches or []
    if matches:
        skill_by_id = {match.skill_id: _make_skill_content(match) for match in matches}

        def load_side_effect(skill_id: str, *_args: Any, **_kwargs: Any) -> MagicMock:
            return skill_by_id[skill_id]

        engine.load.side_effect = load_side_effect
    return engine


async def _fake_stream(*_args: Any, **_kwargs: Any) -> AsyncIterator[AgentEvent]:
    yield AgentChunkEvent(content="Hello")
    yield AgentCompleteEvent(summary="Hello", tokens_used=10)


@pytest.mark.asyncio
async def test_handle_message_yields_skill_match_first(
    tenant_equities: TenantContext,
    skill_bindings: AgentSkillBindings,
) -> None:
    """First event should be SkillMatchEvent when a skill matches."""
    skill_match = SkillSummary(
        skill_id="equities/zscore-monitor",
        name="zscore-monitor",
        description="Monitor z-scores",
        tags=["zscore"],
    )
    engine = _mock_skill_engine([skill_match])

    runtime = MagicMock()
    runtime.create_agent.return_value = MagicMock()
    runtime.stream = _fake_stream

    orchestrator = AgentOrchestrator(
        skill_engine=engine,
        llm_router=MagicMock(resolve=MagicMock(return_value=LLMConfig())),
        runtime=runtime,
        sandbox=AsyncMock(),
    )

    events = [
        event
        async for event in orchestrator.handle_message(
            "z-scores for AAPL", tenant_equities, skill_bindings=skill_bindings
        )
    ]

    assert events[0].type == "skill_match"
    assert events[0].skill_id == "equities/zscore-monitor"
    assert events[0].confidence < 1.0


@pytest.mark.asyncio
async def test_multi_match_yields_multiple_skill_match_events(
    tenant_equities: TenantContext,
    skill_bindings: AgentSkillBindings,
) -> None:
    """Multiple matched skills should emit multiple skill_match events first."""
    skill_matches = [
        SkillSummary(
            skill_id="common/db-query",
            name="db-query",
            description="Query DB",
            tags=["database"],
            score=0.8,
        ),
        SkillSummary(
            skill_id="equities/zscore-monitor",
            name="zscore-monitor",
            description="Monitor z-scores",
            tags=["zscore"],
            score=0.6,
        ),
    ]
    engine = _mock_skill_engine(skill_matches)

    runtime = MagicMock()
    runtime.create_agent.return_value = MagicMock()
    runtime.stream = _fake_stream

    orchestrator = AgentOrchestrator(
        skill_engine=engine,
        llm_router=MagicMock(resolve=MagicMock(return_value=LLMConfig())),
        runtime=runtime,
        sandbox=AsyncMock(),
    )

    events = [
        event
        async for event in orchestrator.handle_message(
            "query and zscore", tenant_equities, skill_bindings=skill_bindings
        )
    ]

    skill_events = [event for event in events if event.type == "skill_match"]
    assert len(skill_events) == 2
    assert events[0].type == "skill_match"
    assert events[1].type == "skill_match"
    assert events[2].type == "agent_chunk"


@pytest.mark.asyncio
async def test_single_skill_backward_compat(
    tenant_equities: TenantContext,
    skill_bindings: AgentSkillBindings,
) -> None:
    """Single-skill match should still produce one skill_match and singular prompt."""
    skill_match = SkillSummary(
        skill_id="common/db-query",
        name="db-query",
        description="Query DB",
        tags=["database"],
        score=0.8,
    )
    engine = _mock_skill_engine([skill_match])

    runtime = MagicMock()
    runtime.create_agent.return_value = MagicMock()
    runtime.stream = _fake_stream

    orchestrator = AgentOrchestrator(
        skill_engine=engine,
        llm_router=MagicMock(resolve=MagicMock(return_value=LLMConfig())),
        runtime=runtime,
        sandbox=AsyncMock(),
    )

    events = [
        event
        async for event in orchestrator.handle_message(
            "query db", tenant_equities, skill_bindings=skill_bindings
        )
    ]

    assert len([event for event in events if event.type == "skill_match"]) == 1
    system_prompt = runtime.create_agent.call_args.kwargs["system_prompt"]
    assert "## Active Skill: db-query" in system_prompt


@pytest.mark.asyncio
async def test_handle_message_no_skill_match_no_filter(
    tenant_equities: TenantContext,
    skill_bindings: AgentSkillBindings,
) -> None:
    """When no skills match, all tools should be available (no filtering)."""
    engine = _mock_skill_engine([])

    runtime = MagicMock()
    runtime.create_agent.return_value = MagicMock()
    runtime.stream = _fake_stream

    orchestrator = AgentOrchestrator(
        skill_engine=engine,
        llm_router=MagicMock(resolve=MagicMock(return_value=LLMConfig())),
        runtime=runtime,
        sandbox=AsyncMock(),
    )

    events = [
        event
        async for event in orchestrator.handle_message(
            "random question", tenant_equities, skill_bindings=skill_bindings
        )
    ]

    assert not any(event.type == "skill_match" for event in events)
    tools = runtime.create_agent.call_args.kwargs["tools"]
    assert len(tools) >= 1


@pytest.mark.asyncio
async def test_skill_load_failure_skips_gracefully(
    tenant_equities: TenantContext,
    skill_bindings: AgentSkillBindings,
) -> None:
    """A failed load for one matched skill should not block remaining loaded skills."""
    skill_matches = [
        SkillSummary(
            skill_id="common/db-query",
            name="db-query",
            description="Query DB",
            tags=["database"],
            score=0.8,
        ),
        SkillSummary(
            skill_id="equities/zscore-monitor",
            name="zscore-monitor",
            description="Monitor z-scores",
            tags=["zscore"],
            score=0.6,
        ),
    ]
    engine = _mock_skill_engine(skill_matches)

    original_side_effect = engine.load.side_effect

    def load_side_effect(skill_id: str, *args: Any, **kwargs: Any) -> Any:
        if skill_id == "equities/zscore-monitor":
            raise RuntimeError("load failed")
        return original_side_effect(skill_id, *args, **kwargs)

    engine.load.side_effect = load_side_effect

    runtime = MagicMock()
    runtime.create_agent.return_value = MagicMock()
    runtime.stream = _fake_stream

    orchestrator = AgentOrchestrator(
        skill_engine=engine,
        llm_router=MagicMock(resolve=MagicMock(return_value=LLMConfig())),
        runtime=runtime,
        sandbox=AsyncMock(),
    )

    events = [
        event
        async for event in orchestrator.handle_message(
            "query and zscore", tenant_equities, skill_bindings=skill_bindings
        )
    ]

    assert len([event for event in events if event.type == "skill_match"]) == 2
    system_prompt = runtime.create_agent.call_args.kwargs["system_prompt"]
    assert "## Active Skill: db-query" in system_prompt


@pytest.mark.asyncio
async def test_system_prompt_contains_skill_body(
    tenant_equities: TenantContext,
    skill_bindings: AgentSkillBindings,
) -> None:
    """System prompt should include the matched skill instructions."""
    skill_match = SkillSummary(
        skill_id="common/db-query",
        name="db-query",
        description="Query databases",
        tags=["database"],
    )
    engine = _mock_skill_engine([skill_match])

    runtime = MagicMock()
    runtime.create_agent.return_value = MagicMock()
    runtime.stream = _fake_stream

    orchestrator = AgentOrchestrator(
        skill_engine=engine,
        llm_router=MagicMock(resolve=MagicMock(return_value=LLMConfig())),
        runtime=runtime,
        sandbox=AsyncMock(),
    )

    _ = [
        event
        async for event in orchestrator.handle_message(
            "query data", tenant_equities, skill_bindings=skill_bindings
        )
    ]

    system_prompt = runtime.create_agent.call_args.kwargs["system_prompt"]
    assert "Active Skill: db-query" in system_prompt
    assert "Do stuff" in system_prompt


@pytest.mark.asyncio
async def test_system_prompt_contains_available_resources(
    skill_bindings: AgentSkillBindings,
) -> None:
    """System prompt should include 'Available Resources' when resource_env is populated."""
    engine = _mock_skill_engine([])

    runtime = MagicMock()
    runtime.create_agent.return_value = MagicMock()
    runtime.stream = _fake_stream

    tenant = TenantContext(
        tenant_id="equities",
        user_id="test-user",
        resource_env={
            "ch-equities": {
                "DB_HOST": "localhost",
                "DB_PORT": "8123",
            }
        },
    )

    orchestrator = AgentOrchestrator(
        skill_engine=engine,
        llm_router=MagicMock(resolve=MagicMock(return_value=LLMConfig())),
        runtime=runtime,
        sandbox=AsyncMock(),
    )

    _ = [
        event
        async for event in orchestrator.handle_message(
            "hello", tenant, skill_bindings=skill_bindings
        )
    ]

    system_prompt = runtime.create_agent.call_args.kwargs["system_prompt"]
    assert "Available Resources" in system_prompt
    assert "ch-equities" in system_prompt


@pytest.mark.asyncio
async def test_tool_filtering_by_allowed_tools() -> None:
    """Only tools listed in allowed_tools should be passed through."""
    tool_a = MagicMock()
    tool_a.name = "execute_code"
    tool_b = MagicMock()
    tool_b.name = "query_database"
    tool_c = MagicMock()
    tool_c.name = "mcp_echo"

    filtered = _filter_tools([tool_a, tool_b, tool_c], ["execute_code", "query_database"])

    assert len(filtered) == 2
    names = {tool.name for tool in filtered}
    assert "execute_code" in names
    assert "query_database" in names
    assert "mcp_echo" not in names


@pytest.mark.asyncio
async def test_handle_message_error_yields_error_event(
    tenant_equities: TenantContext,
    skill_bindings: AgentSkillBindings,
) -> None:
    """Unexpected orchestrator errors should emit ErrorEvent."""
    engine = MagicMock()
    engine.discover.return_value = []
    engine.match.side_effect = RuntimeError("engine crashed")

    orchestrator = AgentOrchestrator(
        skill_engine=engine,
        llm_router=MagicMock(),
        runtime=MagicMock(),
        sandbox=AsyncMock(),
    )

    events = [
        event
        async for event in orchestrator.handle_message(
            "test", tenant_equities, skill_bindings=skill_bindings
        )
    ]

    assert any(isinstance(event, ErrorEvent) for event in events)


@pytest.mark.asyncio
async def test_handle_message_without_mcp_manager(
    tenant_equities: TenantContext,
    skill_bindings: AgentSkillBindings,
) -> None:
    """Orchestrator should work without MCPManager configured."""
    engine = _mock_skill_engine([])
    runtime = MagicMock()
    runtime.create_agent.return_value = MagicMock()
    runtime.stream = _fake_stream

    orchestrator = AgentOrchestrator(
        skill_engine=engine,
        llm_router=MagicMock(resolve=MagicMock(return_value=LLMConfig())),
        runtime=runtime,
        sandbox=AsyncMock(),
        mcp_manager=None,
    )

    events = [
        event
        async for event in orchestrator.handle_message(
            "hello", tenant_equities, skill_bindings=skill_bindings
        )
    ]

    assert isinstance(events[-1], AgentCompleteEvent)


@pytest.mark.asyncio
async def test_handle_message_requires_skill_bindings(
    tenant_equities: TenantContext,
) -> None:
    """handle_message must require skill_bindings — omitting it is a TypeError."""
    orchestrator = AgentOrchestrator(
        skill_engine=MagicMock(),
        llm_router=MagicMock(),
        runtime=MagicMock(),
        sandbox=AsyncMock(),
    )

    with pytest.raises(TypeError):
        # noinspection PyArgumentList
        _ = [
            event
            async for event in orchestrator.handle_message("hello", tenant_equities)  # type: ignore[call-arg]
        ]


@pytest.mark.asyncio
async def test_skill_allowed_tools_present_after_assembly(
    tenant_equities: TenantContext,
    skill_bindings: AgentSkillBindings,
) -> None:
    """When a skill matches, execute_code must survive tool filtering."""
    skill_match = SkillSummary(
        skill_id="equities/zscore-monitor",
        name="zscore-monitor",
        description="Monitor z-scores",
        tags=["zscore"],
    )
    engine = _mock_skill_engine([skill_match])

    runtime = MagicMock()
    runtime.create_agent.return_value = MagicMock()
    runtime.stream = _fake_stream

    orchestrator = AgentOrchestrator(
        skill_engine=engine,
        llm_router=MagicMock(resolve=MagicMock(return_value=LLMConfig())),
        runtime=runtime,
        sandbox=AsyncMock(),
    )

    _ = [
        event
        async for event in orchestrator.handle_message(
            "z-scores for AAPL", tenant_equities, skill_bindings=skill_bindings
        )
    ]

    tools = runtime.create_agent.call_args.kwargs["tools"]
    tool_names = {getattr(t, "name", None) for t in tools}
    assert "execute_code" in tool_names


@pytest.mark.asyncio
async def test_handle_message_passes_history_to_runtime(
    tenant_equities: TenantContext,
    skill_bindings: AgentSkillBindings,
) -> None:
    """History should be forwarded to runtime.stream()."""
    engine = _mock_skill_engine([])
    runtime = MagicMock()
    runtime.create_agent.return_value = MagicMock()
    runtime.stream = _fake_stream

    orchestrator = AgentOrchestrator(
        skill_engine=engine,
        llm_router=MagicMock(resolve=MagicMock(return_value=LLMConfig())),
        runtime=runtime,
        sandbox=AsyncMock(),
    )

    fake_history = [MagicMock(), MagicMock()]
    calls = []

    async def capturing_stream(*args: Any, **kwargs: Any) -> AsyncIterator[AgentEvent]:
        calls.append((args, kwargs))
        async for event in _fake_stream(*args, **kwargs):
            yield event

    runtime.stream = capturing_stream

    _ = [
        event
        async for event in orchestrator.handle_message(
            "follow-up", tenant_equities, skill_bindings=skill_bindings, history=fake_history
        )
    ]

    assert len(calls) == 1
    _, kwargs = calls[0]
    assert kwargs.get("history") is fake_history


def test_merge_allowed_tools_unioned() -> None:
    """Merge should union allowed_tools across active skills."""
    merged = _merge_skill_contents(
        [
            _skill_content_model(skill_id="a/one", allowed_tools=["execute_code"]),
            _skill_content_model(skill_id="b/two", allowed_tools=["execute_code", "get_data"]),
        ]
    )

    assert merged["allowed_tools"] == ["execute_code", "get_data"]


def test_merge_scripts_dirs_merged(tmp_path: Path) -> None:
    """Merge should preserve all non-empty script directories in score order."""
    skill_a_scripts = tmp_path / "a_scripts"
    skill_b_scripts = tmp_path / "b_scripts"
    skill_a_scripts.mkdir()
    skill_b_scripts.mkdir()

    merged = _merge_skill_contents(
        [
            _skill_content_model(skill_id="a/one", scripts_path=str(skill_a_scripts)),
            _skill_content_model(skill_id="b/two", scripts_path=str(skill_b_scripts)),
        ]
    )

    assert merged["scripts_dirs"] == [str(skill_a_scripts), str(skill_b_scripts)]


def test_merge_highest_timeout_wins() -> None:
    """Merge should pick the maximum timeout across skills."""
    merged = _merge_skill_contents(
        [
            _skill_content_model(skill_id="a/one", timeout=60),
            _skill_content_model(skill_id="b/two", timeout=120),
        ]
    )

    assert merged["skill_timeout"] == 120


def test_merge_default_timeout_returns_none() -> None:
    """Merge should keep timeout unset when all active skills use defaults."""
    merged = _merge_skill_contents(
        [
            _skill_content_model(skill_id="a/one", timeout=60),
            _skill_content_model(skill_id="b/two", timeout=60),
        ]
    )

    assert merged["skill_timeout"] is None


def test_merge_mcp_binding_conflict_first_wins() -> None:
    """First-seen binding should win when tools are bound to different servers."""
    merged = _merge_skill_contents(
        [
            _skill_content_model(
                skill_id="a/one",
                mcp_tool_bindings=[MCPToolBinding(tool_name="get_data", server_name="server-x")],
            ),
            _skill_content_model(
                skill_id="b/two",
                mcp_tool_bindings=[MCPToolBinding(tool_name="get_data", server_name="server-y")],
            ),
        ]
    )

    assert merged["mcp_tool_bindings"] == [
        MCPToolBinding(tool_name="get_data", server_name="server-x")
    ]


def test_merge_mcp_server_name_dedup_first_seen() -> None:
    """First-seen MCP server declaration should be retained on name collision."""
    merged = _merge_skill_contents(
        [
            _skill_content_model(
                skill_id="a/one",
                mcp_servers=[
                    SkillMCPServer(name="market-data", transport="sse", url="http://a:8080/sse")
                ],
            ),
            _skill_content_model(
                skill_id="b/two",
                mcp_servers=[
                    SkillMCPServer(name="market-data", transport="sse", url="http://b:8080/sse")
                ],
            ),
        ]
    )

    server = merged["mcp_servers"][0]
    assert server.name == "market-data"
    assert server.url == "http://a:8080/sse"


def test_merge_empty_active_skills_returns_none() -> None:
    """Empty active skill list should preserve no-match behavior."""
    merged = _merge_skill_contents([])

    assert merged["allowed_tools"] is None
    assert merged["scripts_dirs"] is None
    assert merged["skill_timeout"] is None


def test_merge_script_filename_collision_warning(tmp_path: Path, caplog: Any) -> None:
    """Duplicate .py filenames across skills should emit a warning."""
    skill_a_scripts = tmp_path / "a_scripts"
    skill_b_scripts = tmp_path / "b_scripts"
    skill_a_scripts.mkdir()
    skill_b_scripts.mkdir()
    (skill_a_scripts / "utils.py").write_text("A = 1", encoding="utf-8")
    (skill_b_scripts / "utils.py").write_text("B = 2", encoding="utf-8")

    with caplog.at_level("WARNING"):
        _merge_skill_contents(
            [
                _skill_content_model(skill_id="a/one", scripts_path=str(skill_a_scripts)),
                _skill_content_model(skill_id="b/two", scripts_path=str(skill_b_scripts)),
            ]
        )

    assert "Script filename 'utils.py' exists in multiple skills" in caplog.text


def test_system_prompt_single_skill_singular_heading() -> None:
    """Single active skill should use singular heading with no composition guidance."""
    orchestrator = AgentOrchestrator(
        skill_engine=MagicMock(),
        llm_router=MagicMock(),
        runtime=MagicMock(),
        sandbox=AsyncMock(),
    )
    prompt = orchestrator._build_system_prompt(
        context=TenantContext(tenant_id="equities", user_id="test-user"),
        active_skills=[_skill_content_model(skill_id="a/one")],
        all_skills=[],
    )

    assert "## Active Skill:" in prompt
    assert "## Active Skills" not in prompt
    assert "You may combine functionality from multiple active skills" not in prompt


def test_system_prompt_multi_skill_plural_heading() -> None:
    """Multiple active skills should use plural heading and composition guidance."""
    orchestrator = AgentOrchestrator(
        skill_engine=MagicMock(),
        llm_router=MagicMock(),
        runtime=MagicMock(),
        sandbox=AsyncMock(),
    )
    prompt = orchestrator._build_system_prompt(
        context=TenantContext(tenant_id="equities", user_id="test-user"),
        active_skills=[
            _skill_content_model(skill_id="a/one"),
            _skill_content_model(skill_id="b/two"),
        ],
        all_skills=[],
    )

    assert "## Active Skills" in prompt
    assert "You may combine functionality from multiple active skills" in prompt
    assert "### Skill: one" in prompt
    assert "### Skill: two" in prompt


def test_system_prompt_no_skills_no_section() -> None:
    """No active skills should produce no active-skill prompt section."""
    orchestrator = AgentOrchestrator(
        skill_engine=MagicMock(),
        llm_router=MagicMock(),
        runtime=MagicMock(),
        sandbox=AsyncMock(),
    )
    prompt = orchestrator._build_system_prompt(
        context=TenantContext(tenant_id="equities", user_id="test-user"),
        active_skills=[],
        all_skills=[],
    )

    assert "Active Skill" not in prompt
    assert "Active Skills" not in prompt


def test_system_prompt_multi_skill_contains_both_bodies() -> None:
    """Prompt should include body content for each active skill in multi-skill mode."""
    first = _skill_content_model(skill_id="a/one")
    second = _skill_content_model(skill_id="b/two")
    orchestrator = AgentOrchestrator(
        skill_engine=MagicMock(),
        llm_router=MagicMock(),
        runtime=MagicMock(),
        sandbox=AsyncMock(),
    )
    prompt = orchestrator._build_system_prompt(
        context=TenantContext(tenant_id="equities", user_id="test-user"),
        active_skills=[first, second],
        all_skills=[],
    )

    assert first.body in prompt
    assert second.body in prompt
