"""Earnings-calendar persistence: upsert per (ticker, earnings_date), range query."""
from __future__ import annotations

import sqlite3

from equity_scout.earnings_storage import (
    earnings_within,
    init_earnings_db,
    next_earnings,
    save_earnings_dates,
)


def test_save_and_query_within_window(tmp_path):
    db = str(tmp_path / "earnings.db")
    save_earnings_dates(db, "AAPL", ["2026-07-22"], fetched_on="2026-07-15T06:00:00+00:00")
    save_earnings_dates(db, "MSFT", ["2026-08-01"], fetched_on="2026-07-15T06:00:00+00:00")

    rows = earnings_within(db, today="2026-07-15", days=7)
    assert rows == [{"ticker": "AAPL", "earnings_date": "2026-07-22"}]


def test_within_window_is_inclusive_of_both_ends(tmp_path):
    db = str(tmp_path / "earnings.db")
    save_earnings_dates(db, "TODAY", ["2026-07-15"], fetched_on="2026-07-15T06:00:00+00:00")
    save_earnings_dates(db, "EDGE", ["2026-07-22"], fetched_on="2026-07-15T06:00:00+00:00")
    save_earnings_dates(db, "PAST", ["2026-07-14"], fetched_on="2026-07-15T06:00:00+00:00")
    save_earnings_dates(db, "TOO_FAR", ["2026-07-23"], fetched_on="2026-07-15T06:00:00+00:00")

    rows = earnings_within(db, today="2026-07-15", days=7)
    assert {r["ticker"] for r in rows} == {"TODAY", "EDGE"}


def test_within_window_sorted_by_date_then_ticker(tmp_path):
    db = str(tmp_path / "earnings.db")
    save_earnings_dates(db, "ZZZ", ["2026-07-16"], fetched_on="2026-07-15T06:00:00+00:00")
    save_earnings_dates(db, "AAA", ["2026-07-16"], fetched_on="2026-07-15T06:00:00+00:00")
    save_earnings_dates(db, "MID", ["2026-07-15"], fetched_on="2026-07-15T06:00:00+00:00")

    rows = earnings_within(db, today="2026-07-15", days=7)
    assert [(r["ticker"], r["earnings_date"]) for r in rows] == [
        ("MID", "2026-07-15"), ("AAA", "2026-07-16"), ("ZZZ", "2026-07-16"),
    ]


def test_save_upserts_per_ticker_and_date(tmp_path):
    """Re-fetching the same (ticker, date) updates fetched_on, never duplicates the row."""
    db = str(tmp_path / "earnings.db")
    save_earnings_dates(db, "AAPL", ["2026-07-22"], fetched_on="2026-07-14T06:00:00+00:00")
    save_earnings_dates(db, "AAPL", ["2026-07-22"], fetched_on="2026-07-15T06:00:00+00:00")

    with sqlite3.connect(db) as con:
        rows = con.execute(
            "SELECT ticker, earnings_date, fetched_on FROM earnings_dates"
        ).fetchall()
    assert rows == [("AAPL", "2026-07-22", "2026-07-15T06:00:00+00:00")]


def test_save_multiple_dates_for_same_ticker_keeps_both(tmp_path):
    db = str(tmp_path / "earnings.db")
    save_earnings_dates(
        db, "AAPL", ["2026-07-22", "2026-10-24"], fetched_on="2026-07-15T06:00:00+00:00"
    )
    with sqlite3.connect(db) as con:
        rows = con.execute(
            "SELECT earnings_date FROM earnings_dates WHERE ticker = 'AAPL' ORDER BY earnings_date"
        ).fetchall()
    assert rows == [("2026-07-22",), ("2026-10-24",)]


def test_save_empty_dates_is_a_noop(tmp_path):
    """An empty fetch result (ticker has no known upcoming earnings) never touches
    previously-stored dates for that ticker — an honest gap in THIS run's data must
    not erase a date learned in an earlier run."""
    db = str(tmp_path / "earnings.db")
    save_earnings_dates(db, "AAPL", ["2026-07-22"], fetched_on="2026-07-14T06:00:00+00:00")
    save_earnings_dates(db, "AAPL", [], fetched_on="2026-07-15T06:00:00+00:00")

    with sqlite3.connect(db) as con:
        rows = con.execute("SELECT ticker FROM earnings_dates").fetchall()
    assert rows == [("AAPL",)]


def test_earnings_within_empty_when_table_not_created_yet(tmp_path):
    db = str(tmp_path / "fresh.db")
    assert earnings_within(db, today="2026-07-15", days=7) == []


def test_init_earnings_db_is_idempotent(tmp_path):
    db = str(tmp_path / "earnings.db")
    init_earnings_db(db)
    init_earnings_db(db)  # must not raise on a second call
    assert earnings_within(db, today="2026-07-15", days=7) == []


def test_next_earnings_returns_earliest_upcoming_for_ticker(tmp_path):
    db = str(tmp_path / "earnings.db")
    save_earnings_dates(db, "MU", ["2026-12-18", "2026-09-25"], fetched_on="2026-08-07T06:00:00+00:00")
    save_earnings_dates(db, "ASML", ["2026-08-20"], fetched_on="2026-08-07T06:00:00+00:00")

    assert next_earnings(db, ticker="MU", today="2026-08-07") == "2026-09-25"


def test_next_earnings_skips_past_dates_and_includes_today(tmp_path):
    db = str(tmp_path / "earnings.db")
    save_earnings_dates(db, "MU", ["2026-09-25", "2026-12-18"], fetched_on="2026-08-07T06:00:00+00:00")

    assert next_earnings(db, ticker="MU", today="2026-10-01") == "2026-12-18"
    assert next_earnings(db, ticker="MU", today="2026-09-25") == "2026-09-25"


def test_next_earnings_none_for_unknown_ticker(tmp_path):
    db = str(tmp_path / "earnings.db")
    save_earnings_dates(db, "MU", ["2026-09-25"], fetched_on="2026-08-07T06:00:00+00:00")

    assert next_earnings(db, ticker="NVDA", today="2026-08-07") is None


def test_next_earnings_none_when_table_not_created_yet(tmp_path):
    db = str(tmp_path / "fresh.db")
    assert next_earnings(db, ticker="MU", today="2026-08-07") is None
