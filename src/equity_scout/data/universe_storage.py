"""SQLite snapshot persistence for the constituent universe.

`refresh_universe.py` used to only overwrite `universe_combined.csv`, discarding any record of what
the universe looked like on past dates. That is a survivorship-bias trap: a backtest or the ML
research loop that replays history through *today's* constituent list implicitly assumes today's
survivors were always in the universe (delisted/dropped names never appear). This module snapshots
each refresh with its `as_of` date so past compositions stay recoverable; the CSV remains the
"latest" export the live pipeline reads.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from equity_scout.models import Instrument


def init_universe_db(db_path: str | Path) -> None:
    with sqlite3.connect(db_path) as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS universe_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                as_of TEXT NOT NULL,
                instrument_count INTEGER NOT NULL,
                instruments TEXT NOT NULL,
                UNIQUE (as_of)
            );
            """
        )


def save_universe_snapshot(db_path: str | Path, as_of: str, instruments: list[Instrument]) -> None:
    """Insert one immutable snapshot for `as_of`. Re-running the refresh again on the same date
    replaces that date's snapshot rather than duplicating it (idempotent per day)."""
    payload = json.dumps([asdict(i) for i in instruments])
    with sqlite3.connect(db_path) as con:
        con.execute(
            "INSERT INTO universe_snapshots (as_of, instrument_count, instruments) VALUES (?, ?, ?) "
            "ON CONFLICT(as_of) DO UPDATE SET "
            "instrument_count = excluded.instrument_count, instruments = excluded.instruments",
            (as_of, len(instruments), payload),
        )


def load_latest_universe_snapshot(db_path: str | Path) -> tuple[str, list[Instrument]] | None:
    """The most recent snapshot by `as_of`, or None if none exist yet."""
    with sqlite3.connect(db_path) as con:
        try:
            row = con.execute(
                "SELECT as_of, instruments FROM universe_snapshots ORDER BY as_of DESC LIMIT 1"
            ).fetchone()
        except sqlite3.OperationalError:
            return None
    if row is None:
        return None
    as_of, instruments_json = row
    return as_of, [Instrument(**d) for d in json.loads(instruments_json)]


def load_universe_snapshot(db_path: str | Path, as_of: str) -> list[Instrument] | None:
    """The snapshot for an exact `as_of` date, or None if that date has no snapshot."""
    with sqlite3.connect(db_path) as con:
        try:
            row = con.execute(
                "SELECT instruments FROM universe_snapshots WHERE as_of = ?", (as_of,)
            ).fetchone()
        except sqlite3.OperationalError:
            return None
    return [Instrument(**d) for d in json.loads(row[0])] if row else None
