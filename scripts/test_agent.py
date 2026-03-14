#!/usr/bin/env python3
"""Test the Deep Agent end-to-end with a simple invoke call.

Usage:
    # Basic — uses default skill (db-query) and model (from .env or OPENAI_MODEL)
    python scripts/test_agent.py "What tables are available in the database?"

    # Specify a skill to test
    python scripts/test_agent.py --skill equities/zscore-monitor "Show z-scores for AAPL volume"

    # Stream mode (see tokens as they arrive)
    python scripts/test_agent.py --stream "What is the 1-day 95% VaR for portfolio EQ-MACRO-1?"

    # Override model
    OPENAI_MODEL=gpt-4.1 python scripts/test_agent.py "Hello"

    # With tenant resource env vars (simulates sandbox environment)
    python scripts/test_agent.py \\
        --resource "kdb-trading:KDB_HOST=localhost,KDB_PORT=5000" "Show positions"

Prerequisites:
    - OPENAI_API_KEY set in environment or .env file
    - Skills exist under skills/ directory
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure the project root is on sys.path for local development
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from deep_agent.config import AppSettings
from deep_agent.models import TenantContext
from deep_agent.models.events import (
    AgentChunkEvent,
    AgentCompleteEvent,
    ErrorEvent,
    SkillMatchEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from deep_agent.models.skills import AgentSkillBindings
from deep_agent.orchestrator.agent_orchestrator import AgentOrchestrator
from deep_agent.runtime.langgraph_adapter import LangGraphAdapter
from deep_agent.runtime.llm_router import LLMRouter
from deep_agent.sandbox.subprocess_sandbox import PythonSubprocessSandbox
from deep_agent.skills.engine import SkillEngine


def parse_resource_args(raw: list[str] | None) -> dict[str, dict[str, str]]:
    """Parse --resource flags into resource_env dict.

    Format: "alias:KEY1=val1,KEY2=val2"
    Example: "kdb-trading:KDB_HOST=localhost,KDB_PORT=5000"
    """
    if not raw:
        return {}
    result: dict[str, dict[str, str]] = {}
    for entry in raw:
        alias, _, kv_str = entry.partition(":")
        if not alias or not kv_str:
            print(f"⚠️  Skipping malformed --resource: {entry!r} (expected alias:KEY=val,...)")
            continue
        env_vars: dict[str, str] = {}
        for pair in kv_str.split(","):
            key, _, val = pair.partition("=")
            if key and val:
                env_vars[key.strip()] = val.strip()
        result[alias.strip()] = env_vars
    return result


def discover_skills(skills_root: Path) -> list[str]:
    """Find all skill IDs under the skills root."""
    skill_ids = []
    for skill_file in sorted(skills_root.rglob("SKILL.md")):
        rel = skill_file.parent.relative_to(skills_root)
        skill_ids.append(str(rel))
    return skill_ids


async def run_invoke(
    prompt: str,
    skill_ids: list[str],
    settings: AppSettings,
    resource_env: dict[str, dict[str, str]],
    stream: bool = False,
) -> None:
    """Run a single agent invocation and print results."""
    # --- 1. Build components ---
    skill_engine = SkillEngine(
        skills_root=settings.skills_root,
        cache_ttl=0,  # No caching for test script
    )
    llm_router = LLMRouter(settings)
    runtime = LangGraphAdapter()
    sandbox = PythonSubprocessSandbox()

    orchestrator = AgentOrchestrator(
        skill_engine=skill_engine,
        llm_router=llm_router,
        runtime=runtime,
        sandbox=sandbox,
    )

    # --- 2. Build context ---
    context = TenantContext(
        tenant_id="test",
        user_id="test-user",
        resource_env=resource_env,
    )
    bindings = AgentSkillBindings(
        agent_id="test-agent",
        bound_skill_ids=tuple(skill_ids),
    )

    # --- 3. Invoke and print events ---
    print(f"\n{'─' * 60}")
    print(f"  Prompt:  {prompt}")
    print(f"  Model:   {settings.openai_model}")
    print(f"  Skills:  {', '.join(skill_ids) or '(none)'}")
    print(f"{'─' * 60}\n")

    async for event in orchestrator.handle_message(prompt, context, bindings):
        if isinstance(event, SkillMatchEvent):
            print(f"🎯 Skill matched: {event.skill_id} (confidence: {event.confidence:.2f})")
            print()

        elif isinstance(event, ToolCallEvent):
            print(f"🔧 Tool call: {event.tool}")
            if event.input:
                # Truncate long code blocks for readability
                for key, val in event.input.items():
                    val_str = str(val)
                    if len(val_str) > 200:
                        val_str = val_str[:200] + "..."
                    print(f"   {key}: {val_str}")
            print()

        elif isinstance(event, ToolResultEvent):
            output = event.output
            if len(output) > 500:
                output = output[:500] + f"\n   ... ({len(event.output)} chars total)"
            print(f"📤 Tool result ({event.tool}):")
            for line in output.split("\n"):
                print(f"   {line}")
            if event.files:
                print(f"   📎 Files: {', '.join(event.files.keys())}")
            print()

        elif isinstance(event, AgentChunkEvent):
            if stream:
                print(event.content, end="", flush=True)
            # In non-stream mode, we collect chunks and print at AgentComplete

        elif isinstance(event, AgentCompleteEvent):
            if stream:
                print()  # Newline after streaming chunks
            else:
                print("💬 Agent response:")
                print(event.summary)
            print()
            print(f"📊 Tokens used: {event.tokens_used}")

        elif isinstance(event, ErrorEvent):
            print(f"❌ Error [{event.code}]: {event.message}")

    print(f"\n{'─' * 60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test Deep Agent with a single prompt — no server required.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Query with all skills available
  python scripts/test_agent.py "Show me AAPL fundamentals"

  # Test a specific skill
  python scripts/test_agent.py --skill risk/portfolio-var "What's the VaR for EQ-MACRO-1?"

  # Stream tokens as they arrive
  python scripts/test_agent.py --stream "Explain z-scores"

  # With simulated database env vars
  python scripts/test_agent.py \\
    --resource "ch-equities:DB_HOST=localhost,DB_PORT=8123" \\
    "Show top 10 stocks by volume"
        """,
    )
    parser.add_argument("prompt", help="User prompt to send to the agent")
    parser.add_argument(
        "--skill",
        action="append",
        dest="skills",
        help="Bind a specific skill (repeatable). Default: all discovered skills.",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Stream tokens as they arrive (default: print complete response)",
    )
    parser.add_argument(
        "--resource",
        action="append",
        dest="resources",
        help='Inject resource env vars. Format: "alias:KEY=val,KEY2=val2"',
    )

    args = parser.parse_args()

    # Load settings from .env / environment
    settings = AppSettings()  # type: ignore[call-arg]

    # Resolve skills
    if args.skills:
        skill_ids = args.skills
    else:
        skill_ids = discover_skills(settings.skills_root)
        if not skill_ids:
            print("⚠️  No skills found under", settings.skills_root)
            print("   Create a skill: skills/<domain>/<name>/SKILL.md")
            sys.exit(1)

    resource_env = parse_resource_args(args.resources)

    asyncio.run(run_invoke(
        prompt=args.prompt,
        skill_ids=skill_ids,
        settings=settings,
        resource_env=resource_env,
        stream=args.stream,
    ))


if __name__ == "__main__":
    main()
