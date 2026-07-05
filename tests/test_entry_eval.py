"""Entry-eval tests: relative-return labels + OOS classification metrics."""
from __future__ import annotations

import numpy as np
import pandas as pd

from equity_scout.ml.entry_eval import (
    HORIZON_DAYS,
    beats_benchmark_label,
    classification_scores,
    rank_ic,
)


def _prices(values: list[float]) -> pd.Series:
    idx = pd.date_range("2026-01-01", periods=len(values), freq="B")
    return pd.Series(values, index=idx)


def test_beats_benchmark_label_is_relative_not_absolute():
    # stock +10% over the horizon, benchmark +4% → beats (1). Both up, but relative wins.
    stock = _prices([100.0] * 1 + [110.0] * (HORIZON_DAYS + 1))
    bench = _prices([100.0] * 1 + [104.0] * (HORIZON_DAYS + 1))
    at = stock.index[0]
    assert beats_benchmark_label(stock, bench, at, horizon_days=HORIZON_DAYS) == 1
    # stock +2%, benchmark +5% → loses (0) even though the stock rose
    stock2 = _prices([100.0] + [102.0] * (HORIZON_DAYS + 1))
    bench2 = _prices([100.0] + [105.0] * (HORIZON_DAYS + 1))
    assert beats_benchmark_label(stock2, bench2, at, horizon_days=HORIZON_DAYS) == 0


def test_beats_benchmark_label_none_without_full_horizon():
    stock = _prices([100.0, 101.0])
    bench = _prices([100.0, 100.5])
    assert beats_benchmark_label(stock, bench, stock.index[0], horizon_days=HORIZON_DAYS) is None


def test_classification_scores_reward_a_good_ranker():
    y = np.array([0, 0, 1, 1, 1, 0, 1, 0])
    good = np.array([0.1, 0.2, 0.8, 0.7, 0.9, 0.3, 0.6, 0.25])
    scores = classification_scores(y, good)
    assert 0.8 <= scores["auc"] <= 1.0
    assert 0.0 <= scores["brier"] <= 0.25
    assert scores["n"] == 8
    assert "log_loss" in scores and "base_rate" in scores
    assert scores["base_rate"] == 0.5


def test_classification_scores_single_class_auc_is_none_not_crash():
    y = np.array([1, 1, 1])
    scores = classification_scores(y, np.array([0.6, 0.7, 0.8]))
    assert scores["auc"] is None  # AUC undefined with one class — reported honestly, not faked
    assert scores["n"] == 3


def test_rank_ic_detects_monotonic_ranking():
    scores = np.array([0.1, 0.4, 0.6, 0.9])
    realized = np.array([-0.02, 0.01, 0.03, 0.08])  # higher score → higher realized rel-return
    assert rank_ic(scores, realized) > 0.9
    assert rank_ic(scores, -realized) < -0.9
