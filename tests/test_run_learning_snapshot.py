"""Learning-snapshot CLI tests: glues registry n_train + windowed ledger stats, honest on empty."""
from __future__ import annotations

import numpy as np
import pandas as pd

from equity_scout.ml.entry_features import FEATURE_COLUMNS
from equity_scout.ml.entry_model import train_entry_model
from equity_scout.ml.learning_curve import load_daily_curve
from equity_scout.ml.model_registry import promote_if_better, register_challenger
from equity_scout.ml.prediction_ledger import due_predictions, log_predictions, resolve_prediction
from scripts.run_learning_snapshot import run_learning_snapshot

NOW = "2026-07-15T02:30:00+00:00"


def _model():
    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.normal(size=(20, len(FEATURE_COLUMNS))), columns=list(FEATURE_COLUMNS))
    y = pd.Series((X[FEATURE_COLUMNS[0]] > 0.0).astype(int).to_numpy())
    return train_entry_model(X, y)


def test_snapshot_on_empty_db_is_honest_none_not_a_crash(tmp_path):
    db = str(tmp_path / "snap.db")
    snapshot = run_learning_snapshot(db, now=NOW)
    assert snapshot["snapshot_date"] == "2026-07-15"
    assert snapshot["n_train"] is None  # no champion yet
    assert snapshot["n_resolved"] == 0
    assert snapshot["hit_rate"] is None
    assert snapshot["rank_ic"] is None
    # and it actually persisted the row (not just returned it)
    assert load_daily_curve(db) == [snapshot]


def test_snapshot_reflects_champion_n_train_and_resolved_window(tmp_path):
    db = str(tmp_path / "snap.db")
    version = register_challenger(
        db, _model(), metrics={"auc": 0.7, "n_oos": 200}, n_train=42,
        now="2026-01-01T00:00:00+00:00",
    )
    assert promote_if_better(db, version) is True

    log_predictions(
        db, model_version=version, horizon_days=5, now="2026-06-01T00:00:00+00:00",
        scored=[("AAA", 80, {"f": 1.0}), ("BBB", 20, {"f": 2.0})],
    )
    # trading-day stamp: resolve_after = 2026-06-01 + ceil(5*7/5)+4 = 2026-06-12
    due = due_predictions(db, "2026-06-15T00:00:00+00:00")
    resolve_prediction(db, due[0]["id"], realized_relative_return=0.05, resolved_at="2026-06-08T00:00:00+00:00")

    snapshot = run_learning_snapshot(db, now="2026-07-01T00:00:00+00:00", window_days=30)
    assert snapshot["n_train"] == 42
    assert snapshot["n_resolved"] == 1  # only the resolved one, still-open BBB is excluded
    assert snapshot["hit_rate"] == 1.0  # score 80 called "beats", realized > 0 -> correct


def test_snapshot_is_idempotent_when_run_twice_same_day(tmp_path):
    db = str(tmp_path / "snap.db")
    run_learning_snapshot(db, now="2026-07-15T02:30:00+00:00")
    run_learning_snapshot(db, now="2026-07-15T03:00:00+00:00")
    assert len(load_daily_curve(db)) == 1  # same calendar day -> overwrite, not a second row
