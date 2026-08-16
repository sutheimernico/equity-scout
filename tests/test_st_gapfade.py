"""Gap-fade lane decision logic: pre-market gap picks, calibration rejections, staleness."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from equity_scout.shortterm_book import LaneBook, buy
from equity_scout.st_gapfade import (
    GAP_THRESHOLD,
    LOG_THRESHOLD,
    MAX_QUOTE_AGE_MINUTES,
    pick_gap_entries,
)

NOW = datetime(2026, 8, 17, 13, 25, tzinfo=timezone.utc)  # 09:25 ET
FRESH = NOW - timedelta(minutes=3)
STALE = NOW - timedelta(minutes=MAX_QUOTE_AGE_MINUTES + 5)


def test_deep_fresh_gap_is_picked_with_its_signal_price() -> None:
    book = LaneBook.fresh("gapfade")
    picks, rejections = pick_gap_entries(
        {"DOWN": (97.0, FRESH)}, {"DOWN": 100.0}, book, now=NOW, traded=set(),
    )
    assert len(picks) == 1 and rejections == []
    assert picks[0]["ticker"] == "DOWN"
    assert picks[0]["signal_price"] == pytest.approx(97.0)
    assert picks[0]["gap"] == pytest.approx(-0.03)
    assert "Fade" in picks[0]["reason"]


def test_below_threshold_gap_lands_in_the_no_trade_book() -> None:
    """The calibration rows Nico asked for: gaps in (-2 %, -1 %] are rejected AND logged,
    so the evening resolution can answer whether -2 % is the right threshold."""
    book = LaneBook.fresh("gapfade")
    picks, rejections = pick_gap_entries(
        {"NEAR": (98.5, FRESH), "TINY": (99.6, FRESH)}, {"NEAR": 100.0, "TINY": 100.0},
        book, now=NOW, traded=set(),
    )
    assert picks == []
    assert [r["ticker"] for r in rejections] == ["NEAR"]  # -0.4 % is no opportunity at all
    assert rejections[0]["reason"] == "below_threshold"
    assert rejections[0]["ref_price"] == pytest.approx(98.5)
    assert "-1.5" in rejections[0]["detail"] or "−1,5" in rejections[0]["detail"]
    assert rejections[0]["seen_at"] == "2026-08-17"  # deterministic day key, time in detail


def test_stale_premarket_quote_is_logged_not_traded() -> None:
    book = LaneBook.fresh("gapfade")
    picks, rejections = pick_gap_entries(
        {"OLD": (95.0, STALE)}, {"OLD": 100.0}, book, now=NOW, traded=set(),
    )
    assert picks == []
    assert rejections[0]["reason"] == "stale_premarket"


def test_cap_takes_the_deepest_gaps_and_logs_the_loser() -> None:
    book = LaneBook.fresh("gapfade")
    premarket = {t: (price, FRESH) for t, price in
                 [("A", 95.0), ("B", 96.0), ("C", 97.0), ("D", 97.5)]}
    prev = {t: 100.0 for t in premarket}
    picks, rejections = pick_gap_entries(premarket, prev, book, now=NOW, traded=set())
    assert [p["ticker"] for p in picks] == ["A", "B", "C"]  # deepest first
    assert [(r["ticker"], r["reason"]) for r in rejections] == [("D", "cap_full")]


def test_held_or_already_traded_tickers_never_double_enter() -> None:
    book = LaneBook.fresh("gapfade")
    book, _ = buy(book, "HELD", 100.0, "t0", fraction=0.1, reason="x")
    picks, rejections = pick_gap_entries(
        {"HELD": (95.0, FRESH), "DONE": (95.0, FRESH)}, {"HELD": 100.0, "DONE": 100.0},
        book, now=NOW, traded={"DONE"},
    )
    assert picks == []
    assert {r["ticker"]: r["reason"] for r in rejections} == {"HELD": "already_held"}


def test_missing_previous_close_is_silent() -> None:
    book = LaneBook.fresh("gapfade")
    picks, rejections = pick_gap_entries(
        {"NOREF": (95.0, FRESH)}, {}, book, now=NOW, traded=set(),
    )
    assert picks == [] and rejections == []


def test_thresholds_keep_their_documented_relation() -> None:
    assert GAP_THRESHOLD < LOG_THRESHOLD < 0
