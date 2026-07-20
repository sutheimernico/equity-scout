"""Meta-allocation across strategy sleeves for the Auto-Depot (vision v10).

The autotrader combines the existing forward-paper strategies ("sleeves") into one book. Sleeve
weights come from each sleeve's OWN forward track record (`forward_valuations` equity series) —
the sleeves keep running untouched as measurement instruments; nothing is re-simulated.

Weighting follows the shrinkage lesson of the 1/N literature (DeMiguel et al. 2009: estimation
error eats optimisation on short samples): a fixed equal-weight anchor blended with a Sharpe-
softmax tilt over a trailing walk-forward window, then floored/capped per sleeve so noisy
short-sample Sharpe estimates can neither zero out nor dominate a lane. While the sleeves have
fewer than `min_obs` overlapping daily observations there is nothing honest to tilt on, so the
allocation is pure equal weight and says so (`mode="anchor"`) — the same "no track record, no
claim" stance as `MLBot.ready`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from equity_scout.forward_storage import load_valuations
from equity_scout.market import TRADING_DAYS_PER_YEAR

WINDOW_DAYS = 63  # one quarter of trading days
MIN_OVERLAP_OBS = 60  # below this, tilt estimates are noise — stay on the anchor
ANCHOR = 0.5  # fixed equal-weight share of the blend
FLOOR = 0.05  # no sleeve is ever zeroed out ...
CAP = 0.40  # ... and none may dominate


@dataclass(frozen=True)
class SleeveAllocation:
    """The allocator's verdict: per-sleeve weights (sum 1), how they were derived, and the
    Sharpe estimates behind a tilt (empty in anchor mode — there was nothing to estimate)."""

    weights: dict[str, float]
    mode: str  # "anchor" (pure equal weight) | "tilt" (anchor-blended Sharpe softmax)
    sharpes: dict[str, float] = field(default_factory=dict)
    window_obs: int = 0


def sleeve_return_frame(db_path: str | Path, sleeve_names: list[str]) -> pd.DataFrame:
    """Daily simple returns per sleeve from its forward-valuation equity series.

    Sleeves with fewer than two valuations yield no column (no return is computable) — the
    caller's overlap check handles their absence honestly instead of inventing zeros."""
    series: dict[str, pd.Series] = {}
    for name in sleeve_names:
        vals = load_valuations(db_path, name)
        if len(vals) < 2:
            continue
        equity = pd.Series(
            {pd.Timestamp(v["created_at"]): float(v["equity"]) for v in vals}
        ).sort_index()
        series[name] = equity.pct_change().iloc[1:]
    return pd.DataFrame(series)


def returns_before(returns: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Walk-forward guard: only rows strictly before `as_of` — a weight recompute must never
    see the day it takes effect (same convention as MarketView)."""
    return returns.loc[returns.index < pd.Timestamp(as_of)]


def _annualised_sharpe(daily: pd.Series) -> float:
    std = float(daily.std(ddof=1))
    if std <= 0 or not math.isfinite(std):
        return 0.0
    return float(daily.mean()) / std * math.sqrt(TRADING_DAYS_PER_YEAR)


def _clip_renormalise(weights: dict[str, float], floor: float, cap: float) -> dict[str, float]:
    """Project weights onto {sum = 1, floor <= w <= cap}: pin every bound violator to its bound,
    spread the remaining budget proportionally over the free weights, repeat. Each round pins at
    least one weight, so this terminates exactly (a plain clip-then-renormalise oscillates).
    Bounds are widened to stay feasible for small n (n*floor <= 1 <= n*cap must hold)."""
    n = len(weights)
    lo = min(floor, 1.0 / n)
    hi = max(cap, 1.0 / n)
    pinned: dict[str, float] = {}
    free = dict(weights)
    for _ in range(n):
        budget = 1.0 - sum(pinned.values())
        total_free = sum(free.values())
        if total_free <= 0:
            scaled = {t: budget / len(free) for t in free}
        else:
            scaled = {t: w / total_free * budget for t, w in free.items()}
        violators = {
            t: (hi if w > hi else lo)
            for t, w in scaled.items()
            if w > hi + 1e-12 or w < lo - 1e-12
        }
        if not violators:
            return {**pinned, **scaled}
        for ticker, bound in violators.items():
            pinned[ticker] = bound
            del free[ticker]
        if not free:
            return pinned
    return {**pinned, **free}


def blend_weights(
    returns: pd.DataFrame,
    sleeves: list[str],
    *,
    window: int = WINDOW_DAYS,
    min_obs: int = MIN_OVERLAP_OBS,
    anchor: float = ANCHOR,
    floor: float = FLOOR,
    cap: float = CAP,
) -> SleeveAllocation:
    """Blend an equal-weight anchor with a Sharpe-softmax tilt over the trailing window.

    `sleeves` is the full list of currently active sleeve names — a sleeve missing from
    `returns` (no forward history yet) forces anchor mode for everyone: tilting the sleeves
    that happen to have history would silently punish the new lane for being new."""
    if not sleeves:
        return SleeveAllocation(weights={}, mode="anchor")
    equal = {name: 1.0 / len(sleeves) for name in sleeves}

    overlap = returns.reindex(columns=sleeves).dropna(how="any")
    if len(overlap) < min_obs:
        return SleeveAllocation(weights=equal, mode="anchor", window_obs=len(overlap))

    tail = overlap.iloc[-window:]
    sharpes = {name: _annualised_sharpe(tail[name]) for name in sleeves}
    peak = max(sharpes.values())
    exp = {name: math.exp(s - peak) for name, s in sharpes.items()}  # shift: overflow-safe
    total = sum(exp.values())
    softmax = {name: e / total for name, e in exp.items()}

    blended = {
        name: anchor * equal[name] + (1.0 - anchor) * softmax[name] for name in sleeves
    }
    return SleeveAllocation(
        weights=_clip_renormalise(blended, floor, cap),
        mode="tilt",
        sharpes=sharpes,
        window_obs=len(tail),
    )
