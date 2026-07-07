"""Append-only store for external evidence events.

`record_events` is idempotent per (source, ticker, event_key) — re-running a collector
never duplicates a fact — and returns ONLY the newly inserted events, so the caller can
ledger-log each fact exactly once. Rows are never updated or deleted. `now` is always
injected; no wall clock in this module (same rule as ml/prediction_ledger.py).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.evidence.base import EvidenceEvent


def init_evidence_db(db_path: str = DEFAULT_DB_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS evidence_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                ticker TEXT NOT NULL,
                event_key TEXT NOT NULL,
                event_date TEXT NOT NULL,
                details_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(source, ticker, event_key)
            )"""
        )


def record_events(
    db_path: str, events: list[EvidenceEvent], *, now: str
) -> list[EvidenceEvent]:
    """Insert events, skipping already-known (source, ticker, event_key) rows.

    Returns the subset that was actually new. Inserted one-by-one (volumes are tiny)
    because executemany cannot tell which rows an INSERT OR IGNORE dropped.
    """
    init_evidence_db(db_path)
    inserted: list[EvidenceEvent] = []
    with sqlite3.connect(db_path) as conn:
        for event in events:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO evidence_events"
                " (source, ticker, event_key, event_date, details_json, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    event.source,
                    event.ticker,
                    event.event_key,
                    event.event_date,
                    json.dumps(event.details, ensure_ascii=False),
                    now,
                ),
            )
            if cursor.rowcount == 1:
                inserted.append(event)
    return inserted


def _within_window(event_date: str, now: str, window_days: int) -> bool:
    """Real datetime compare (not lexical): event dates may carry times or offsets."""
    event = datetime.fromisoformat(event_date)
    cutoff = datetime.fromisoformat(now) - timedelta(days=window_days)
    # Some sources report bare dates (naive), `now` is tz-aware ISO — strip tzinfo on
    # both sides so the comparison never raises; day precision is all we need here.
    return event.replace(tzinfo=None) >= cutoff.replace(tzinfo=None)


def events_in_window(
    db_path: str,
    *,
    window_days: int,
    now: str,
    tickers: list[str] | None = None,
    exclude_tickers: list[str] | None = None,
) -> dict[str, list[dict]]:
    """Events grouped by ticker whose event_date falls inside the trailing window.

    `tickers` restricts to a candidate list (pitch annotation); `exclude_tickers` inverts
    that for off-watchlist alert clustering. Each event dict carries parsed details.
    """
    init_evidence_db(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT source, ticker, event_key, event_date, details_json"
            " FROM evidence_events ORDER BY event_date DESC, id DESC"
        ).fetchall()
    wanted = {t.upper() for t in tickers} if tickers is not None else None
    unwanted = {t.upper() for t in exclude_tickers} if exclude_tickers is not None else set()
    grouped: dict[str, list[dict]] = {}
    for source, ticker, event_key, event_date, details_json in rows:
        if wanted is not None and ticker.upper() not in wanted:
            continue
        if ticker.upper() in unwanted:
            continue
        if not _within_window(event_date, now, window_days):
            continue
        grouped.setdefault(ticker, []).append(
            {
                "source": source,
                "ticker": ticker,
                "event_key": event_key,
                "event_date": event_date,
                "details": json.loads(details_json),
            }
        )
    return grouped
