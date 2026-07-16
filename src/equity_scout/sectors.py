"""Sector momentum snapshot (v8): rank the 11 SPDR sector ETFs by trailing momentum.

Read-only context for the dashboard card, the digest head line, and anyone asking
"which sectors lead right now". Reuses MarketView so the return arithmetic (21
trading days per month, look-ahead-safe) is identical to what the rotation
strategy trades on — the display can never disagree with the strategy.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from equity_scout.etf_universe import SECTOR_ETF_TICKERS, SECTOR_ETF_UNIVERSE
from equity_scout.market import MarketView

if TYPE_CHECKING:
    from equity_scout.market import PricePanel

RETURN_WINDOWS_MONTHS = (1, 3, 6, 12)


def sector_momentum(panel: PricePanel) -> list[dict]:
    """One row per sector ETF, sorted by the 12m/6m blend (the rotation's ranking
    signal), missing-history rows last. Returns are fractions (0.12 = +12 %)."""
    market = MarketView(panel, panel.dates[-1] + pd.Timedelta(days=1))
    rows: list[dict] = []
    for instrument in SECTOR_ETF_UNIVERSE:
        returns = {
            f"m{months}": market.trailing_return(instrument.ticker, months)
            for months in RETURN_WINDOWS_MONTHS
        }
        r12, r6 = returns["m12"], returns["m6"]
        blend = (r12 + r6) / 2 if r12 is not None and r6 is not None else None
        rows.append({
            "ticker": instrument.ticker,
            "name": instrument.name,
            "sector": instrument.sector.removeprefix("US Sector: "),
            "returns": returns,
            "blend": blend,
        })
    rows.sort(key=lambda row: (row["blend"] is None, -(row["blend"] or 0.0)))
    return rows


def sector_breadth(panel: PricePanel) -> float | None:
    """% of the 11 sector ETFs above their own 200d SMA — the honest, zero-cost breadth
    approximation for the regime light (the full stock universe has no cached history).
    None when the panel predates the sector extension. Coarse by design (steps of 1/11);
    callers label it as sector breadth, never as full-market breadth."""
    from equity_scout.regime import compute_breadth

    universe = {
        ticker: [float(v) for v in panel.closes[ticker].dropna()]
        for ticker in (set(SECTOR_ETF_TICKERS) & set(panel.closes.columns))
    }
    return compute_breadth(universe)


def top_sector_line(rows: list[dict], n: int = 3) -> str | None:
    """Compact German head line for the digest: the n leading sectors by blend.
    None when nothing is rankable — the caller renders an honest absence."""
    ranked = [row for row in rows if row["blend"] is not None][:n]
    if not ranked:
        return None
    parts = [f"{row['sector']} ({row['blend'] * 100:+.0f} %)" for row in ranked]
    return "Stärkste Sektoren: " + ", ".join(parts)
