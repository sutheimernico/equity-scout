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


def test_flat_curve_has_no_sharpe() -> None:
    report = book_report(_curve(100, daily=0.0), label="Flach")
    assert report["sharpe_annualised"] is None  # zero variance is not evidence
