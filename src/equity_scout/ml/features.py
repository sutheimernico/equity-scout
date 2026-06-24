"""Features for the meta-model — kept orthogonal to the primary signal (per the research: otherwise
meta-labeling finds no new information). These describe the market *regime*, not the trend direction:
volatility, breadth, drawdown state, short-term momentum, and distance to the long MA. All are rolling
functions of past prices; the meta-model samples them with a one-day lag so a decision on date t never
uses t's close — the same no-look-ahead discipline as the backtest engine.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from equity_scout.market import PricePanel

EQUITY_TICKERS = ("SPY", "VEU", "VWO", "VNQ")
FEATURE_NAMES = ("vol", "trend", "breadth", "drawdown", "mom_3m")


def primary_long_signal(panel: PricePanel, asset: str = "SPY", lookback_days: int = 252) -> pd.Series:
    """Primary signal = absolute momentum (Faber/Antonacci trend): is the asset above its level a
    year ago? The meta-model only ever decides whether to *follow* this long signal."""
    price = panel.closes[asset]
    return (price / price.shift(lookback_days) - 1.0) > 0


def regime_features(panel: PricePanel, asset: str = "SPY") -> pd.DataFrame:
    closes = panel.closes
    price = closes[asset]
    returns = price.pct_change()

    features = pd.DataFrame(index=closes.index)
    features["vol"] = returns.rolling(63).std() * np.sqrt(252)
    features["trend"] = price / price.rolling(200).mean() - 1.0
    equity = [t for t in EQUITY_TICKERS if t in closes.columns]
    above_ma = pd.DataFrame({t: closes[t] > closes[t].rolling(200).mean() for t in equity})
    features["breadth"] = above_ma.mean(axis=1)
    features["drawdown"] = price / price.rolling(252, min_periods=1).max() - 1.0
    features["mom_3m"] = price / price.shift(63) - 1.0
    return features
