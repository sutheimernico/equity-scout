"""Tests for entry-zone derivation and the watchlist builder."""
from __future__ import annotations

from equity_scout.entry import compute_entry_plan
from equity_scout.radar import Watchlist, build_watchlist, entry_zone
from tests.test_signals import downtrend_history, stabilized_history


def test_entry_zone_is_ordered_and_at_or_below_anchor():
    plan = compute_entry_plan("AAA", *downtrend_history())
    zone = entry_zone(plan)
    assert zone is not None
    low, high = zone
    assert 0 < low < high
    assert plan.sma200 is None or high <= plan.sma200


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


def test_watchlist_entry_carries_readings_zone_and_proximity():
    wl = build_watchlist(
        [_finalist("DIP")], {"DIP": downtrend_history()}, created_at="2026-07-04T12:00:00"
    )
    entry = wl.entries[0]
    assert {r.name for r in entry.readings} == {"dip_quality", "value_gap", "momentum"}
    assert entry.entry_zone_low < entry.entry_zone_high
    assert entry.in_zone == (entry.entry_zone_low <= entry.price <= entry.entry_zone_high)
    # proximity: relative distance of price to the zone's upper edge (<= 0 means at/inside)
    assert abs(entry.proximity - (entry.price / entry.entry_zone_high - 1.0)) < 1e-9
