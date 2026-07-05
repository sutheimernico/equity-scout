"""Price-derived feature row for the entry-quality model — NO FUNDAMENTALS.

Honesty invariant (spec §5.2, ADR 0003): every feature here is a pure function of PAST
adjusted closes at or before `as_of`. There is deliberately no `.info`/fundamentals
lookup — yfinance has no historical fundamentals, so any fundamentals backfill would be
look-ahead. The live `signal_readings` log keeps the point-in-time fundamentals picture
for a future fundamentals-aware model; the backfill model stays strictly price-derived.

A feature row combines two blocks:
  * market context — the benchmark's regime (reused verbatim from `ml.features.regime_features`,
    same value for every ticker on a date; prefixed `mkt_` in the row to keep it distinct from
    the per-stock momentum and to avoid the `mom_3m` name collision);
  * per-stock price geometry — trailing momentum, distance to the 200d mean, 1y drawdown, and
    annualised 3m volatility, all from the stock's own trailing closes.

`FEATURE_COLUMNS` is the ordered, single source of truth for the feature layout; the dataset
builder and the model both consume it, never a hand-copied list.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from equity_scout.market import PricePanel
from equity_scout.ml.features import regime_features

# Reused subset of regime_features (its full output today) — the market-regime context.
MARKET_CONTEXT_COLUMNS: tuple[str, ...] = ("vol", "trend", "breadth", "drawdown", "mom_3m")
# Per-stock price geometry computed from the stock's own trailing closes.
STOCK_COLUMNS: tuple[str, ...] = (
    "mom_1m",
    "mom_3m",
    "mom_6m",
    "dist_sma200",
    "drawdown_1y",
    "vol_3m",
)
# Ordered, single-source feature layout. Market columns are `mkt_`-prefixed so market `mom_3m`
# (benchmark) never collides with the per-stock `mom_3m`.
FEATURE_COLUMNS: tuple[str, ...] = tuple(f"mkt_{c}" for c in MARKET_CONTEXT_COLUMNS) + STOCK_COLUMNS

# One trading year — the longest window (1y drawdown / 200d mean) any feature needs.
MIN_HISTORY = 252

_MOM_LOOKBACKS = {"mom_1m": 21, "mom_3m": 63, "mom_6m": 126}


def market_context(panel: PricePanel, benchmark: str = "SPY") -> pd.DataFrame:
    """Market-regime context per date — a thin wrapper over `regime_features` on the benchmark,
    selecting the reused columns. Same row applies to every ticker scored on that date."""
    feats = regime_features(panel, asset=benchmark)
    return feats[list(MARKET_CONTEXT_COLUMNS)]


def build_feature_row(
    stock: pd.Series, context: dict[str, float], as_of: pd.Timestamp
) -> dict | None:
    """Price-derived feature row for one (stock, as_of) using only closes at/before `as_of`.

    Returns exactly `FEATURE_COLUMNS` keys (ordered), or None when the row cannot be built
    honestly: fewer than `MIN_HISTORY` closes up to `as_of`, or any non-finite value (e.g. an
    unfilled regime window in `context`, or a degenerate price)."""
    hist = stock.loc[:as_of].dropna()
    if len(hist) < MIN_HISTORY:
        return None

    price = float(hist.iloc[-1])
    if price <= 0:
        return None

    row: dict[str, float] = {
        f"mkt_{k}": float(context.get(k, float("nan"))) for k in MARKET_CONTEXT_COLUMNS
    }

    for name, lookback in _MOM_LOOKBACKS.items():
        past = float(hist.iloc[-1 - lookback])
        row[name] = price / past - 1.0 if past > 0 else float("nan")

    sma200 = float(hist.iloc[-200:].mean())
    row["dist_sma200"] = price / sma200 - 1.0 if sma200 > 0 else float("nan")

    max_1y = float(hist.iloc[-MIN_HISTORY:].max())
    row["drawdown_1y"] = price / max_1y - 1.0 if max_1y > 0 else float("nan")

    rets = hist.iloc[-64:].pct_change().dropna()  # 63 trailing daily returns
    row["vol_3m"] = float(rets.std(ddof=1) * np.sqrt(252)) if len(rets) >= 2 else float("nan")

    if any(not np.isfinite(v) for v in row.values()):
        return None
    return {k: row[k] for k in FEATURE_COLUMNS}
