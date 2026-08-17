"""Proof metrics (v12 P1): honest per-book evidence — a metric that cannot be computed
yet returns None WITH a reason, never a guess."""
from __future__ import annotations

import pytest

from equity_scout.proof import MIN_DAYS_FOR_RATES, book_report


def _curve(days: int, *, start: str = "2026-01-01", daily: float = 0.001) -> list:
    import pandas as pd

    idx = pd.date_range(start, periods=days, freq="D")
    equity = 10_000.0
    out = []
    for ts in idx:
        out.append((ts.date().isoformat(), equity))
        equity *= 1.0 + daily
    return out


def test_short_track_record_returns_none_rates_with_reason() -> None:
    report = book_report(_curve(10), label="Testbuch")
    assert report["n_days"] == 9
    assert report["sharpe_annualised"] is None
    assert report["cagr_pct"] is None
    assert f"< {MIN_DAYS_FOR_RATES} Tage" in report["verdict_label"]
    assert report["max_drawdown_pct"] == pytest.approx(0.0)  # monotone up


def test_long_track_record_computes_rates_and_drawdown() -> None:
    curve = _curve(100)
    # inject a dip: equity drops 10% below its running peak mid-way
    peak_equity = curve[50][1]
    curve[51] = (curve[51][0], peak_equity * 0.9)
    report = book_report(curve, label="Testbuch")
    assert report["sharpe_annualised"] is not None
    assert report["cagr_pct"] is not None and report["cagr_pct"] > 0
    assert report["max_drawdown_pct"] == pytest.approx(10.0, abs=0.5)


def test_win_rate_costs_and_benchmark_delta() -> None:
    report = book_report(
        _curve(100, daily=0.002),
        label="Testbuch",
        benchmark_curve=_curve(100, daily=0.001),
        realized_pnls=[10.0, -5.0, 20.0, -1.0],
        costs_paid=7.5,
    )
    assert report["realized_win_rate"] == pytest.approx(0.5)
    assert report["vs_benchmark_pct"] is not None and report["vs_benchmark_pct"] > 0
    assert report["cost_share_of_pnl"] == pytest.approx(7.5 / (24.0 + 7.5))
    assert "schlägt Benchmark" in report["verdict_label"]


def test_cost_share_uses_pre_fee_magnitude_when_costs_flip_book_negative() -> None:
    # net -100 with 80 of costs means the pre-fee P&L was -20; costs are 4x that
    # magnitude — the old |net| + costs denominator hid this as a harmless ~44%.
    report = book_report(
        _curve(100),
        label="Testbuch",
        realized_pnls=[-100.0],
        costs_paid=80.0,
    )
    assert report["cost_share_of_pnl"] == pytest.approx(4.0)


def test_cost_share_zero_gross_stays_none() -> None:
    # net -80 with 80 of costs: pre-fee P&L is exactly 0 — no denominator, no guess
    report = book_report(
        _curve(100),
        label="Testbuch",
        realized_pnls=[-80.0],
        costs_paid=80.0,
    )
    assert report["cost_share_of_pnl"] is None


def test_flat_curve_has_no_sharpe() -> None:
    report = book_report(_curve(100, daily=0.0), label="Flach")
    assert report["sharpe_annualised"] is None  # zero variance is not evidence


def test_conviction_thresholds_are_the_risk_reframed_bar() -> None:
    from equity_scout.proof import CONVICTION_THRESHOLDS

    assert CONVICTION_THRESHOLDS == {
        "min_track_days": 730,
        "min_vs_benchmark_pct": 0.0,
        "max_drawdown_ratio_vs_benchmark": 0.60,
    }


def test_book_report_carries_benchmark_max_drawdown() -> None:
    curve = [("2026-01-01", 100.0), ("2026-01-02", 110.0), ("2026-01-03", 105.0)]
    bench = [("2026-01-01", 100.0), ("2026-01-02", 90.0), ("2026-01-03", 95.0)]
    report = book_report(curve, label="t", benchmark_curve=bench)
    assert report["benchmark_max_drawdown_pct"] == pytest.approx(10.0)


def test_book_report_benchmark_drawdown_none_without_benchmark() -> None:
    curve = [("2026-01-01", 100.0), ("2026-01-02", 110.0)]
    assert book_report(curve, label="t")["benchmark_max_drawdown_pct"] is None
