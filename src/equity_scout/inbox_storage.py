"""SQLite persistence for the decision inbox (one pitch = one notification).

Same idiom as radar_storage.py: raw sqlite3, idempotent init, per-function
connections. `status` lifecycle: open -> buy | pass | later (single transition,
enforced in decide_pitch's WHERE clause — concurrency-safe by construction).
last_pitch_at() is the cooldown source: notify.py never re-pitches a ticker
inside its cooldown window regardless of the previous pitch's outcome.
"""
from __future__ import annotations

import sqlite3

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.telegram_client import ACTIONS

_COLUMNS = (
    "id, created_at, ticker, watchlist_id, price, composite, zone_low, zone_high, "
    "pitch, status, decided_at, telegram_message_id"
)


def init_inbox_db(db_path: str = DEFAULT_DB_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS pitches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                ticker TEXT NOT NULL,
                watchlist_id INTEGER,
                price REAL NOT NULL,
                composite REAL NOT NULL,
                zone_low REAL NOT NULL,
                zone_high REAL NOT NULL,
                pitch TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                decided_at TEXT,
                telegram_message_id INTEGER
            )"""
        )


def create_pitch(
    db_path: str,
    *,
    ticker: str,
    watchlist_id: int | None,
    price: float,
    composite: float,
    zone_low: float,
    zone_high: float,
    pitch: str,
    created_at: str,
) -> int:
    init_inbox_db(db_path)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO pitches (created_at, ticker, watchlist_id, price, composite,"
            " zone_low, zone_high, pitch) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (created_at, ticker, watchlist_id, price, composite, zone_low, zone_high, pitch),
        )
        assert cursor.lastrowid is not None
        return int(cursor.lastrowid)


def decide_pitch(db_path: str, pitch_id: int, action: str, *, decided_at: str) -> bool:
    """True iff the pitch existed, was still open, and `action` is valid."""
    if action not in ACTIONS:
        return False
    if not 0 <= pitch_id < 2**63:
        # Outside SQLite's signed 64-bit INTEGER range such an id cannot exist, and
        # binding it would raise OverflowError. Guards both the API route and the receiver.
        return False
    init_inbox_db(db_path)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "UPDATE pitches SET status = ?, decided_at = ? WHERE id = ? AND status = 'open'",
            (action, decided_at, pitch_id),
        )
        return cursor.rowcount == 1


def set_message_id(db_path: str, pitch_id: int, message_id: int) -> None:
    init_inbox_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE pitches SET telegram_message_id = ? WHERE id = ?", (message_id, pitch_id)
        )


def last_pitch_at(db_path: str, ticker: str) -> str | None:
    # SQL MAX() on TEXT compares lexicographically. That is only chronologically
    # correct because ALL writers produce UTC "+00:00" ISO-8601 strings
    # (run_notify's main() does); never mix timezone offsets in created_at.
    init_inbox_db(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT MAX(created_at) FROM pitches WHERE ticker = ?", (ticker,)
        ).fetchone()
    return row[0] if row and row[0] else None


def load_pitches(db_path: str = DEFAULT_DB_PATH, limit: int = 100) -> list[dict]:
    """Newest first, open pitches before decided ones."""
    init_inbox_db(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM pitches"
            " ORDER BY (status = 'open') DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    keys = [k.strip() for k in _COLUMNS.split(",")]
    return [dict(zip(keys, row)) for row in rows]
