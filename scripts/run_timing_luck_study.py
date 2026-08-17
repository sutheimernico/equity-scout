#!/usr/bin/env python3
"""Rebalance timing luck across the rule sleeves (study, 2026-08).

All sleeves rebalance on the month-end panel date. Hoffstein/Faber/Braun (JII 2020) show the
CHOICE of rebalance day alone creates large long-run dispersion in exactly this strategy
class. This script measures that dispersion on OUR panel and OUR strategies: the same
strategy, after costs, rebalanced k trading days after month-end for k in OFFSETS.

Measurement only — it changes nothing live. If the spread is material, tranching (running the
offsets side by side and averaging) is the literature remedy; building that would create new
sleeve identities and is a separate, Nico-gated plan.

Run from the repo root (uses the cached ETF panel; --refresh to re-fetch):
    uv run python scripts/run_timing_luck_study.py
"""
from __future__ import annotations

import argparse
import math

import pandas as pd

from equity_scout.data.etf_panel import load_etf_panel
from equity_scout.engine import run_backtest
from equity_scout.etf_universe import ETF_TICKERS
from equity_scout.strategies.ensemble import EnsembleStrategy
from equity_scout.strategies.registry import default_strategies

OFFSETS = (0, 5, 10, 15)  # trading days after month-end — four weekly-staggered variants
COSTS_BPS = 10.0
TRADING_DAYS_PER_YEAR = 252


def shifted_dates(panel, offset: int) -> pd.DatetimeIndex:
    """Each month-end panel date moved `offset` trading days later (bounded at panel end)."""
    index = pd.DatetimeIndex(panel.dates)
    positions = index.get_indexer(panel.rebalance_dates("ME"))
    shifted = [index[min(p + offset, len(index) - 1)] for p in positions if p >= 0]
    return pd.DatetimeIndex(shifted).unique()


def cagr(equity: pd.Series) -> float:
    years = max(len(equity) / TRADING_DAYS_PER_YEAR, 1e-9)
    return (float(equity.iloc[-1]) / float(equity.iloc[0])) ** (1.0 / years) - 1.0


def sharpe(equity: pd.Series) -> float:
    returns = equity.pct_change().dropna()
    std = float(returns.std(ddof=1))
    if std <= 0 or not math.isfinite(std):
        return 0.0
    return float(returns.mean()) / std * math.sqrt(TRADING_DAYS_PER_YEAR)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--start", default="2007-01-01")
    args = parser.parse_args()

    panel = load_etf_panel(ETF_TICKERS, start=args.start, refresh=args.refresh)
    strategies = [s for s in default_strategies() if not isinstance(s, EnsembleStrategy)]

    print(f"Panel {panel.dates[0].date()}..{panel.dates[-1].date()} — "
          f"{len(strategies)} Strategien x Offsets {OFFSETS} Handelstage, {COSTS_BPS:.0f} bps\n")
    header = "".join(f"{'+' + str(o) + 'd':>9}" for o in OFFSETS)
    print(f"{'Strategie':<34}{header}{'Spread pp':>11}{'Sharpe min..max':>20}")
    per_offset: dict[int, list[float]] = {offset: [] for offset in OFFSETS}
    for strategy in strategies:
        cagrs, sharpes = [], []
        for offset in OFFSETS:
            result = run_backtest(
                strategy, panel,
                rebalance_dates=shifted_dates(panel, offset), costs_bps=COSTS_BPS,
            )
            cagrs.append(cagr(result.equity))
            sharpes.append(sharpe(result.equity))
            per_offset[offset].append(cagrs[-1])
        spread_pp = (max(cagrs) - min(cagrs)) * 100.0
        cells = "".join(f"{value:>+9.2%}" for value in cagrs)
        print(f"{strategy.name:<34}{cells}{spread_pp:>11.2f}"
              f"{min(sharpes):>10.2f} .. {max(sharpes):.2f}")
    # Per-offset means separate LUCK from STRUCTURE: if one offset won across the board, the
    # spread would be a calendar effect worth exploiting (and turn-of-month is already refuted
    # here, 2026-08-16), not the path-dependence dispersion tranching is meant to average out.
    means = {offset: sum(values) / len(values) for offset, values in per_offset.items()}
    mean_cells = "".join(f"{means[offset]:>+9.2%}" for offset in OFFSETS)
    print(f"\n{'Mittel über alle Strategien':<34}{mean_cells}"
          f"{(max(means.values()) - min(means.values())) * 100.0:>11.2f}")
    print("\nLesart: der Spread ist reines Kalenderglück — dieselbe Regel, dieselben Kosten,")
    print("nur ein anderer Rebalance-Tag. Material (>~1 pp CAGR über mehrere Strategien)")
    print("=> Tranching-Plan lohnt; sonst ist Month-End fein und der Punkt ist gemessen erledigt.")
    print("Gewinnt EIN Offset systematisch (Mittelzeile), ist es ein Kalendereffekt, kein Glück.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
