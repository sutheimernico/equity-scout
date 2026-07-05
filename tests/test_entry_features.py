"""Entry-feature tests: price-derived feature row per (ticker, as_of) — no fundamentals."""
from __future__ import annotations

import pandas as pd

from equity_scout.market import PricePanel
from equity_scout.ml.entry_features import (
    FEATURE_COLUMNS,
    MARKET_CONTEXT_COLUMNS,
    build_feature_row,
    market_context,
)

# A plausible market-context row (regime_features column names) for the per-stock unit tests.
_CTX = {"vol": 0.15, "trend": 0.05, "breadth": 0.75, "drawdown": -0.02, "mom_3m": 0.03}


def _series(values: list[float]) -> pd.Series:
    idx = pd.bdate_range("2020-01-01", periods=len(values))
    return pd.Series(values, index=idx)


def test_build_feature_row_has_exactly_feature_columns():
    up = _series([100.0 * 1.001**i for i in range(300)])
    row = build_feature_row(up, _CTX, up.index[-1])
    assert row is not None
    assert list(row) == list(FEATURE_COLUMNS)  # exact keys, ordered — single source of truth


def test_build_feature_row_none_on_short_history():
    short = _series([100.0 + i for i in range(120)])  # < 252 closes → can't build a full row
    assert build_feature_row(short, _CTX, short.index[-1]) is None


def test_build_feature_row_none_on_nan_context():
    up = _series([100.0 * 1.001**i for i in range(300)])
    bad_ctx = {**_CTX, "vol": float("nan")}  # unfilled regime window → unusable row
    assert build_feature_row(up, bad_ctx, up.index[-1]) is None


def test_momentum_signs_track_trend():
    up = _series([100.0 * 1.001**i for i in range(300)])
    down = _series([100.0 * 0.999**i for i in range(300)])
    up_row = build_feature_row(up, _CTX, up.index[-1])
    down_row = build_feature_row(down, _CTX, down.index[-1])
    assert up_row["mom_1m"] > 0 and up_row["mom_3m"] > 0 and up_row["mom_6m"] > 0
    assert down_row["mom_1m"] < 0 and down_row["mom_3m"] < 0 and down_row["mom_6m"] < 0


def test_deep_drawdown_is_negative():
    # rise for 250 days, then crash the last 50 → price well below the 1y high and the sma200
    rising = [100.0 * 1.002**i for i in range(250)]
    peak = rising[-1]
    crash = [peak * (1 - 0.004 * j) for j in range(1, 51)]  # ~ -20%
    s = _series(rising + crash)
    row = build_feature_row(s, _CTX, s.index[-1])
    assert row["drawdown_1y"] < -0.1
    assert row["dist_sma200"] < 0


def test_market_context_wraps_regime_features():
    n = 400
    data = {t: [100.0 * 1.0005**i for i in range(n)] for t in ["SPY", "VEU", "VWO", "VNQ"]}
    panel = PricePanel(pd.DataFrame(data, index=pd.bdate_range("2019-01-01", periods=n)))
    ctx = market_context(panel)
    assert list(ctx.columns) == list(MARKET_CONTEXT_COLUMNS)
    assert len(ctx) == n
    # a late row is fully filled (rolling windows warmed up) and usable as a context dict
    late = ctx.iloc[-1].to_dict()
    assert all(pd.notna(v) for v in late.values())
