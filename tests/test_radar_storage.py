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
    return build_watchlist(
        [_finalist("DIP")], {"DIP": downtrend_history()}, created_at="2026-07-04T12:00:00"
    )


def test_save_and_load_latest_watchlist_round_trip(tmp_path):
    db = str(tmp_path / "radar.db")
    save_watchlist(db, _watchlist())
    loaded = load_latest_watchlist(db)
    assert loaded is not None
    assert loaded["created_at"] == "2026-07-04T12:00:00"
    assert loaded["entries"][0]["ticker"] == "DIP"
    assert loaded["entries"][0]["readings"][0]["name"] == "dip_quality"


def test_load_latest_returns_none_on_empty_db(tmp_path):
    db = str(tmp_path / "radar.db")
    init_radar_db(db)
    assert load_latest_watchlist(db) is None


def test_save_appends_signal_readings_rows(tmp_path):
    db = str(tmp_path / "radar.db")
    save_watchlist(db, _watchlist())
    save_watchlist(db, _watchlist())  # second snapshot appends, never overwrites
    with sqlite3.connect(db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM signal_readings").fetchone()[0]
    assert count == 6  # 2 snapshots x 1 ticker x 3 readings
