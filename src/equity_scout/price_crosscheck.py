"""Compare the depot panel's closes against an independent reference (pure logic).

Only dates BOTH sources have are compared — a reference that lags a day (holiday, fetch
timing) is 'no reference for today', never a divergence. The tolerance is wide (2 %): this
gate exists to catch WRONG prices (split/adjustment glitches, scraper breakage), not to
adjudicate cent-level differences between two EOD sources. Measured agreement between the
two live sources on 2026-08-14 was 0.007 %.
"""
from __future__ import annotations

import pandas as pd

TOLERANCE = 0.02
CHECK_TICKERS = ("SPY", "IEF", "GLD")  # three liquid depot cornerstones, three asset classes


def crosscheck(
    panel_closes: pd.DataFrame,
    reference: dict[str, tuple[str, float]],
    *,
    tolerance: float = TOLERANCE,
) -> list[str]:
    """Human-readable divergence messages; empty list = no contradiction found."""
    problems: list[str] = []
    for ticker, (ref_date, ref_close) in reference.items():
        if ticker not in panel_closes.columns or ref_close <= 0:
            continue
        series = panel_closes[ticker].dropna()
        stamp = pd.Timestamp(ref_date)
        if series.empty or stamp not in series.index:
            continue
        ours = float(series.loc[stamp])
        if ours <= 0:
            continue
        deviation = abs(ours / ref_close - 1.0)
        if deviation > tolerance:
            problems.append(
                f"{ticker} {stamp.date().isoformat()}: Panel {ours:.2f} vs "
                f"Referenz {ref_close:.2f} ({deviation:.1%} > {tolerance:.0%})"
            )
    return problems
