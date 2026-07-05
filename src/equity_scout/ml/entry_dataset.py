"""Historical backfill dataset for the entry-quality model — features + relative-return labels.

For each ticker and each monthly `rebalance_dates` sample, build the price-derived feature row
(`entry_features.build_feature_row`) and the relative-return label
(`entry_eval.beats_benchmark_label`). A row is kept only when BOTH the full feature row AND a
full-horizon label exist — no partial rows, no peeking past the panel end. Rows are sorted by
(as_of, ticker) so downstream walk-forward splits on the as_of dates are reproducible.

Strictly price-derived (the features carry no fundamentals; the label is a forward relative return),
so the whole backfill is free of look-ahead — see `entry_features` for the honesty invariant.
"""
from __future__ import annotations

import pandas as pd

from equity_scout.market import PricePanel
from equity_scout.ml.entry_eval import (
    HORIZON_DAYS,
    beats_benchmark_label,
    relative_forward_return,
)
from equity_scout.ml.entry_features import (
    FEATURE_COLUMNS,
    MIN_HISTORY,
    build_feature_row,
    market_context,
)


def build_backfill_dataset(
    panel: PricePanel,
    tickers: list[str],
    *,
    benchmark: str = "SPY",
    horizon_days: int = HORIZON_DAYS,
    min_history: int = MIN_HISTORY,
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    """Assemble aligned (X, y, meta) from a stock+benchmark `PricePanel`.

    X: features, columns == FEATURE_COLUMNS. y: 0/1 beats-benchmark labels. meta: ticker/as_of/
    relative_return per row (for Rank-IC and attribution). Rows lacking a full feature row or a
    full-horizon label are dropped; the result is sorted by (as_of, ticker).

    The label and relative return are computed on windows ALIGNED to the benchmark's calendar
    (`closes[[ticker, benchmark]].dropna()`), so both legs' forward horizons end on the SAME date.
    A global universe carries interior NaN from differing exchange calendars; aligning drops those
    dates from both legs instead of fabricating a mismatched (and often spuriously 0) label. Feature
    building stays on the stock's OWN history — it is as-of and already leak-free."""
    closes = panel.closes
    context_df = market_context(panel, benchmark=benchmark)  # regime context once for the panel
    sample_dates = panel.rebalance_dates()

    rows: list[tuple[pd.Timestamp, str, dict, int, float]] = []
    for ticker in tickers:
        if ticker not in closes.columns or ticker == benchmark:
            continue
        stock_hist = closes[ticker].dropna()  # own calendar → leak-free as-of features
        pair = closes[[ticker, benchmark]].dropna()  # shared calendar for the forward label
        stock_leg, bench_leg = pair[ticker], pair[benchmark]
        for as_of in sample_dates:
            if as_of not in context_df.index or as_of not in stock_hist.index:
                continue
            if len(stock_hist.loc[:as_of]) < min_history:
                continue
            features = build_feature_row(
                stock_hist, context_df.loc[as_of].to_dict(), as_of, min_history=min_history
            )
            if features is None:
                continue
            if as_of not in pair.index:  # benchmark gap on the decision day — cannot label honestly
                continue
            label = beats_benchmark_label(stock_leg, bench_leg, as_of, horizon_days=horizon_days)
            if label is None:  # no aligned full forward horizon inside the panel — drop it
                continue
            rel = relative_forward_return(stock_leg, bench_leg, as_of, horizon_days)
            rows.append((as_of, ticker, features, int(label), float(rel)))

    rows.sort(key=lambda r: (r[0], r[1]))  # deterministic: as_of then ticker

    X = pd.DataFrame([r[2] for r in rows], columns=list(FEATURE_COLUMNS))
    y = pd.Series([r[3] for r in rows], dtype=int)
    meta = pd.DataFrame(
        {
            "ticker": [r[1] for r in rows],
            "as_of": [r[0] for r in rows],
            "relative_return": [r[4] for r in rows],
        }
    )
    return X, y, meta
