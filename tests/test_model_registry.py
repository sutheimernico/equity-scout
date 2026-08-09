"""Registry tests: versioned pickled EntryModel + gated champion/challenger promotion (F2)."""
from __future__ import annotations

import pickle
import sqlite3

import numpy as np
import pandas as pd
import pytest

from equity_scout.ml.entry_features import FEATURE_COLUMNS
from equity_scout.ml.entry_model import EntryModel, train_entry_model
from equity_scout.ml.labeling import BarrierConfig
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


def test_n_candidates_one_matches_legacy_threshold(tmp_path):
    """C2: n_candidates=1 (the default, and every pre-C2 call site) must reproduce the exact legacy
    MIN_AUC_DELTA threshold — a delta just below it still rejects, a delta right at it still
    promotes, whether or not n_candidates=1 is passed explicitly."""
    db = str(tmp_path / "reg.db")
    v1 = register_challenger(db, _model(1), metrics=_metrics(0.70), n_train=20, now=NOW)
    assert promote_if_better(db, v1, n_candidates=1) is True
    v2 = register_challenger(db, _model(2), metrics=_metrics(0.705), n_train=20, now=NOW)
    assert promote_if_better(db, v2, n_candidates=1) is False  # delta 0.005 < MIN_AUC_DELTA (0.01)
    v3 = register_challenger(db, _model(3), metrics=_metrics(0.71), n_train=20, now=NOW)
    assert promote_if_better(db, v3, n_candidates=1) is True  # delta 0.01 == MIN_AUC_DELTA -> promotes
    assert entry_champion(db)[0] == v3


def test_borderline_candidate_promoted_at_n1_rejected_at_n4(tmp_path):
    """C2: the whole point of the multiple-testing guard — a delta that clears the single-candidate
    hurdle (0.01) can fail the 4-candidate hurdle (0.01 * sqrt(4) == 0.02), because testing 4 nightly
    presets against the same champion makes a lucky 0.015 wiggle far more likely than testing 1."""
    delta = 0.015
    db1 = str(tmp_path / "n1.db")
    v1 = register_challenger(db1, _model(1), metrics=_metrics(0.70), n_train=20, now=NOW)
    promote_if_better(db1, v1, n_candidates=1)
    v2 = register_challenger(db1, _model(2), metrics=_metrics(0.70 + delta), n_train=20, now=NOW)
    assert promote_if_better(db1, v2, n_candidates=1) is True  # 0.015 >= MIN_AUC_DELTA

    db4 = str(tmp_path / "n4.db")
    w1 = register_challenger(db4, _model(1), metrics=_metrics(0.70), n_train=20, now=NOW)
    promote_if_better(db4, w1, n_candidates=4)
    w2 = register_challenger(db4, _model(2), metrics=_metrics(0.70 + delta), n_train=20, now=NOW)
    assert promote_if_better(db4, w2, n_candidates=4) is False  # 0.015 < 0.02 -> rejected
    assert entry_champion(db4)[0] == w1


def test_clearly_better_candidate_still_promoted_at_n4(tmp_path):
    """C2: the guard raises the bar, it doesn't freeze promotion — a genuinely large improvement
    still gets through even with 4 simultaneous candidates."""
    db = str(tmp_path / "reg.db")
    v1 = register_challenger(db, _model(1), metrics=_metrics(0.70), n_train=20, now=NOW)
    promote_if_better(db, v1, n_candidates=4)
    v2 = register_challenger(db, _model(2), metrics=_metrics(0.80), n_train=20, now=NOW)  # delta 0.10
    assert promote_if_better(db, v2, n_candidates=4) is True
    assert entry_champion(db)[0] == v2


def test_effective_threshold_grows_monotonically_with_n_candidates(tmp_path):
    """C2: the effective threshold at n=16 must be at least as strict as at n=4 — a delta that
    exactly clears the n=4 hurdle (0.01 * sqrt(4) == 0.02) must not clear the stricter n=16 hurdle
    (0.01 * sqrt(16) == 0.04)."""
    delta = 0.02
    db4 = str(tmp_path / "n4.db")
    v1 = register_challenger(db4, _model(1), metrics=_metrics(0.70), n_train=20, now=NOW)
    promote_if_better(db4, v1, n_candidates=4)
    v2 = register_challenger(db4, _model(2), metrics=_metrics(0.70 + delta), n_train=20, now=NOW)
    assert promote_if_better(db4, v2, n_candidates=4) is True  # exactly at the n=4 hurdle

    db16 = str(tmp_path / "n16.db")
    w1 = register_challenger(db16, _model(1), metrics=_metrics(0.70), n_train=20, now=NOW)
    promote_if_better(db16, w1, n_candidates=16)
    w2 = register_challenger(db16, _model(2), metrics=_metrics(0.70 + delta), n_train=20, now=NOW)
    assert promote_if_better(db16, w2, n_candidates=16) is False  # below the stricter n=16 hurdle


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


def test_anti_predictive_challenger_never_displaces_legitimate_champion(tmp_path):
    """F2 (one-sided `_no_edge`): a strongly anti-predictive challenger (0.30) must not displace an
    existing LEGITIMATE champion (0.70), no matter how large the raw numeric gap looks.

    Repurposed from a pre-fix version of this test that used an ANTI-PREDICTIVE value (0.30) as
    the CHAMPION itself and asserted it bootstrapped successfully — that assertion embodied the
    symmetric-`_no_edge` hole (I1): the old `abs(auc - 0.5)` check mistook "far from 0.5" for "has
    a demonstrated edge" regardless of direction, so 0.30 cleared the band and became a fake
    champion. Under the one-sided fix a 0.30 candidate can no longer become champion at all (see
    `test_first_model_with_anti_predictive_auc_does_not_bootstrap`), so this test now demonstrates
    the same "no-edge blocks regardless of apparent numeric gap" property one step later — against
    an already-legitimate incumbent instead of via a hole-exploiting bootstrap."""
    db = str(tmp_path / "reg.db")
    v1 = register_challenger(db, _model(1), metrics=_metrics(0.70), n_train=20, now=NOW)
    assert promote_if_better(db, v1) is True
    v2 = register_challenger(db, _model(2), metrics=_metrics(0.30), n_train=20, now=NOW)
    assert promote_if_better(db, v2) is False  # anti-predictive: blocked outright, no delta fight
    assert entry_champion(db)[0] == v1


def test_first_model_with_anti_predictive_auc_does_not_bootstrap(tmp_path):
    """F2 (I1 fix): `_no_edge` is one-sided now — a candidate must clear 0.5 + NO_EDGE_BAND, not
    just be far from 0.5 in EITHER direction. An anti-predictive AUC (0.44, distance 0.06 >=
    NO_EDGE_BAND, which the old symmetric check would have crowned a champion) must not bootstrap
    a fake champion just because the arena is empty. Anti-predictive models stay visible as
    registered challengers (information for research) but never as champion — nothing downstream
    (ModelPanel, /api/model/history) inverts scores to trade on the anti-predictive direction."""
    db = str(tmp_path / "reg.db")
    v1 = register_challenger(db, _model(1), metrics=_metrics(0.44), n_train=20, now=NOW)
    assert promote_if_better(db, v1) is False
    assert entry_champion(db) is None


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


def test_promotion_appends_champion_history(tmp_path):
    from equity_scout.ml.model_registry import load_champion_history

    db = str(tmp_path / "registry.db")
    v1 = register_challenger(db, _model(1), metrics=_metrics(0.60), n_train=25, now=NOW)
    assert promote_if_better(db, v1, now=NOW) is True
    v2 = register_challenger(db, _model(2), metrics=_metrics(0.80), n_train=25, now=NOW)
    assert promote_if_better(db, v2, now=NOW) is True
    v3 = register_challenger(db, _model(3), metrics=_metrics(0.805), n_train=25, now=NOW)
    assert promote_if_better(db, v3, now=NOW) is False  # below MIN_AUC_DELTA -> no history row

    history = load_champion_history(db)
    assert [(h["version"], h["prior_version"]) for h in history] == [(v1, None), (v2, v1)]
    assert history[0]["promoted_at"] == NOW
    assert history[1]["auc"] == 0.80
    assert load_champion_history(db, family="entry_short") == []


def test_entry_tb_family_never_competes_with_entry_champion(tmp_path):
    """entry_tb gets its own champion track (F3, AUC across label definitions is not comparable):
    a strong entry_tb challenger must never displace the `entry` family's champion, and vice
    versa, even though both live in the same registry db."""
    db = str(tmp_path / "reg.db")
    v_entry = register_challenger(db, _model(1), metrics=_metrics(0.80), n_train=20, now=NOW, family="entry")
    assert promote_if_better(db, v_entry) is True

    v_tb = register_challenger(db, _model(2), metrics=_metrics(0.90), n_train=20, now=NOW, family="entry_tb")
    assert promote_if_better(db, v_tb) is True  # bootstraps entry_tb's OWN champion track

    assert entry_champion(db, family="entry")[0] == v_entry  # untouched by the entry_tb promotion
    assert entry_champion(db, family="entry_tb")[0] == v_tb
    assert _champion_count(db) == 2  # one champion per family, never a single global champion

    # a WEAKER entry_tb challenger still cannot touch the (higher-AUC) entry champion
    v_tb_weak = register_challenger(
        db, _model(3), metrics=_metrics(0.55), n_train=20, now=NOW, family="entry_tb"
    )
    assert promote_if_better(db, v_tb_weak) is False
    assert entry_champion(db, family="entry")[0] == v_entry
    assert entry_champion(db, family="entry_tb")[0] == v_tb


def test_barrier_config_round_trips_through_registry(tmp_path):
    """The barrier config (k_pt, k_sl, horizon, vol window) MUST be retrievable from the champion's
    stored metrics — a follow-up task derives price target/stop from exactly this."""
    db = str(tmp_path / "reg.db")
    config = BarrierConfig(k_pt=2.5, k_sl=1.2, horizon_days=35, vol_window=45)
    metrics = _metrics(0.80)
    metrics["barrier_config"] = config.as_dict()
    version = register_challenger(
        db, _model(1), metrics=metrics, n_train=20, now=NOW, family="entry_tb"
    )
    assert promote_if_better(db, version) is True

    _, _, got_metrics = entry_champion(db, family="entry_tb")
    assert got_metrics["barrier_config"] == config.as_dict()
    assert BarrierConfig(**got_metrics["barrier_config"]) == config
