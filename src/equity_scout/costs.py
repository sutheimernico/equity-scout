"""Trading-cost model for depot fills (v13 O3): a liquidity-aware LOWER BOUND.

Corwin & Schultz (2012) estimate the bid-ask spread from two-day high/low ranges: the
daily range reflects variance PLUS spread, the two-day combined range the same spread but
double the variance — the difference isolates the spread. We take the rolling median of
the daily two-day estimators over the last `CS_WINDOW` trading days, clip negative days
(overnight jumps make the estimator go negative) to 0, and charge each depot fill
`max(flat floor, half the estimated spread)` on its notional.

Honesty label, everywhere this number surfaces: this is a LOWER BOUND. The estimator is
known to understate spreads for thin names, and it says nothing about market impact.
The forward-paper sleeves deliberately stay on the flat floor — they are the signal
layer; execution realism lives in the depot (see autotrader_engine's fill path).
"""
from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

FLAT_FLOOR_BPS = 10.0  # the pre-v13 flat assumption, kept as the floor
CS_WINDOW = 21  # trading days of two-day estimates behind the rolling median

_DENOM = 3.0 - 2.0 * math.sqrt(2.0)


def cs_spread(high: pd.Series, low: pd.Series) -> float:
    """The Corwin-Schultz spread estimate as a FRACTION of price (0.002 = 20 bps):
    median of the last `CS_WINDOW` daily two-day estimators, each clipped at 0.
    Returns 0.0 when fewer than two clean (positive, non-NaN) days exist — no estimate
    means no surcharge; the caller's flat floor still applies."""
    frame = pd.DataFrame({"high": high, "low": low}).dropna()
    frame = frame[(frame["high"] > 0) & (frame["low"] > 0)]
    if len(frame) < 2:
        return 0.0
    frame = frame.iloc[-(CS_WINDOW + 1):]
    highs, lows = frame["high"].to_numpy(), frame["low"].to_numpy()
    estimates = []
    for i in range(1, len(frame)):
        h0, l0, h1, l1 = highs[i - 1], lows[i - 1], highs[i], lows[i]
        beta = math.log(h0 / l0) ** 2 + math.log(h1 / l1) ** 2
        gamma = math.log(max(h0, h1) / min(l0, l1)) ** 2
        alpha = (math.sqrt(2.0 * beta) - math.sqrt(beta)) / _DENOM - math.sqrt(gamma / _DENOM)
        spread = 2.0 * (math.exp(alpha) - 1.0) / (1.0 + math.exp(alpha))
        estimates.append(max(0.0, spread))
    return float(np.median(estimates))


def fill_cost_rate_bps(
    ohlc_frame: pd.DataFrame | None, *, flat_bps: float = FLAT_FLOOR_BPS
) -> float:
    """Per-fill cost rate in bps for one ticker: `max(flat floor, half the CS spread)`.
    LOWER BOUND by construction (see module docstring). No usable OHLC — lane fund-share
    tickers, feed gaps — falls back to the flat floor with a log line."""
    if ohlc_frame is None or not {"high", "low"}.issubset(ohlc_frame.columns):
        logger.info("no OHLC for cost estimate — flat %.0f bps floor", flat_bps)
        return flat_bps
    half_spread_bps = cs_spread(ohlc_frame["high"], ohlc_frame["low"]) / 2.0 * 10_000.0
    return max(flat_bps, half_spread_bps)
