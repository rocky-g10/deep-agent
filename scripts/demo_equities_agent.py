#!/usr/bin/env python3
"""
Demo: Invoke the Equities Desk Agent — Chat with a Trade Database.

This script shows developers how to:
  1. Seed a local SQLite database with realistic trade execution data
     (mimicking a ClickHouse equities trade database)
  2. Boot the Deep Agent server in-process
  3. Ask natural-language questions about trades, slippage, fill rates, etc.
  4. Stream back events showing SQL generation → execution → formatted results
  5. **Multi-skill composition** — a cross-domain query activates both
     trade-analytics and zscore-monitor skills in a single request,
     demonstrating multi-skill matching and merged execution

The seed data includes:
  - 5,000+ trade executions across 8 symbols, 4 algos, 3 desks, 5 brokers
  - Market data (daily OHLCV + VWAP) for benchmark calculations
  - Realistic patterns: dark pool routing, partial fills, venue distribution

No ClickHouse or API keys required — uses SQLite + mock LLM runtime.

Usage:
    # Interactive demo (6 questions, pretty-printed)
    python scripts/demo_equities_agent.py

    # As pytest (validates full pipeline incl. multi-skill)
    pytest scripts/demo_equities_agent.py -v
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import sqlite3
import sys
import textwrap
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 0. Project setup
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.chdir(PROJECT_ROOT)

DB_PATH = "/tmp/equities_trades.db"

# ---------------------------------------------------------------------------
# 1. Seed realistic trade data
# ---------------------------------------------------------------------------

SYMBOLS = ["AAPL", "MSFT", "GOOG", "NVDA", "AMZN", "META", "TSLA", "JPM"]
ALGOS = ["TWAP", "VWAP", "IS", "DMA"]
DESKS = ["eq-cash", "eq-derivs", "eq-etf"]
BROKERS = ["GS", "MS", "JPM", "BAML", "UBS"]
VENUES = ["XNYS", "XNAS", "ARCX", "BATS", "dark"]
TRADERS = ["alice", "bob", "carol", "dave", "eve"]
SIDES = ["buy", "sell", "short_sell"]


def seed_database() -> None:
    """Create trades + market_data_daily tables with ~5000 realistic executions."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS trades")
    cur.execute("DROP TABLE IF EXISTS market_data_daily")

    cur.execute("""
        CREATE TABLE trades (
            trade_id        TEXT,
            order_id        TEXT,
            trade_date      TEXT,
            trade_time      TEXT,
            symbol          TEXT,
            side            TEXT,
            qty             INTEGER,
            price           REAL,
            order_qty       INTEGER,
            algo            TEXT,
            trader          TEXT,
            desk            TEXT,
            broker          TEXT,
            venue           TEXT,
            is_dark         INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE market_data_daily (
            symbol TEXT,
            date   TEXT,
            open   REAL,
            high   REAL,
            low    REAL,
            close  REAL,
            vwap   REAL,
            volume INTEGER,
            adv_20d REAL
        )
    """)

    random.seed(2026)

    # Base prices for each symbol
    base_prices = {
        "AAPL": 192.50, "MSFT": 430.20, "GOOG": 168.40, "NVDA": 920.80,
        "AMZN": 205.60, "META": 580.30, "TSLA": 245.10, "JPM": 215.70,
    }

    # Generate 20 trading days
    start_date = datetime(2026, 2, 24)
    trading_days = []
    d = start_date
    while len(trading_days) < 20:
        if d.weekday() < 5:  # Mon–Fri
            trading_days.append(d)
        d += timedelta(days=1)

    market_rows = []
    trade_rows = []

    for day in trading_days:
        date_str = day.strftime("%Y-%m-%d")

        for sym in SYMBOLS:
            px = base_prices[sym]

            # Daily price action
            daily_ret = random.gauss(0.001, 0.018)
            open_px = round(px * (1 + random.gauss(0, 0.003)), 2)
            close_px = round(px * (1 + daily_ret), 2)
            high_px = round(max(open_px, close_px) * (1 + abs(random.gauss(0, 0.005))), 2)
            low_px = round(min(open_px, close_px) * (1 - abs(random.gauss(0, 0.005))), 2)
            mkt_vwap = round((open_px + high_px + low_px + close_px) / 4, 2)
            volume = int(random.gauss(45_000_000, 15_000_000))
            volume = max(volume, 5_000_000)
            adv_20d = volume * random.uniform(0.85, 1.15)

            base_prices[sym] = close_px

            market_rows.append((sym, date_str, open_px, high_px, low_px,
                                close_px, mkt_vwap, volume, round(adv_20d)))

            # Generate 25-40 trade executions per symbol per day
            n_orders = random.randint(5, 10)
            for _ in range(n_orders):
                order_id = str(uuid.uuid4())[:12]
                side = random.choices(SIDES, weights=[45, 45, 10])[0]
                algo = random.choice(ALGOS)
                trader = random.choice(TRADERS)
                desk = random.choice(DESKS)
                broker = random.choice(BROKERS)
                order_qty = random.choice([500, 1000, 2000, 5000, 10000, 25000])

                # Split into 2-6 child fills
                n_fills = random.randint(2, 6)
                remaining = order_qty
                for fill_i in range(n_fills):
                    if fill_i == n_fills - 1:
                        # Partial fill ~80% of the time
                        if random.random() < 0.80:
                            fill_qty = remaining
                        else:
                            fill_qty = int(remaining * random.uniform(0.3, 0.9))
                    else:
                        fill_qty = int(remaining * random.uniform(0.15, 0.45))
                    fill_qty = max(fill_qty, 100)
                    if fill_qty > remaining:
                        fill_qty = remaining
                    remaining -= fill_qty
                    if fill_qty <= 0:
                        break

                    # Execution price: market VWAP + slippage (algo-dependent)
                    slippage_map = {"TWAP": 0.0003, "VWAP": 0.0001, "IS": 0.0005, "DMA": 0.0008}
                    slip = random.gauss(slippage_map[algo], 0.0004)
                    direction = 1 if side == "buy" else -1
                    exec_price = round(mkt_vwap * (1 + direction * slip), 2)

                    venue = random.choices(
                        VENUES, weights=[30, 25, 15, 15, 15]
                    )[0]
                    is_dark = 1 if venue == "dark" else 0

                    # Random time during trading hours
                    hour = random.randint(9, 15)
                    minute = random.randint(0, 59)
                    second = random.randint(0, 59)
                    ms = random.randint(0, 999)
                    trade_time = f"{date_str} {hour:02d}:{minute:02d}:{second:02d}.{ms:03d}"

                    trade_rows.append((
                        str(uuid.uuid4())[:12], order_id, date_str, trade_time,
                        sym, side, fill_qty, exec_price, order_qty,
                        algo, trader, desk, broker, venue, is_dark,
                    ))

    cur.executemany(
        "INSERT INTO market_data_daily VALUES (?,?,?,?,?,?,?,?,?)", market_rows
    )
    cur.executemany(
        "INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", trade_rows
    )

    # Create indexes for fast queries
    cur.execute("CREATE INDEX idx_trades_date ON trades(trade_date)")
    cur.execute("CREATE INDEX idx_trades_symbol ON trades(symbol)")
    cur.execute("CREATE INDEX idx_trades_trader ON trades(trader)")
    cur.execute("CREATE INDEX idx_mkt_date ON market_data_daily(date, symbol)")

    conn.commit()

    trade_count = cur.execute("SELECT count(*) FROM trades").fetchone()[0]
    order_count = cur.execute("SELECT count(DISTINCT order_id) FROM trades").fetchone()[0]
    conn.close()

    print(f"✅ Seeded {DB_PATH}")
    print(f"   {trade_count:,} executions across {order_count:,} orders")
    print(f"   {len(SYMBOLS)} symbols × {len(trading_days)} trading days")
    print(f"   {len(market_rows)} market data rows")


# ---------------------------------------------------------------------------
# 2. Scripted queries — what the LLM would generate
# ---------------------------------------------------------------------------

Q_TOP_SYMBOLS = textwrap.dedent("""\
    import sqlite3, os
    conn = sqlite3.connect(os.environ.get("DB_PATH", "/tmp/equities_trades.db"))
    cur = conn.cursor()

    sql = '''
    SELECT
        symbol,
        CAST(sum(qty * price) AS INTEGER) AS notional,
        count(DISTINCT order_id) AS orders,
        sum(qty) AS total_shares,
        count(*) AS fills
    FROM trades
    GROUP BY symbol
    ORDER BY notional DESC
    LIMIT 10
    '''
    print("SQL: " + sql.strip().replace(chr(10), ' '))
    print()

    rows = cur.execute(sql).fetchall()
    conn.close()

    print(f"{'Symbol':<8} {'Notional':>14} {'Orders':>8} {'Shares':>12} {'Fills':>8}")
    print("-" * 54)
    for sym, notional, orders, shares, fills in rows:
        print(f"{sym:<8} ${notional:>13,} {orders:>8,} {shares:>12,} {fills:>8,}")
""")

Q_SLIPPAGE_BY_ALGO = textwrap.dedent("""\
    import sqlite3, os
    conn = sqlite3.connect(os.environ.get("DB_PATH", "/tmp/equities_trades.db"))
    cur = conn.cursor()

    sql = '''
    SELECT
        t.algo,
        count(*) AS fills,
        sum(t.qty) AS shares,
        CAST(sum(t.qty * t.price) AS INTEGER) AS notional,
        round(sum(t.qty * t.price) / sum(t.qty), 4) AS exec_vwap,
        round(avg(md.vwap), 4) AS mkt_vwap,
        round(
            avg(
                CASE WHEN t.side = 'buy' THEN 1 ELSE -1 END
                * (t.price - md.vwap) / md.vwap * 10000
            ), 2
        ) AS avg_slippage_bps
    FROM trades t
    JOIN market_data_daily md ON md.symbol = t.symbol AND md.date = t.trade_date
    GROUP BY t.algo
    ORDER BY avg_slippage_bps ASC
    '''
    print("SQL: " + ' '.join(sql.split()))
    print()

    rows = cur.execute(sql).fetchall()
    conn.close()

    print(f"{'Algo':<8} {'Fills':>8} {'Shares':>10} {'Notional':>14} {'Exec VWAP':>11} {'Mkt VWAP':>10} {'Slip (bps)':>11}")
    print("-" * 78)
    for algo, fills, shares, notional, evwap, mvwap, slip in rows:
        print(f"{algo:<8} {fills:>8,} {shares:>10,} ${notional:>13,} {evwap:>11.4f} {mvwap:>10.4f} {slip:>+11.2f}")
""")

Q_TRADER_LEADERBOARD = textwrap.dedent("""\
    import sqlite3, os
    conn = sqlite3.connect(os.environ.get("DB_PATH", "/tmp/equities_trades.db"))
    cur = conn.cursor()

    sql = '''
    SELECT
        t.trader,
        count(DISTINCT t.order_id) AS orders,
        count(*) AS fills,
        CAST(sum(t.qty * t.price) AS INTEGER) AS notional,
        round(
            avg(
                CASE WHEN t.side = 'buy' THEN 1 ELSE -1 END
                * (t.price - md.vwap) / md.vwap * 10000
            ), 2
        ) AS avg_slippage_bps,
        round(
            CAST(sum(CASE WHEN t.venue = 'dark' THEN t.qty ELSE 0 END) AS REAL)
            / sum(t.qty) * 100, 1
        ) AS dark_pct
    FROM trades t
    JOIN market_data_daily md ON md.symbol = t.symbol AND md.date = t.trade_date
    GROUP BY t.trader
    ORDER BY avg_slippage_bps ASC
    '''
    print("SQL: " + ' '.join(sql.split()))
    print()

    rows = cur.execute(sql).fetchall()
    conn.close()

    print(f"{'Trader':<10} {'Orders':>8} {'Fills':>8} {'Notional':>14} {'Slip (bps)':>11} {'Dark %':>8}")
    print("-" * 63)
    for trader, orders, fills, notional, slip, dark in rows:
        print(f"{trader:<10} {orders:>8,} {fills:>8,} ${notional:>13,} {slip:>+11.2f} {dark:>7.1f}%")
""")

Q_DARK_POOL_TREND = textwrap.dedent("""\
    import sqlite3, os
    conn = sqlite3.connect(os.environ.get("DB_PATH", "/tmp/equities_trades.db"))
    cur = conn.cursor()

    sql = '''
    SELECT
        trade_date,
        sum(CASE WHEN is_dark = 1 THEN qty ELSE 0 END) AS dark_volume,
        sum(qty) AS total_volume,
        round(
            CAST(sum(CASE WHEN is_dark = 1 THEN qty ELSE 0 END) AS REAL)
            / sum(qty) * 100, 1
        ) AS dark_pct
    FROM trades
    GROUP BY trade_date
    ORDER BY trade_date
    '''
    print("SQL: " + ' '.join(sql.split()))
    print()

    rows = cur.execute(sql).fetchall()
    conn.close()

    print(f"{'Date':<12} {'Dark Vol':>12} {'Total Vol':>12} {'Dark %':>8}")
    print("-" * 48)
    for date, dark, total, pct in rows:
        bar = "█" * int(pct / 2)
        print(f"{date:<12} {dark:>12,} {total:>12,} {pct:>7.1f}% {bar}")
""")

Q_BROKER_SCORECARD = textwrap.dedent("""\
    import sqlite3, os
    conn = sqlite3.connect(os.environ.get("DB_PATH", "/tmp/equities_trades.db"))
    cur = conn.cursor()

    sql = '''
    SELECT
        t.broker,
        count(*) AS fills,
        count(DISTINCT t.symbol) AS symbols,
        CAST(sum(t.qty * t.price) AS INTEGER) AS notional,
        round(
            avg(
                CASE WHEN t.side = 'buy' THEN 1 ELSE -1 END
                * (t.price - md.vwap) / md.vwap * 10000
            ), 2
        ) AS avg_slippage_bps,
        round(avg(t.qty), 0) AS avg_fill_size,
        round(
            CAST(sum(CASE WHEN t.venue = 'dark' THEN t.qty ELSE 0 END) AS REAL)
            / sum(t.qty) * 100, 1
        ) AS dark_pct
    FROM trades t
    JOIN market_data_daily md ON md.symbol = t.symbol AND md.date = t.trade_date
    GROUP BY t.broker
    ORDER BY avg_slippage_bps ASC
    '''
    print("SQL: " + ' '.join(sql.split()))
    print()

    rows = cur.execute(sql).fetchall()
    conn.close()

    print(f"{'Broker':<8} {'Fills':>8} {'Syms':>6} {'Notional':>14} {'Slip (bps)':>11} {'Avg Fill':>10} {'Dark %':>8}")
    print("-" * 71)
    for broker, fills, syms, notional, slip, avg_fill, dark in rows:
        print(f"{broker:<8} {fills:>8,} {syms:>6} ${notional:>13,} {slip:>+11.2f} {avg_fill:>10,.0f} {dark:>7.1f}%")
""")

Q_MULTI_SKILL_VWAP_ZSCORE = textwrap.dedent("""\
    import sqlite3, os, math
    conn = sqlite3.connect(os.environ.get("DB_PATH", "/tmp/equities_trades.db"))
    cur = conn.cursor()

    # ── Part 1: VWAP slippage by algorithm (trade-analytics) ─────────
    slip_sql = '''
    SELECT
        t.algo,
        count(*) AS fills,
        round(
            avg(
                CASE WHEN t.side = 'buy' THEN 1 ELSE -1 END
                * (t.price - md.vwap) / md.vwap * 10000
            ), 2
        ) AS avg_slippage_bps
    FROM trades t
    JOIN market_data_daily md ON md.symbol = t.symbol AND md.date = t.trade_date
    GROUP BY t.algo
    ORDER BY avg_slippage_bps ASC
    '''
    print("SQL (slippage): " + ' '.join(slip_sql.split()))
    print()
    slip_rows = cur.execute(slip_sql).fetchall()

    print(f"{'Algo':<8} {'Fills':>8} {'Slip (bps)':>11}")
    print("-" * 30)
    for algo, fills, slip in slip_rows:
        print(f"{algo:<8} {fills:>8,} {slip:>+11.2f}")

    # ── Part 2: z-score outliers on volume (zscore-monitor) ──────────
    vol_sql = '''
    SELECT symbol, date, volume FROM market_data_daily ORDER BY symbol, date
    '''
    vol_rows = cur.execute(vol_sql).fetchall()
    conn.close()

    from collections import defaultdict
    by_sym = defaultdict(list)
    for sym, dt, vol in vol_rows:
        by_sym[sym].append((dt, vol))

    print()
    print(f"{'Symbol':<8} {'Last Date':<12} {'Volume':>12} {'Z-Score':>9} {'Flag':>8}")
    print("-" * 53)
    for sym in sorted(by_sym):
        entries = by_sym[sym]
        volumes = [v for _, v in entries]
        if len(volumes) < 2:
            continue
        mean = sum(volumes) / len(volumes)
        std = math.sqrt(sum((v - mean) ** 2 for v in volumes) / (len(volumes) - 1))
        if std == 0:
            std = 1e-9
        last_date, last_vol = entries[-1]
        z = (last_vol - mean) / std
        flag = "OUTLIER" if abs(z) > 2.0 else ""
        print(f"{sym:<8} {last_date:<12} {last_vol:>12,} {z:>+9.2f} {flag:>8}")
""")

# Question → (code, summary)
SCRIPTED: dict[str, tuple[str, str]] = {
    "top_symbols": (
        Q_TOP_SYMBOLS,
        "Top symbols ranked by notional value traded across all desks.",
    ),
    "slippage": (
        Q_SLIPPAGE_BY_ALGO,
        "VWAP slippage breakdown by algorithm. VWAP and IS algos show"
        " tighter execution; DMA has wider slippage as expected.",
    ),
    "trader": (
        Q_TRADER_LEADERBOARD,
        "Trader leaderboard ranked by average slippage. Lower (more"
        " negative for sells / closer to zero for buys) is better.",
    ),
    "dark": (
        Q_DARK_POOL_TREND,
        "Daily dark pool utilization over the past 20 trading days."
        " Bar chart shows percentage of volume routed to dark venues.",
    ),
    "broker": (
        Q_BROKER_SCORECARD,
        "Broker scorecard comparing execution quality, fill sizes,"
        " and dark pool routing across all 5 brokers.",
    ),
    "multi_skill": (
        Q_MULTI_SKILL_VWAP_ZSCORE,
        "VWAP slippage by algorithm combined with z-score volume"
        " outlier flags — two skills activated in one query.",
    ),
}


def match_question(msg: str) -> str:
    """Keyword-match a user question to a scripted query."""
    m = msg.lower()
    # Order matters — more specific matches first
    # Multi-skill: needs terms from BOTH trade-analytics AND zscore-monitor
    has_trade = any(w in m for w in ("slippage", "algo", "vwap", "algorithm", "trades"))
    has_zscore = any(w in m for w in ("z-score", "zscore", "z score", "outlier", "volume outlier"))
    if has_trade and has_zscore:
        return "multi_skill"
    if any(w in m for w in ("broker", "scorecard", "counterparty")):
        return "broker"
    if any(w in m for w in ("dark", "pool", "venue", "lit")):
        return "dark"
    if any(w in m for w in ("trader", "leaderboard", "who", "person", "best")):
        return "trader"
    if has_trade:
        return "slippage"
    if any(w in m for w in ("top", "symbol", "notional", "biggest")):
        return "top_symbols"
    return "top_symbols"


# ---------------------------------------------------------------------------
# 3. Mock runtime
# ---------------------------------------------------------------------------

class DemoRuntime:
    """Maps user questions to scripted SQL + execute_code calls."""

    def create_agent(self, model: str, tools: list[Any], system_prompt: str, **kw: Any) -> dict:
        return {"tools": tools}

    async def stream(self, agent: dict, message: str, context: Any, history: Any = None):
        from deep_agent.models.events import (
            AgentChunkEvent,
            AgentCompleteEvent,
            ToolCallEvent,
            ToolResultEvent,
        )

        key = match_question(message)
        code, summary = SCRIPTED[key]

        tool = next(
            (t for t in agent["tools"] if getattr(t, "name", "") == "execute_code"),
            None,
        )
        assert tool, "execute_code tool not found"

        yield ToolCallEvent(tool="execute_code", input={"code": code})

        raw = await tool.ainvoke({"code": code})
        parsed = json.loads(raw)
        output = parsed.get("stdout") or parsed.get("stderr") or "(no output)"

        files = parsed.get("output_files", {})
        yield ToolResultEvent(tool="execute_code", output=output, files=files)
        yield AgentChunkEvent(content=summary)
        yield AgentCompleteEvent(summary=summary, tokens_used=0)


# ---------------------------------------------------------------------------
# 4. App builder
# ---------------------------------------------------------------------------

def build_app():
    from deep_agent.api.app import create_app
    from deep_agent.api.config_loader import build_tenant_context, load_agent_bindings
    from deep_agent.config import AppSettings

    settings = AppSettings(
        OPENAI_API_KEY="sk-demo-not-needed",
        SKILLS_ROOT=PROJECT_ROOT / "skills",
    )
    config_root = PROJECT_ROOT / "config"

    app = create_app(settings=settings, config_root=config_root, runtime=DemoRuntime())

    tenant = build_tenant_context("equities", config_root=config_root)
    bindings = load_agent_bindings("equities-desk-agent", config_root=config_root)
    assert bindings, (
        "Could not load equities-desk-agent"
        " — check config/agents/equities-desk-agent.yaml"
    )

    return app, tenant, bindings


# ---------------------------------------------------------------------------
# 5. WebSocket test double
# ---------------------------------------------------------------------------

from fastapi import WebSocketDisconnect


class FakeWebSocket:
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
# 6. Core ask function
# ---------------------------------------------------------------------------

async def ask_agent(question: str) -> list[dict]:
    """Send a question to equities-desk-agent and return streamed events."""
    from deep_agent.api.ws_chat import _handle_client_message

    app, tenant, bindings = build_app()
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

    return [json.loads(t) for t in ws.sent_texts]


def print_events(events: list[dict]) -> None:
    """Pretty-print event stream."""
    skill_matches = [e for e in events if e.get("type") == "skill_match"]
    if len(skill_matches) >= 2:
        ids = " + ".join(e.get("skill_id", "?") for e in skill_matches)
        print(f"\n🎯 Multi-skill activated: {ids}")
    for ev in events:
        etype = ev.get("type", "unknown")
        if etype == "skill_match":
            print(f"\n🎯 Skill matched: {ev.get('skill_id', '?')}")
        elif etype == "tool_call":
            print(f"\n🔧 Tool call: {ev.get('tool', '?')}")
            code = ev.get("input", {}).get("code", "")
            # Show just the SQL portion
            lines = code.strip().split("\n")
            skip = ("import", "conn", "cur", "rows", "print", "#", "for ", "bar ")
            sql_lines = [ln for ln in lines if ln.strip() and not ln.strip().startswith(skip)]
            for line in sql_lines[:12]:
                print(f"   │ {line}")
            if len(sql_lines) > 12:
                print(f"   │ ... ({len(lines)} lines total)")
        elif etype == "tool_result":
            print("\n📊 Result:")
            for line in ev.get("output", "").strip().split("\n"):
                print(f"   {line}")
        elif etype == "agent_chunk":
            print(f"\n💬 {ev.get('content', '')}")
        elif etype == "agent_complete":
            print("\n✅ Complete")
        elif etype == "error":
            print(f"\n❌ Error [{ev.get('code')}]: {ev.get('message')}")


# ---------------------------------------------------------------------------
# 7. Interactive demo
# ---------------------------------------------------------------------------

DEMO_QUESTIONS = [
    ("📈 Top Symbols by Notional", "What are the top symbols by notional traded?"),
    ("⚡ Algo Slippage Analysis", "Show me VWAP slippage by algo — which algorithm executes best?"),
    ("👤 Trader Leaderboard", "Who are the best traders by execution quality?"),
    ("🌑 Dark Pool Trend", "Show me daily dark pool usage over the past 20 days"),
    ("🏦 Broker Scorecard", "Give me a broker scorecard — slippage, fill sizes, dark pool routing"),
    ("🔀 Multi-Skill", "Show trades slippage by algorithm and flag volume outlier symbols"),
]


async def run_demo() -> None:
    seed_database()

    print("\n" + "=" * 65)
    print("  Deep Agent — Equities Trade Analytics Demo")
    print("  Chat with your trade database using natural language")
    print("=" * 65)

    for title, question in DEMO_QUESTIONS:
        print(f"\n\n{'─' * 65}")
        print(f"  {title}")
        print(f"{'─' * 65}")
        print(f"👤 User: {question}")
        events = await ask_agent(question)
        print_events(events)

    print("\n\n" + "=" * 65)
    print("  Demo complete!")
    print("=" * 65)
    print("""
To run with a real LLM against ClickHouse:

  1. Set environment variables:
     export OPENAI_API_KEY="sk-..."
     export DB_HOST="clickhouse.equities.internal"
     export DB_PORT="9000"

  2. Start the server:
     python scripts/run_dev.py

  3. Connect via WebSocket:
     wscat -c 'ws://localhost:8000/ws/chat?tenant_id=equities&agent_id=equities-desk-agent'

  4. Ask anything:
     > What was our VWAP slippage on AAPL today?
     > Show me the top 10 symbols by notional traded this week
     > How does alice's fill rate compare to the desk average?
     > Which algo had the worst slippage last month?
     > Plot hourly participation rate for MSFT on March 14
""")


# ---------------------------------------------------------------------------
# 8. Pytest tests
# ---------------------------------------------------------------------------

import pytest


@pytest.fixture(autouse=True)
def _seed():
    seed_database()


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_top_symbols_query():
    """Agent returns top symbols by notional with correct data."""
    events = await ask_agent("Show me top symbols by notional")
    types = [e["type"] for e in events]
    assert "tool_call" in types
    assert "tool_result" in types
    assert "agent_complete" in types

    result = next(e for e in events if e["type"] == "tool_result")
    output = result["output"]
    # All 8 symbols should appear
    for sym in SYMBOLS:
        assert sym in output, f"Expected {sym} in output"


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_slippage_by_algo():
    """Agent computes VWAP slippage per algo with bps metric."""
    events = await ask_agent("VWAP slippage by algorithm")
    result = next(e for e in events if e["type"] == "tool_result")
    output = result["output"]
    for algo in ALGOS:
        assert algo in output, f"Expected {algo} in output"
    assert "bps" in output.lower() or "slip" in output.lower()


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_trader_leaderboard():
    """Agent returns trader leaderboard with slippage ranking."""
    events = await ask_agent("Who are the best traders?")
    result = next(e for e in events if e["type"] == "tool_result")
    output = result["output"]
    for trader in TRADERS:
        assert trader in output, f"Expected {trader} in output"


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_dark_pool_trend():
    """Agent shows daily dark pool percentage with visual bars."""
    events = await ask_agent("Dark pool usage trend")
    result = next(e for e in events if e["type"] == "tool_result")
    output = result["output"]
    assert "2026-" in output  # Date column present
    assert "%" in output      # Percentage shown
    assert "█" in output      # Visual bar rendered


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_broker_scorecard():
    """Agent produces broker scorecard with multiple metrics."""
    events = await ask_agent("Broker scorecard")
    result = next(e for e in events if e["type"] == "tool_result")
    output = result["output"]
    for broker in BROKERS:
        assert broker in output, f"Expected {broker} in output"


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_event_pipeline_order():
    """Events follow correct order: skill_match → tool_call → tool_result → complete."""
    events = await ask_agent("Show trades slippage by algo")
    types = [e["type"] for e in events]
    sm = types.index("skill_match")
    tc = types.index("tool_call")
    tr = types.index("tool_result")
    ac = types.index("agent_complete")
    assert sm < tc < tr < ac, f"Wrong event order: {types}"


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_sql_shown_in_output():
    """The generated SQL query is visible in tool output (transparency)."""
    events = await ask_agent("top symbols by notional")
    result = next(e for e in events if e["type"] == "tool_result")
    output = result["output"]
    assert "SELECT" in output and "FROM trades" in output


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_multi_skill_cross_domain_query():
    """Cross-domain query activates 2 skills: trade-analytics + zscore-monitor."""
    events = await ask_agent(
        "Show trades slippage by algorithm and flag volume outlier symbols"
    )
    skill_matches = [e for e in events if e["type"] == "skill_match"]
    matched_ids = {e["skill_id"] for e in skill_matches}
    assert len(skill_matches) >= 2
    assert "equities/trade-analytics" in matched_ids
    assert "equities/zscore-monitor" in matched_ids


# ---------------------------------------------------------------------------
# 9. __main__
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(run_demo())
