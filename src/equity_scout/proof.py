"""Per-book proof metrics (v12 P1): the "kann das funktionieren?"-evidence.

One pure function turns a book's stored equity curve (plus optional realised trades,
costs and a benchmark curve) into the honest report card the proof surfaces render.
Honesty rules, same spirit as MLBot.ready: a metric that cannot be computed yet —
track record too short, zero variance, no benchmark — comes back as None WITH a
reason baked into the verdict label. Nothing here forecasts; it only measures what
already happened in the paper books.
"""
from __future__ import annotations

import math

import pandas as pd

MIN_DAYS_FOR_RATES = 60  # below this, annualised rates are noise, not evidence
TRADING_DAYS_PER_YEAR = 252

# What WOULD justify trusting this system with real money (rendered on the proof
# surfaces so the bar is explicit, not vibes; the decision itself stays Nico's):
CONVICTION_THRESHOLDS = {
    "min_track_days": 180,
    "min_sharpe_after_costs": 1.0,
    "max_drawdown_pct": 15.0,
}


def _daily_series(curve: list[tuple[str, float]]) -> pd.Series:
    # last value per calendar day; dict comprehension keeps the final write per key
    return pd.Series({pd.Timestamp(d[:10]): float(v) for d, v in curve}).sort_index()


def _total_return(series: pd.Series) -> float | None:
    first = float(series.iloc[0])
    return float(series.iloc[-1]) / first - 1.0 if first > 0 else None


def book_report(
    equity_curve: list[tuple[str, float]],
    *,
    label: str,
    benchmark_curve: list[tuple[str, float]] | None = None,
    realized_pnls: list[float] | None = None,
    costs_paid: float | None = None,
) -> dict:
    """Report card for one book. `equity_curve` = [(iso_ts, equity), ...] in order."""
    series = _daily_series(equity_curve)
    if len(series) < 2:
        return {
            "label": label, "n_days": 0, "period": None,
            "total_return_pct": None, "cagr_pct": None, "sharpe_annualised": None,
            "max_drawdown_pct": None, "realized_win_rate": None,
            "cost_share_of_pnl": None, "vs_benchmark_pct": None,
            "verdict_label": "Noch kein Track Record (weniger als 2 Bewertungspunkte).",
        }

    n_days = (series.index[-1] - series.index[0]).days
    period = f"{series.index[0].date().isoformat()} – {series.index[-1].date().isoformat()}"
    total_return = _total_return(series)

    running_peak = series.cummax()
    max_drawdown = float((1.0 - series / running_peak).max())

    returns = series.pct_change().iloc[1:]
    sharpe: float | None = None
    cagr: float | None = None
    if n_days >= MIN_DAYS_FOR_RATES:
        std = float(returns.std(ddof=1))
        if std > 0 and math.isfinite(std):
            sharpe = float(returns.mean()) / std * math.sqrt(TRADING_DAYS_PER_YEAR)
        if total_return is not None and total_return > -1.0:
            cagr = ((1.0 + total_return) ** (365.25 / n_days) - 1.0) * 100.0

    win_rate: float | None = None
    if realized_pnls:
        win_rate = sum(1 for p in realized_pnls if p > 0) / len(realized_pnls)

    cost_share: float | None = None
    if costs_paid is not None and realized_pnls is not None:
        gross = abs(sum(realized_pnls)) + costs_paid
        cost_share = costs_paid / gross if gross > 0 else None

    vs_benchmark: float | None = None
    if benchmark_curve:
        bench = _daily_series(benchmark_curve)
        overlap = bench.loc[(bench.index >= series.index[0]) & (bench.index <= series.index[-1])]
        if len(overlap) >= 2 and total_return is not None:
            bench_return = _total_return(overlap)
            if bench_return is not None:
                vs_benchmark = (total_return - bench_return) * 100.0

    if n_days < MIN_DAYS_FOR_RATES:
        verdict = (
            f"Track Record zu kurz für ein Urteil ({n_days} < {MIN_DAYS_FOR_RATES} Tage) — "
            "weiter messen."
        )
    elif vs_benchmark is not None:
        verdict = (
            f"schlägt Benchmark nach Kosten um {vs_benchmark:+.1f} %-Punkte über {n_days} Tage"
            if vs_benchmark > 0
            else f"hinter Benchmark ({vs_benchmark:+.1f} %-Punkte über {n_days} Tage)"
        )
    else:
        verdict = f"{n_days} Tage Track Record, kein Benchmark hinterlegt."

    return {
        "label": label,
        "n_days": n_days,
        "period": period,
        "total_return_pct": None if total_return is None else total_return * 100.0,
        "cagr_pct": cagr,
        "sharpe_annualised": sharpe,
        "max_drawdown_pct": max_drawdown * 100.0,
        "realized_win_rate": win_rate,
        "cost_share_of_pnl": cost_share,
        "vs_benchmark_pct": vs_benchmark,
        "verdict_label": verdict,
    }
