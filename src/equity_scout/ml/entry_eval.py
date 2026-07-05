"""Labels and out-of-sample metrics for the entry-quality model.

Label = did the stock BEAT the benchmark (SPY) over the forward horizon — a relative
return, not an absolute one (spec §5.2). Metrics are classification/ranking metrics
(AUC, Brier, log-loss, Rank-IC) because the model outputs a probability, not a return.
Everything here is computed on OUT-OF-SAMPLE predictions by the caller — this module
has no notion of train/test, it just scores arrays honestly (AUC is None, never faked,
when a fold has one class).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

HORIZON_DAYS = 20  # ~4 weeks, the primary forward horizon
SECONDARY_HORIZON_DAYS = 60  # ~12 weeks


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
    if start_px <= 0:
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


def classification_scores(y_true: np.ndarray, y_prob: np.ndarray) -> dict:
    """OOS classification metrics. AUC is None (not faked) when y_true is single-class."""
    y_true = np.asarray(y_true, dtype=int)
    y_prob = np.asarray(y_prob, dtype=float)
    n = int(len(y_true))
    base_rate = float(y_true.mean()) if n else 0.0
    single_class = len(np.unique(y_true)) < 2
    auc = None if single_class else float(roc_auc_score(y_true, y_prob))
    # log_loss needs both labels present; guard the single-class case honestly
    ll = None if single_class else float(log_loss(y_true, y_prob, labels=[0, 1]))
    return {
        "n": n,
        "base_rate": round(base_rate, 4),
        "auc": None if auc is None else round(auc, 4),
        "brier": round(float(brier_score_loss(y_true, y_prob)), 4) if n else None,
        "log_loss": None if ll is None else round(ll, 4),
    }


def rank_ic(scores: np.ndarray, realized: np.ndarray) -> float:
    """Spearman rank correlation between model scores and realized relative returns —
    the honest 'does a higher score actually mean a better outcome' number."""
    s = pd.Series(np.asarray(scores, dtype=float))
    r = pd.Series(np.asarray(realized, dtype=float))
    if len(s) < 2 or s.nunique() < 2 or r.nunique() < 2:
        return 0.0
    return round(float(s.corr(r, method="spearman")), 4)
