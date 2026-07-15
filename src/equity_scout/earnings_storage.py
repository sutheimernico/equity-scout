"""SQLite persistence for the earnings calendar (Strang B1).

One flat table, upsert per (ticker, earnings_date): re-fetching the same known date just
updates ``fetched_on`` rather than duplicating a row — this is a current-snapshot table
(what we currently believe the upcoming dates are), not an append-only log like
radar_storage's signal_readings. CREATE TABLE IF NOT EXISTS, same idiom as forward_storage
and radar_storage — an existing equity_scout.db just gains this table on first use.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path


def init_earnings_db(db_path: str | Path) -> None:
    with sqlite3.connect(db_path) as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS earnings_dates (
                ticker TEXT NOT NULL,
                earnings_date TEXT NOT NULL,
                fetched_on TEXT NOT NULL,
                PRIMARY KEY (ticker, earnings_date)
            )"""
        )


def save_earnings_dates(
    db_path: str | Path, ticker: str, dates: list[str], *, fetched_on: str
) -> None:
    """Upsert ``ticker``'s known upcoming earnings dates.

    An empty ``dates`` list is a no-op: yfinance's calendar coverage can honestly be empty
    for a run (rate limit, no coverage yet) without meaning the previously-learned date is
    wrong — never delete what an earlier successful fetch established.
    """
    if not dates:
        return
    init_earnings_db(db_path)
    with sqlite3.connect(db_path) as con:
        con.executemany(
            "INSERT INTO earnings_dates (ticker, earnings_date, fetched_on) VALUES (?, ?, ?) "
            "ON CONFLICT(ticker, earnings_date) DO UPDATE SET fetched_on = excluded.fetched_on",
            [(ticker, d, fetched_on) for d in dates],
        )


def earnings_within(db_path: str | Path, *, today: str, days: int) -> list[dict]:
    """Known earnings dates in [today, today + days] (inclusive), across all tickers.

    Sorted by date then ticker. Returns [] if the table does not exist yet (no
    scripts/run_earnings.py run so far) — same "not-yet-initialised" honesty as
    forward_storage's OperationalError guards, not an error.
    """
    end = (date.fromisoformat(today) + timedelta(days=days)).isoformat()
    with sqlite3.connect(db_path) as con:
        try:
            rows = con.execute(
                "SELECT ticker, earnings_date FROM earnings_dates "
                "WHERE earnings_date >= ? AND earnings_date <= ? "
                "ORDER BY earnings_date ASC, ticker ASC",
                (today, end),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [{"ticker": t, "earnings_date": d} for t, d in rows]
