"""Round-trip tests for radar persistence (tmp_path SQLite, as in test_storage.py)."""
from __future__ import annotations

import json
import sqlite3

from equity_scout.radar import build_watchlist
from equity_scout.radar_storage import (
    init_radar_db,
    load_latest_watchlist,
    save_watchlist,
)
from tests.test_radar import _finalist
from tests.test_signals import downtrend_history


def _watchlist():
    # GONE has no history: exercises the `skipped` field through the persistence round trip.
    return build_watchlist(
        [_finalist("DIP"), _finalist("GONE")],
        {"DIP": downtrend_history(), "GONE": ([], [], [])},
        created_at="2026-07-04T12:00:00",
    )


def test_save_and_load_latest_watchlist_round_trip(tmp_path):
    db = str(tmp_path / "radar.db")
    wl = _watchlist()
    snapshot_id = save_watchlist(db, wl)
    loaded = load_latest_watchlist(db)
    assert loaded is not None
    assert loaded["created_at"] == "2026-07-04T12:00:00"
    # The loaded dict carries its snapshot row id so downstream consumers (notify.py)
    # can FK pitches to the exact watchlist they were selected from.
    assert loaded["watchlist_id"] == snapshot_id
    entry = loaded["entries"][0]
    built = wl.entries[0]
    assert entry["ticker"] == "DIP"
    assert entry["readings"][0]["name"] == "dip_quality"
    assert entry["entry_zone_low"] == built.entry_zone_low
    assert entry["entry_zone_high"] == built.entry_zone_high
    assert entry["composite"] == built.composite
    assert entry["breakdown"] == built.breakdown
    assert loaded["skipped"] == {"GONE": "keine verwertbare Kurshistorie"}

    # Every reading is FK'd to the snapshot it was read from, and carries the finalist's
    # full funnel breakdown as JSON (spec §5.2: market context for the ML combiner).
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT watchlist_id, breakdown FROM signal_readings WHERE ticker = 'DIP'"
        ).fetchall()
    assert rows
    assert all(watchlist_id == snapshot_id for watchlist_id, _ in rows)
    assert all(json.loads(breakdown) == built.breakdown for _, breakdown in rows)


def test_load_latest_returns_none_on_empty_db(tmp_path):
    db = str(tmp_path / "radar.db")
    init_radar_db(db)
    assert load_latest_watchlist(db) is None


def test_save_appends_signal_readings_rows(tmp_path):
    db = str(tmp_path / "radar.db")
    query = (
        "SELECT id, created_at, ticker, signal, score, watchlist_id"
        " FROM signal_readings ORDER BY id"
    )
    first_snapshot_id = save_watchlist(db, _watchlist())
    with sqlite3.connect(db) as conn:
        first = conn.execute(query).fetchall()
    second_snapshot_id = save_watchlist(db, _watchlist())  # second snapshot appends, never overwrites
    with sqlite3.connect(db) as conn:
        rows = conn.execute(query).fetchall()
    assert len(first) == 3  # 1 scored ticker x 3 readings
    assert len(rows) == 6  # 2 snapshots x 1 ticker x 3 readings
    # Append-only contract (Phase-4 training data): originals untouched, new rows appended after.
    assert rows[: len(first)] == first
    assert all(row[0] > first[-1][0] for row in rows[len(first) :])
    # Each batch of readings is FK'd to the snapshot it belongs to.
    assert first_snapshot_id != second_snapshot_id
    assert all(row[5] == first_snapshot_id for row in first)
    assert all(row[5] == second_snapshot_id for row in rows[len(first) :])


def test_init_radar_db_migrates_pre_watchlist_id_breakdown_schema(tmp_path):
    """A DB whose signal_readings predates watchlist_id/breakdown must not crash init or save."""
    db = str(tmp_path / "old-schema.db")
    with sqlite3.connect(db) as conn:
        conn.execute(
            """CREATE TABLE signal_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                ticker TEXT NOT NULL,
                signal TEXT NOT NULL,
                score REAL NOT NULL,
                price REAL NOT NULL,
                reason TEXT NOT NULL
            )"""
        )
        conn.execute(
            "INSERT INTO signal_readings (created_at, ticker, signal, score, price, reason)"
            " VALUES ('2026-01-01T00:00:00', 'OLD', 'dip_quality', 0.5, 10.0, 'legacy row')"
        )

    init_radar_db(db)
    with sqlite3.connect(db) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(signal_readings)")]
    assert "watchlist_id" in cols
    assert "breakdown" in cols

    snapshot_id = save_watchlist(db, _watchlist())  # must succeed against the migrated table
    with sqlite3.connect(db) as conn:
        legacy_row = conn.execute(
            "SELECT watchlist_id, breakdown FROM signal_readings WHERE ticker = 'OLD'"
        ).fetchone()
        new_rows = conn.execute(
            "SELECT watchlist_id FROM signal_readings WHERE ticker != 'OLD'"
        ).fetchall()
    assert legacy_row == (None, None)  # pre-migration row keeps NULL, untouched
    assert all(watchlist_id == snapshot_id for (watchlist_id,) in new_rows)
