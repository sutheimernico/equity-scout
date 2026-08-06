"""Store for historical catalyst events (P2a backfill: congress/insider/statement history).

Mirrors evidence/storage.py's record contract — `record_historical_events` is idempotent
per (source, ticker, event_key) and returns ONLY the newly inserted rows, `now` is always
injected, no wall clock in this module (same rule as evidence/storage.py and
ml/prediction_ledger.py). Unlike the live evidence lanes, history needs no
predict-then-resolve ledger: every backfilled event's forward-return windows have already
elapsed, so returns are resolved in place as nullable columns on the event row.

Resolution follows evidence/ledger.py's one-way convention: `mark_resolved` and
`mark_unresolvable` are the only two permitted terminal transitions on a row, each gated
on the row still being open (`resolved_at IS NULL AND unresolvable = 0`) — the first
transition to land stands, a second attempt (by either function) is refused.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from equity_scout.constants import DEFAULT_DB_PATH

RETURN_HORIZONS = ("r_1w", "r_1m", "r_3m", "r_6m", "r_12m")


@dataclass(frozen=True)
class HistoricalEvent:
    source: str
    person: str
    ticker: str
    # Idempotency key within (source, ticker) — same convention as evidence.base.EvidenceEvent.
    event_key: str
    t0: str  # ISO date/timestamp the fact became PUBLICLY knowable (filing/post date)
    details: dict  # JSON-serializable extras (amount band, chamber, cluster size, ...)


def init_historical_db(db_path: str = DEFAULT_DB_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS historical_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                person TEXT NOT NULL,
                ticker TEXT NOT NULL,
                event_key TEXT NOT NULL,
                t0 TEXT NOT NULL,
                details_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                r_1w REAL,
                r_1m REAL,
                r_3m REAL,
                r_6m REAL,
                r_12m REAL,
                resolved_at TEXT,
                unresolvable INTEGER NOT NULL DEFAULT 0,
                unresolvable_reason TEXT,
                UNIQUE(source, ticker, event_key)
            )"""
        )


def record_historical_events(
    db_path: str, events: list[HistoricalEvent], *, now: str
) -> list[HistoricalEvent]:
    """Insert events, skipping already-known (source, ticker, event_key) rows.

    Returns the subset that was actually new. Inserted one-by-one (volumes are tiny)
    because executemany cannot tell which rows an INSERT OR IGNORE dropped.
    """
    init_historical_db(db_path)
    inserted: list[HistoricalEvent] = []
    with sqlite3.connect(db_path) as conn:
        for event in events:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO historical_events"
                " (source, person, ticker, event_key, t0, details_json, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    event.source,
                    event.person,
                    event.ticker,
                    event.event_key,
                    event.t0,
                    json.dumps(event.details, ensure_ascii=False),
                    now,
                ),
            )
            if cursor.rowcount == 1:
                inserted.append(event)
    return inserted


def _row_to_dict(row: tuple) -> dict:
    (event_id, source, person, ticker, event_key, t0, details_json, created_at) = row
    return {
        "id": event_id,
        "source": source,
        "person": person,
        "ticker": ticker,
        "event_key": event_key,
        "t0": t0,
        "details": json.loads(details_json),
        "created_at": created_at,
    }


def unresolved_events(db_path: str, limit: int | None = None) -> list[dict]:
    """Rows still awaiting a terminal transition, oldest first."""
    init_historical_db(db_path)
    query = (
        "SELECT id, source, person, ticker, event_key, t0, details_json, created_at"
        " FROM historical_events WHERE resolved_at IS NULL AND unresolvable = 0 ORDER BY id"
    )
    params: tuple = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (int(limit),)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_dict(row) for row in rows]


def mark_resolved(
    db_path: str, event_id: int, returns: dict[str, float], *, now: str
) -> bool:
    """One guarded open->resolved transition, writing whichever r_* horizons are present
    in `returns` — young events may only have some windows elapsed yet, and future runs
    never revisit an already-resolved row (one-way, same as evidence/ledger.py).

    Returns False (no-op) if the row is already resolved or already marked unresolvable —
    the first transition stands. Raises ValueError for an unknown event id or an unknown
    horizon key.
    """
    unknown = set(returns) - set(RETURN_HORIZONS)
    if unknown:
        raise ValueError(f"unknown return horizon(s): {sorted(unknown)}")
    init_historical_db(db_path)
    with sqlite3.connect(db_path) as conn:
        exists = conn.execute(
            "SELECT 1 FROM historical_events WHERE id = ?", (event_id,)
        ).fetchone()
        if exists is None:
            raise ValueError(f"unknown historical event id: {event_id}")
        set_columns = ", ".join(f"{column} = ?" for column in returns)
        values = [float(v) for v in returns.values()]
        cursor = conn.execute(
            f"UPDATE historical_events SET resolved_at = ?, {set_columns}"
            " WHERE id = ? AND resolved_at IS NULL AND unresolvable = 0",
            (now, *values, event_id),
        )
        return cursor.rowcount == 1


def mark_unresolvable(db_path: str, event_id: int, reason: str, *, now: str) -> bool:
    """One guarded open->unresolvable transition (ticker delisted, panel gap, ...).

    Returns False (no-op) if the row is already resolved or already marked unresolvable —
    the first transition stands. Raises ValueError for an unknown event id.
    """
    init_historical_db(db_path)
    with sqlite3.connect(db_path) as conn:
        exists = conn.execute(
            "SELECT 1 FROM historical_events WHERE id = ?", (event_id,)
        ).fetchone()
        if exists is None:
            raise ValueError(f"unknown historical event id: {event_id}")
        cursor = conn.execute(
            "UPDATE historical_events SET unresolvable = 1, unresolvable_reason = ?,"
            " resolved_at = ? WHERE id = ? AND resolved_at IS NULL AND unresolvable = 0",
            (reason, now, event_id),
        )
        return cursor.rowcount == 1
