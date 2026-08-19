"""Tests for the catalyst radar's layer 1 (ignition scan) and its signal book.

The fixtures are not invented: every symbol below is a real row from the live Alpaca
screener/snapshot/quote responses of 2026-08-19, the day Moderna jumped 127 %. That day
produced exactly the failure modes this module has to survive, so they are the test cases.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from equity_scout import catalyst_scan as cs
from equity_scout.catalyst_storage import (
    SOURCE_SCAN,
    init_catalyst_db,
    last_alert_at,
    load_signals,
    mark_alerted,
    mark_traded,
    record_rejections,
    record_signals,
    stats,
)

NOW = datetime(2026, 8, 19, 16, 40, tzinfo=timezone.utc)


def _assets(**overrides: dict) -> dict[str, dict]:
    base = {
        "MRNA": {"name": "Moderna, Inc. Common Stock", "exchange": "NASDAQ",
                 "tradable": True, "fractionable": True, "shortable": True},
        "FIXX": {"name": "Leverage Shares 2X Long FIX Daily ETF", "exchange": "BATS",
                 "tradable": True, "fractionable": False, "shortable": False},
        "TNONW": {"name": "Tenon Medical, Inc. Warrant", "exchange": "NASDAQ",
                  "tradable": True, "fractionable": False, "shortable": False},
        "ZSTK": {"name": "ZSpace Technologies Inc Common Stock", "exchange": "NASDAQ",
                 "tradable": True, "fractionable": False, "shortable": False},
        "AACBR": {"name": "Artius II Acquisition Inc. Rights", "exchange": "NASDAQ",
                  "tradable": True, "fractionable": False, "shortable": False},
    }
    base.update(overrides)
    return base


def _mrna_snapshot(minute_at: str = "2026-08-19T16:38:00Z") -> dict:
    return {"price": 142.71, "prev_close": 62.93, "volume": 2_284_942,
            "prev_volume": 129_956, "open": 120.0, "high": 145.0,
            "minute_at": minute_at, "minute_price": 142.71}


def _mrna_quote() -> dict:
    return {"bid": 138.0, "ask": 143.63, "bid_size": 100, "ask_size": 1000,
            "spread_bp": 400.0}


# --- the headline case: Moderna must be found -------------------------------------------

def test_moderna_becomes_a_signal():
    signals, rejections = cs.pick_ignitions(
        [{"symbol": "MRNA", "percent_change": 127.19, "price": 143.04}], [],
        {"MRNA": {"volume": 120_924_364, "trade_count": 1_853_811}},
        {"MRNA": _mrna_snapshot()}, {"MRNA": _mrna_quote()}, _assets(), now=NOW,
    )
    assert [s["ticker"] for s in signals] == ["MRNA"]
    assert not rejections
    signal = signals[0]
    assert signal["kind"] == "ignition_up"
    # Verified against the bars, not taken from the screener's claim.
    assert signal["change_pct"] == pytest.approx(142.71 / 62.93 - 1.0, abs=1e-4)
    assert signal["volume_ratio"] == pytest.approx(17.58, abs=0.05)
    assert signal["spread_bp"] == 400.0
    assert "Moderna" in signal["detail"]
    assert signal["score"] > 0.7  # big move, huge volume, market-wide activity


# --- the four ways the day tried to poison the scanner ----------------------------------

def test_stale_close_claim_is_rejected():
    """FIXX: screener claimed +1378 %, bars said +7 % (it divided by a stale close)."""
    signals, rejections = cs.pick_ignitions(
        [{"symbol": "FIXX", "percent_change": 1378.55, "price": 13.82}], [], {},
        {"FIXX": {"price": 0.965, "prev_close": 0.8978, "volume": 5781,
                  "prev_volume": 1697, "open": None, "high": None,
                  "minute_at": "2024-03-25T16:51:00Z", "minute_price": 0.965}},
        {}, _assets(), now=NOW,
    )
    assert not signals
    # Caught on the instrument name (a 2x ETF) before the price/claim checks even matter.
    assert rejections[0]["reason"] == "instrument_type"


def test_stale_listing_is_rejected_when_instrument_is_ordinary():
    """The same stale-print pathology on a plain common stock must still be caught."""
    signals, rejections = cs.pick_ignitions(
        [{"symbol": "ZSTK", "percent_change": 483.08, "price": 10.73}], [], {},
        {"ZSTK": {"price": 10.48, "prev_close": 1.66, "volume": 17_779,
                  "prev_volume": 100, "open": None, "high": None,
                  "minute_at": "2024-03-25T16:51:00Z", "minute_price": 10.48}},
        {}, _assets(), now=NOW,
    )
    assert not signals
    assert rejections[0]["reason"] == "stale_listing"


def test_warrants_and_rights_are_rejected():
    signals, rejections = cs.pick_ignitions(
        [{"symbol": "TNONW", "percent_change": 276.62, "price": 0.029},
         {"symbol": "AACBR", "percent_change": 181.82, "price": 0.0093}], [], {},
        {}, {}, _assets(), now=NOW,
    )
    assert not signals
    assert {r["reason"] for r in rejections} == {"instrument_type"}


def test_unusable_spread_is_rejected():
    """ZSTK's real quote was bid 9.20 / ask 11.93 — 2584 bp. Not tradable at any conviction."""
    signals, rejections = cs.pick_ignitions(
        [{"symbol": "ZSTK", "percent_change": 483.08, "price": 10.73}], [], {},
        {"ZSTK": {"price": 10.48, "prev_close": 1.66, "volume": 700_000,
                  "prev_volume": 100_000, "open": None, "high": None,
                  "minute_at": "2026-08-19T16:38:00Z", "minute_price": 10.48}},
        {"ZSTK": {"bid": 9.2, "ask": 11.93, "bid_size": 100, "ask_size": 100,
                  "spread_bp": 2584.0}},
        _assets(), now=NOW,
    )
    assert not signals
    assert rejections[0]["reason"] == "spread_unusable"


# --- the individual gates ---------------------------------------------------------------

def test_unknown_and_untradable_assets_are_rejected():
    signals, rejections = cs.pick_ignitions(
        [{"symbol": "NOPE", "percent_change": 50.0, "price": 10.0},
         {"symbol": "HALT", "percent_change": 50.0, "price": 10.0}], [], {}, {}, {},
        {"HALT": {"name": "Halted Corp Common Stock", "exchange": "NYSE",
                  "tradable": False, "fractionable": False, "shortable": False}},
        now=NOW,
    )
    assert not signals
    assert {r["reason"] for r in rejections} == {"unknown_asset", "not_tradable"}


def test_price_floor_rejects_penny_movers():
    _, rejections = cs.pick_ignitions(
        [{"symbol": "MRNA", "percent_change": 50.0, "price": 1.5}], [], {},
        {"MRNA": {"price": 1.5, "prev_close": 1.0, "volume": 5_000_000,
                  "prev_volume": 100_000, "open": None, "high": None,
                  "minute_at": "2026-08-19T16:38:00Z", "minute_price": 1.5}},
        {}, _assets(), now=NOW,
    )
    assert rejections[0]["reason"] == "price_floor"


def test_move_below_threshold_is_rejected_but_logged():
    """Calibration data: these rows answer nightly whether 7 % is the right bar."""
    _, rejections = cs.pick_ignitions(
        [{"symbol": "MRNA", "percent_change": 4.0, "price": 65.0}], [], {},
        {"MRNA": {"price": 65.0, "prev_close": 62.93, "volume": 5_000_000,
                  "prev_volume": 129_956, "open": None, "high": None,
                  "minute_at": "2026-08-19T16:38:00Z", "minute_price": 65.0}},
        {}, _assets(), now=NOW,
    )
    assert rejections[0]["reason"] == "below_move"
    assert "3.3%" in rejections[0]["detail"] or "3,3" in rejections[0]["detail"]


def test_volume_must_confirm_the_move():
    _, rejections = cs.pick_ignitions(
        [{"symbol": "MRNA", "percent_change": 20.0, "price": 75.0}], [], {},
        {"MRNA": {"price": 75.0, "prev_close": 62.93, "volume": 140_000,
                  "prev_volume": 129_956, "open": None, "high": None,
                  "minute_at": "2026-08-19T16:38:00Z", "minute_price": 75.0}},
        {}, _assets(), now=NOW,
    )
    assert rejections[0]["reason"] == "no_volume_confirmation"


def test_thin_dollar_volume_is_rejected():
    _, rejections = cs.pick_ignitions(
        [{"symbol": "MRNA", "percent_change": 20.0, "price": 5.0}], [], {},
        {"MRNA": {"price": 5.0, "prev_close": 4.0, "volume": 1_000,
                  "prev_volume": 100, "open": None, "high": None,
                  "minute_at": "2026-08-19T16:38:00Z", "minute_price": 5.0}},
        {}, _assets(), now=NOW,
    )
    assert rejections[0]["reason"] == "thin_dollar_volume"


def test_missing_snapshot_means_unverified():
    _, rejections = cs.pick_ignitions(
        [{"symbol": "MRNA", "percent_change": 127.0, "price": 143.0}], [], {}, {}, {},
        _assets(), now=NOW,
    )
    assert rejections[0]["reason"] == "unverified"


def test_missing_quote_means_no_entry():
    _, rejections = cs.pick_ignitions(
        [{"symbol": "MRNA", "percent_change": 127.0, "price": 143.0}], [], {},
        {"MRNA": _mrna_snapshot()}, {}, _assets(), now=NOW,
    )
    assert rejections[0]["reason"] == "no_quote"


# --- crashes are seen too ---------------------------------------------------------------

def test_losers_are_recorded_as_downward_ignitions():
    signals, _ = cs.pick_ignitions(
        [], [{"symbol": "MRNA", "percent_change": -30.0, "price": 44.0}], {},
        {"MRNA": {"price": 44.0, "prev_close": 62.93, "volume": 2_000_000,
                  "prev_volume": 129_956, "open": None, "high": None,
                  "minute_at": "2026-08-19T16:38:00Z", "minute_price": 44.0}},
        {"MRNA": {"bid": 43.9, "ask": 44.1, "bid_size": 100, "ask_size": 100,
                  "spread_bp": 45.0}},
        _assets(), now=NOW,
    )
    assert signals[0]["kind"] == "ignition_down"
    assert signals[0]["change_pct"] < 0
    assert "▼" in signals[0]["detail"]


def test_a_symbol_in_both_lists_is_only_judged_once():
    row = {"symbol": "MRNA", "percent_change": 127.19, "price": 143.04}
    signals, _ = cs.pick_ignitions(
        [row], [row], {}, {"MRNA": _mrna_snapshot()}, {"MRNA": _mrna_quote()},
        _assets(), now=NOW,
    )
    assert len(signals) == 1


# --- dedup / scoring / alerting ---------------------------------------------------------

def test_move_bucket_absorbs_minute_noise_but_not_escalation():
    assert cs.move_bucket(0.12) == cs.move_bucket(0.19)
    assert cs.move_bucket(0.12) != cs.move_bucket(0.34)


def test_score_is_monotone_in_each_input():
    base = dict(move=0.15, volume_ratio=5.0, spread_bp=100.0, sip_active=False)
    assert cs.score_ignition(**{**base, "move": 0.25}) > cs.score_ignition(**base)
    assert cs.score_ignition(**{**base, "volume_ratio": 15.0}) > cs.score_ignition(**base)
    assert cs.score_ignition(**{**base, "spread_bp": 50.0}) > cs.score_ignition(**base)
    assert cs.score_ignition(**{**base, "sip_active": True}) > cs.score_ignition(**base)


def test_alertable_applies_score_floor_and_cooldown():
    strong = {"ticker": "MRNA", "score": 0.9}
    weak = {"ticker": "AAPL", "score": 0.2}
    assert cs.alertable([strong, weak], {}, now=NOW) == [strong]
    recent = (NOW - timedelta(hours=1)).isoformat()
    assert cs.alertable([strong], {"MRNA": recent}, now=NOW) == []
    old = (NOW - timedelta(hours=12)).isoformat()
    assert cs.alertable([strong], {"MRNA": old}, now=NOW) == [strong]


def test_candidate_symbols_dedupes_across_both_sides():
    assert cs.candidate_symbols(
        [{"symbol": "A"}, {"symbol": "B"}], [{"symbol": "B"}, {"symbol": "C"}]
    ) == ["A", "B", "C"]


# --- the signal book --------------------------------------------------------------------

def _signal(ticker: str, key: str, score: float = 0.8) -> dict:
    return {"source": SOURCE_SCAN, "ticker": ticker, "kind": "ignition_up",
            "seen_at": "2026-08-19T16:40:00+00:00", "dedup_key": key, "score": score,
            "detail": "test"}


def test_signal_book_is_idempotent(tmp_path):
    """A minute-cadence writer that double-counts would inflate every statistic downstream."""
    path = tmp_path / "catalysts.db"
    init_catalyst_db(path)
    assert record_signals(path, [_signal("MRNA", "k1")]) == 1
    assert record_signals(path, [_signal("MRNA", "k1")]) == 0
    assert record_signals(path, [_signal("MRNA", "k2")]) == 1
    assert len(load_signals(path)) == 2


def test_signal_book_filters_and_marks(tmp_path):
    path = tmp_path / "catalysts.db"
    init_catalyst_db(path)
    record_signals(path, [_signal("MRNA", "k1", 0.9), _signal("AAPL", "k2", 0.2)])
    assert [s["ticker"] for s in load_signals(path, min_score=0.5)] == ["MRNA"]
    assert len(load_signals(path, unalerted_only=True)) == 2

    mrna_id = load_signals(path, min_score=0.5)[0]["id"]
    mark_alerted(path, [mrna_id], now="2026-08-19T16:45:00+00:00")
    assert last_alert_at(path, "MRNA") == "2026-08-19T16:45:00+00:00"
    assert [s["ticker"] for s in load_signals(path, unalerted_only=True)] == ["AAPL"]

    mark_traded(path, [mrna_id], now="2026-08-19T16:46:00+00:00")
    assert [s["ticker"] for s in load_signals(path, untraded_only=True)] == ["AAPL"]


def test_signal_book_since_window(tmp_path):
    path = tmp_path / "catalysts.db"
    init_catalyst_db(path)
    old = {**_signal("OLD", "k-old"), "seen_at": "2026-08-18T10:00:00+00:00"}
    record_signals(path, [old, _signal("NEW", "k-new")])
    assert [s["ticker"] for s in load_signals(path, since="2026-08-19T00:00:00+00:00")] == ["NEW"]


def test_rejections_are_deduped_per_day_and_summarised(tmp_path):
    path = tmp_path / "catalysts.db"
    init_catalyst_db(path)
    rej = {"source": "scan", "ticker": "ZSTK", "reason": "spread_unusable",
           "seen_at": "2026-08-19", "detail": "2584 bp"}
    assert record_rejections(path, [rej]) == 1
    assert record_rejections(path, [rej]) == 0  # same day, same reason: one row
    record_signals(path, [_signal("MRNA", "k1")])
    summary = stats(path)
    assert summary["total"] == 1
    assert summary["by_source"] == {"scan": 1}
    assert summary["rejections"] == {"spread_unusable": 1}


def test_empty_inputs_are_no_ops(tmp_path):
    path = tmp_path / "catalysts.db"
    init_catalyst_db(path)
    assert record_signals(path, []) == 0
    assert record_rejections(path, []) == 0
    assert load_signals(path) == []
    assert cs.pick_ignitions([], [], {}, {}, {}, {}, now=NOW) == ([], [])


def test_derivative_products_on_the_moving_stock_are_rejected():
    """Live scan 2026-08-19 leaked MRNY through: a YieldMax option-income ETF on MRNA.

    Such a vehicle carries no information MRNA itself does not, and adds decay plus a
    thinner book. The rule is ordinary equity only.
    """
    pooled = {
        "MRNY": "YieldMax MRNA Option Income Strategy ETF",
        "MRNX": "Defiance Daily Target 2X Long MRNA ETF",
        "SPY": "SPDR S&P 500 ETF Trust",
        "TQQQ": "ProShares UltraPro QQQ",
    }
    rows = [{"symbol": s, "percent_change": 120.0, "price": 34.0} for s in pooled]
    snapshots = {s: {"price": 34.0, "prev_close": 15.0, "volume": 3_000_000,
                     "prev_volume": 20_000, "open": None, "high": None,
                     "minute_at": "2026-08-19T16:38:00Z", "minute_price": 34.0}
                 for s in pooled}
    quotes = {s: {"bid": 33.9, "ask": 34.1, "bid_size": 100, "ask_size": 100,
                  "spread_bp": 59.0} for s in pooled}
    assets = {s: {"name": n, "exchange": "ARCA", "tradable": True,
                  "fractionable": False, "shortable": False} for s, n in pooled.items()}
    signals, rejections = cs.pick_ignitions(
        rows, [], {}, snapshots, quotes, assets, now=NOW,
    )
    assert not signals
    assert {r["reason"] for r in rejections} == {"instrument_type"}
    # The name is kept in the rejection so a pooled mover stays VISIBLE in calibration data.
    assert any("YieldMax" in r["detail"] for r in rejections)


def test_ordinary_equity_names_still_pass_the_instrument_filter():
    """The blunt pooled-vehicle rule must not swallow ordinary listings."""
    for name in ("Moderna, Inc. Common Stock",
                 "Barrick Mining Corporation Common Shares",
                 "Novartis AG American Depositary Shares",
                 "Trustmark Corporation Common Stock"):
        assert not cs._is_excluded_instrument(name), name
