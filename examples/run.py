"""End-to-end demo: WebSocket API -> Orchestrator -> Skill -> Sandbox.

Starts a real uvicorn server on a random port, connects via WebSocket,
and runs a two-turn VaR calculation — all without an LLM API key.

Usage:
    python -m examples.run
"""
from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from pathlib import Path
from urllib.request import urlopen

import uvicorn
import websockets

from deep_agent.api.app import create_app
from deep_agent.config import AppSettings
from examples.display import print_divider, print_event, print_header
from examples.scripted_runtime import ScriptedRuntime
from examples.seed_data import seed

# ---------------------------------------------------------------------------
# Scripted code blocks — executed inside the sandbox via execute_code tool.
# Turn 1 computes 95% VaR; Turn 2 computes 99% VaR.
# Both use DB_PATH (env var passed through sandbox allowlist) and
# risk_calc.py (available via PYTHONPATH injection from the skill's scripts/).
# ---------------------------------------------------------------------------

TURN_1_CODE = """\
import sqlite3, os
import pandas as pd
import numpy as np
from risk_calc import calculate_var

portfolio_id = "EQ-MACRO-1"
confidence = 0.95
horizon = 1

db_path = os.environ.get("DB_PATH", "/tmp/portfolio.db")
conn = sqlite3.connect(db_path)
positions = pd.read_sql(
    f"SELECT sym, qty, avg_cost FROM positions WHERE portfolio_id='{portfolio_id}'",
    conn,
)
conn.close()

print(f"Portfolio Positions ({portfolio_id}):")
print(positions.to_string(index=False))
print()

rng = np.random.default_rng(42)
symbols = positions["sym"].tolist()
returns = pd.DataFrame({sym: rng.normal(0.0005, 0.02, 252) for sym in symbols})

result = calculate_var(positions, returns, confidence=confidence, horizon=horizon)

print(f"1-Day {int(confidence * 100)}% VaR: ${result['var']:,.2f}")
print(f"Expected Shortfall: ${result['es']:,.2f}")
print(f"P&L samples: {len(result['pnl_distribution'])}")
"""

TURN_2_CODE = """\
import sqlite3, os
import pandas as pd
import numpy as np
from risk_calc import calculate_var

portfolio_id = "EQ-MACRO-1"
confidence = 0.99
horizon = 1

db_path = os.environ.get("DB_PATH", "/tmp/portfolio.db")
conn = sqlite3.connect(db_path)
positions = pd.read_sql(
    f"SELECT sym, qty, avg_cost FROM positions WHERE portfolio_id='{portfolio_id}'",
    conn,
)
conn.close()

print(f"Portfolio Positions ({portfolio_id}):")
print(positions.to_string(index=False))
print()

rng = np.random.default_rng(42)
symbols = positions["sym"].tolist()
returns = pd.DataFrame({sym: rng.normal(0.0005, 0.02, 252) for sym in symbols})

result = calculate_var(positions, returns, confidence=confidence, horizon=horizon)

print(f"1-Day {int(confidence * 100)}% VaR: ${result['var']:,.2f}")
print(f"Expected Shortfall: ${result['es']:,.2f}")
print(f"P&L samples: {len(result['pnl_distribution'])}")
"""


# ---------------------------------------------------------------------------
# Server helpers
# ---------------------------------------------------------------------------

def _find_free_port() -> int:
    """Bind to port 0 and let the OS assign a free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(app: object, host: str, port: int) -> uvicorn.Server:
    """Start uvicorn in a daemon thread and return the server handle."""
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server


def _wait_for_health(host: str, port: int, timeout: float = 10.0) -> None:
    """Block until the /health endpoint returns 200."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = urlopen(f"http://{host}:{port}/health")  # noqa: S310
            if resp.status == 200:
                return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("Server did not become healthy in time")


# ---------------------------------------------------------------------------
# WebSocket demo
# ---------------------------------------------------------------------------

async def _run_demo(host: str, port: int) -> None:
    """Connect via WebSocket and run two VaR calculation turns."""
    uri = f"ws://{host}:{port}/ws/chat?tenant_id=risk&agent_id=risk-desk-agent"

    async with websockets.connect(uri) as ws:
        # Receive session_started
        data = json.loads(await ws.recv())
        print_event(data)
        session_id = data.get("session_id", "")

        # --- Turn 1: 95% VaR ---
        print_header("Turn 1: Calculate 95% VaR")
        await ws.send(json.dumps({
            "type": "user_message",
            "content": "Calculate the 1-day 95% VaR for portfolio EQ-MACRO-1",
            "session_id": session_id,
        }))

        while True:
            raw = json.loads(await ws.recv())
            print_event(raw)
            if raw["type"] in ("agent_complete", "error"):
                break

        print_divider()

        # --- Turn 2: 99% VaR ---
        print_header("Turn 2: Calculate 99% VaR")
        await ws.send(json.dumps({
            "type": "user_message",
            "content": "What about at 99% confidence?",
            "session_id": session_id,
        }))

        while True:
            raw = json.loads(await ws.recv())
            print_event(raw)
            if raw["type"] in ("agent_complete", "error"):
                break

    print()
    print_header("Demo Complete")
    print("  Two-turn VaR calculation over WebSocket — no LLM API key required.")
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the end-to-end demo."""
    print_header("Deep Agent — End-to-End Demo")

    # 1. Seed SQLite
    print("\n  Seeding database...")
    seed()

    # 2. Build config — examples/ is both config_root and skills_root
    examples_root = Path(__file__).resolve().parent
    settings = AppSettings(
        OPENAI_API_KEY="sk-fake",  # type: ignore[arg-type]
        SKILLS_ROOT=examples_root / "skills",
    )

    # 3. Create ScriptedRuntime with 2 turn scripts
    runtime = ScriptedRuntime(scripts=[TURN_1_CODE, TURN_2_CODE])

    # 4. Create app with examples/ as config_root (agents/, tenants/ live here)
    app = create_app(
        settings=settings,
        config_root=examples_root,
        runtime=runtime,
    )

    # 5. Start server in daemon thread
    host = "127.0.0.1"
    port = _find_free_port()
    print(f"  Starting server on {host}:{port}...")
    server = _start_server(app, host, port)

    # 6. Wait for health
    _wait_for_health(host, port)
    print("  Server healthy.\n")

    # 7. Run demo
    try:
        asyncio.run(_run_demo(host, port))
    except KeyboardInterrupt:
        print("\n  Interrupted.")
    finally:
        # 8. Shutdown
        server.should_exit = True
        print("  Server shut down.")


if __name__ == "__main__":
    main()
