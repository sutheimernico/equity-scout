"""Registry tests: versioned pickled EntryModel + gated champion/challenger promotion (F2)."""
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
    entry_champion,
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


def _metrics(auc: float | None, *, n_oos: int = 200) -> dict:
    """A metrics dict clearing MIN_OOS_N by default, so tests can focus on the AUC comparison
    under test instead of restating the OOS-row-count gate every time."""
    return {"auc": auc, "n_oos": n_oos}


def _champion_count(db: str) -> int:
    with sqlite3.connect(db) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM entry_models WHERE is_champion=1").fetchone()[0])


def test_champion_is_none_on_empty_registry(tmp_path):
    db = str(tmp_path / "reg.db")
    assert entry_champion(db) is None


def test_first_model_auto_promotes_and_round_trips(tmp_path):
    db = str(tmp_path / "reg.db")
    model = _model(1)
    metrics = {"auc": 0.7, "brier": 0.2, "rank_ic": 0.4, "n_oos": 200}
    version = register_challenger(db, model, metrics=metrics, n_train=20, now=NOW)
    assert version == 1
    assert promote_if_better(db, version) is True  # clears baseline quality → bootstraps

    got = entry_champion(db)
    assert got is not None
    got_version, got_model, got_metrics = got
    assert got_version == version
    assert got_metrics == metrics
    # the pickled artifact round-trips into a working EntryModel
    sample = {c: 0.1 for c in FEATURE_COLUMNS}
    assert got_model.score_row(sample) == model.score_row(sample)


def test_better_challenger_displaces_worse_does_not(tmp_path):
    db = str(tmp_path / "reg.db")
    v1 = register_challenger(db, _model(1), metrics=_metrics(0.70), n_train=20, now=NOW)
    assert promote_if_better(db, v1) is True

    v2 = register_challenger(db, _model(2), metrics=_metrics(0.60), n_train=20, now=NOW)
    assert promote_if_better(db, v2) is False  # worse OOS AUC → no displacement
    assert entry_champion(db)[0] == v1

    v3 = register_challenger(db, _model(3), metrics=_metrics(0.80), n_train=20, now=NOW)
    assert promote_if_better(db, v3) is True  # delta 0.10 >= MIN_AUC_DELTA → promoted
    assert entry_champion(db)[0] == v3
    assert _champion_count(db) == 1  # exactly one champion after the flip


def test_equal_metric_does_not_displace(tmp_path):
    db = str(tmp_path / "reg.db")
    v1 = register_challenger(db, _model(1), metrics=_metrics(0.70), n_train=20, now=NOW)
    promote_if_better(db, v1)
    v2 = register_challenger(db, _model(2), metrics=_metrics(0.70), n_train=20, now=NOW)
    assert promote_if_better(db, v2) is False  # zero delta < MIN_AUC_DELTA, ties keep the incumbent
    assert entry_champion(db)[0] == v1


def test_challenger_below_min_delta_does_not_displace(tmp_path):
    """F2: a challenger that is nominally better but by less than MIN_AUC_DELTA must not swap the
    champion — nightly retrains are nightly trials, and a 0.005 wiggle is noise, not skill."""
    db = str(tmp_path / "reg.db")
    v1 = register_challenger(db, _model(1), metrics=_metrics(0.70), n_train=20, now=NOW)
    assert promote_if_better(db, v1) is True
    v2 = register_challenger(db, _model(2), metrics=_metrics(0.705), n_train=20, now=NOW)
    assert promote_if_better(db, v2) is False  # delta 0.005 < MIN_AUC_DELTA (0.01)
    assert entry_champion(db)[0] == v1


def test_promote_if_better_is_idempotent(tmp_path):
    db = str(tmp_path / "reg.db")
    v1 = register_challenger(db, _model(1), metrics=_metrics(0.70), n_train=20, now=NOW)
    assert promote_if_better(db, v1) is True
    assert promote_if_better(db, v1) is False  # already champion → no-op
    assert entry_champion(db)[0] == v1
    assert _champion_count(db) == 1


def test_none_metric_never_wins(tmp_path):
    db = str(tmp_path / "reg.db")
    v1 = register_challenger(db, _model(1), metrics=_metrics(0.65), n_train=20, now=NOW)
    assert promote_if_better(db, v1) is True
    v2 = register_challenger(db, _model(2), metrics=_metrics(None), n_train=20, now=NOW)
    assert promote_if_better(db, v2) is False  # un-scored challenger (None = no edge) never wins
    assert entry_champion(db)[0] == v1


def test_first_model_with_none_metric_does_not_bootstrap(tmp_path):
    """F2: baseline quality applies to the FIRST champion too — an undemonstrated edge must not
    bootstrap a fake champion just because the arena is empty."""
    db = str(tmp_path / "reg.db")
    v1 = register_challenger(db, _model(1), metrics=_metrics(None), n_train=20, now=NOW)
    assert promote_if_better(db, v1) is False
    assert entry_champion(db) is None


def test_first_model_with_weak_auc_does_not_bootstrap(tmp_path):
    """F2: an AUC within the no-edge band (here 0.52, |0.52-0.5| < 0.05) is a coin flip even with
    plenty of OOS rows — still no champion."""
    db = str(tmp_path / "reg.db")
    v1 = register_challenger(db, _model(1), metrics=_metrics(0.52), n_train=20, now=NOW)
    assert promote_if_better(db, v1) is False
    assert entry_champion(db) is None


def test_first_model_below_min_oos_does_not_bootstrap(tmp_path):
    """F2: a real-looking AUC on too few OOS rows is not trustworthy enough to crown a champion."""
    db = str(tmp_path / "reg.db")
    v1 = register_challenger(db, _model(1), metrics=_metrics(0.80, n_oos=50), n_train=20, now=NOW)
    assert promote_if_better(db, v1) is False
    assert entry_champion(db) is None


def test_first_model_above_baseline_quality_bootstraps(tmp_path):
    """F2: the counterpart to the two tests above — clearing both the no-edge band and MIN_OOS_N is
    enough for the first model to become champion."""
    db = str(tmp_path / "reg.db")
    v1 = register_challenger(db, _model(1), metrics=_metrics(0.80), n_train=20, now=NOW)
    assert promote_if_better(db, v1) is True
    assert entry_champion(db)[0] == v1


def test_no_edge_challenger_blocked_even_with_large_apparent_delta(tmp_path):
    """F2: the no-edge gate is checked independently of the AUC-delta gate. A weak-but-non-no-edge
    champion (0.30 — the symmetric band only cares about distance from 0.5, direction is a separate,
    pre-existing concern outside F2's scope) must not be displaceable by a no-edge challenger (0.50)
    just because the raw numbers show a large gap."""
    db = str(tmp_path / "reg.db")
    v1 = register_challenger(db, _model(1), metrics=_metrics(0.30), n_train=20, now=NOW)
    assert promote_if_better(db, v1) is True
    v2 = register_challenger(db, _model(2), metrics=_metrics(0.50), n_train=20, now=NOW)
    assert promote_if_better(db, v2) is False  # no-edge, despite a nominal +0.20 "delta"
    assert entry_champion(db)[0] == v1


def test_registry_summary_shape_newest_first(tmp_path):
    db = str(tmp_path / "reg.db")
    v1 = register_challenger(db, _model(1), metrics=_metrics(0.60), n_train=20, now=NOW)
    promote_if_better(db, v1)
    v2 = register_challenger(db, _model(2), metrics=_metrics(0.80), n_train=25, now=NOW)
    promote_if_better(db, v2)

    summary = registry_summary(db)
    versions = summary["versions"]
    assert [v["version"] for v in versions] == [v2, v1]  # newest first
    top = versions[0]
    assert set(top) == {"version", "created_at", "model_kind", "n_train", "metrics", "is_champion", "family"}
    assert top["is_champion"] is True and versions[1]["is_champion"] is False
    assert top["metrics"] == _metrics(0.80)
    assert top["n_train"] == 25
    assert summary["champion_version"] == v2


def test_non_finite_metric_never_displaces_finite_champion(tmp_path):
    db = str(tmp_path / "reg.db")
    v1 = register_challenger(db, _model(1), metrics=_metrics(0.80), n_train=20, now=NOW)
    assert promote_if_better(db, v1) is True
    # NaN and +inf both round-trip through json but must be treated as no-edge (never win) —
    # otherwise a corrupt-metric challenger silently displaces a legitimate champion.
    v2 = register_challenger(db, _model(2), metrics=_metrics(float("nan")), n_train=20, now=NOW)
    assert promote_if_better(db, v2) is False
    v3 = register_challenger(db, _model(3), metrics=_metrics(float("inf")), n_train=20, now=NOW)
    assert promote_if_better(db, v3) is False
    assert entry_champion(db)[0] == v1


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
        entry_champion(db)
