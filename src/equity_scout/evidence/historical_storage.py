"""Store for historical catalyst events (P2a backfill: congress/insider/statement history).

Mirrors evidence/storage.py's record contract — `record_historical_events` is idempotent
per (source, ticker, event_key) and returns ONLY the newly inserted rows, `now` is always
injected, no wall clock in this module (same rule as evidence/storage.py and
ml/prediction_ledger.py). Unlike the live evidence lanes, history needs no
predict-then-resolve ledger: every backfilled event's forward-return windows have already
elapsed, so returns are resolved in place as nullable columns on the event row.

Resolution is PER-COLUMN one-way, not row-level: each r_* horizon column may be written
exactly once via `mark_resolved` (a call touching an already-filled column is refused
whole — nothing is written), because young events only have some windows elapsed yet
(Task 5 fills the rest once later runs catch up). `resolved_at` means FULLY resolved when
set by `mark_resolved` — only once all five r_* columns are non-NULL, never on a partial
write. `mark_unresolvable` is the parallel terminal transition for rows that can never be
resolved (delisted ticker, panel gap, ...); once a row is unresolvable, `mark_resolved`
refuses any further write to it.

Connections go through equity_scout.db.connect (WAL + 30s busy timeout), not a bare
sqlite3.connect: this table lives in equity_scout.db, which a minutely writer (session
lane) already holds open, and multi-hour backfill runs must queue rather than crash.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from equity_scout import db
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
    with db.connect(db_path) as conn:
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
    with db.connect(db_path) as conn:
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
    (
        event_id, source, person, ticker, event_key, t0, details_json, created_at,
        r_1w, r_1m, r_3m, r_6m, r_12m,
    ) = row
    return {
        "id": event_id,
        "source": source,
        "person": person,
        "ticker": ticker,
        "event_key": event_key,
        "t0": t0,
        "details": json.loads(details_json),
        "created_at": created_at,
        "r_1w": r_1w,
        "r_1m": r_1m,
        "r_3m": r_3m,
        "r_6m": r_6m,
        "r_12m": r_12m,
    }


def unresolved_events(db_path: str, limit: int | None = None) -> list[dict]:
    """Rows still awaiting full resolution, in insertion order (stable for resumable
    batches; NOT t0 order). Rows with some but not all r_* horizons already written keep
    appearing here — the returned dicts carry the current r_* values (None = not yet
    written) so the Task-5 resolver can compute which horizons are still missing.
    """
    init_historical_db(db_path)
    query = (
        "SELECT id, source, person, ticker, event_key, t0, details_json, created_at,"
        " r_1w, r_1m, r_3m, r_6m, r_12m"
        " FROM historical_events WHERE resolved_at IS NULL AND unresolvable = 0 ORDER BY id"
    )
    params: tuple = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (int(limit),)
    with db.connect(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_dict(row) for row in rows]


def mark_resolved(
    db_path: str, event_id: int, returns: dict[str, float], *, now: str
) -> bool:
    """Per-column one-way write of forward-return horizons.

    Each r_* column may be written exactly once: if ANY column named in `returns` is
    already non-NULL, the whole call is refused and nothing is written (first write
    stands, per column) — young events legitimately get resolved in several calls as
    more windows elapse. A row already marked unresolvable refuses any write. Once all
    five r_* columns are non-NULL, `resolved_at` is set to `now` — that column means
    FULLY resolved, never partially.

    Returns False (no-op) if the row is unresolvable or if any passed column already
    holds a value. Raises ValueError for an unknown event id, an unknown horizon key, an
    empty `returns`, or a None value in `returns` (any of which would otherwise reach the
    database as malformed SQL or a silently accepted non-fact).
    """
    if not returns:
        raise ValueError("returns must not be empty")
    if any(value is None for value in returns.values()):
        raise ValueError("returns must not contain None values")
    unknown = set(returns) - set(RETURN_HORIZONS)
    if unknown:
        raise ValueError(f"unknown return horizon(s): {sorted(unknown)}")
    init_historical_db(db_path)
    with db.connect(db_path) as conn:
        row = conn.execute(
            "SELECT r_1w, r_1m, r_3m, r_6m, r_12m, unresolvable"
            " FROM historical_events WHERE id = ?",
            (event_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown historical event id: {event_id}")
        current = dict(zip(RETURN_HORIZONS, row[:5], strict=True))
        if row[5]:  # unresolvable
            return False
        if any(current[column] is not None for column in returns):
            return False  # a targeted column already has a value — refuse the whole call
        set_columns = ", ".join(f"{column} = ?" for column in returns)
        null_guards = " AND ".join(f"{column} IS NULL" for column in returns)
        values = [float(v) for v in returns.values()]
        cursor = conn.execute(
            f"UPDATE historical_events SET {set_columns}"
            f" WHERE id = ? AND unresolvable = 0 AND {null_guards}",
            (*values, event_id),
        )
        if cursor.rowcount != 1:
            return False
        fully_resolved = conn.execute(
            "SELECT 1 FROM historical_events WHERE id = ? AND r_1w IS NOT NULL"
            " AND r_1m IS NOT NULL AND r_3m IS NOT NULL AND r_6m IS NOT NULL"
            " AND r_12m IS NOT NULL",
            (event_id,),
        ).fetchone()
        if fully_resolved is not None:
            conn.execute(
                "UPDATE historical_events SET resolved_at = ? WHERE id = ?", (now, event_id)
            )
        return True


def mark_unresolvable(db_path: str, event_id: int, reason: str, *, now: str) -> bool:
    """One guarded open->unresolvable transition (ticker delisted, panel gap, ...).

    Returns False (no-op) if the row is already resolved or already marked unresolvable —
    the first transition stands. Raises ValueError for an unknown event id.
    """
    init_historical_db(db_path)
    with db.connect(db_path) as conn:
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
