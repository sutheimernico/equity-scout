"""Arena runner: both lanes advanced in one run against ONE shared price fetch.

No network — fetch_price is injected (run_lanes) or _fetch_spot is monkeypatched (main).
"""
from __future__ import annotations

import sys
from collections.abc import Callable

import pytest

import scripts.run_lanes as run_lanes_mod
from equity_scout.inbox_storage import create_pitch, decide_pitch
from equity_scout.lane_storage import (
    load_lane_portfolio,
    load_lane_trades,
    load_lane_valuations,
)
from equity_scout.lanes import LANE_AUTOPILOT, LANE_NICO, ExitRules
from equity_scout.radar import Watchlist, WatchlistEntry
from equity_scout.radar_storage import save_watchlist
from equity_scout.signals import SignalReading
from scripts.run_lanes import LaneParams, main, run_lanes

NOW = "2026-07-05T14:00:00+00:00"


def _prices(mapping: dict[str, float]) -> Callable[[str], float | None]:
    return lambda ticker: mapping.get(ticker)


def _seed_watchlist(db: str, ticker: str = "CAND", composite: float = 0.6) -> int:
    entry = WatchlistEntry(
        ticker=ticker,
        name=f"{ticker} Corp",
        bucket="core",
        price=100.0,
        entry_zone_low=95.0,
        entry_zone_high=105.0,
        proximity=-0.05,
        in_zone=True,
        composite=composite,
        readings=[SignalReading("dip_quality", 0.5, "Grund.")],
        zone_note="Kurs in der Entry-Zone (95.00–105.00).",
        breakdown={"value": 0.5, "quality": 0.5, "momentum": 0.5, "growth": 0.5},
    )
    return save_watchlist(db, Watchlist(created_at=NOW, entries=[entry]))


def _seed_buy_pitch(db: str, ticker: str = "PICK") -> int:
    pitch_id = create_pitch(
        db, ticker=ticker, watchlist_id=1, price=90.0, composite=0.7,
        zone_low=85.0, zone_high=95.0, pitch="P", created_at="2026-07-04T10:00:00+00:00",
    )
    decide_pitch(db, pitch_id, "buy", decided_at="2026-07-04T11:00:00+00:00")
    return pitch_id


def test_run_lanes_end_to_end_buys_both_queues(tmp_path):
    db = str(tmp_path / "arena.db")
    _seed_watchlist(db, ticker="CAND")
    pitch_id = _seed_buy_pitch(db, ticker="PICK")

    summary = run_lanes(
        db,
        now=NOW,
        fetch_price=_prices({"PICK": 90.0, "CAND": 100.0, "SPY": 400.0}),
        params=LaneParams(rules=ExitRules()),
        threshold=0.45,
    )

    # Lane nico executes only Nico's approved pitch; the trade row carries pitch_id.
    nico_trades = load_lane_trades(db, LANE_NICO)
    assert [(t["ticker"], t["side"], t["pitch_id"]) for t in nico_trades] == [
        ("PICK", "buy", pitch_id)
    ]
    # Lane autopilot buys the in-zone watchlist candidate autonomously (no pitch link).
    auto_trades = load_lane_trades(db, LANE_AUTOPILOT)
    assert [(t["ticker"], t["side"], t["pitch_id"]) for t in auto_trades] == [
        ("CAND", "buy", None)
    ]

    for lane in (LANE_NICO, LANE_AUTOPILOT):
        vals = load_lane_valuations(db, lane)
        assert len(vals) == 1 and vals[0]["valued_on"] == NOW[:10]
        assert load_lane_portfolio(db, lane) is not None

    # Benchmark shares are initialised from the shared SPY price, so "vs SPY" is real, not flat.
    assert load_lane_portfolio(db, LANE_NICO).benchmark_shares > 0
    assert summary[LANE_NICO]["buys"] == 1 and summary[LANE_AUTOPILOT]["buys"] == 1


def test_run_lanes_idempotent_same_day(tmp_path):
    db = str(tmp_path / "arena.db")
    _seed_watchlist(db, ticker="CAND")
    _seed_buy_pitch(db, ticker="PICK")
    kwargs = dict(
        now=NOW,
        fetch_price=_prices({"PICK": 90.0, "CAND": 100.0, "SPY": 400.0}),
        params=LaneParams(rules=ExitRules()),
        threshold=0.45,
    )

    run_lanes(db, **kwargs)
    run_lanes(db, **kwargs)  # same day: pitch already executed, candidate already held

    assert len(load_lane_trades(db, LANE_NICO)) == 1  # no duplicate buy
    assert len(load_lane_trades(db, LANE_AUTOPILOT)) == 1
    for lane in (LANE_NICO, LANE_AUTOPILOT):
        assert len(load_lane_valuations(db, lane)) == 1  # one row per lane+day (replaced)


def test_run_lanes_empty_no_watchlist_no_pitches(tmp_path):
    db = str(tmp_path / "arena.db")
    summary = run_lanes(
        db,
        now=NOW,
        fetch_price=_prices({"SPY": 400.0}),
        params=LaneParams(rules=ExitRules()),
        threshold=0.45,
    )
    for lane in (LANE_NICO, LANE_AUTOPILOT):
        assert load_lane_trades(db, lane) == []
        assert len(load_lane_valuations(db, lane)) == 1  # valuation still recorded
        assert load_lane_portfolio(db, lane) is not None
    assert summary[LANE_NICO] == {
        "buys": 0, "sells": 0, "total_value": 10_000.0, "total_return": 0.0,
        "benchmark_return": 0.0,
    }


def test_benchmark_shares_persist_across_runs(tmp_path):
    """vs-SPY anchors to inception: benchmark_shares are set once and never re-initialised,
    even after SPY moves. A regression that re-inits each run would flip this — the most
    money-adjacent property in the arena.
    """
    db = str(tmp_path / "arena.db")
    day1 = "2026-07-05T14:00:00+00:00"
    day2 = "2026-07-06T14:00:00+00:00"
    params = LaneParams(rules=ExitRules())

    run_lanes(db, now=day1, fetch_price=_prices({"SPY": 400.0}), params=params, threshold=0.45)
    shares_after_day1 = load_lane_portfolio(db, LANE_NICO).benchmark_shares
    assert shares_after_day1 == 10_000.0 / 400.0  # 25.0, bought once at inception

    # SPY moves +10% on day 2 — benchmark_shares must NOT re-initialise to 10_000/440.
    run_lanes(db, now=day2, fetch_price=_prices({"SPY": 440.0}), params=params, threshold=0.45)
    assert load_lane_portfolio(db, LANE_NICO).benchmark_shares == shares_after_day1

    day2_val = load_lane_valuations(db, LANE_NICO)[-1]  # oldest -> newest
    assert day2_val["valued_on"] == "2026-07-06"
    assert day2_val["benchmark_return"] == pytest.approx(0.10)  # +10% held from inception


def test_main_happy_path_exits_zero(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "arena.db")
    _seed_watchlist(db, ticker="CAND")
    _seed_buy_pitch(db, ticker="PICK")
    prices = {"PICK": 90.0, "CAND": 100.0, "SPY": 400.0}
    monkeypatch.setattr(run_lanes_mod, "_fetch_spot", lambda ticker: prices.get(ticker))
    monkeypatch.setattr(sys, "argv", ["run_lanes.py", "--db", db, "--threshold", "0.45"])

    assert main() == 0

    out = capsys.readouterr().out
    assert "Lane nico" in out and "Lane autopilot" in out
    assert load_lane_trades(db, LANE_NICO)[0]["ticker"] == "PICK"
