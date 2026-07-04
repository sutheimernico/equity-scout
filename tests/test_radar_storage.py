"""Round-trip tests for radar persistence (tmp_path SQLite, as in test_storage.py)."""
from __future__ import annotations

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
    save_watchlist(db, wl)
    loaded = load_latest_watchlist(db)
    assert loaded is not None
    assert loaded["created_at"] == "2026-07-04T12:00:00"
    entry = loaded["entries"][0]
    built = wl.entries[0]
    assert entry["ticker"] == "DIP"
    assert entry["readings"][0]["name"] == "dip_quality"
    assert entry["entry_zone_low"] == built.entry_zone_low
    assert entry["entry_zone_high"] == built.entry_zone_high
    assert entry["composite"] == built.composite
    assert loaded["skipped"] == {"GONE": "keine verwertbare Kurshistorie"}


def test_load_latest_returns_none_on_empty_db(tmp_path):
    db = str(tmp_path / "radar.db")
    init_radar_db(db)
    assert load_latest_watchlist(db) is None


def test_save_appends_signal_readings_rows(tmp_path):
    db = str(tmp_path / "radar.db")
    query = "SELECT id, created_at, ticker, signal, score FROM signal_readings ORDER BY id"
    save_watchlist(db, _watchlist())
    with sqlite3.connect(db) as conn:
        first = conn.execute(query).fetchall()
    save_watchlist(db, _watchlist())  # second snapshot appends, never overwrites
    with sqlite3.connect(db) as conn:
        rows = conn.execute(query).fetchall()
    assert len(first) == 3  # 1 scored ticker x 3 readings
    assert len(rows) == 6  # 2 snapshots x 1 ticker x 3 readings
    # Append-only contract (Phase-4 training data): originals untouched, new rows appended after.
    assert rows[: len(first)] == first
    assert all(row[0] > first[-1][0] for row in rows[len(first) :])
