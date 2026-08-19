"""Tests for the ignition lane's decision logic (catalyst radar, layer 4).

The numbers in the fixtures are the real ones from 2026-08-19 — MRNA's spread of 400 bp and
its +136 % day move are what the chase protection and the limit pricing have to handle.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from equity_scout import st_ignition as ig
from equity_scout.shortterm_book import LaneBook, LanePosition

NOW = datetime(2026, 8, 19, 17, 0, tzinfo=timezone.utc)  # 13:00 ET, mid-session


def _book(**positions: LanePosition) -> LaneBook:
    return LaneBook(lane=ig.LANE, initial_capital=10_000.0, cash=10_000.0,
                    benchmark_ticker="SPY", positions=dict(positions))


def _signal(ticker="ABCD", *, score=0.8, move=0.15, volume_ratio=8.0, kind="ignition_up",
            signal_id=1) -> dict:
    return {"id": signal_id, "ticker": ticker, "kind": kind, "score": score,
            "change_pct": move, "volume_ratio": volume_ratio, "ref_price": 20.0}


def _quote(bid=19.9, ask=20.1, spread_bp=100.0) -> dict:
    return {"bid": bid, "ask": ask, "bid_size": 500, "ask_size": 500,
            "spread_bp": spread_bp}


# --- limit pricing: the module's whole cost defence ---------------------------------------

def test_limit_sits_inside_the_spread_not_at_the_ask():
    """MRNA's real quote on the day: bid 138.00 / ask 143.63 (400 bp).

    Crossing costs the full spread; offering a quarter of it costs a quarter. If it is not
    hit, we do not own the stock — the cheapest possible outcome.
    """
    offer = ig.limit_price(138.00, 143.63)
    assert 138.00 < offer < 143.63
    assert offer == pytest.approx(139.41, abs=0.01)  # bid + 25 % of a 5.63 spread


def test_limit_price_refuses_unusable_quotes():
    assert ig.limit_price(0.0, 10.0) == 0.0
    assert ig.limit_price(10.0, 10.0) == 0.0   # zero spread means no book
    assert ig.limit_price(11.0, 10.0) == 0.0   # crossed


def test_bracket_levels_put_the_stop_below_and_the_target_far_away():
    """The take-profit leg is a runaway backstop, not the intended exit — the trail is."""
    stop, target = ig.target_prices(100.0)
    assert stop == pytest.approx(100.0 * (1 - ig.STOP_LOSS), abs=0.01)
    assert target > 100.0 * (1 + ig.TRAIL_PCT)


# --- the four rules that keep it from being a chase --------------------------------------

def test_chase_protection_refuses_a_move_that_already_ran():
    """The Moderna case itself: +136 % is not participation, it is exit liquidity."""
    picks, rejections = ig.pick_entries(
        [_signal("MRNA", move=1.36, score=0.93)], {"MRNA": _quote()}, _book(),
        now=NOW, entries_today=0, traded_today=set(),
    )
    assert not picks
    assert rejections[0]["reason"] == "chase_protection"


def test_a_move_inside_the_window_is_entered():
    picks, rejections = ig.pick_entries(
        [_signal(move=0.15)], {"ABCD": _quote()}, _book(),
        now=NOW, entries_today=0, traded_today=set(),
    )
    assert not rejections
    assert picks[0]["ticker"] == "ABCD"
    assert picks[0]["limit_price"] == pytest.approx(19.95, abs=0.01)
    assert picks[0]["stop_price"] < picks[0]["limit_price"]
    assert picks[0]["signal_id"] == 1


def test_faded_volume_blocks_the_entry():
    """The scan verified the move a minute ago; by order time it must still be carried."""
    _, rejections = ig.pick_entries(
        [_signal(volume_ratio=1.2)], {"ABCD": _quote()}, _book(),
        now=NOW, entries_today=0, traded_today=set(),
    )
    assert rejections[0]["reason"] == "volume_faded"


def test_wide_spread_blocks_the_entry_more_strictly_than_the_scan():
    """The scan's 600 bp is a sight threshold; trading needs 250 bp. MRNA at 400 bp is seen
    but not bought — exactly the asymmetry the radar is designed around."""
    _, rejections = ig.pick_entries(
        [_signal()], {"ABCD": _quote(spread_bp=400.0)}, _book(),
        now=NOW, entries_today=0, traded_today=set(),
    )
    assert rejections[0]["reason"] == "spread_too_wide"
    assert ig.MAX_SPREAD_BP_AT_ENTRY < 600.0


def test_weak_signals_are_not_traded():
    _, rejections = ig.pick_entries(
        [_signal(score=0.3)], {"ABCD": _quote()}, _book(),
        now=NOW, entries_today=0, traded_today=set(),
    )
    assert rejections[0]["reason"] == "score_too_low"


def test_downward_ignitions_are_never_bought():
    """A crash is recorded by the radar for sight. This lane is long-only."""
    picks, rejections = ig.pick_entries(
        [_signal(kind="ignition_down", move=-0.3)], {"ABCD": _quote()}, _book(),
        now=NOW, entries_today=0, traded_today=set(),
    )
    assert not picks and not rejections  # silently skipped, not a rejection


# --- caps ---------------------------------------------------------------------------------

def test_position_cap_is_respected():
    full = _book(**{f"T{i}": LanePosition(qty=1, entry_price=10.0, opened_at=NOW.isoformat())
                    for i in range(ig.MAX_POSITIONS)})
    _, rejections = ig.pick_entries(
        [_signal()], {"ABCD": _quote()}, full,
        now=NOW, entries_today=0, traded_today=set(),
    )
    assert rejections[0]["reason"] == "cap_full"


def test_daily_entry_cap_is_respected():
    """Without it, one wild session could put the whole book into ignition names in an hour."""
    _, rejections = ig.pick_entries(
        [_signal()], {"ABCD": _quote()}, _book(),
        now=NOW, entries_today=ig.MAX_ENTRIES_PER_DAY, traded_today=set(),
    )
    assert rejections[0]["reason"] == "daily_cap"


def test_already_held_and_already_traded_today_are_not_re_entered():
    held = _book(ABCD=LanePosition(qty=5, entry_price=20.0, opened_at=NOW.isoformat()))
    _, rejections = ig.pick_entries(
        [_signal()], {"ABCD": _quote()}, held,
        now=NOW, entries_today=0, traded_today=set(),
    )
    assert rejections[0]["reason"] == "already_held"

    picks, rejections = ig.pick_entries(
        [_signal()], {"ABCD": _quote()}, _book(),
        now=NOW, entries_today=0, traded_today={"ABCD"},
    )
    assert not picks and not rejections  # day marker already tells the story


def test_missing_quote_blocks_the_entry():
    _, rejections = ig.pick_entries(
        [_signal()], {}, _book(), now=NOW, entries_today=0, traded_today=set(),
    )
    assert rejections[0]["reason"] == "no_quote"


def test_strongest_signal_takes_the_last_slot():
    """Signals arrive score-sorted; the cap must not hand the slot to a weaker one."""
    three_held = _book(**{f"T{i}": LanePosition(qty=1, entry_price=10.0,
                                               opened_at=NOW.isoformat())
                          for i in range(ig.MAX_POSITIONS - 1)})
    picks, _ = ig.pick_entries(
        [_signal("STRONG", score=0.9), _signal("WEAKER", score=0.6, signal_id=2)],
        {"STRONG": _quote(), "WEAKER": _quote()}, three_held,
        now=NOW, entries_today=0, traded_today=set(),
    )
    assert [p["ticker"] for p in picks] == ["STRONG"]


# --- exits --------------------------------------------------------------------------------

def _held(entry: float, opened: datetime) -> LaneBook:
    return _book(ABCD=LanePosition(qty=10, entry_price=entry, opened_at=opened.isoformat()))


def test_hard_stop_fires():
    exits = ig.pick_exits(_held(100.0, NOW), {"ABCD": 91.0}, {"ABCD": 100.0}, now=NOW)
    assert exits and "Stop" in exits[0]["reason"]


def test_trailing_stop_fires_from_the_high_water_mark():
    """Entry 100, peak 150, now 134 — down 10.7 % from the peak but still +34 % on the trade.
    The trail is what takes the profit; there is no fixed target."""
    exits = ig.pick_exits(_held(100.0, NOW), {"ABCD": 134.0}, {"ABCD": 150.0}, now=NOW)
    assert exits
    assert "Trailing-Stop" in exits[0]["reason"]
    assert exits[0]["return_pct"] == pytest.approx(0.34, abs=0.01)


def test_trailing_stop_does_not_fire_below_the_entry():
    """A position that never rose has no trail to give back — the hard stop owns that case."""
    exits = ig.pick_exits(_held(100.0, NOW), {"ABCD": 95.0}, {"ABCD": 100.0}, now=NOW)
    assert not exits


def test_time_stop_fires():
    old = NOW - timedelta(days=ig.MAX_HOLD_DAYS + 1)
    exits = ig.pick_exits(_held(100.0, old), {"ABCD": 101.0}, {"ABCD": 101.0}, now=NOW)
    assert exits and "Zeitstop" in exits[0]["reason"]


def test_a_winner_inside_all_rules_is_held():
    exits = ig.pick_exits(_held(100.0, NOW), {"ABCD": 145.0}, {"ABCD": 150.0}, now=NOW)
    assert not exits


def test_position_without_a_price_is_held_untouched():
    """House stance across every lane: you cannot honestly value a sale you have no price for."""
    assert ig.pick_exits(_held(100.0, NOW), {}, {"ABCD": 150.0}, now=NOW) == []


# --- high-water bookkeeping ---------------------------------------------------------------

def test_high_water_rises_and_never_falls():
    marks = ig.update_high_water({"ABCD": 150.0}, {"ABCD": 140.0}, {"ABCD"})
    assert marks["ABCD"] == 150.0
    marks = ig.update_high_water(marks, {"ABCD": 160.0}, {"ABCD"})
    assert marks["ABCD"] == 160.0


def test_high_water_is_dropped_for_closed_positions():
    assert ig.update_high_water({"GONE": 10.0}, {}, set()) == {}


def test_new_position_seeds_its_own_mark():
    assert ig.update_high_water({}, {"NEW": 42.0}, {"NEW"}) == {"NEW": 42.0}


# --- guards --------------------------------------------------------------------------------

def test_no_new_entries_just_before_the_close():
    late = datetime(2026, 8, 19, 19, 55, tzinfo=timezone.utc)  # 15:55 ET
    assert ig.market_closing_soon(late)
    assert not ig.market_closing_soon(NOW)


def test_stop_criterion_triggers_at_sixty_closed_trades():
    assert not ig.stop_criterion_reached(59)
    assert ig.stop_criterion_reached(60)


def test_leverage_stays_at_one_times_until_a_verdict_exists():
    """Documented decision, pinned as a test: the account allows 4x, the lane uses 1x.

    ENTRY_FRACTION * MAX_POSITIONS <= 1.0 means the book can never be more than fully
    invested from its own cash — no margin, whatever the broker would permit.
    """
    assert ig.ENTRY_FRACTION * ig.MAX_POSITIONS <= 1.0


def test_empty_input_is_a_no_op():
    assert ig.pick_entries([], {}, _book(), now=NOW, entries_today=0,
                           traded_today=set()) == ([], [])
