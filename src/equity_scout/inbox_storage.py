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
    "pitch, status, decided_at, telegram_message_id, verdict, verdict_why, pitch_html"
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
                telegram_message_id INTEGER,
                verdict TEXT,
                verdict_why TEXT,
                pitch_html TEXT
            )"""
        )
        # v8 migration for pre-existing inboxes: rows from before these columns simply
        # stay NULL (surfaces render an honest absence, never a recomputed guess — the
        # readings that fed the damping rule are not persisted, and the HTML detail
        # variant cannot be rebuilt without the original entry/fundamentals).
        existing = {row[1] for row in conn.execute("PRAGMA table_info(pitches)")}
        for column in ("verdict", "verdict_why", "pitch_html"):
            if column not in existing:
                conn.execute(f"ALTER TABLE pitches ADD COLUMN {column} TEXT")


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
    verdict: str | None = None,
    verdict_why: str | None = None,
    pitch_html: str | None = None,
) -> int:
    init_inbox_db(db_path)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO pitches (created_at, ticker, watchlist_id, price, composite,"
            " zone_low, zone_high, pitch, verdict, verdict_why, pitch_html)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (created_at, ticker, watchlist_id, price, composite, zone_low, zone_high, pitch,
             verdict, verdict_why, pitch_html),
        )
        assert cursor.lastrowid is not None
        return int(cursor.lastrowid)


def _plausible_id(pitch_id: int) -> bool:
    # Outside SQLite's signed 64-bit INTEGER range such an id cannot exist, and
    # binding it would raise OverflowError. Guards the API route, the receiver,
    # and direct lookups alike.
    return 0 <= pitch_id < 2**63


def decide_pitch(db_path: str, pitch_id: int, action: str, *, decided_at: str) -> bool:
    """True iff the pitch existed, was still open, and `action` is valid."""
    if action not in ACTIONS:
        return False
    if not _plausible_id(pitch_id):
        return False
    init_inbox_db(db_path)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "UPDATE pitches SET status = ?, decided_at = ? WHERE id = ? AND status = 'open'",
            (action, decided_at, pitch_id),
        )
        return cursor.rowcount == 1


def expire_stale_pitches(db_path: str, active_tickers: list[str], *, expired_at: str) -> int:
    """Expire open pitches the system no longer stands behind. Two stale cases:

    1. The ticker left the current watchlist — the funnel no longer watches the name,
       so the pitch's basis is gone (Nico 2026-08-06: "nichts Veraltetes").
    2. The pitch predates the v8 verdict column (verdict IS NULL) — every pitch since
       carries a rating, and an unrated offer is not decidable (Nico 2026-08-07: "beim
       Entscheiden soll mir nix angezeigt werden, was keine Bewertung hat").

    Withdrawing is NOT a decision on Nico's behalf (that would be "pass"). Returns the
    number expired. An EMPTY ticker list skips case 1 by design — a broken radar run
    must never wipe the whole inbox in one sweep — while case 2 stays independent of it.
    """
    init_inbox_db(db_path)
    expired = 0
    with sqlite3.connect(db_path) as conn:
        if active_tickers:
            placeholders = ",".join("?" for _ in active_tickers)
            expired += conn.execute(
                f"UPDATE pitches SET status = 'expired', decided_at = ?"
                f" WHERE status = 'open' AND ticker NOT IN ({placeholders})",
                (expired_at, *active_tickers),
            ).rowcount
        expired += conn.execute(
            "UPDATE pitches SET status = 'expired', decided_at = ?"
            " WHERE status = 'open' AND verdict IS NULL",
            (expired_at,),
        ).rowcount
    return expired


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


def get_pitch(db_path: str, pitch_id: int) -> dict | None:
    """One pitch by id, or None for unknown/implausible ids."""
    if not _plausible_id(pitch_id):
        return None
    init_inbox_db(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM pitches WHERE id = ?", (pitch_id,)
        ).fetchone()
    if row is None:
        return None
    keys = [k.strip() for k in _COLUMNS.split(",")]
    return dict(zip(keys, row))


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
