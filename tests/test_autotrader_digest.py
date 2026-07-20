"""Digest Auto-Depot block: rendering variants, honest absence, collector shape."""
from __future__ import annotations

import pytest

from equity_scout.autotrader_engine import AutoDepotAccount, AutoDepotValuation, TradeRecord
from equity_scout.autotrader_protections import BreakerState, RiskEvent
from equity_scout.autotrader_storage import record_advance, save_depot
from equity_scout.digest import build_digest
from scripts.run_digest import collect_autodepot


def _autodepot(**overrides) -> dict:
    base = {
        "as_of": "2026-07-17",
        "equity": 101_500.0,
        "equity_eur": 91_350.0,
        "total_return": 0.015,
        "benchmark_return": 0.011,
        "gross_exposure": 0.85,
        "drawdown": 0.012,
        "mode": "tilt",
        "breaker_stage": 0,
        "trades": [
            {"ticker": "XLK", "delta_weight": 0.02},
            {"ticker": "IEF", "delta_weight": -0.01},
        ],
        "risk_events": [],
    }
    base.update(overrides)
    return base


def test_autodepot_block_renders_equity_returns_and_trades() -> None:
    text = build_digest([], date_label="2026-07-18", autodepot=_autodepot())
    assert "🤖 Auto-Depot (Stand 2026-07-17): 101,500 USD (91,350 EUR)" in text
    assert "Gesamt +1.5 % vs SPY +1.1 %" in text
    assert "Trades: ↑XLK ↓IEF" in text
    assert "Anker-Phase" not in text  # tilt mode carries no anchor note


def test_autodepot_block_is_absent_without_data() -> None:
    text = build_digest([], date_label="2026-07-18")
    assert "Auto-Depot" not in text


def test_trades_are_capped_and_counted() -> None:
    trades = [{"ticker": f"T{i}", "delta_weight": 0.01} for i in range(8)]
    text = build_digest([], date_label="2026-07-18", autodepot=_autodepot(trades=trades))
    assert "↑T4" in text and "↑T5" not in text
    assert "+3 weitere" in text


def test_anchor_mode_breaker_and_events_are_labelled() -> None:
    autodepot = _autodepot(
        mode="anchor", breaker_stage=1,
        risk_events=["Markt-Ampel ROT — Exposure auf 50% reduziert"], trades=[],
    )
    text = build_digest([], date_label="2026-07-18", autodepot=autodepot)
    assert "Keine Trades an diesem Stand." in text
    assert "⚠ Markt-Ampel ROT" in text
    assert "⛔ Drawdown-Breaker aktiv: halbes Exposure" in text
    assert "Anker-Phase" in text


def test_html_mode_bolds_the_head_and_escapes() -> None:
    text = build_digest([], date_label="2026-07-18", autodepot=_autodepot(), html=True)
    assert "<b>🤖 Auto-Depot" in text


def test_missing_eur_renders_usd_only() -> None:
    text = build_digest([], date_label="2026-07-18", autodepot=_autodepot(equity_eur=None))
    assert "101,500 USD\n" in text or "101,500 USD" in text
    assert "EUR" not in text


def test_collect_autodepot_reads_the_seeded_db(tmp_path) -> None:
    db = str(tmp_path / "autotrader.db")
    account = AutoDepotAccount(
        initial_capital=100_000.0, equity=101_500.0, benchmark_ticker="SPY",
        benchmark_equity=101_100.0, peak_equity=102_000.0, last_as_of="2026-07-17",
        weights={"XLK": 0.1}, breaker=BreakerState(stage=1, changed_at="2026-07-16"),
        sleeve_weights={"gem": 0.5, "daa": 0.5}, sleeve_mode="anchor",
    )
    save_depot(db, account, updated_at="2026-07-17")
    record_advance(db, AutoDepotValuation(
        created_at="2026-07-17", equity=101_500.0, total_return=0.015,
        benchmark_equity=101_100.0, benchmark_return=0.011,
        gross_exposure=0.85, drawdown=0.005, equity_eur=91_350.0, fx_rate=0.9,
        trades=(TradeRecord("2026-07-17", "XLK", 0.02, 2_030.0, 2.03),),
        risk_events=(RiskEvent("vol_target", "scale_0.9", "Vol über Ziel"),),
    ))
    collected = collect_autodepot(db)
    assert collected is not None
    assert collected["as_of"] == "2026-07-17"
    assert collected["equity"] == pytest.approx(101_500.0)
    assert collected["mode"] == "anchor"
    assert collected["breaker_stage"] == 1
    assert [t["ticker"] for t in collected["trades"]] == ["XLK"]
    assert collected["risk_events"] == ["Vol über Ziel"]


def test_collect_autodepot_without_account_is_none(tmp_path) -> None:
    assert collect_autodepot(str(tmp_path / "empty.db")) is None
