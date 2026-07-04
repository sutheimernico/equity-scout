"""SQLite persistence for radar watchlists.

Two tables, same style as storage.py (raw sqlite3, JSON snapshot column):
- watchlists:      one row per radar run (full snapshot, newest wins for the API)
- signal_readings: append-only log of every sub-signal reading — this is the
  training-data seed for the ML combiner (Phase 4). Never UPDATE or DELETE here.
  Each row carries watchlist_id (FK to the snapshot it was read from) and a JSON
  breakdown of the finalist's full funnel breakdown (spec §5.2: market context for ML).
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
                reason TEXT NOT NULL,
                watchlist_id INTEGER,
                breakdown TEXT
            )"""
        )
        # Defensive migration for DBs created before watchlist_id/breakdown existed (same
        # PRAGMA table_info + ALTER TABLE idiom as storage.py's init_db). Existing rows keep
        # NULL for both — signal_readings is append-only, so old rows are never rewritten.
        cols = [r[1] for r in conn.execute("PRAGMA table_info(signal_readings)")]
        if "watchlist_id" not in cols:
            conn.execute("ALTER TABLE signal_readings ADD COLUMN watchlist_id INTEGER")
        if "breakdown" not in cols:
            conn.execute("ALTER TABLE signal_readings ADD COLUMN breakdown TEXT")


def save_watchlist(db_path: str, watchlist: Watchlist) -> int:
    """Persist one snapshot + append its readings, FK'd to the snapshot. Returns the snapshot
    row id."""
    init_radar_db(db_path)
    payload = json.dumps(asdict(watchlist), ensure_ascii=False)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO watchlists (created_at, data) VALUES (?, ?)",
            (watchlist.created_at, payload),
        )
        assert cursor.lastrowid is not None  # guaranteed after a successful INSERT
        watchlist_id = int(cursor.lastrowid)
        conn.executemany(
            "INSERT INTO signal_readings"
            " (created_at, ticker, signal, score, price, reason, watchlist_id, breakdown)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    watchlist.created_at, e.ticker, r.name, r.score, e.price, r.reason,
                    watchlist_id, json.dumps(e.breakdown, ensure_ascii=False),
                )
                for e in watchlist.entries
                for r in e.readings
            ],
        )
        return watchlist_id


def load_latest_watchlist(db_path: str = DEFAULT_DB_PATH) -> dict | None:
    """Newest snapshot as a plain dict (JSON round-trip), or None if none exists."""
    init_radar_db(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT data FROM watchlists ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return json.loads(row[0]) if row else None
