"""Seed a local SQLite database with sample portfolio and market data.

Creates /tmp/portfolio.db with positions and historical prices.
"""
from __future__ import annotations

import os
import random
import sqlite3

DB_PATH = os.environ.get("DB_PATH", "/tmp/portfolio.db")


def seed() -> None:
    """Create tables and insert sample data."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Positions table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            portfolio_id TEXT,
            sym TEXT,
            qty REAL,
            avg_cost REAL
        )
    """)

    # Historical prices table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_prices (
            date TEXT,
            sym TEXT,
            close REAL,
            volume INTEGER
        )
    """)

    # Clear and re-seed
    cur.execute("DELETE FROM positions")
    cur.execute("DELETE FROM daily_prices")

    # Portfolio EQ-MACRO-1
    positions = [
        ("EQ-MACRO-1", "AAPL", 500, 178.50),
        ("EQ-MACRO-1", "MSFT", 300, 415.20),
        ("EQ-MACRO-1", "GOOG", 200, 141.80),
    ]
    cur.executemany("INSERT INTO positions VALUES (?, ?, ?, ?)", positions)

    # Generate 252 trading days of synthetic prices
    random.seed(42)
    symbols = {"AAPL": 178.50, "MSFT": 415.20, "GOOG": 141.80}
    base_date = 20230103  # YYYYMMDD
    rows = []
    for day_offset in range(252):
        date_int = base_date + day_offset
        date_str = f"{date_int // 10000}-{(date_int % 10000) // 100:02d}-{date_int % 100:02d}"
        for sym, base_price in symbols.items():
            daily_return = random.gauss(0.0005, 0.02)
            symbols[sym] = base_price * (1 + daily_return)
            price = round(symbols[sym], 2)
            volume = int(random.gauss(50_000_000, 15_000_000))
            rows.append((date_str, sym, price, max(volume, 1_000_000)))

    cur.executemany("INSERT INTO daily_prices VALUES (?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    seed()
