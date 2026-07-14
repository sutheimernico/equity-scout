"""Labels and out-of-sample metrics for the entry-quality model.

Two label strategies live here, one per registry family:
  * `beats_benchmark_label` (families `entry`/`entry_short`) — did the stock BEAT the benchmark
    (SPY) over the forward horizon, a relative return, not an absolute one (spec §5.2).
  * `triple_barrier_entry_label` (family `entry_tb`) — did the stock reach its OWN vol-scaled
    profit target before its stop, an absolute, single-asset question with no benchmark involved.
AUC across the two is NOT comparable (different label definitions), which is exactly why they are
gated as separate registry families (see `model_registry.py`).

Metrics are classification/ranking metrics (AUC, Brier, log-loss, Rank-IC) because the model
outputs a probability, not a return. Everything here is computed on OUT-OF-SAMPLE predictions by
the caller — this module has no notion of train/test, it just scores arrays honestly (AUC is None,
never faked, when a fold has one class).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from equity_scout.ml.labeling import trailing_daily_vol, triple_barrier_labels

HORIZON_DAYS = 20  # ~4 weeks, the primary forward horizon
SECONDARY_HORIZON_DAYS = 60  # ~12 weeks
SHORT_HORIZON_DAYS = 10  # ~2 weeks — the ML bots' shorter trading horizon (plan v6 P2/P3)


def forward_return(prices: pd.Series, at: pd.Timestamp, horizon_days: int) -> float | None:
    """Simple return from `at` to `horizon_days` trading days later. None if the series
    does not extend a full horizon past `at`."""
    if at not in prices.index:
        return None
    pos = prices.index.get_loc(at)
    end = pos + horizon_days
    if end >= len(prices):
        return None
    start_px, end_px = float(prices.iloc[pos]), float(prices.iloc[end])
    # A NaN at either endpoint (interior gap from a differing exchange calendar) must drop the
    # row, not slip through: NaN <= 0 is False, so without this guard int(NaN > 0) == 0 would
    # fabricate a "loses" label.
    if not math.isfinite(start_px) or not math.isfinite(end_px) or start_px <= 0:
        return None
    return end_px / start_px - 1.0


def relative_forward_return(
    stock: pd.Series, benchmark: pd.Series, at: pd.Timestamp, horizon_days: int
) -> float | None:
    """Stock forward return minus benchmark forward return over the same window."""
    s = forward_return(stock, at, horizon_days)
    b = forward_return(benchmark, at, horizon_days)
    if s is None or b is None:
        return None
    return s - b


def beats_benchmark_label(
    stock: pd.Series, benchmark: pd.Series, at: pd.Timestamp, *, horizon_days: int
) -> int | None:
    """1 if the stock's forward return exceeds the benchmark's, else 0. None if the
    horizon is not fully observable (no peeking past the data)."""
    rel = relative_forward_return(stock, benchmark, at, horizon_days)
    return None if rel is None else int(rel > 0.0)


def triple_barrier_entry_label(
    stock: pd.Series, at: pd.Timestamp, *, horizon_days: int, k_pt: float, k_sl: float, vol_window: int
) -> int | None:
    """The `entry_tb` family's label: 1 if the vol-scaled profit barrier (`k_pt` × the ticker's own
    trailing daily-return volatility) is touched before the vol-scaled stop barrier (`k_sl` × the
    same sigma) within `horizon_days`, else 0 — stop hit first OR neither barrier touched by the
    time barrier. Unlike the meta-model's triple-barrier label, a timeout is NOT resolved by the
    sign of the final return: this label answers "did we reach the target before the stop", so an
    inconclusive timeout is honestly a miss, not a coin flip on the drift (`on_timeout="zero"`).

    None when trailing vol is not yet observable (fewer than `vol_window` trailing returns up to
    `at`, or a degenerate zero/non-finite sigma) or `stock` has no full forward horizon past `at` —
    the same honesty contract as `beats_benchmark_label`. The full-horizon check is explicit here
    (unlike the lower-level `triple_barrier_labels`, which — for its other caller, the meta-model —
    tolerates a short forward window): this label must never be resolved on partial data."""
    if at not in stock.index:
        return None
    pos = stock.index.get_loc(at)
    if pos + horizon_days >= len(stock):  # no full forward horizon past `at` — mirrors forward_return
        return None
    sigma_series = trailing_daily_vol(stock.loc[:at], window=vol_window)
    sigma = float(sigma_series.iloc[-1]) if len(sigma_series) else float("nan")
    if not math.isfinite(sigma) or sigma <= 0:
        return None
    labels = triple_barrier_labels(
        stock,
        pd.DatetimeIndex([at]),
        horizon_days=horizon_days,
        profit_take=k_pt * sigma,
        stop_loss=k_sl * sigma,
        on_timeout="zero",
    )
    if at not in labels.index:  # no full forward horizon inside `stock` past `at`
        return None
    return int(labels.loc[at])


def classification_scores(y_true: np.ndarray, y_prob: np.ndarray) -> dict:
    """OOS classification metrics. AUC is None (not faked) when y_true is single-class."""
    y_true = np.asarray(y_true, dtype=int)
    y_prob = np.asarray(y_prob, dtype=float)
    n = int(len(y_true))
    base_rate = round(float(y_true.mean()), 4) if n else None  # undefined on empty, like the rest
    single_class = len(np.unique(y_true)) < 2
    auc = None if single_class else float(roc_auc_score(y_true, y_prob))
    # log_loss needs both labels present; guard the single-class case honestly
    ll = None if single_class else float(log_loss(y_true, y_prob, labels=[0, 1]))
    return {
        "n": n,
        "base_rate": base_rate,
        "auc": None if auc is None else round(auc, 4),
        "brier": round(float(brier_score_loss(y_true, y_prob)), 4) if n else None,
        "log_loss": None if ll is None else round(ll, 4),
    }


def rank_ic(scores: np.ndarray, realized: np.ndarray) -> float | None:
    """Spearman rank correlation between model scores and realized relative returns — the honest
    'does a higher score actually mean a better outcome' number. None when the correlation is
    undefined (fewer than 2 observations); 0.0 for constant input on either side (no dispersion →
    no observable ranking skill, which is a real 'no edge' result rather than an undefined one)."""
    s = pd.Series(np.asarray(scores, dtype=float))
    r = pd.Series(np.asarray(realized, dtype=float))
    if len(s) < 2:
        return None
    if s.nunique() < 2 or r.nunique() < 2:
        return 0.0
    return round(float(s.corr(r, method="spearman")), 4)
