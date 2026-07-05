"""Registry tests: versioned pickled EntryModel + strictly-better champion/challenger promotion."""
from __future__ import annotations

import pickle
import sqlite3

import numpy as np
import pandas as pd
import pytest

from equity_scout.ml.entry_features import FEATURE_COLUMNS
from equity_scout.ml.entry_model import EntryModel, train_entry_model
from equity_scout.ml.model_registry import (
    RegistryError,
    champion,
    promote_if_better,
    register_challenger,
    registry_summary,
)

NOW = "2026-07-05T12:00:00+00:00"


def _model(seed: int = 0) -> EntryModel:
    """A tiny real EntryModel trained on a 20-row synthetic set (both classes present)."""
    rng = np.random.default_rng(seed)
    X = pd.DataFrame(rng.normal(size=(20, len(FEATURE_COLUMNS))), columns=list(FEATURE_COLUMNS))
    y = pd.Series((X[FEATURE_COLUMNS[0]] > 0.0).astype(int).to_numpy())
    return train_entry_model(X, y)


def _champion_count(db: str) -> int:
    with sqlite3.connect(db) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM entry_models WHERE is_champion=1").fetchone()[0])


def test_champion_is_none_on_empty_registry(tmp_path):
    db = str(tmp_path / "reg.db")
    assert champion(db) is None


def test_first_model_auto_promotes_and_round_trips(tmp_path):
    db = str(tmp_path / "reg.db")
    model = _model(1)
    metrics = {"auc": 0.7, "brier": 0.2, "rank_ic": 0.4}
    version = register_challenger(db, model, metrics=metrics, n_train=20, now=NOW)
    assert version == 1
    assert promote_if_better(db, version) is True  # first trained model bootstraps the champion

    got = champion(db)
    assert got is not None
    got_version, got_model, got_metrics = got
    assert got_version == version
    assert got_metrics == metrics
    # the pickled artifact round-trips into a working EntryModel
    sample = {c: 0.1 for c in FEATURE_COLUMNS}
    assert got_model.score_row(sample) == model.score_row(sample)


def test_better_challenger_displaces_worse_does_not(tmp_path):
    db = str(tmp_path / "reg.db")
    v1 = register_challenger(db, _model(1), metrics={"auc": 0.70}, n_train=20, now=NOW)
    assert promote_if_better(db, v1) is True

    v2 = register_challenger(db, _model(2), metrics={"auc": 0.60}, n_train=20, now=NOW)
    assert promote_if_better(db, v2) is False  # worse OOS AUC → no displacement
    assert champion(db)[0] == v1

    v3 = register_challenger(db, _model(3), metrics={"auc": 0.80}, n_train=20, now=NOW)
    assert promote_if_better(db, v3) is True  # strictly better → promoted
    assert champion(db)[0] == v3
    assert _champion_count(db) == 1  # exactly one champion after the flip


def test_equal_metric_does_not_displace(tmp_path):
    db = str(tmp_path / "reg.db")
    v1 = register_challenger(db, _model(1), metrics={"auc": 0.70}, n_train=20, now=NOW)
    promote_if_better(db, v1)
    v2 = register_challenger(db, _model(2), metrics={"auc": 0.70}, n_train=20, now=NOW)
    assert promote_if_better(db, v2) is False  # strictly-greater only, ties keep the incumbent
    assert champion(db)[0] == v1


def test_promote_if_better_is_idempotent(tmp_path):
    db = str(tmp_path / "reg.db")
    v1 = register_challenger(db, _model(1), metrics={"auc": 0.70}, n_train=20, now=NOW)
    assert promote_if_better(db, v1) is True
    assert promote_if_better(db, v1) is False  # already champion → no-op
    assert champion(db)[0] == v1
    assert _champion_count(db) == 1


def test_none_metric_never_wins(tmp_path):
    db = str(tmp_path / "reg.db")
    v1 = register_challenger(db, _model(1), metrics={"auc": 0.55}, n_train=20, now=NOW)
    assert promote_if_better(db, v1) is True
    v2 = register_challenger(db, _model(2), metrics={"auc": None}, n_train=20, now=NOW)
    assert promote_if_better(db, v2) is False  # un-scored challenger (None = -inf) never wins
    assert champion(db)[0] == v1


def test_first_model_with_none_metric_still_bootstraps(tmp_path):
    db = str(tmp_path / "reg.db")
    v1 = register_challenger(db, _model(1), metrics={"auc": None}, n_train=20, now=NOW)
    assert promote_if_better(db, v1) is True  # bootstrap: something must be champion
    assert champion(db)[0] == v1


def test_registry_summary_shape_newest_first(tmp_path):
    db = str(tmp_path / "reg.db")
    v1 = register_challenger(db, _model(1), metrics={"auc": 0.60}, n_train=20, now=NOW)
    promote_if_better(db, v1)
    v2 = register_challenger(db, _model(2), metrics={"auc": 0.80}, n_train=25, now=NOW)
    promote_if_better(db, v2)

    summary = registry_summary(db)
    versions = summary["versions"]
    assert [v["version"] for v in versions] == [v2, v1]  # newest first
    top = versions[0]
    assert set(top) == {"version", "created_at", "model_kind", "n_train", "metrics", "is_champion"}
    assert top["is_champion"] is True and versions[1]["is_champion"] is False
    assert top["metrics"] == {"auc": 0.80}
    assert top["n_train"] == 25
    assert summary["champion_version"] == v2


def test_promote_unknown_version_raises(tmp_path):
    db = str(tmp_path / "reg.db")
    register_challenger(db, _model(1), metrics={"auc": 0.6}, n_train=20, now=NOW)
    with pytest.raises(ValueError):
        promote_if_better(db, 999)


def test_bad_artifact_raises_clear_error(tmp_path):
    db = str(tmp_path / "reg.db")
    register_challenger(db, _model(1), metrics={"auc": 0.6}, n_train=20, now=NOW)
    # corrupt the champion artifact with a non-EntryModel pickle
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE entry_models SET is_champion=1, artifact=? WHERE version=1",
            (sqlite3.Binary(pickle.dumps({"not": "a model"})),),
        )
    with pytest.raises(RegistryError):
        champion(db)
