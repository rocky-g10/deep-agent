#!/usr/bin/env python3
"""Invoke the Deep Agent directly from the command line — no server required.

This script wires up the full agent stack (SkillEngine, LLMRouter,
LangGraphAdapter, SandboxManager, AgentOrchestrator) and streams a single
user prompt through it.  Use it to test skills in isolation before standing
up the WebSocket API.

Usage
-----
    # Basic query (uses default "equities" agent bound to all skills):
    python scripts/invoke_agent.py "What is the 1-day 95% VaR for portfolio EQ-MACRO-1?"

    # Choose a specific agent config:
    python scripts/invoke_agent.py --agent risk-desk-agent "Show me z-scores for AAPL volume"

    # Streaming off — print final answer only:
    python scripts/invoke_agent.py --no-stream "Summarise the db-query skill"

Environment
-----------
    OPENAI_API_KEY   required — your OpenAI API key
    OPENAI_MODEL     optional — defaults to gpt-5 (set in AppSettings)
    SKILLS_ROOT      optional — path to skills directory (default: skills/)

Examples
--------
    export OPENAI_API_KEY=sk-...
    python scripts/invoke_agent.py "List all skills available to the equities agent"
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Make sure the package is importable when run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deep_agent.config import get_settings
from deep_agent.models import AgentSkillBindings, TenantContext
from deep_agent.models.events import (
    AgentChunkEvent,
    AgentCompleteEvent,
    ErrorEvent,
    InteractionRequiredEvent,
    SkillMatchEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from deep_agent.models.hitl import InteractionResponse
from deep_agent.orchestrator.agent_orchestrator import AgentOrchestrator
from deep_agent.runtime.langgraph_adapter import LangGraphAdapter
from deep_agent.runtime.llm_router import LLMRouter
from deep_agent.sandbox.subprocess_sandbox import PythonSubprocessSandbox
from deep_agent.skills.engine import SkillEngine

# ---------------------------------------------------------------------------
# Agent configs — add your own here or point --agent at a YAML file (future)
# ---------------------------------------------------------------------------

AGENT_CONFIGS: dict[str, AgentSkillBindings] = {
    "default": AgentSkillBindings(
        agent_id="default",
        bound_skill_ids=[
            "common/db-query",
            "equities/zscore-monitor",
            "risk/portfolio-var",
        ],
    ),
    "equities-agent": AgentSkillBindings(
        agent_id="equities-agent",
        bound_skill_ids=[
            "common/db-query",
            "equities/zscore-monitor",
        ],
    ),
    "risk-desk-agent": AgentSkillBindings(
        agent_id="risk-desk-agent",
        bound_skill_ids=[
            "common/db-query",
            "risk/portfolio-var",
        ],
    ),
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run(prompt: str, agent_id: str, stream: bool, interactive: bool) -> None:
    """Wire up the full stack and invoke the agent with a single prompt."""
    settings = get_settings()

    # 1. SkillEngine — discovers and loads SKILL.md files from disk
    skill_engine = SkillEngine(
        skills_root=settings.skills_root,
        cache_ttl=settings.cache_ttl_seconds,
    )

    # 2. LLMRouter — resolves which model to use (reads OPENAI_MODEL from env)
    llm_router = LLMRouter(settings)

    # 3. RuntimeAdapter — LangGraph agent loop (swap for ClaudeAgentAdapter etc.)
    runtime = LangGraphAdapter()

    # 4. SandboxManager — subprocess backend for execute_code tool
    sandbox = PythonSubprocessSandbox()

    # 5. Orchestrator — ties everything together
    orchestrator = AgentOrchestrator(
        skill_engine=skill_engine,
        llm_router=llm_router,
        runtime=runtime,
        sandbox=sandbox,
        # mcp_manager=None  # add a MCPManager here to attach MCP servers
    )

    # 6. TenantContext — identifies the tenant/user (use TenantContext.default()
    #    for local dev; populate resource_env to inject DB credentials)
    context = TenantContext(
        tenant_id="local-dev",
        user_id="developer",
        resource_env={},   # e.g. {"kdb-trading": {"KDB_HOST": "localhost", ...}}
    )

    # 7. AgentSkillBindings — controls which skills this agent can use
    bindings = AGENT_CONFIGS.get(agent_id)
    if bindings is None:
        print(f"[error] Unknown agent '{agent_id}'. Available: {list(AGENT_CONFIGS)}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  Agent : {agent_id}")
    print(f"  Prompt: {prompt}")
    print(f"{'='*60}\n")

    # 8. Stream events from the orchestrator
    current_stream = orchestrator.handle_message(
        message=prompt,
        context=context,
        skill_bindings=bindings,
    )
    while True:
        interaction_pending = False
        async for event in current_stream:
            if isinstance(event, InteractionRequiredEvent):
                interaction_pending = True
                if not interactive:
                    print(event.model_dump_json())
                    return
                response = await _prompt_interaction_response(event)
                if response is None:
                    print("[hitl] Timed out waiting for user input; exiting.")
                    return
                current_stream = orchestrator.resume_run(event.run_id, response)
                break
            _print_event(event, stream=stream)

        if not interaction_pending:
            break


def _print_event(event: object, stream: bool) -> None:
    if isinstance(event, SkillMatchEvent):
        print(f"[skill matched] {event.skill_id} (score: {event.confidence:.2f})")

    elif isinstance(event, ToolCallEvent):
        args_preview = str(event.input)[:120]
        truncated = "..." if len(str(event.input)) > 120 else ""
        print(f"\n[tool call] {event.tool}({args_preview}{truncated})")

    elif isinstance(event, ToolResultEvent):
        output_preview = event.output[:300]
        print(f"[tool result] {output_preview}{'...' if len(event.output) > 300 else ''}")
        if event.files:
            print(f"[output files] {list(event.files.keys())}")

    elif isinstance(event, AgentChunkEvent):
        if stream:
            print(event.content, end="", flush=True)

    elif isinstance(event, AgentCompleteEvent):
        if not stream:
            print(event.summary)
        else:
            print()
        print(f"\n[done] tokens used: {event.tokens_used}")

    elif isinstance(event, ErrorEvent):
        print(f"\n[error] {event.code}: {event.message}", file=sys.stderr)
        sys.exit(1)


async def _prompt_interaction_response(event: InteractionRequiredEvent) -> InteractionResponse | None:
    interaction = event.interaction
    timeout = max(interaction.timeout_seconds, 1)
    try:
        if interaction.kind == "clarify":
            print(f"\n❓ {interaction.question or 'Please clarify'}")
            if interaction.options:
                for idx, option in enumerate(interaction.options, start=1):
                    print(f"  {idx}. {option}")
            value = await _read_line_with_timeout("Your answer: ", timeout=timeout)
            if value is None:
                return _fallback_response(interaction.fallback, interaction.kind)
            return InteractionResponse(kind="clarify", value=value)

        if interaction.kind == "approve":
            print(f"\n⚠️ Action: {interaction.action_description or 'Approval required'}")
            print(f"Risk level: {interaction.risk_level or 'unknown'}")
            answer = await _read_line_with_timeout("Approve? (y/n): ", timeout=timeout)
            if answer is None:
                return _fallback_response(interaction.fallback, interaction.kind)
            approved = answer.strip().lower() in {"y", "yes"}
            return InteractionResponse(kind="approve", approved=approved, reason="")

        values: dict[str, object] = {}
        for field in interaction.fields or []:
            prompt = f"{field.name} ({field.description}): " if field.description else f"{field.name}: "
            value = await _read_line_with_timeout(prompt, timeout=timeout)
            if value is None:
                return _fallback_response(interaction.fallback, interaction.kind, fields=interaction.fields)
            values[field.name] = value
        return InteractionResponse(kind="collect", values=values)
    except KeyboardInterrupt:
        return None


async def _read_line_with_timeout(prompt: str, timeout: int) -> str | None:
    loop = asyncio.get_running_loop()
    print(prompt, end="", flush=True)
    try:
        value = await asyncio.wait_for(loop.run_in_executor(None, sys.stdin.readline), timeout=timeout)
    except TimeoutError:
        print("\n[hitl] input timed out")
        return None
    return value.rstrip("\n")


def _fallback_response(
    fallback: str,
    kind: str,
    fields: list[object] | None = None,
) -> InteractionResponse | None:
    print(f"[hitl] Applying fallback strategy: {fallback}")
    if fallback == "abort":
        return None
    if kind == "clarify":
        value = "[skipped]" if fallback == "skip" else ""
        return InteractionResponse(kind="clarify", value=value)
    if kind == "approve":
        reason = "[skipped]" if fallback == "skip" else ""
        return InteractionResponse(kind="approve", approved=False, reason=reason)
    values: dict[str, str] = {}
    for field in fields or []:
        name = getattr(field, "name", "")
        default = getattr(field, "default", None)
        values[name] = "[skipped]" if fallback == "skip" else (default or "")
    return InteractionResponse(kind="collect", values=values)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Invoke the Deep Agent in isolation with a single prompt.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("prompt", help="Natural-language prompt to send to the agent")
    parser.add_argument(
        "--agent",
        default="default",
        help="Agent config to use (default: 'default'). Options: " + ", ".join(AGENT_CONFIGS),
    )
    parser.add_argument(
        "--no-stream",
        dest="stream",
        action="store_false",
        default=True,
        help="Disable streaming — print final answer only",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        default=False,
        help="Enable interactive HITL prompts for interaction_required events",
    )
    args = parser.parse_args()

    asyncio.run(
        run(
            prompt=args.prompt,
            agent_id=args.agent,
            stream=args.stream,
            interactive=args.interactive,
        )
    )


if __name__ == "__main__":
    main()
