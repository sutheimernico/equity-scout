"""SQLite persistence for classified beat/miss/guidance + 8-K category events
(Strang B3).

One flat table, unique per event_key: re-classifying the same headline or filing (a
later scripts/run_evidence.py run re-collecting the same underlying fact) is a no-op —
same INSERT OR IGNORE idempotency as evidence/storage.py's record_events, and it never
shifts the row's original seen_at. `published_at` and `seen_at` are the honest latency
pair this Strang exists for: `published_at` is whatever the source reported (NULL when
the source had none — never backfilled from seen_at), `seen_at` is always the caller-
supplied collection timestamp, never a wall-clock call inside this module. Strang B4
does the actual latency measurement; this module only stores both timestamps.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from equity_scout.evidence.event_classifier import ClassifiedEvent


def init_classified_events_db(db_path: str | Path) -> None:
    with sqlite3.connect(db_path) as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS classified_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                event_type TEXT NOT NULL,
                source TEXT NOT NULL,
                published_at TEXT,
                seen_at TEXT NOT NULL,
                detail TEXT,
                event_key TEXT NOT NULL UNIQUE
            )"""
        )


def save_classified_events(
    db_path: str | Path, events: list[ClassifiedEvent], *, seen_at: str
) -> list[ClassifiedEvent]:
    """Insert, skipping already-known event_key rows. Returns only the newly inserted
    ones — same "tell the caller what's actually new" contract as evidence/storage.py's
    record_events. Inserted one-by-one (volumes are tiny; executemany can't report
    which rows an INSERT OR IGNORE dropped).
    """
    init_classified_events_db(db_path)
    inserted: list[ClassifiedEvent] = []
    with sqlite3.connect(db_path) as con:
        for event in events:
            cursor = con.execute(
                "INSERT OR IGNORE INTO classified_events"
                " (ticker, event_type, source, published_at, seen_at, detail, event_key)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    event.ticker,
                    event.event_type,
                    event.source,
                    event.published_at,
                    seen_at,
                    event.detail,
                    event.event_key,
                ),
            )
            if cursor.rowcount == 1:
                inserted.append(event)
    return inserted


def load_classified_events(db_path: str | Path, ticker: str | None = None) -> list[dict]:
    """All stored classifications, optionally filtered to one ticker. Newest first by
    seen_at; id as tiebreaker so same-timestamp inserts stay stable. Returns [] if the
    table does not exist yet — same not-yet-initialised honesty as forward_storage."""
    init_classified_events_db(db_path)
    with sqlite3.connect(db_path) as con:
        if ticker is None:
            rows = con.execute(
                "SELECT ticker, event_type, source, published_at, seen_at, detail, event_key"
                " FROM classified_events ORDER BY seen_at DESC, id DESC"
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT ticker, event_type, source, published_at, seen_at, detail, event_key"
                " FROM classified_events WHERE ticker = ? ORDER BY seen_at DESC, id DESC",
                (ticker.upper(),),
            ).fetchall()
    return [
        {
            "ticker": t,
            "event_type": et,
            "source": s,
            "published_at": pa,
            "seen_at": sa,
            "detail": d,
            "event_key": ek,
        }
        for t, et, s, pa, sa, d, ek in rows
    ]
