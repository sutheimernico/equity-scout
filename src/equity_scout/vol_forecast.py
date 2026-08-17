"""VIX-calibrated forward-vol multiplier for the VolTarget protection (study 2026-08-12).

`VolTarget` throttles on the depot's TRAILING 20-day vol, i.e. after volatility has already
risen. The study (docs/research/2026-08-12-voltarget-uses-the-weaker-estimator.md, reproducible
via scripts/run_vol_forecast_study.py) showed the VIX predicts the same 20-day window better
(rho 0.642 vs 0.539 on 233 non-overlapping windows over 19 years) but reads ~36% high, because
implied vol carries the variance risk premium. Build rules, from the study + PLAN.md:

- DIMENSIONLESS multiplier only: (calibrated VIX forecast) / (SPY trailing vol), applied by the
  caller to the depot's OWN trailing vol. The depot is multi-asset with lower absolute vol, so
  the SPY level itself must never be used directly.
- The calibration divisor was fitted on 2007-2016 ONLY and held out of sample on 2017-2026
  (calibration ratio 1.07). It is a pinned constant here, never a live re-fit.
- Any missing or implausible input -> None; the caller falls back to the trailing estimator.
  A data gap must never be read as "no risk".
"""
from __future__ import annotations

import math

import pandas as pd

from equity_scout.market import TRADING_DAYS_PER_YEAR

VIX_DIVISOR = 1.341  # variance-risk-premium divisor: fitted < 2017, verified OOS >= 2017
TRAILING_WINDOW = 20  # VolTarget's own window — the multiplier answers ITS question
# Plausibility band for forecast/trailing. Asymmetric on purpose: an implausibly LOW ratio
# (bad VIX print like 0.16) would switch the protection off, so it is distrusted (None ->
# trailing fallback). An extreme HIGH ratio only over-throttles, which is the safe direction,
# so it is clipped to the cap instead of discarded.
MULTIPLIER_CLAMP = (0.5, 3.0)


def trailing_vol(closes: pd.Series | None, window: int = TRAILING_WINDOW) -> float | None:
    """Annualised stdev of the last `window` daily returns; None when too short/degenerate."""
    if closes is None:
        return None
    returns = closes.astype(float).pct_change().dropna()
    if len(returns) < window:
        return None
    vol = float(returns.iloc[-window:].std(ddof=1)) * math.sqrt(TRADING_DAYS_PER_YEAR)
    return vol if math.isfinite(vol) and vol > 0 else None


def vix_multiplier(vix_level: float | None, spy_closes: pd.Series | None) -> float | None:
    """Forecast/trailing ratio, or None when either leg is missing or implausible."""
    if vix_level is None:
        return None
    spy_trailing = trailing_vol(spy_closes)
    if spy_trailing is None:
        return None
    forecast = (float(vix_level) / 100.0) / VIX_DIVISOR  # VIX quotes percentage points
    if not math.isfinite(forecast) or forecast <= 0:
        return None
    ratio = forecast / spy_trailing
    low, high = MULTIPLIER_CLAMP
    if not math.isfinite(ratio) or ratio < low:
        return None
    return min(ratio, high)
