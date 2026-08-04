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
    """2026-08-04 Telegram diet: German-formatted numbers, no "(Stand ...)" in the
    headline (dashboard shows the as_of date), trades named without the old
    "(Fill: next-open)" label — that convention is documented once, not repeated daily."""
    text = build_digest([], date_label="2026-07-18", autodepot=_autodepot())
    assert "🤖 Auto-Depot 101.500 $ (91.350 €)" in text
    assert "  Gesamt +1,5 % vs SPY +1,1 %" in text
    assert "  Trades: ↑XLK 2,0 % · ↓IEF 1,0 %" in text
    assert "Anker-Phase" not in text  # the note is gone entirely, not just for tilt mode


def test_autodepot_block_is_absent_without_data() -> None:
    text = build_digest([], date_label="2026-07-18")
    assert "Auto-Depot" not in text


def test_trades_are_capped_and_counted() -> None:
    """TRADE_NAME_CAP is 3 (2026-08-04 diet, was 4) — the rest are counted, not named."""
    trades = [{"ticker": f"T{i}", "delta_weight": 0.01} for i in range(8)]
    text = build_digest([], date_label="2026-07-18", autodepot=_autodepot(trades=trades))
    assert "↑T0" in text and "↑T1" in text and "↑T2" in text
    assert "↑T3" not in text
    assert "+5 kleine" in text


def test_anchor_mode_breaker_and_events_are_labelled() -> None:
    autodepot = _autodepot(
        mode="anchor", breaker_stage=1,
        risk_events=["Markt-Ampel ROT — Exposure auf 50% reduziert"], trades=[],
    )
    text = build_digest([], date_label="2026-07-18", autodepot=autodepot)
    assert "Keine Trades an diesem Stand." in text
    assert "⚠ Markt-Ampel ROT" in text
    assert "⛔ Drawdown-Breaker aktiv: halbes Exposure" in text
    # The "(Anker-Phase: …)" note is gone entirely (2026-08-04 diet) — the sleeve mode
    # is not information the phone digest needs; risk events + breaker stage still are.
    assert "Anker-Phase" not in text


def test_html_mode_bolds_the_head_and_escapes() -> None:
    text = build_digest([], date_label="2026-07-18", autodepot=_autodepot(), html=True)
    assert "<b>🤖 Auto-Depot" in text


def test_missing_eur_renders_usd_only() -> None:
    text = build_digest([], date_label="2026-07-18", autodepot=_autodepot(equity_eur=None))
    assert "🤖 Auto-Depot 101.500 $" in text
    assert "€" not in text


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


def test_stale_autodepot_gets_a_warning_line() -> None:
    """R7/P1 (review 2026-07-20): a silently stopped nightly chain must be visible."""
    text = build_digest([], date_label="2026-07-18", autodepot=_autodepot(stale_days=4))
    assert "⚠️ Stand 4 Handelstage alt — Kette prüfen" in text


def test_fresh_autodepot_has_no_staleness_warning() -> None:
    text = build_digest([], date_label="2026-07-18", autodepot=_autodepot())
    assert "veraltet" not in text


def test_collect_autodepot_flags_stale_as_of(tmp_path) -> None:
    db = str(tmp_path / "autotrader.db")
    save_depot(db, AutoDepotAccount.fresh(), updated_at="2026-07-10")
    record_advance(db, AutoDepotValuation(
        created_at="2026-07-10", equity=100_000.0, total_return=0.0,
        benchmark_equity=100_000.0, benchmark_return=0.0,
        gross_exposure=0.5, drawdown=0.0,
    ))
    collected = collect_autodepot(db, today="2026-07-20")
    assert collected is not None
    assert collected["stale_days"] == 6  # business days 07-10 .. 07-17 inclusive

    fresh = collect_autodepot(db, today="2026-07-13")  # Fri -> Mon = 1 business day
    assert fresh is not None
    assert "stale_days" not in fresh
