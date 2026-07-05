"""Tests for entry-zone derivation and the watchlist builder."""
from __future__ import annotations

from dataclasses import replace

import pytest

from equity_scout.entry import compute_entry_plan
from equity_scout.radar import Watchlist, build_watchlist, entry_zone, zone_note
from tests.test_signals import downtrend_history, stabilized_history


def test_entry_zone_is_ordered_and_at_or_below_anchor():
    plan = compute_entry_plan("AAA", *downtrend_history())
    zone = entry_zone(plan)
    assert zone is not None
    low, high = zone
    assert 0 < low < high
    assert plan.sma200 is None or high <= plan.sma200


def test_entry_zone_low_is_bounded_when_atr_is_oversized():
    plan = compute_entry_plan("AAA", *downtrend_history())
    supports = [lvl.price for lvl in plan.levels if lvl.kind == "support"]
    # An unbounded ATR buffer would push low below zero for deep-drawdown/high-vol names.
    oversized = replace(plan, atr=min(supports) * 2)
    zone = entry_zone(oversized)
    assert zone is not None
    low, high = zone
    assert 0 < low < high
    assert low == round(min(supports) * 0.8, 2)  # buffer capped at 20% below lowest support


def _finalist(ticker: str, bucket: str = "core") -> dict:
    return {
        "ticker": ticker,
        "name": f"{ticker} AG",
        "bucket": bucket,
        "breakdown": {"value": 0.8, "quality": 0.8, "momentum": 0.6, "growth": 0.5},
    }


def test_build_watchlist_sorts_by_composite_and_skips_missing_history():
    histories = {
        "DIP": downtrend_history(),
        "FLAT": stabilized_history(),
        "GONE": ([], [], []),
    }
    wl = build_watchlist(
        [_finalist("DIP"), _finalist("FLAT"), _finalist("GONE")],
        histories,
        created_at="2026-07-04T12:00:00",
    )
    assert isinstance(wl, Watchlist)
    assert wl.created_at == "2026-07-04T12:00:00"
    tickers = [e.ticker for e in wl.entries]
    assert set(tickers) == {"DIP", "FLAT"}
    composites = [e.composite for e in wl.entries]
    assert composites == sorted(composites, reverse=True)
    assert "GONE" in wl.skipped  # honest: missing data is reported, never silently dropped


def test_build_watchlist_skips_non_finite_history_without_crashing():
    # inf passes a naive `c and c > 0` check but leaves <2 usable closes for the entry plan.
    histories = {"BAD": ([float("inf"), 10.0], [float("inf"), 10.1], [float("inf"), 9.9])}
    wl = build_watchlist([_finalist("BAD")], histories, created_at="2026-07-04T12:00:00")
    assert wl.entries == []
    assert wl.skipped["BAD"] == "keine verwertbare Kurshistorie"


def test_watchlist_entry_carries_readings_zone_and_proximity():
    wl = build_watchlist(
        [_finalist("DIP")], {"DIP": downtrend_history()}, created_at="2026-07-04T12:00:00"
    )
    entry = wl.entries[0]
    assert {r.name for r in entry.readings} == {"dip_quality", "value_gap", "momentum"}
    assert entry.entry_zone_low < entry.entry_zone_high
    assert entry.in_zone == (entry.entry_zone_low <= entry.price <= entry.entry_zone_high)
    # proximity: relative distance of price to the zone's upper edge (<= 0 means at/inside)
    assert entry.proximity == round(entry.price / entry.entry_zone_high - 1.0, 4)
    assert entry.breakdown == _finalist("DIP")["breakdown"]


def test_watchlist_entry_carries_dip_tranches():
    """Task 1: the dip tranche plan (now / −7 % / −15 %) rides along on the entry as
    JSON-round-trippable dicts, so the pitch can render a concrete scale-in plan."""
    wl = build_watchlist(
        [_finalist("DIP")], {"DIP": downtrend_history()}, created_at="2026-07-04T12:00:00"
    )
    entry = wl.entries[0]
    assert len(entry.tranches) == 3
    for tranche in entry.tranches:
        assert set(tranche) == {"label", "fraction", "trigger_price"}
    prices = [tranche["trigger_price"] for tranche in entry.tranches]
    assert prices == sorted(prices, reverse=True)  # now > −7 % > −15 %
    assert abs(sum(tranche["fraction"] for tranche in entry.tranches) - 1.0) < 1e-9


def test_zone_note_in_zone_states_the_band():
    assert zone_note(87.0, 85.0, 90.0, True, -0.0333) == "Kurs in der Entry-Zone (85.00–90.00)."


def test_zone_note_below_zone_flags_it():
    assert zone_note(80.0, 85.0, 90.0, False, -0.1111) == (
        "Kurs unter der Entry-Zone — tiefer als die Support-Levels."
    )


def test_zone_note_above_zone_reports_proximity():
    assert zone_note(95.0, 85.0, 90.0, False, 0.0556) == "Kurs +5.6 % über der Entry-Zone."


@pytest.mark.parametrize(
    "price, low, high",
    [
        (87.0, 85.0, 90.0),    # inside the zone
        (80.0, 85.0, 90.0),    # below the zone
        (95.0, 85.0, 90.0),    # above the zone
        (84.95, 85.16, 90.91),  # the exact contradiction case from the review finding
    ],
)
def test_zone_note_never_contradicts_in_zone(price, low, high):
    in_zone = low <= price <= high
    proximity = round(price / high - 1.0, 4)
    note = zone_note(price, low, high, in_zone, proximity)
    assert ("in der Entry-Zone" in note) == in_zone
