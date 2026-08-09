"""Historical backfill dataset for the entry-quality model — features + relative-return labels.

For each ticker and each monthly `rebalance_dates` sample, build the price-derived feature row
(`entry_features.build_feature_row`) and the relative-return label
(`entry_eval.beats_benchmark_label`). A row is kept only when BOTH the full feature row AND a
full-horizon label exist — no partial rows, no peeking past the panel end. Rows are sorted by
(as_of, ticker) so downstream walk-forward splits on the as_of dates are reproducible.

Strictly price-derived by default (the features carry no fundamentals; the label is a forward
relative return), so the whole backfill is free of look-ahead — see `entry_features` for the
honesty invariant. With an `evidence_index` the point-in-time insider block is appended — see
below.
"""
from __future__ import annotations

import pandas as pd

from equity_scout.market import PricePanel
from equity_scout.ml.entry_eval import (
    HORIZON_DAYS,
    beats_benchmark_label,
    relative_forward_return,
    triple_barrier_entry_label,
)
from equity_scout.ml.entry_features import (
    FEATURE_COLUMNS,
    MIN_HISTORY,
    build_feature_row,
    market_context,
)
from equity_scout.ml.evidence_features import EVIDENCE_FEATURE_COLUMNS, EvidenceIndex
from equity_scout.ml.labeling import BarrierConfig


def build_backfill_dataset(
    panel: PricePanel,
    tickers: list[str],
    *,
    benchmark: str = "SPY",
    horizon_days: int = HORIZON_DAYS,
    min_history: int = MIN_HISTORY,
    label_direction: str = "beats",
    barrier_config: BarrierConfig | None = None,
    evidence_index: EvidenceIndex | None = None,
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    """Assemble aligned (X, y, meta) from a stock+benchmark `PricePanel`.

    X: features, columns == FEATURE_COLUMNS (+ EVIDENCE_FEATURE_COLUMNS with an evidence_index).
    y: 0/1 labels (meaning depends on `label_direction`).
    meta: ticker/as_of/relative_return per row (for Rank-IC and attribution, ALWAYS vs `benchmark`
    regardless of label_direction). Rows lacking a full feature row or a full-horizon label are
    dropped; the result is sorted by (as_of, ticker).

    `label_direction`:
      * "beats" (default, family `entry`) — y = 1 iff the stock beats the benchmark.
      * "lags" (family `entry_short`) — inverts the target: y = 1 when the stock UNDERPERFORMS the
        benchmark, and meta's relative_return is sign-flipped to match, so Rank-IC keeps meaning
        "higher score ↔ better outcome for the bot" in both directions.
      * "triple_barrier" (family `entry_tb`) — y comes from
        `entry_eval.triple_barrier_entry_label` instead: 1 iff the ticker's OWN vol-scaled profit
        barrier is touched before its stop barrier within `barrier_config.horizon_days`. In this
        mode `barrier_config.horizon_days` is THE horizon — the separate `horizon_days` param is
        IGNORED (labels, relative_return window and end-of-panel cropping all use the config's
        value), so the persisted barrier config can never lie about the horizon the model was
        actually trained on (the follow-up target/stop derivation reads exactly that config). AUC
        is not comparable across label definitions — that is exactly why `entry_tb` is its own
        registry family, never compared against `entry`/`entry_short`. `barrier_config` (defaults
        to `BarrierConfig()`) is REQUIRED context for this mode; it is ignored otherwise.

    The label and relative return are computed on windows ALIGNED to the benchmark's calendar
    (`closes[[ticker, benchmark]].dropna()`), so both legs' forward horizons end on the SAME date.
    A global universe carries interior NaN from differing exchange calendars; aligning drops those
    dates from both legs instead of fabricating a mismatched (and often spuriously 0) label. Feature
    building stays on the stock's OWN history — it is as-of and already leak-free.

    `evidence_index` (v15 P3, additive — default None reproduces the pre-P3 layout exactly):
    when given, every row's feature dict is extended by `EVIDENCE_FEATURE_COLUMNS`, appended
    after the price block, so X's columns become FEATURE_COLUMNS + EVIDENCE_FEATURE_COLUMNS. The
    block is point-in-time by construction (`EvidenceIndex.features` only sees events strictly
    before `as_of`) and never returns None, so it can add columns but can never drop a row —
    which keeps the with/without comparison an apples-to-apples one on the SAME sample."""
    if label_direction not in ("beats", "lags", "triple_barrier"):
        raise ValueError(
            f"label_direction must be 'beats', 'lags' or 'triple_barrier', got {label_direction!r}"
        )
    invert = label_direction == "lags"
    tb_config = barrier_config if barrier_config is not None else BarrierConfig()
    if label_direction == "triple_barrier":
        # Single source of truth: the barrier config IS the horizon in TB mode (see docstring).
        # Deriving it here (instead of trusting the caller to keep two params in sync) makes it
        # impossible for the persisted config to disagree with the actual training horizon.
        horizon_days = tb_config.horizon_days
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
            if evidence_index is not None:
                features = {**features, **evidence_index.features(ticker, as_of)}
            if as_of not in pair.index:  # benchmark gap on the decision day — cannot label honestly
                continue
            if label_direction == "triple_barrier":
                label = triple_barrier_entry_label(
                    stock_leg, as_of, horizon_days=horizon_days,
                    k_pt=tb_config.k_pt, k_sl=tb_config.k_sl, vol_window=tb_config.vol_window,
                )
            else:
                label = beats_benchmark_label(stock_leg, bench_leg, as_of, horizon_days=horizon_days)
            if label is None:  # no aligned full forward horizon inside the panel — drop it
                continue
            rel = relative_forward_return(stock_leg, bench_leg, as_of, horizon_days)
            if rel is None:  # triple_barrier's label doesn't touch bench_leg — re-check explicitly
                continue
            if invert:
                label, rel = 1 - int(label), -float(rel)
            rows.append((as_of, ticker, features, int(label), float(rel)))

    rows.sort(key=lambda r: (r[0], r[1]))  # deterministic: as_of then ticker

    columns = list(FEATURE_COLUMNS)
    if evidence_index is not None:
        columns += list(EVIDENCE_FEATURE_COLUMNS)
    X = pd.DataFrame([r[2] for r in rows], columns=columns)
    # No-op today by construction (every row's feature dict is already complete before it lands
    # in `rows`, verified 0 NaN on real data) — but `pd.DataFrame(..., columns=...)` silently
    # NaN-fills any column missing from a row dict, so a future change above this point (e.g. a
    # feature builder returning a partial dict) would otherwise corrupt training rows instead of
    # failing loudly. Mirrors the honesty stance of `EntryModel.score_row`'s missing-column guard.
    nan_columns = list(X.columns[X.isna().any()])
    if nan_columns:
        raise ValueError(f"build_backfill_dataset produced NaN in columns {nan_columns!r}")
    y = pd.Series([r[3] for r in rows], dtype=int)
    meta = pd.DataFrame(
        {
            "ticker": [r[1] for r in rows],
            "as_of": [r[0] for r in rows],
            "relative_return": [r[4] for r in rows],
        }
    )
    return X, y, meta
