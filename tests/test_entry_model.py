"""Entry-model tests: fit/score 0-100 + group-aware purged walk-forward OOS evaluation."""
from __future__ import annotations

import numpy as np
import pandas as pd

from equity_scout.ml.entry_eval import HORIZON_DAYS
from equity_scout.ml.entry_features import FEATURE_COLUMNS
from equity_scout.ml.entry_model import (
    EntryModel,
    _date_grouped_folds,
    train_entry_model,
    walk_forward_efficiency,
    walk_forward_evaluate,
)

_SIGNAL_COL = FEATURE_COLUMNS[0]  # the one informative feature in the synthetic sets


def _dataset(*, n_dates: int, per_date: int, informative: bool, seed: int):
    """Monthly as_of dates (real rebalance cadence → the horizon purge is meaningful), several
    rows per date. When `informative`, one feature drives the label and the realized relative
    return; otherwise the label is pure noise (no learnable edge)."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2008-01-31", periods=n_dates, freq="ME")
    feats, labels, tickers, as_ofs, rels = [], [], [], [], []
    for d in dates:
        for j in range(per_date):
            row = rng.normal(size=len(FEATURE_COLUMNS))
            signal = row[0]
            if informative:
                prob = 1.0 / (1.0 + np.exp(-(3.5 * signal)))
                label = int(rng.random() < prob)
                rel = 0.01 * signal + 0.001 * rng.normal()
            else:
                label = int(rng.random() < 0.5)
                rel = 0.001 * rng.normal()
            feats.append(row)
            labels.append(label)
            tickers.append(f"T{j}")
            as_ofs.append(d)
            rels.append(rel)
    X = pd.DataFrame(feats, columns=list(FEATURE_COLUMNS))
    y = pd.Series(labels, dtype=int)
    meta = pd.DataFrame({"ticker": tickers, "as_of": as_ofs, "relative_return": rels})
    return X, y, meta


def test_train_and_score_many_returns_ints_in_range():
    X, y, _ = _dataset(n_dates=40, per_date=6, informative=True, seed=1)
    model = train_entry_model(X, y, model="random_forest")
    scores = model.score_many(X)
    assert scores.dtype.kind in ("i", "u")
    assert scores.min() >= 0 and scores.max() <= 100
    assert len(scores) == len(X)


def test_score_is_monotonic_in_the_signal():
    X, y, _ = _dataset(n_dates=60, per_date=8, informative=True, seed=2)
    model = train_entry_model(X, y, model="random_forest")
    grid = pd.DataFrame(0.0, index=range(9), columns=list(FEATURE_COLUMNS))
    grid[_SIGNAL_COL] = np.linspace(-2.5, 2.5, 9)
    scores = model.score_many(grid)
    assert scores[0] < scores[-1]  # higher signal → higher score
    assert np.all(np.diff(scores) >= 0)  # non-decreasing across the grid


def test_score_row_matches_single_row_of_score_many():
    X, y, _ = _dataset(n_dates=40, per_date=6, informative=True, seed=3)
    model = train_entry_model(X, y)
    row = X.iloc[0].to_dict()
    assert model.score_row(row) == int(model.score_many(X.iloc[[0]])[0])


def test_walk_forward_reports_expected_keys():
    X, y, meta = _dataset(n_dates=120, per_date=6, informative=True, seed=4)
    result = walk_forward_evaluate(X, y, meta, model="random_forest")
    assert set(result) == {
        "auc", "brier", "rank_ic", "n_oos", "n_splits_used", "feature_importance",
        "is_auc", "wfe",
    }
    assert result["n_oos"] > 0
    assert result["n_splits_used"] >= 1
    assert set(result["feature_importance"]) == set(FEATURE_COLUMNS)
    # a random forest fits its training set nearly perfectly -> IS edge exists, WFE defined
    assert result["is_auc"] is not None and result["is_auc"] > 0.5
    assert result["wfe"] is not None


def test_walk_forward_efficiency_ratio_and_guards():
    """v13 Q3: WFE = share of the IS excess-AUC edge surviving OOS; None instead of a
    made-up number when a side is missing or there is no IS edge to preserve."""
    assert walk_forward_efficiency(0.6, 0.7) == 0.5  # 0.1 of 0.2 survives
    assert walk_forward_efficiency(0.7, 0.7) == 1.0
    assert walk_forward_efficiency(0.55, 0.5) is None  # no IS edge -> nothing to measure
    assert walk_forward_efficiency(0.6, 0.0) is None  # degenerate is_metric, no crash
    assert walk_forward_efficiency(None, 0.9) is None
    assert walk_forward_efficiency(0.6, None) is None


def test_learnable_dataset_has_oos_edge():
    X, y, meta = _dataset(n_dates=120, per_date=6, informative=True, seed=5)
    result = walk_forward_evaluate(X, y, meta, model="random_forest")
    assert result["auc"] > 0.6  # a real, out-of-sample edge on a learnable set
    assert result["rank_ic"] > 0.0  # higher score tracks higher realized relative return


def test_noise_dataset_has_no_fake_edge():
    X, y, meta = _dataset(n_dates=120, per_date=6, informative=False, seed=6)
    result = walk_forward_evaluate(X, y, meta, model="random_forest")
    assert 0.4 <= result["auc"] <= 0.6  # no fabricated edge where none exists


def test_walk_forward_split_is_date_grouped():
    # The honesty-critical property: every row sharing an as_of date lands on ONE side of a split,
    # so no date straddles train/test. A regression to a row-based split would still pass the
    # auc/noise tests but would fail here.
    X, y, meta = _dataset(n_dates=120, per_date=6, informative=True, seed=11)
    as_of = pd.to_datetime(meta["as_of"]).reset_index(drop=True)
    folds = list(_date_grouped_folds(as_of, n_splits=4, horizon_days=HORIZON_DAYS))
    assert len(folds) >= 1
    for train_mask, test_mask in folds:
        train_dates = set(as_of[train_mask])
        test_dates = set(as_of[test_mask])
        assert train_dates and test_dates  # both sides populated
        assert train_dates.isdisjoint(test_dates)  # no as_of date appears on both sides


def test_walk_forward_is_reproducible():
    X, y, meta = _dataset(n_dates=120, per_date=6, informative=True, seed=7)
    a = walk_forward_evaluate(X, y, meta, model="random_forest")
    b = walk_forward_evaluate(X, y, meta, model="random_forest")
    assert a == b  # seeded estimator + deterministic split → identical metrics


def test_train_entry_model_rejects_unknown_kind():
    X, y, _ = _dataset(n_dates=40, per_date=6, informative=True, seed=8)
    try:
        train_entry_model(X, y, model="nope")
    except ValueError:
        return
    raise AssertionError("unknown model kind should raise ValueError")


def test_entry_model_pickles_and_still_scores():
    import pickle

    X, y, _ = _dataset(n_dates=40, per_date=6, informative=True, seed=9)
    model = train_entry_model(X, y)
    revived: EntryModel = pickle.loads(pickle.dumps(model))
    assert revived.score_row(X.iloc[0].to_dict()) == model.score_row(X.iloc[0].to_dict())


def test_build_estimator_catboost_and_ensemble_presets():
    from equity_scout.ml.entry_model import ENTRY_PRESETS, _build_estimator

    assert set(ENTRY_PRESETS) == {"random_forest", "elastic_net", "catboost", "ensemble"}
    assert _build_estimator("catboost").__class__.__name__ == "CatBoostClassifier"
    assert _build_estimator("ensemble").__class__.__name__ == "VotingClassifier"


def test_walk_forward_collect_oos_returns_probability_arrays():
    X, y, meta = _dataset(n_dates=40, per_date=6, informative=True, seed=5)
    result = walk_forward_evaluate(X, y, meta, model="elastic_net", collect_oos=True)
    oos = result["oos"]
    assert len(oos["prob"]) == result["n_oos"]
    assert len(oos["y"]) == result["n_oos"]
    assert ((oos["prob"] >= 0) & (oos["prob"] <= 1)).all()


def test_walk_forward_runs_with_ensemble_without_feature_importance():
    X, y, meta = _dataset(n_dates=40, per_date=6, informative=True, seed=6)
    result = walk_forward_evaluate(X, y, meta, model="ensemble")
    assert result["n_oos"] > 0
    assert result["feature_importance"] == {}  # voting ensemble exposes no importances


def test_calibrated_model_scores_through_the_calibrator():
    from sklearn.isotonic import IsotonicRegression

    X, y, _ = _dataset(n_dates=40, per_date=6, informative=True, seed=7)
    # An inverting calibrator makes the effect unmistakable: p -> 1 - p (isotonic is
    # non-decreasing by default, so inversion needs increasing=False).
    calibrator = IsotonicRegression(
        y_min=0.0, y_max=1.0, out_of_bounds="clip", increasing=False
    ).fit([0.0, 1.0], [1.0, 0.0])
    plain = train_entry_model(X, y, model="elastic_net")
    calibrated = train_entry_model(X, y, model="elastic_net", calibrator=calibrator)
    plain_scores = plain.score_many(X.head(10))
    calibrated_scores = calibrated.score_many(X.head(10))
    assert (plain_scores + calibrated_scores == 100).all()


def test_model_pickled_without_calibrator_field_still_scores():
    """Artifacts registered before the calibrator field existed unpickle WITHOUT that attribute —
    scoring must fall back to raw probabilities instead of raising AttributeError."""
    X, y, _ = _dataset(n_dates=20, per_date=4, informative=True, seed=8)
    model = train_entry_model(X, y, model="elastic_net")
    object.__delattr__(model, "calibrator")  # simulate the legacy pickle layout
    scores = model.score_many(X.head(5))
    assert ((scores >= 0) & (scores <= 100)).all()


def test_score_row_refuses_a_row_missing_a_fitted_feature_column():
    """v15 P3: models with different feature sets now coexist in one registry.
    `pd.DataFrame([features], columns=...)` would NaN-fill a missing column and score it
    silently — the one path that could fabricate a number. Extra keys stay fine."""
    import pytest  # only test in this module that needs it

    X = pd.DataFrame({"a": np.linspace(0.0, 1.0, 40), "b": np.linspace(1.0, 0.0, 40)})
    y = pd.Series([0, 1] * 20)
    model = train_entry_model(X, y, model="elastic_net")

    # "fitted on" is unique to the guard's own message (sklearn's NaN ValueError also says
    # "missing", so matching that word alone would stay green even with the guard removed).
    with pytest.raises(ValueError, match="fitted on"):
        model.score_row({"a": 0.5})

    assert 0 <= model.score_row({"a": 0.5, "b": 0.5, "unused": 9.9}) <= 100


def test_elastic_net_training_is_reproducible():
    """The registry crowns champions on AUC differences in the third decimal. A stochastic
    solver without a seed makes the same data give slightly different coefficients, so a
    champion could not be re-derived from its own inputs. Found 2026-08-10: `saga` had no
    random_state and a calibration test flipped between full runs when new test files shifted
    the global numpy state."""
    import numpy as np

    X, y, _ = _dataset(n_dates=30, per_date=5, informative=True, seed=11)
    first = train_entry_model(X, y, model="elastic_net").score_many(X.head(20))
    # Disturb the global random state exactly as an unrelated test would.
    np.random.default_rng(999).normal(size=5000)
    np.random.seed(4242)
    second = train_entry_model(X, y, model="elastic_net").score_many(X.head(20))
    assert (first == second).all()
