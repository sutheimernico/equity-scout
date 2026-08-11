#!/usr/bin/env python3
"""Does `VolTarget` use the best available volatility estimate? (study, 2026-08-11)

`autotrader_protections.VolTarget` scales exposure by the TRAILING 20-day realised vol, i.e. it
throttles after volatility has already risen. W0 (2026-08-11) established that VIX level predicts
FORWARD volatility, so the question is whether the protection is reacting later than it needs to.

Method follows the W0 gate, because the failure mode is the same one: rank correlation against
realised FORWARD vol, measured on NON-OVERLAPPING windows only (a daily series of 20-day forwards
shares 19 of 20 days and inflates every statistic), plus an incremental test — does VIX add
anything once the trailing vol is accounted for, and vice versa.

Two things are judged separately, and conflating them is the trap here:
  * RANK quality (rho) — does the estimator flag the right days?
  * CALIBRATION (median estimate/realised) — is it in the right UNITS? VolTarget's factor is
    `target / estimate`, so an estimator that reads 36% high throttles 36% too hard on every
    single day. Raw VIX is exactly that: implied vol carries the variance risk premium.

Proxy honesty: the depot's own return history is ~10 valuations, far too short for a vol study, so
SPY stands in. The depot is multi-asset and its absolute vol is lower — which is why the BUILD
recommendation is a dimensionless multiplier (expected/realised) applied to the depot's own
trailing vol, never the SPY number itself.

Run from the repo root (snapshots only, no network):
    uv run python scripts/run_vol_forecast_study.py
"""
from __future__ import annotations

import argparse
import math

import numpy as np
import pandas as pd

from equity_scout.behaviour_study import (
    MIN_INDEPENDENT_OBS,
    TRADING_DAYS_PER_YEAR,
    align,
    forward_volatility,
    independent_subsample,
    residualise,
)
from equity_scout.behaviour_study import _spearman as spearman

HORIZON = 20  # VolTarget's own window, so the study answers ITS question
SLEEVE_CLOSES = "data/prices/behaviour_sleeve_closes.csv"
VIX_TERM = "data/prices/vix_term.csv"
# Split for the out-of-sample check on the fitted divisor. Roughly halves the 2007-2026 panel;
# picked as a round year boundary rather than tuned, and the verdict is read off the SECOND half.
OOS_SPLIT = "2017-01-01"


def _panel(path: str) -> pd.DataFrame:
    return pd.read_csv(path, index_col=0, parse_dates=True).sort_index()


def trailing_vol(closes: pd.Series, window: int = HORIZON) -> pd.Series:
    """Exactly what VolTarget computes today: annualised stdev of the last `window` returns."""
    rets = closes.astype(float).pct_change()
    return rets.rolling(window).std(ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR)


def score(estimate: pd.Series, target: pd.Series, *, since=None, until=None) -> dict:
    """Rank quality and calibration of one estimator on non-overlapping windows."""
    frame = align(estimate, target)
    if since is not None:
        frame = frame[frame.index >= pd.Timestamp(since)]
    if until is not None:
        frame = frame[frame.index < pd.Timestamp(until)]
    indep = independent_subsample(frame, HORIZON)
    if len(indep) < MIN_INDEPENDENT_OBS:
        return {"rho": None, "calibration": None, "n": len(indep)}
    ratio = (indep["signal"] / indep["target"]).replace([np.inf, -np.inf], np.nan).dropna()
    return {
        "rho": spearman(indep["signal"], indep["target"]),
        "calibration": float(ratio.median()) if not ratio.empty else None,
        "n": len(indep),
    }


def _line(name: str, result: dict) -> str:
    rho = "n/a" if result["rho"] is None else f"{result['rho']:+.3f}"
    cal = "n/a" if result["calibration"] is None else f"{result['calibration']:.2f}"
    return f"  {name:32s} rho={rho:>6}  Schaetzer/Ist={cal:>5}  n={result['n']}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sleeve", default=SLEEVE_CLOSES)
    parser.add_argument("--vix", default=VIX_TERM)
    args = parser.parse_args()

    sleeve = _panel(args.sleeve)
    vix_panel = _panel(args.vix)
    spy = sleeve["SPY"].dropna()
    target = forward_volatility(spy, HORIZON)
    trail = trailing_vol(spy)
    vix = vix_panel["^VIX"].dropna() / 100.0  # VIX quotes percentage points

    print(f"SPY {spy.index[0].date()}..{spy.index[-1].date()} ({len(spy)} Tage), "
          f"Horizont {HORIZON} Handelstage")

    print("\n=== Einzelpraediktoren der FOLGE-Vola ===")
    print(_line("trailing (Status quo)", score(trail, target)))
    print(_line("VIX (unskaliert)", score(vix, target)))

    print("\n=== Inkrementell (das W0-Gate) ===")
    print(_line("VIX ohne trailing", score(residualise(vix, [trail]), target)))
    print(_line("trailing ohne VIX", score(residualise(trail, [vix]), target)))

    # Divisor for the variance risk premium, fitted on the FIRST half only.
    fit = align(vix, target)
    fit = independent_subsample(fit[fit.index < pd.Timestamp(OOS_SPLIT)], HORIZON)
    divisor = float((fit["signal"] / fit["target"]).median())
    print(f"\nDivisor der Varianzrisikoprämie, gefittet auf < {OOS_SPLIT}: "
          f"{divisor:.3f} (n={len(fit)})")

    vix_mean = vix.rolling(HORIZON).mean()
    parameter_free = trail * (vix / vix_mean).replace([np.inf, -np.inf], np.nan)

    for label, kwargs in (
        (f"ERSTE Haelfte (< {OOS_SPLIT}, in-sample)", {"until": OOS_SPLIT}),
        (f"ZWEITE Haelfte (>= {OOS_SPLIT}, OUT OF SAMPLE)", {"since": OOS_SPLIT}),
    ):
        print(f"\n=== {label} ===")
        print(_line("A trailing", score(trail, target, **kwargs)))
        print(_line("B VIX / Divisor", score(vix / divisor, target, **kwargs)))
        print(_line("C trailing x VIX/VIX-Mittel", score(parameter_free, target, **kwargs)))

    print("\nLesart: B verdient seinen gefitteten Divisor nur, wenn er in der ZWEITEN Haelfte")
    print("beides haelt — bessere Rangfolge UND Kalibrierung nahe 1. Sonst gewinnt C, das")
    print("dieselbe Richtung ohne jeden gefitteten Parameter liefert.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
