"""CSCV probability of backtest overfitting on constructed matrices with known answers."""
from __future__ import annotations

import math

import numpy as np

from equity_scout.ml.pbo import probability_of_backtest_overfitting


def test_pbo_zero_when_one_config_dominates_every_block() -> None:
    # config 0 is best in every block → in-sample best is always out-of-sample best → no overfit
    matrix = np.array([[3.0, 3.0, 3.0, 3.0], [2.0, 2.0, 2.0, 2.0], [1.0, 1.0, 1.0, 1.0]])
    assert probability_of_backtest_overfitting(matrix) == 0.0


def test_pbo_one_when_in_sample_winner_is_out_of_sample_loser() -> None:
    # each config wins exactly one block and loses the other → IS-best is always OOS-worst
    matrix = np.array([[10.0, 0.0], [0.0, 10.0]])
    assert probability_of_backtest_overfitting(matrix) == 1.0


def test_pbo_nan_for_degenerate_matrix() -> None:
    assert math.isnan(probability_of_backtest_overfitting(np.array([[1.0, 2.0]])))  # one config
    assert math.isnan(probability_of_backtest_overfitting(np.zeros((3, 1))))  # one block
