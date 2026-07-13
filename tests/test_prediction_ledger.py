"""Prediction-ledger tests: append-only log, one-way resolve, resolved stats, drift snapshot."""
from __future__ import annotations

import sqlite3

import pytest

from equity_scout.ml.prediction_ledger import (
    drift_snapshot,
    due_predictions,
    log_predictions,
    resolve_prediction,
    resolved_stats,
)

NOW = "2026-01-01T00:00:00+00:00"
BEFORE = "2026-01-15T00:00:00+00:00"  # < NOW + 20 calendar days (2026-01-21)
AFTER = "2026-02-01T00:00:00+00:00"  # > resolve_after
HORIZON = 20


def _scored():
    return [
        ("AAA", 80, {"mkt_vol": 0.1, "mom_1m": 0.05}),
        ("BBB", 40, {"mkt_vol": 0.1, "mom_1m": -0.02}),
        ("CCC", 60, {"mkt_vol": 0.1, "mom_1m": 0.01}),
    ]


def _row(db: str, prediction_id: int) -> dict:
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        r = conn.execute("SELECT * FROM entry_predictions WHERE id=?", (prediction_id,)).fetchone()
    return dict(r)


def _count(db: str) -> int:
    with sqlite3.connect(db) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM entry_predictions").fetchone()[0])


def test_log_predictions_all_open_and_not_due_before_horizon(tmp_path):
    db = str(tmp_path / "led.db")
    log_predictions(db, model_version=1, scored=_scored(), now=NOW, horizon_days=HORIZON)
    stats = resolved_stats(db)
    assert stats["n_open"] == 3
    assert stats["n_resolved"] == 0
    assert due_predictions(db, BEFORE) == []  # resolve_after not yet reached


def test_due_predictions_after_resolve_after(tmp_path):
    db = str(tmp_path / "led.db")
    log_predictions(db, model_version=1, scored=_scored(), now=NOW, horizon_days=HORIZON)
    due = due_predictions(db, AFTER)
    assert {d["ticker"] for d in due} == {"AAA", "BBB", "CCC"}
    assert due[0]["features"] == {"mkt_vol": 0.1, "mom_1m": 0.05}  # features round-trip


def test_due_check_compares_real_time_not_lexical_string(tmp_path):
    db = str(tmp_path / "led.db")
    log_predictions(db, model_version=1, scored=_scored(), now=NOW, horizon_days=HORIZON)
    # resolve_after = 2026-01-21T00:00:00+00:00. A +02:00 clock reading 01:00 is 2026-01-20T23:00Z,
    # i.e. BEFORE resolve_after in real time — but it sorts AFTER lexically. It must NOT be due.
    not_yet_due = "2026-01-21T01:00:00+02:00"
    assert due_predictions(db, not_yet_due) == []
    # a +02:00 reading of 03:00 is 2026-01-21T01:00Z — genuinely past resolve_after → due
    genuinely_due = "2026-01-21T03:00:00+02:00"
    assert len(due_predictions(db, genuinely_due)) == 3


def test_resolve_sets_label_and_correct_and_shrinks_open_set(tmp_path):
    db = str(tmp_path / "led.db")
    log_predictions(db, model_version=1, scored=_scored(), now=NOW, horizon_days=HORIZON)
    due = due_predictions(db, AFTER)
    aaa = next(d for d in due if d["ticker"] == "AAA")  # score 80 → predicted "beats"
    bbb = next(d for d in due if d["ticker"] == "BBB")  # score 40 → predicted "does not beat"

    assert resolve_prediction(
        db, aaa["id"], realized_relative_return=0.05, resolved_at=AFTER
    ) is True
    assert resolve_prediction(
        db, bbb["id"], realized_relative_return=0.03, resolved_at=AFTER
    ) is True

    aaa_row = _row(db, aaa["id"])
    assert aaa_row["label"] == 1 and aaa_row["correct"] == 1  # beat, and we said so
    bbb_row = _row(db, bbb["id"])
    assert bbb_row["label"] == 1 and bbb_row["correct"] == 0  # beat, but we said it would not

    stats = resolved_stats(db)
    assert stats["n_resolved"] == 2 and stats["n_open"] == 1  # one still open


def test_double_resolve_is_refused_and_keeps_first_resolution(tmp_path):
    db = str(tmp_path / "led.db")
    log_predictions(db, model_version=1, scored=_scored(), now=NOW, horizon_days=HORIZON)
    pid = due_predictions(db, AFTER)[0]["id"]
    assert resolve_prediction(db, pid, realized_relative_return=0.05, resolved_at=AFTER) is True
    # a second attempt with a different value must be refused (one-way open→resolved)
    assert resolve_prediction(
        db, pid, realized_relative_return=-0.9, resolved_at="2026-03-01T00:00:00+00:00"
    ) is False
    row = _row(db, pid)
    assert row["realized_relative_return"] == 0.05 and row["label"] == 1  # first resolution stands


def test_ledger_is_append_only_count_stable(tmp_path):
    db = str(tmp_path / "led.db")
    log_predictions(db, model_version=1, scored=_scored(), now=NOW, horizon_days=HORIZON)
    assert _count(db) == 3
    for d in due_predictions(db, AFTER):
        resolve_prediction(db, d["id"], realized_relative_return=0.01, resolved_at=AFTER)
    assert _count(db) == 3  # resolution never inserts or deletes


def test_resolved_stats_over_resolved_rows_only(tmp_path):
    db = str(tmp_path / "led.db")
    log_predictions(db, model_version=1, scored=_scored(), now=NOW, horizon_days=HORIZON)
    due = {d["ticker"]: d["id"] for d in due_predictions(db, AFTER)}
    resolve_prediction(db, due["AAA"], realized_relative_return=0.05, resolved_at=AFTER)  # 80
    resolve_prediction(db, due["CCC"], realized_relative_return=0.02, resolved_at=AFTER)  # 60
    resolve_prediction(db, due["BBB"], realized_relative_return=-0.03, resolved_at=AFTER)  # 40

    stats = resolved_stats(db)
    assert stats["n_resolved"] == 3 and stats["n_open"] == 0
    assert stats["hit_rate"] == 1.0  # all three calls agreed with reality
    assert stats["rank_ic"] > 0.9  # higher score tracked higher realized rel-return
    assert stats["by_score_bucket"]["75-100"] == pytest.approx(0.05)
    assert stats["by_score_bucket"]["50-74"] == pytest.approx(0.02)
    assert stats["by_score_bucket"]["25-49"] == pytest.approx(-0.03)


def test_resolved_stats_filters_by_model_version(tmp_path):
    db = str(tmp_path / "led.db")
    log_predictions(db, model_version=1, scored=_scored()[:1], now=NOW, horizon_days=HORIZON)
    log_predictions(db, model_version=2, scored=_scored()[1:], now=NOW, horizon_days=HORIZON)
    for d in due_predictions(db, AFTER):
        resolve_prediction(db, d["id"], realized_relative_return=0.01, resolved_at=AFTER)
    assert resolved_stats(db, model_version=1)["n_resolved"] == 1
    assert resolved_stats(db, model_version=2)["n_resolved"] == 2


def test_resolved_stats_empty_is_honest(tmp_path):
    db = str(tmp_path / "led.db")
    log_predictions(db, model_version=1, scored=_scored(), now=NOW, horizon_days=HORIZON)
    stats = resolved_stats(db)
    assert stats["n_resolved"] == 0 and stats["n_open"] == 3
    assert stats["hit_rate"] is None and stats["rank_ic"] is None  # nothing to score yet


def test_drift_flags_shifted_feature_not_stable():
    train_means = {"mkt_vol": 1.0, "mom_1m": 1.0}
    recent = [
        {"mkt_vol": 1.02, "mom_1m": 5.0},
        {"mkt_vol": 0.98, "mom_1m": 5.2},
        {"mkt_vol": 1.00, "mom_1m": 4.8},
    ]
    snap = drift_snapshot(train_means, recent)
    assert snap["mkt_vol"]["flagged"] is False  # stable around the training mean
    assert snap["mom_1m"]["flagged"] is True  # shifted far from the training mean
    assert snap["mom_1m"]["z_shift"] > 2.0


def test_drift_handles_zero_train_mean_without_division_error():
    snap = drift_snapshot({"x": 0.0}, [{"x": 0.5}, {"x": 0.5}])
    assert snap["x"]["z_shift"] is not None  # |mean| fallback guards the zero denominator


def test_drift_ignores_non_finite_values_when_flagging():
    # A partly-NaN feature must still flag on its finite readings, not be silently swallowed to
    # flagged=False by NaN contaminating the mean.
    snap = drift_snapshot({"g": 1.0}, [{"g": float("nan")}, {"g": 5.0}, {"g": 5.2}])
    assert snap["g"]["flagged"] is True
    assert snap["g"]["recent_mean"] == pytest.approx(5.1)


def test_resolved_stats_windowed_filters_by_resolved_at(tmp_path):
    from equity_scout.ml.prediction_ledger import resolved_stats_windowed

    db = str(tmp_path / "ledger.db")
    log_predictions(
        db, model_version=1,
        scored=[("AAA", 80, {"f": 1.0}), ("BBB", 20, {"f": 2.0})],
        now="2026-01-01T00:00:00+00:00", horizon_days=5,
    )
    due = due_predictions(db, "2026-03-01T00:00:00+00:00")
    resolve_prediction(db, due[0]["id"], realized_relative_return=0.05,
                       resolved_at="2026-01-10T00:00:00+00:00")
    resolve_prediction(db, due[1]["id"], realized_relative_return=0.04,
                       resolved_at="2026-06-01T00:00:00+00:00")

    recent = resolved_stats_windowed(db, window_days=30, now="2026-06-15T00:00:00+00:00")
    assert recent["n_resolved"] == 1  # only the June resolution is inside the window
    assert recent["hit_rate"] == 0.0  # score 20 called "lags", it beat -> incorrect
    stale = resolved_stats_windowed(db, window_days=30, now="2027-01-01T00:00:00+00:00")
    assert stale["n_resolved"] == 0 and stale["hit_rate"] is None


def test_recent_prediction_features_returns_latest_dicts(tmp_path):
    from equity_scout.ml.prediction_ledger import recent_prediction_features

    db = str(tmp_path / "ledger.db")
    log_predictions(
        db, model_version=1,
        scored=[("AAA", 80, {"f": 1.0}), ("BBB", 20, {"f": 2.0})],
        now="2026-01-01T00:00:00+00:00", horizon_days=5,
    )
    features = recent_prediction_features(db, limit=1)
    assert features == [{"f": 2.0}]
