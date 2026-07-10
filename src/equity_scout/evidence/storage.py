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


def init_alerts_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Evidence alerts live OUTSIDE the decision inbox: they carry no price, no entry
    zone, no composite and no decision buttons — a separate table keeps the inbox's
    NOT-NULL screener contract intact instead of faking zeros into it."""
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS evidence_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                ticker TEXT NOT NULL,
                reasons_json TEXT NOT NULL,
                text TEXT NOT NULL,
                telegram_message_id INTEGER
            )"""
        )


def record_alert(
    db_path: str,
    *,
    ticker: str,
    reasons: list[str],
    text: str,
    telegram_message_id: int | None,
    now: str,
) -> int:
    init_alerts_db(db_path)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO evidence_alerts"
            " (created_at, ticker, reasons_json, text, telegram_message_id)"
            " VALUES (?, ?, ?, ?, ?)",
            (now, ticker, json.dumps(reasons, ensure_ascii=False), text,
             telegram_message_id),
        )
        return int(cursor.lastrowid or 0)


def set_alert_message_id(db_path: str, alert_id: int, message_id: int) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE evidence_alerts SET telegram_message_id = ? WHERE id = ?",
            (message_id, alert_id),
        )


def last_alert_at(db_path: str, ticker: str) -> str | None:
    """Cooldown source for alerts, mirroring inbox_storage.last_pitch_at."""
    init_alerts_db(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT created_at FROM evidence_alerts WHERE ticker = ?"
            " ORDER BY created_at DESC LIMIT 1",
            (ticker,),
        ).fetchone()
    return row[0] if row else None


def load_alerts(db_path: str, *, limit: int = 50) -> list[dict]:
    """Newest-first alert rows for the API/dashboard and tests."""
    init_alerts_db(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, created_at, ticker, reasons_json, text, telegram_message_id"
            " FROM evidence_alerts ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "id": row[0],
            "created_at": row[1],
            "ticker": row[2],
            "reasons": json.loads(row[3]),
            "text": row[4],
            "telegram_message_id": row[5],
        }
        for row in rows
    ]


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
