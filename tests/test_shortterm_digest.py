"""Kurzfrist-Arena digest block: rendering, absence, collector shape."""
from __future__ import annotations

import pytest

from equity_scout.digest import build_digest
from equity_scout.shortterm_book import LaneBook, LaneValuation, TradeFill
from equity_scout.shortterm_storage import append_trades, append_valuation, save_book
from scripts.run_digest import collect_shortterm


def test_arena_block_renders_one_line_per_lane() -> None:
    """2026-08-04 diet: the whole arena condenses to ONE line (lane count, best lane's
    total return, today's combined P&L) — per-lane returns/benchmarks/trade counts
    moved to the cockpit; only malfunctions or state changes still earn their own line."""
    shortterm = [
        {"lane": "swing", "label": "Event-Swing", "total_return": 0.012, "day_pnl": 55.0,
         "benchmark_ticker": "SPY", "benchmark_return": 0.004, "trades_today": 2},
        {"lane": "crypto", "label": "Crypto", "total_return": -0.008, "day_pnl": -80.0,
         "benchmark_ticker": "BTC", "benchmark_return": None, "trades_today": 0},
    ]
    text = build_digest([], date_label="2026-07-20", shortterm=shortterm)
    assert "⚡ Arena 2 Lanes · beste Event-Swing +1,2 % · heute −25 $" in text
    assert "Crypto: " not in text
    assert "Trades heute" not in text
    assert "(BTC" not in text  # benchmark not yet captured -> no fake number


def test_autodepot_day_pnl_line_renders_with_traffic_light() -> None:
    """2026-08-04 diet: the day move folds into the headline itself (no separate
    "🔴 Heute:" line) — the return carries the meaning, German-formatted."""
    from tests.test_autotrader_digest import _autodepot

    positive = _autodepot(day_pnl=132.2, day_return=0.0013)
    text = build_digest([], date_label="2026-07-20", autodepot=positive)
    assert "🤖 Auto-Depot 101.500 $ (91.350 €) · 🟢 heute +0,1 %" in text
    negative = _autodepot(day_pnl=-1073.0, day_return=-0.0106)
    text2 = build_digest([], date_label="2026-07-20", autodepot=negative)
    assert "🤖 Auto-Depot 101.500 $ (91.350 €) · 🔴 heute −1,1 %" in text2


def test_arena_block_absent_without_lanes() -> None:
    assert "Kurzfrist" not in build_digest([], date_label="2026-07-20")
    assert "Kurzfrist" not in build_digest([], date_label="2026-07-20", shortterm=None)


def test_collect_shortterm_reads_started_lanes_only(tmp_path) -> None:
    db = str(tmp_path / "shortterm.db")
    save_book(db, LaneBook.fresh("crypto", benchmark_ticker="BTC"), updated_at="t")
    append_valuation(db, LaneValuation(
        lane="crypto", created_at="2026-07-20T18:00", equity=10_080.0, total_return=0.008,
        cash=7_500.0, open_positions=1, benchmark_return=0.015,
    ))
    append_trades(db, [TradeFill(
        lane="crypto", executed_at="2026-07-20T10:15:00+00:00", ticker="BTC", side="buy",
        qty=0.05, price=105.0, fees=0.5, reason="Donchian",
    )])
    lanes = collect_shortterm("2026-07-20", db)
    assert lanes is not None and len(lanes) == 1
    lane = lanes[0]
    assert lane["label"] == "Crypto"
    assert lane["total_return"] == pytest.approx(0.008)
    assert lane["trades_today"] == 1


def test_collect_shortterm_is_none_on_fresh_db(tmp_path) -> None:
    assert collect_shortterm("2026-07-20", str(tmp_path / "empty.db")) is None


def test_stale_lane_gets_warning_suffix() -> None:
    from equity_scout.digest import build_digest

    lane = {
        "lane": "crypto", "label": "Crypto", "total_return": 0.01, "day_pnl": None,
        "benchmark_ticker": "BTC", "benchmark_return": 0.02, "trades_today": 0,
        "stale_days": 3,
    }
    text = build_digest([], date_label="2026-07-20", shortterm=[lane])
    assert "  ⚠ Crypto: 3 Tage keine Daten" in text


def test_collect_shortterm_flags_stale_crypto_lane(tmp_path) -> None:
    """R7/P1: a dead Kraken feed must not render days-old numbers as current."""
    db = str(tmp_path / "shortterm.db")
    save_book(db, LaneBook.fresh("crypto", benchmark_ticker="BTC"), updated_at="t")
    append_valuation(db, LaneValuation(
        lane="crypto", created_at="2026-07-17T18:00", equity=10_080.0, total_return=0.008,
        cash=7_500.0, open_positions=1, benchmark_return=0.015,
    ))
    lanes = collect_shortterm("2026-07-20", db)
    assert lanes is not None and lanes[0]["stale_days"] == 3

    # swing books trade on business days: Fri -> Mon is fresh, not stale
    save_book(db, LaneBook.fresh("swing"), updated_at="t")
    append_valuation(db, LaneValuation(
        lane="swing", created_at="2026-07-17", equity=10_000.0, total_return=0.0,
        cash=10_000.0, open_positions=0, benchmark_return=None,
    ))
    lanes = collect_shortterm("2026-07-20", db)
    swing = next(entry for entry in lanes if entry["lane"] == "swing")
    assert "stale_days" not in swing


def test_promotion_state_change_is_announced() -> None:
    """2026-08-04 diet: the per-lane 'Prüfstand: N/30 Trades · N/60 Tage · PF x'
    checklist is gone (the cockpit shows the running counters) — a lane grinding
    through its test bench gets no line at all. Only a STATE CHANGE still earns one:
    newly eligible for promotion, or already promoted."""
    from equity_scout.digest import build_digest

    base = {
        "lane": "crypto", "label": "Crypto", "total_return": 0.01, "day_pnl": None,
        "benchmark_ticker": "BTC", "benchmark_return": None, "trades_today": 0,
    }
    on_trial = {**base, "promoted": False, "promotion": {
        "realized_trades": 12, "days_active": 41, "net_pnl": 80.0,
        "profit_factor": 0.87, "eligible": False, "missing": ["x"],
    }}
    text = build_digest([], date_label="2026-07-21", shortterm=[on_trial])
    assert "Prüfstand" not in text
    assert "Crypto:" not in text and "  ✅" not in text and "  🎓" not in text

    eligible = {**base, "promoted": False, "promotion": {
        "realized_trades": 40, "days_active": 90, "net_pnl": 400.0,
        "profit_factor": 1.5, "eligible": True, "missing": [],
    }}
    text = build_digest([], date_label="2026-07-21", shortterm=[eligible])
    assert (
        "  ✅ Crypto hat den Prüfstand bestanden — Aufnahme beim nächsten Nightly-Lauf"
        in text
    )

    # promoted=True wins over an also-eligible promotion dict — a graduated lane never
    # gets BOTH lines on the same day.
    graduated = {**base, "promoted": True, "promotion": eligible["promotion"]}
    text = build_digest([], date_label="2026-07-21", shortterm=[graduated])
    assert "  🎓 Crypto verdient jetzt Depot-Kapital" in text
    assert "hat den Prüfstand bestanden" not in text
