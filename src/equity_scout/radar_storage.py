"""SQLite persistence for radar watchlists.

Two tables, same style as storage.py (raw sqlite3, JSON snapshot column):
- watchlists:      one row per radar run (full snapshot, newest wins for the API)
- signal_readings: append-only log of every sub-signal reading — this is the
  training-data seed for the ML combiner (Phase 4). Never UPDATE or DELETE here.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.radar import Watchlist


def init_radar_db(db_path: str = DEFAULT_DB_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS watchlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                data TEXT NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS signal_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                ticker TEXT NOT NULL,
                signal TEXT NOT NULL,
                score REAL NOT NULL,
                price REAL NOT NULL,
                reason TEXT NOT NULL
            )"""
        )


def save_watchlist(db_path: str, watchlist: Watchlist) -> int:
    """Persist one snapshot + append its readings. Returns the snapshot row id."""
    init_radar_db(db_path)
    payload = json.dumps(asdict(watchlist), ensure_ascii=False)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO watchlists (created_at, data) VALUES (?, ?)",
            (watchlist.created_at, payload),
        )
        conn.executemany(
            "INSERT INTO signal_readings (created_at, ticker, signal, score, price, reason)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [
                (watchlist.created_at, e.ticker, r.name, r.score, e.price, r.reason)
                for e in watchlist.entries
                for r in e.readings
            ],
        )
        assert cursor.lastrowid is not None  # guaranteed after a successful INSERT
        return int(cursor.lastrowid)


def load_latest_watchlist(db_path: str = DEFAULT_DB_PATH) -> dict | None:
    """Newest snapshot as a plain dict (JSON round-trip), or None if none exists."""
    init_radar_db(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT data FROM watchlists ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return json.loads(row[0]) if row else None
