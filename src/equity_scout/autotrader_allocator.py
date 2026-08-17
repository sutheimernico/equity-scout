"""Meta-allocation across strategy sleeves for the Auto-Depot (vision v10).

The autotrader combines the existing forward-paper strategies ("sleeves") into one book. Sleeve
weights come from each sleeve's OWN forward track record (`forward_valuations` equity series) —
the sleeves keep running untouched as measurement instruments; nothing is re-simulated.

Weighting follows the shrinkage lesson of the 1/N literature (DeMiguel et al. 2009: estimation
error eats optimisation on short samples): a fixed equal-weight anchor blended with an
INVERSE-VOL tilt over a trailing walk-forward window, then floored/capped per sleeve so no lane
is zeroed out or dominates. While the sleeves have fewer than `min_obs` overlapping daily
observations there is nothing honest to tilt on, so the allocation is pure equal weight and says
so (`mode="anchor"`) — the same "no track record, no claim" stance as `MLBot.ready`.

Tilt basis changed 2026-08-17 (review 2026-08-16): it used to be a Sharpe softmax. A Sharpe
estimated on 63 daily observations has a standard error of roughly 2 annualised units, so the
softmax exponent was dominated by noise — the same estimation-error trap the anchor exists to
shrink, re-entered through the tilt. Volatility IS estimable on 63 observations, and the depot's
own W0 finding says the same thing from the data side: returns are not predictable here, risk
is. Sharpes stay reported on every surface, they just no longer decide weights.
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
MAX_RETURN_GAP_DAYS = 4  # Fri->Mon = 3, +1 holiday = 4; anything longer is an outage


@dataclass(frozen=True)
class SleeveAllocation:
    """The allocator's verdict: per-sleeve weights (sum 1), how they were derived, and the
    Sharpe estimates behind a tilt (empty in anchor mode — there was nothing to estimate)."""

    weights: dict[str, float]
    # "anchor" (pure equal weight) | "tilt_invvol" (anchor-blended inverse-vol tilt).
    # The retired "tilt" (Sharpe softmax) only exists in DB rows written before 2026-08-17.
    mode: str
    sharpes: dict[str, float] = field(default_factory=dict)
    window_obs: int = 0


def sleeve_return_frame(db_path: str | Path, sleeve_names: list[str]) -> pd.DataFrame:
    """Daily simple returns per sleeve from its forward-valuation equity series.

    Sleeves with fewer than two valuations yield no column (no return is computable) — the
    caller's overlap check handles their absence honestly instead of inventing zeros.
    Observations spanning more than MAX_RETURN_GAP_DAYS calendar days (missed-cron
    outages) are dropped — a multi-day jump is not a daily return and would distort the
    sqrt(252)-annualised Sharpe that decides the tilt (v12 R9, review 2026-07-20).
    Weekend and single-holiday gaps stay."""
    series: dict[str, pd.Series] = {}
    for name in sleeve_names:
        vals = load_valuations(db_path, name)
        if len(vals) < 2:
            continue
        equity = pd.Series(
            {pd.Timestamp(v["created_at"]): float(v["equity"]) for v in vals}
        ).sort_index()
        returns = equity.pct_change().iloc[1:]
        gaps = equity.index.to_series().diff().dt.days.iloc[1:]
        series[name] = returns[gaps <= MAX_RETURN_GAP_DAYS]
    return pd.DataFrame(series)


def returns_before(returns: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Walk-forward guard: only rows strictly before `as_of` — a weight recompute must never
    see the day it takes effect (same convention as MarketView)."""
    if returns.empty:
        return returns  # no history at all — nothing to guard (index may not be datetimes)
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
    """Blend an equal-weight anchor with an inverse-vol tilt over the trailing window.

    A sleeve without enough history of its own is not ranked — it keeps the equal-weight
    anchor share, so being new costs it nothing. The sleeves that DO have a track record are
    still ranked against each other, on their own common window.

    Until 2026-08-16 one young sleeve forced anchor mode on the whole depot, and the overlap
    was counted across all sleeves at once (`dropna(how="any")`). Taking on four new lanes on
    2026-08-14 therefore reset the shared clock to five observations and moved the first
    performance-based weighting from October to November — and every future intake would have
    moved it again. The intent behind that rule was right (do not punish a newcomer for being
    new); the mechanism punished everyone instead.

    The comparison still happens on ONE sample: the tilt reads the common window of the
    seasoned sleeves only, never each sleeve's own private stretch of history."""
    if not sleeves:
        return SleeveAllocation(weights={}, mode="anchor")
    equal = {name: 1.0 / len(sleeves) for name in sleeves}

    present = returns.reindex(columns=sleeves)
    seasoned = [name for name in sleeves if int(present[name].notna().sum()) >= min_obs]
    # One measurable sleeve is not a ranking, and zero is not a measurement.
    if len(seasoned) < 2:
        return SleeveAllocation(weights=equal, mode="anchor", window_obs=0)

    overlap = present.reindex(columns=seasoned).dropna(how="any")
    if len(overlap) < min_obs:
        return SleeveAllocation(weights=equal, mode="anchor", window_obs=len(overlap))

    tail = overlap.iloc[-window:]
    # Sharpes stay REPORTED (dashboard/CLI transparency) but no longer drive weights: over 63
    # daily observations the Sharpe standard error is ~2 annualised units, so a softmax on it
    # ranks noise (DeMiguel et al. 2009; review 2026-08-16). Vol IS estimable on this window.
    sharpes = {name: _annualised_sharpe(tail[name]) for name in seasoned}
    vols = {
        name: float(tail[name].std(ddof=1)) * math.sqrt(TRADING_DAYS_PER_YEAR)
        for name in seasoned
    }
    inverse = {
        name: (1.0 / vol) if vol > 0 and math.isfinite(vol) else 0.0
        for name, vol in vols.items()
    }
    total_inverse = sum(inverse.values())
    if total_inverse <= 0:
        # every seasoned sleeve is flat: no risk to differentiate, so no claim to make
        return SleeveAllocation(weights=equal, mode="anchor", window_obs=len(tail))
    tilt = {name: value / total_inverse for name, value in inverse.items()}

    # The young sleeves keep their anchor shares; the seasoned ones divide what is left,
    # equal-weighted among themselves and then tilted.
    #
    # Floor and cap run on the seasoned part ALONE, rescaled into its share of the book. Run
    # over everything, the cap's redistribution handed the newcomer the leftovers of whatever
    # the top sleeve had to give up — a sleeve with no measurement ended up at the 40 % cap,
    # which is a reward, not the neutrality the anchor is meant to express.
    seasoned_share = sum(equal[name] for name in seasoned)
    equal_seasoned = 1.0 / len(seasoned)
    tilted = {
        name: anchor * equal_seasoned + (1.0 - anchor) * tilt[name] for name in seasoned
    }
    bounded = _clip_renormalise(tilted, floor / seasoned_share, cap / seasoned_share)
    weights = {name: equal[name] for name in sleeves if name not in seasoned}
    weights.update({name: share * seasoned_share for name, share in bounded.items()})
    return SleeveAllocation(
        weights=weights,
        mode="tilt_invvol",
        sharpes=sharpes,
        window_obs=len(tail),
    )
