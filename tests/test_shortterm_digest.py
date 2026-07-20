"""Kurzfrist-Arena digest block: rendering, absence, collector shape."""
from __future__ import annotations

import pytest

from equity_scout.digest import build_digest
from equity_scout.shortterm_book import LaneBook, LaneValuation, TradeFill
from equity_scout.shortterm_storage import append_trades, append_valuation, save_book
from scripts.run_digest import collect_shortterm


def test_arena_block_renders_one_line_per_lane() -> None:
    shortterm = [
        {"lane": "swing", "label": "Event-Swing", "total_return": 0.012, "day_pnl": 55.0,
         "benchmark_ticker": "SPY", "benchmark_return": 0.004, "trades_today": 2},
        {"lane": "crypto", "label": "Crypto", "total_return": -0.008, "day_pnl": -80.0,
         "benchmark_ticker": "BTC", "benchmark_return": None, "trades_today": 0},
    ]
    text = build_digest([], date_label="2026-07-20", shortterm=shortterm)
    assert "⚡ Kurzfrist-Arena:" in text
    assert "Event-Swing: 🟢 heute +55 $ · gesamt +1.2 % (SPY +0.4 %) · 2 Trades heute" in text
    assert "Crypto: 🔴 heute -80 $ · gesamt -0.8 %" in text
    assert "(BTC" not in text  # benchmark not yet captured -> no fake number
    assert "🔴 Arena heute gesamt: -25 $" in text


def test_autodepot_day_pnl_line_renders_with_traffic_light() -> None:
    from tests.test_autotrader_digest import _autodepot

    positive = _autodepot(day_pnl=132.2, day_return=0.0013)
    text = build_digest([], date_label="2026-07-20", autodepot=positive)
    assert "🟢 Heute: +132 $ (+0.13 %)" in text
    negative = _autodepot(day_pnl=-40.0, day_return=-0.0004)
    text2 = build_digest([], date_label="2026-07-20", autodepot=negative)
    assert "🔴 Heute: -40 $" in text2


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
