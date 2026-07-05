"""Backfill-dataset tests: assemble (X, y, meta) from a PricePanel — features + rel-return labels."""
from __future__ import annotations

import numpy as np
import pandas as pd

from equity_scout.market import PricePanel
from equity_scout.ml.entry_dataset import build_backfill_dataset
from equity_scout.ml.entry_eval import HORIZON_DAYS
from equity_scout.ml.entry_features import FEATURE_COLUMNS


def _panel(n: int = 500) -> PricePanel:
    """SPY benchmark; AAA beats it every horizon (label 1), BBB lags (label 0); CCC has too
    little history (mostly NaN) so it must contribute nothing without crashing."""
    idx = pd.bdate_range("2019-01-01", periods=n)
    ccc = [np.nan] * (n - 40) + [100.0 * 1.001**i for i in range(40)]
    data = {
        "SPY": [100.0 * 1.0004**i for i in range(n)],
        "AAA": [100.0 * 1.0006**i for i in range(n)],  # steeper → beats SPY over any window
        "BBB": [100.0 * 1.0002**i for i in range(n)],  # flatter → lags SPY over any window
        "CCC": ccc,
    }
    return PricePanel(pd.DataFrame(data, index=idx))


def test_build_backfill_dataset_shapes_and_columns():
    panel = _panel()
    X, y, meta = build_backfill_dataset(panel, ["AAA", "BBB", "CCC"], horizon_days=HORIZON_DAYS)
    assert list(X.columns) == list(FEATURE_COLUMNS)
    assert len(X) == len(y) == len(meta) > 0
    assert list(meta.columns) == ["ticker", "as_of", "relative_return"]
    assert set(y.unique()) <= {0, 1}


def test_labels_track_relative_performance():
    panel = _panel()
    _, y, meta = build_backfill_dataset(panel, ["AAA", "BBB"], horizon_days=HORIZON_DAYS)
    # AAA always beats SPY → all 1; BBB always lags → all 0 → both classes present.
    assert set(y.unique()) == {0, 1}
    aaa = y[meta["ticker"] == "AAA"]
    bbb = y[meta["ticker"] == "BBB"]
    assert (aaa == 1).all()
    assert (bbb == 0).all()
    # meta.relative_return sign agrees with the label
    assert (meta.loc[meta["ticker"] == "AAA", "relative_return"] > 0).all()
    assert (meta.loc[meta["ticker"] == "BBB", "relative_return"] < 0).all()


def test_too_short_ticker_contributes_nothing():
    panel = _panel()
    _, _, meta = build_backfill_dataset(panel, ["AAA", "BBB", "CCC"], horizon_days=HORIZON_DAYS)
    assert "CCC" not in set(meta["ticker"])  # < 252 history → dropped, no crash


def test_end_of_panel_rows_dropped_for_lack_of_horizon():
    panel = _panel()
    _, _, meta = build_backfill_dataset(panel, ["AAA", "BBB"], horizon_days=HORIZON_DAYS)
    # every kept as_of must leave a full forward horizon inside the panel
    last_labelable = panel.dates[-1 - HORIZON_DAYS]
    assert meta["as_of"].max() <= last_labelable


def test_deterministic_ordering_by_as_of_then_ticker():
    panel = _panel()
    _, _, meta = build_backfill_dataset(panel, ["BBB", "AAA"], horizon_days=HORIZON_DAYS)
    pairs = list(zip(meta["as_of"], meta["ticker"]))
    assert pairs == sorted(pairs, key=lambda p: (p[0], p[1]))


def test_unknown_ticker_is_ignored():
    panel = _panel()
    X, _, meta = build_backfill_dataset(panel, ["AAA", "NOPE"], horizon_days=HORIZON_DAYS)
    assert "NOPE" not in set(meta["ticker"])
    assert len(X) > 0
