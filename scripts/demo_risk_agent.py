#!/usr/bin/env python3
"""
Demo: Invoke the Risk Desk Agent end-to-end.

This script shows developers how to:
  1. Seed a local SQLite database with sample portfolio + market data
  2. Boot the Deep Agent server (in-process, no external services needed)
  3. Connect via WebSocket and chat with the risk-desk-agent
  4. Stream back events (skill_match → tool_call → tool_result → agent_complete)

No real ClickHouse, no real API keys required — uses a mock LLM runtime that
executes deterministic tool calls against local SQLite.

Usage:
    # Run the interactive demo (starts server, sends questions, prints events)
    python scripts/demo_risk_agent.py

    # Or run as a pytest test (non-interactive, validates full pipeline)
    pytest scripts/demo_risk_agent.py -v
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import sqlite3
import sys
import textwrap
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 0. Ensure project root is on sys.path
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.chdir(PROJECT_ROOT)

# ---------------------------------------------------------------------------
# 1. Seed sample data — a lightweight SQLite stand-in for ClickHouse / KDB+
# ---------------------------------------------------------------------------
DB_PATH = "/tmp/portfolio.db"


def seed_database() -> None:
    """Create positions + daily_prices tables with realistic sample data."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS positions")
    cur.execute("DROP TABLE IF EXISTS daily_prices")

    cur.execute("""
        CREATE TABLE positions (
            portfolio_id TEXT,
            sym          TEXT,
            qty          REAL,
            avg_cost     REAL
        )
    """)
    cur.execute("""
        CREATE TABLE daily_prices (
            date   TEXT,
            sym    TEXT,
            close  REAL,
            volume INTEGER
        )
    """)

    # Three-stock portfolio
    positions = [
        ("EQ-MACRO-1", "AAPL", 500,  185.40),
        ("EQ-MACRO-1", "MSFT", 300,  420.10),
        ("EQ-MACRO-1", "GOOG", 200,  155.30),
        ("EQ-MACRO-1", "NVDA", 150, 880.60),
    ]
    cur.executemany("INSERT INTO positions VALUES (?, ?, ?, ?)", positions)

    # 252 trading days of synthetic prices (repeatable via seed)
    random.seed(42)
    prices = {"AAPL": 185.40, "MSFT": 420.10, "GOOG": 155.30, "NVDA": 880.60}
    rows = []
    for day in range(252):
        # Simple date string (good enough for demo)
        date_str = f"2025-{(day // 28) + 1:02d}-{(day % 28) + 1:02d}"
        for sym, px in list(prices.items()):
            ret = random.gauss(0.0005, 0.02)
            prices[sym] = round(px * (1 + ret), 2)
            vol = max(int(random.gauss(40_000_000, 12_000_000)), 500_000)
            rows.append((date_str, sym, prices[sym], vol))

    cur.executemany("INSERT INTO daily_prices VALUES (?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()
    print(f"✅ Seeded {DB_PATH} — {len(positions)} positions, {len(rows)} price rows")


# ---------------------------------------------------------------------------
# 2. Deterministic runtime — replaces the real LLM with scripted tool calls
# ---------------------------------------------------------------------------
# This lets you run the full pipeline without an OpenAI key.  In production
# you'd just set OPENAI_API_KEY and the real LLM would generate these calls.

QUERY_POSITIONS = textwrap.dedent("""\
    import sqlite3, os
    conn = sqlite3.connect(os.environ.get("DB_PATH", "/tmp/portfolio.db"))
    rows = conn.execute(
        "SELECT portfolio_id, sym, qty, avg_cost FROM positions ORDER BY sym"
    ).fetchall()
    conn.close()
    print(f"{'Portfolio':<15} {'Symbol':<8} {'Qty':>8} {'Avg Cost':>10}")
    print("-" * 45)
    total = 0.0
    for pid, sym, qty, cost in rows:
        notional = qty * cost
        total += notional
        print(f"{pid:<15} {sym:<8} {qty:>8.0f} ${cost:>9.2f}")
    print("-" * 45)
    print(f"Total notional: ${total:,.2f}")
""")

COMPUTE_VAR = textwrap.dedent("""\
    import sqlite3, os, math, random

    conn = sqlite3.connect(os.environ.get("DB_PATH", "/tmp/portfolio.db"))
    positions = conn.execute("SELECT sym, qty, avg_cost FROM positions WHERE portfolio_id='EQ-MACRO-1'").fetchall()
    prices = {}
    for sym, qty, cost in positions:
        rows = conn.execute("SELECT close FROM daily_prices WHERE sym=? ORDER BY date", (sym,)).fetchall()
        prices[sym] = [r[0] for r in rows]
    conn.close()

    # Historical simulation VaR
    n_days = min(len(v) for v in prices.values())
    pnl_dist = []
    for i in range(1, n_days):
        daily_pnl = 0.0
        for sym, qty, cost in positions:
            px = prices[sym]
            ret = (px[i] - px[i-1]) / px[i-1]
            daily_pnl += qty * px[i] * ret
        pnl_dist.append(daily_pnl)

    pnl_dist.sort()
    confidence = 0.95
    var_idx = int(len(pnl_dist) * (1 - confidence))
    var_95 = abs(pnl_dist[var_idx])
    es = abs(sum(pnl_dist[:var_idx]) / max(var_idx, 1))

    total_notional = sum(qty * cost for _, qty, cost in positions)
    print(f"Portfolio:          EQ-MACRO-1")
    print(f"Positions:          {len(positions)} stocks")
    print(f"Total Notional:     ${total_notional:,.2f}")
    print(f"Confidence:         {confidence:.0%}")
    print(f"Horizon:            1 day")
    print(f"1-Day 95% VaR:      ${var_95:,.2f}")
    print(f"Expected Shortfall: ${es:,.2f}")
    print(f"VaR / Notional:     {var_95/total_notional*100:.2f}%")
    print(f"Simulations:        {len(pnl_dist)} historical days")
""")

# Map user questions → the code the "LLM" would generate
SCRIPTED_RESPONSES: dict[str, tuple[str, str]] = {
    "positions": (
        QUERY_POSITIONS,
        "Here are the current positions in portfolio EQ-MACRO-1.",
    ),
    "var": (
        COMPUTE_VAR,
        "Computed 1-day 95% VaR using historical simulation over 252 trading days.",
    ),
}


class DemoRuntime:
    """Drop-in runtime that maps keywords to scripted tool calls."""

    def create_agent(self, model: str, tools: list[Any], system_prompt: str, **kw: Any) -> dict:
        return {"tools": tools}

    async def stream(
        self,
        agent: dict[str, Any],
        message: str,
        context: Any,
        history: list[Any] | None = None,
    ):
        from deep_agent.models.events import (
            AgentChunkEvent,
            AgentCompleteEvent,
            ToolCallEvent,
            ToolResultEvent,
        )

        # Pick the scripted response based on keyword matching
        key = "positions"  # default
        msg_lower = message.lower()
        if any(w in msg_lower for w in ("var", "risk", "value at risk")):
            key = "var"

        code, summary = SCRIPTED_RESPONSES[key]

        # Find the execute_code tool
        tool = next(
            (t for t in agent["tools"] if getattr(t, "name", "") == "execute_code"),
            None,
        )
        assert tool, "execute_code tool not found — check skill allowed-tools"

        yield ToolCallEvent(tool="execute_code", input={"code": code})

        raw_result = await tool.ainvoke({"code": code})
        parsed = json.loads(raw_result)
        output = parsed.get("stdout") or parsed.get("stderr") or "(no output)"

        yield ToolResultEvent(tool="execute_code", output=output, files=parsed.get("output_files", {}))
        yield AgentChunkEvent(content=summary)
        yield AgentCompleteEvent(summary=summary, tokens_used=0)


# ---------------------------------------------------------------------------
# 3. Build the app with real skill engine + sandbox, mock runtime
# ---------------------------------------------------------------------------

def build_demo_app():
    """Wire up the full Deep Agent app using the risk tenant + agent config."""
    from deep_agent.api.app import create_app
    from deep_agent.api.config_loader import build_tenant_context, load_agent_bindings
    from deep_agent.config import AppSettings

    settings = AppSettings(
        OPENAI_API_KEY="sk-demo-not-needed",  # type: ignore[arg-type]
        SKILLS_ROOT=PROJECT_ROOT / "skills",
    )

    config_root = PROJECT_ROOT / "config"

    app = create_app(
        settings=settings,
        config_root=config_root,
        runtime=DemoRuntime(),
    )

    # Resolve tenant + agent
    tenant = build_tenant_context("risk", config_root=config_root)
    bindings = load_agent_bindings("risk-desk-agent", config_root=config_root)
    assert bindings is not None, (
        "Could not load risk-desk-agent bindings — "
        "check config/agents/risk-desk-agent.yaml exists"
    )

    return app, tenant, bindings


# ---------------------------------------------------------------------------
# 4. WebSocket test double (same pattern used in tests/)
# ---------------------------------------------------------------------------

from fastapi import WebSocketDisconnect  # noqa: E402


class FakeWebSocket:
    """Captures sent events without a real socket connection."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.sent_texts: list[str] = []

    async def accept(self) -> None:
        pass

    async def send_text(self, text: str) -> None:
        self.sent_texts.append(text)

    async def receive_text(self) -> str:
        raise WebSocketDisconnect()


# ---------------------------------------------------------------------------
# 5. Core demo function — send a question, stream events
# ---------------------------------------------------------------------------

async def ask_agent(question: str) -> list[dict]:
    """Send a question to the risk-desk-agent and return all streamed events."""
    from deep_agent.api.ws_chat import _handle_client_message

    app, tenant, bindings = build_demo_app()

    # Inject resource env so sandbox picks up DB_PATH
    tenant.resource_env["mock-portfolio-db"] = {
        "DB_PATH": DB_PATH,
        "DB_ENGINE": "sqlite",
    }
    # Also set as flat env (some sandbox impls read from flat env)
    os.environ["DB_PATH"] = DB_PATH

    session = app.state.session_manager.create(tenant=tenant, bindings=bindings)
    ws = FakeWebSocket(app)

    await _handle_client_message(
        raw=json.dumps({
            "type": "user_message",
            "content": question,
            "session_id": session.session_id,
        }),
        websocket=ws,
        orchestrator=app.state.orchestrator,
        session_manager=app.state.session_manager,
        session_id=session.session_id,
    )

    events = [json.loads(t) for t in ws.sent_texts]
    return events


def print_events(events: list[dict]) -> None:
    """Pretty-print streamed events to the console."""
    for ev in events:
        etype = ev.get("type", "unknown")

        if etype == "skill_match":
            print(f"\n🎯 Skill matched: {ev.get('skill_id', '?')}")
            print(f"   Score: {ev.get('score', '?')}")

        elif etype == "tool_call":
            tool = ev.get("tool", "?")
            print(f"\n🔧 Tool call: {tool}")
            code = ev.get("input", {}).get("code", "")
            # Show first 5 lines of code
            lines = code.strip().split("\n")[:5]
            for line in lines:
                print(f"   │ {line}")
            if len(code.strip().split("\n")) > 5:
                print(f"   │ ... ({len(code.strip().split(chr(10)))} lines total)")

        elif etype == "tool_result":
            print(f"\n📊 Result:")
            for line in ev.get("output", "").strip().split("\n"):
                print(f"   {line}")

        elif etype == "agent_chunk":
            print(f"\n💬 {ev.get('content', '')}")

        elif etype == "agent_complete":
            print(f"\n✅ Complete — {ev.get('summary', '')}")

        elif etype == "error":
            print(f"\n❌ Error [{ev.get('code')}]: {ev.get('message')}")

        else:
            print(f"\n📎 {etype}: {json.dumps(ev, indent=2)[:200]}")


# ---------------------------------------------------------------------------
# 6. Interactive demo runner
# ---------------------------------------------------------------------------

async def run_demo() -> None:
    """Run two demo questions through the risk agent."""
    seed_database()

    print("\n" + "=" * 60)
    print("  Deep Agent — Risk Desk Agent Demo")
    print("=" * 60)

    # Question 1: Show positions
    print("\n" + "-" * 60)
    print("👤 User: Show me the positions in portfolio EQ-MACRO-1")
    print("-" * 60)
    events = await ask_agent("Show me the positions in portfolio EQ-MACRO-1")
    print_events(events)

    # Question 2: Compute VaR
    print("\n\n" + "-" * 60)
    print("👤 User: What's the 1-day 95% VaR for portfolio EQ-MACRO-1?")
    print("-" * 60)
    events = await ask_agent("What's the 1-day 95% VaR for portfolio EQ-MACRO-1?")
    print_events(events)

    print("\n" + "=" * 60)
    print("  Demo complete!")
    print("=" * 60)
    print()
    print("To run with a real LLM, set OPENAI_API_KEY and use:")
    print("  python scripts/run_dev.py")
    print()
    print("Then connect via WebSocket:")
    print("  wscat -c 'ws://localhost:8000/ws/chat?tenant_id=risk&agent_id=risk-desk-agent'")
    print()


# ---------------------------------------------------------------------------
# 7. Pytest entry points (run with: pytest scripts/demo_risk_agent.py -v)
# ---------------------------------------------------------------------------

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _seed():
    seed_database()


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_positions_query():
    """Risk agent can list portfolio positions via SQLite."""
    events = await ask_agent("Show me portfolio positions")
    types = [e["type"] for e in events]

    assert "tool_call" in types, f"Expected tool_call, got: {types}"
    assert "tool_result" in types, f"Expected tool_result, got: {types}"
    assert "agent_complete" in types

    result = next(e for e in events if e["type"] == "tool_result")
    assert "AAPL" in result["output"], f"Expected AAPL in output: {result['output'][:200]}"
    assert "NVDA" in result["output"], f"Expected NVDA in output: {result['output'][:200]}"


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_var_computation():
    """Risk agent can compute historical VaR for a portfolio."""
    events = await ask_agent("What is the 1-day 95% VaR for EQ-MACRO-1?")
    types = [e["type"] for e in events]

    assert "tool_call" in types
    assert "tool_result" in types
    assert "agent_complete" in types

    result = next(e for e in events if e["type"] == "tool_result")
    output = result["output"]
    assert "VaR" in output, f"Expected VaR in output: {output[:300]}"
    assert "EQ-MACRO-1" in output
    assert "95%" in output


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_event_ordering():
    """Events arrive in correct order: tool_call → tool_result → chunk → complete."""
    events = await ask_agent("positions")
    types = [e["type"] for e in events]

    tc_idx = types.index("tool_call")
    tr_idx = types.index("tool_result")
    ac_idx = types.index("agent_complete")
    assert tc_idx < tr_idx < ac_idx, f"Wrong order: {types}"


# ---------------------------------------------------------------------------
# 8. __main__ — run the interactive demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(run_demo())
