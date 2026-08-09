"""Backfill-dataset tests: assemble (X, y, meta) from a PricePanel — features + labels."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from equity_scout.market import PricePanel
from equity_scout.ml.entry_dataset import build_backfill_dataset
from equity_scout.ml.entry_eval import HORIZON_DAYS
from equity_scout.ml.entry_features import FEATURE_COLUMNS
from equity_scout.ml.labeling import BarrierConfig


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


def test_labels_align_to_benchmark_calendar_on_interior_nan():
    # A global universe produces interior NaN from differing exchange calendars. The label must be
    # computed on windows ALIGNED to the benchmark's calendar, never fabricated as 0 from a NaN.
    n = 500
    idx = pd.bdate_range("2019-01-01", periods=n)
    spy = [100.0 * 1.0004**i for i in range(n)]
    aaa = [100.0 * 1.0006**i for i in range(n)]  # beats SPY on every aligned window
    spy[300] = np.nan  # an interior benchmark gap
    panel = PricePanel(pd.DataFrame({"SPY": spy, "AAA": aaa}, index=idx))

    _, y, meta = build_backfill_dataset(panel, ["AAA"], horizon_days=HORIZON_DAYS)

    assert set(y.unique()) == {1}  # no fabricated 0 labels from the NaN
    # every kept as_of's relative_return equals stock_fwd − bench_fwd over the SAME aligned dates
    pair = panel.closes[["AAA", "SPY"]].dropna()
    for _, r in meta.iterrows():
        pos = pair.index.get_loc(r["as_of"])
        end = pos + HORIZON_DAYS
        s_fwd = pair["AAA"].iloc[end] / pair["AAA"].iloc[pos] - 1.0
        b_fwd = pair["SPY"].iloc[end] / pair["SPY"].iloc[pos] - 1.0
        assert r["relative_return"] == pytest.approx(s_fwd - b_fwd)
    # rows without an aligned full horizon are dropped
    assert meta["as_of"].max() <= pair.index[-1 - HORIZON_DAYS]


def test_min_history_is_propagated_into_feature_building():
    panel = _panel()
    _, _, meta_low = build_backfill_dataset(panel, ["AAA"], min_history=252)
    _, _, meta_high = build_backfill_dataset(panel, ["AAA"], min_history=450)
    # a stricter min_history must actually drop early rows, not silently build from 252
    assert len(meta_high) < len(meta_low)
    assert meta_high["as_of"].min() > meta_low["as_of"].min()


def test_invalid_label_direction_raises():
    panel = _panel()
    with pytest.raises(ValueError):
        build_backfill_dataset(panel, ["AAA"], label_direction="bogus")


# --- label_direction="triple_barrier" (entry_tb family) ---
def _panel_with_vol(n: int = 500) -> PricePanel:
    """Like `_panel()` but with a small daily oscillation added on top of the smooth exponential
    growth. `_panel()`'s series have a CONSTANT daily return (pure geometric growth), so their
    trailing realized vol is exactly 0 — every triple-barrier label would come back None (a
    zero-width barrier is rejected, see `triple_barrier_entry_label`). The oscillation gives the
    trailing vol window something real to measure."""
    idx = pd.bdate_range("2019-01-01", periods=n)
    data = {
        "SPY": [100.0 * 1.0004**i + 0.05 * ((-1) ** i) for i in range(n)],
        "AAA": [100.0 * 1.0006**i + 0.05 * ((-1) ** i) for i in range(n)],
        "BBB": [100.0 * 1.0002**i + 0.05 * ((-1) ** i) for i in range(n)],
    }
    return PricePanel(pd.DataFrame(data, index=idx))


def test_build_backfill_dataset_triple_barrier_shape():
    panel = _panel_with_vol()
    config = BarrierConfig(k_pt=2.0, k_sl=1.0, horizon_days=40, vol_window=60)
    X, y, meta = build_backfill_dataset(
        panel,
        ["AAA", "BBB"],
        horizon_days=config.horizon_days,
        label_direction="triple_barrier",
        barrier_config=config,
    )
    assert list(X.columns) == list(FEATURE_COLUMNS)
    assert len(X) == len(y) == len(meta) > 0
    assert list(meta.columns) == ["ticker", "as_of", "relative_return"]
    assert set(y.unique()) <= {0, 1}


def test_triple_barrier_dataset_falls_back_to_default_barrier_config():
    panel = _panel_with_vol()
    X, _, meta = build_backfill_dataset(
        panel, ["AAA"], horizon_days=BarrierConfig().horizon_days, label_direction="triple_barrier"
    )
    assert len(X) == len(meta) > 0


def test_triple_barrier_horizon_comes_from_barrier_config_not_param():
    """Single source of truth: in TB mode `barrier_config.horizon_days` IS the horizon; the
    separate `horizon_days` param is ignored. Otherwise a caller passing the relative-return
    default (20) would train on horizon 20 while persisting a config that claims 40 — and the
    follow-up target/stop derivation reads exactly that config."""
    panel = _panel_with_vol()
    config = BarrierConfig()  # horizon_days=40
    _, y_wrong, meta_wrong = build_backfill_dataset(
        panel, ["AAA", "BBB"], horizon_days=20, label_direction="triple_barrier", barrier_config=config
    )
    _, y_right, meta_right = build_backfill_dataset(
        panel, ["AAA", "BBB"], horizon_days=config.horizon_days, label_direction="triple_barrier",
        barrier_config=config,
    )
    pd.testing.assert_frame_equal(meta_wrong, meta_right)
    pd.testing.assert_series_equal(y_wrong, y_right)
    # and the config horizon is genuinely in effect: end-of-panel cropping follows 40, not 20
    pair = panel.closes[["AAA", "SPY"]].dropna()
    assert meta_wrong["as_of"].max() <= pair.index[-1 - config.horizon_days]


def test_default_call_is_unchanged_by_the_additive_evidence_param():
    """Regression: `evidence_index=None` must reproduce today's exact layout — the nightly
    chain calls this without the parameter and must not move an inch."""
    panel = _panel()
    X, y, meta = build_backfill_dataset(panel, ["AAA", "BBB"], horizon_days=HORIZON_DAYS)
    X2, y2, meta2 = build_backfill_dataset(
        panel, ["AAA", "BBB"], horizon_days=HORIZON_DAYS, evidence_index=None
    )
    assert list(X.columns) == list(FEATURE_COLUMNS)
    pd.testing.assert_frame_equal(X, X2)
    pd.testing.assert_series_equal(y, y2)
    pd.testing.assert_frame_equal(meta, meta2)


def test_evidence_index_appends_its_block_point_in_time():
    """With an index, X carries FEATURE_COLUMNS + EVIDENCE_FEATURE_COLUMNS, and the flag is 0
    for every as_of at or before the cluster's t0 and 1 inside the window after it."""
    from datetime import date

    from equity_scout.ml.evidence_features import EVIDENCE_FEATURE_COLUMNS, EvidenceIndex

    panel = _panel()
    cluster_day = date(2020, 6, 1)
    index = EvidenceIndex({"AAA": [(cluster_day, 7)]})
    X, _, meta = build_backfill_dataset(
        panel, ["AAA", "BBB"], horizon_days=HORIZON_DAYS, evidence_index=index
    )
    assert list(X.columns) == list(FEATURE_COLUMNS) + list(EVIDENCE_FEATURE_COLUMNS)

    as_of = pd.to_datetime(meta["as_of"])
    is_aaa = meta["ticker"] == "AAA"
    flag = X["ev_insider_cluster_91d"]
    # BBB has no clusters at all -> the whole block is zero for it.
    assert (X.loc[~is_aaa.to_numpy(), list(EVIDENCE_FEATURE_COLUMNS)] == 0.0).all().all()
    # AAA before the filing day: invisible. Inside the 91-day window after it: visible.
    before = is_aaa.to_numpy() & (as_of.dt.date <= cluster_day).to_numpy()
    inside = (
        is_aaa.to_numpy()
        & (as_of.dt.date > cluster_day).to_numpy()
        & (as_of.dt.date <= date(2020, 8, 1)).to_numpy()
    )
    assert (flag[before] == 0.0).all()
    assert inside.any() and (flag[inside] == 1.0).all()
    assert (X.loc[inside, "ev_insider_max_size_91d"] == 7.0).all()
