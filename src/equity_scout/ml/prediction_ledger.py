"""Append-only predict-then-resolve ledger + a simple feature-drift snapshot.

The honesty centrepiece (invariant #3). Every live score is logged BEFORE its outcome is known,
with a `resolve_after` date one horizon out. Once that date passes, a resolver fills the outcome
against REAL forward prices — never a back-filled guess. The ledger is append-only: `log_predictions`
only ever INSERTs, and `resolve_prediction` performs the ONE permitted mutation per row — a single
open→resolved transition, guarded so a row can never be re-resolved (a second attempt is refused and
the first resolution stands). Nothing is ever deleted.

`resolved_stats` reports only over resolved rows (realized hit-rate, Rank-IC of score vs realized,
mean realized return per score bucket) so a claim like "the model is calibrated" is a query, not a
promise. `drift_snapshot` is a cheap distribution-shift flag: how far the recent live feature means
have moved from the training means. Only training MEANS are available here (the registry stores the
model, not the training matrix), so the shift is scaled by |train mean| — a relative move, guarded
against a zero denominator; it flags features that warrant a retrain look, it is not a formal test.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

import numpy as np

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.ml.entry_eval import rank_ic

# |z-shift| above this flags a feature as drifted (a retrain-look trigger, not a formal test).
DRIFT_FLAG_THRESHOLD = 2.0

_SCORE_BUCKETS = ((0, 25, "0-24"), (25, 50, "25-49"), (50, 75, "50-74"), (75, 101, "75-100"))


def init_ledger_db(db_path: str = DEFAULT_DB_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS entry_predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                model_version INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                score INTEGER NOT NULL,
                horizon_days INTEGER NOT NULL,
                features_json TEXT NOT NULL,
                resolve_after TEXT NOT NULL,
                resolved_at TEXT,
                realized_relative_return REAL,
                label INTEGER,
                correct INTEGER
            )"""
        )


def log_predictions(
    db_path: str,
    *,
    model_version: int,
    scored: list[tuple[str, int, dict]],
    now: str,
    horizon_days: int,
) -> None:
    """Append one open prediction per scored entry. `resolve_after = now + horizon_days` CALENDAR
    days — a deliberate over-estimate of the trading-day horizon, so a prediction is never resolved
    before its full forward window has actually elapsed. `now` is injected (no wall clock here)."""
    init_ledger_db(db_path)
    resolve_after = (datetime.fromisoformat(now) + timedelta(days=horizon_days)).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO entry_predictions"
            " (created_at, model_version, ticker, score, horizon_days, features_json, resolve_after)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    now, int(model_version), ticker, int(score), int(horizon_days),
                    json.dumps(features, ensure_ascii=False), resolve_after,
                )
                for ticker, score, features in scored
            ],
        )


def due_predictions(db_path: str, now: str) -> list[dict]:
    """Unresolved predictions whose `resolve_after` is at or before `now` — ready to resolve."""
    init_ledger_db(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, created_at, model_version, ticker, score, horizon_days, features_json,"
            " resolve_after FROM entry_predictions"
            " WHERE resolved_at IS NULL AND resolve_after <= ? ORDER BY id",
            (now,),
        ).fetchall()
    return [
        {
            "id": int(r[0]),
            "created_at": r[1],
            "model_version": int(r[2]),
            "ticker": r[3],
            "score": int(r[4]),
            "horizon_days": int(r[5]),
            "features": json.loads(r[6]),
            "resolve_after": r[7],
        }
        for r in rows
    ]


def resolve_prediction(
    db_path: str,
    prediction_id: int,
    *,
    realized_relative_return: float,
    resolved_at: str,
) -> bool:
    """Fill the outcome of one open prediction. label = int(realized > 0); correct = the call
    (score>=50 → "beats") matched the label. The UPDATE is guarded `WHERE ... resolved_at IS NULL`,
    so a re-resolution finds no open row and is refused. Returns True iff it was applied."""
    init_ledger_db(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT score FROM entry_predictions WHERE id = ?", (prediction_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown prediction id: {prediction_id}")
        score = int(row[0])
        label = int(realized_relative_return > 0.0)
        correct = int((label == 1) == (score >= 50))
        cursor = conn.execute(
            "UPDATE entry_predictions"
            " SET resolved_at = ?, realized_relative_return = ?, label = ?, correct = ?"
            " WHERE id = ? AND resolved_at IS NULL",
            (resolved_at, float(realized_relative_return), label, correct, prediction_id),
        )
        return cursor.rowcount == 1


def _score_bucket(score: int) -> str:
    for lo, hi, name in _SCORE_BUCKETS:
        if lo <= score < hi:
            return name
    return _SCORE_BUCKETS[-1][2]


def resolved_stats(db_path: str, model_version: int | None = None) -> dict:
    """Stats over RESOLVED rows only (plus the open count). hit_rate/rank_ic are None until there
    is something to score; by_score_bucket maps each populated bucket to its mean realized return."""
    init_ledger_db(db_path)
    filt = "" if model_version is None else " AND model_version = ?"
    args: tuple = () if model_version is None else (model_version,)
    with sqlite3.connect(db_path) as conn:
        resolved = conn.execute(
            "SELECT score, realized_relative_return, correct FROM entry_predictions"
            f" WHERE resolved_at IS NOT NULL{filt} ORDER BY id",
            args,
        ).fetchall()
        n_open = int(
            conn.execute(
                f"SELECT COUNT(*) FROM entry_predictions WHERE resolved_at IS NULL{filt}", args
            ).fetchone()[0]
        )

    n_resolved = len(resolved)
    if n_resolved == 0:
        return {
            "n_resolved": 0, "n_open": n_open,
            "hit_rate": None, "rank_ic": None, "by_score_bucket": {},
        }

    scores = np.array([r[0] for r in resolved], dtype=float)
    realized = np.array([r[1] for r in resolved], dtype=float)
    hit_rate = round(float(np.mean([r[2] for r in resolved])), 4)

    buckets: dict[str, float] = {}
    for lo, hi, name in _SCORE_BUCKETS:
        mask = (scores >= lo) & (scores < hi)
        if mask.any():
            buckets[name] = round(float(realized[mask].mean()), 4)

    return {
        "n_resolved": n_resolved,
        "n_open": n_open,
        "hit_rate": hit_rate,
        "rank_ic": rank_ic(scores, realized),
        "by_score_bucket": buckets,
    }


def drift_snapshot(training_feature_means: dict, recent_features: list[dict]) -> dict:
    """Per-feature shift of recent live feature means from the training means. The shift is scaled
    by |train mean| (the only training statistic available here), guarded so a ~0 mean falls back to
    a unit scale rather than dividing by zero. A feature is flagged when |shift| exceeds the
    threshold — a signal to look at retraining, not a formal distribution test."""
    snapshot: dict[str, dict] = {}
    for feature, train_mean in training_feature_means.items():
        values = [f[feature] for f in recent_features if feature in f]
        train_mean = float(train_mean)
        if not values:
            snapshot[feature] = {
                "train_mean": round(train_mean, 4),
                "recent_mean": None, "z_shift": None, "flagged": False,
            }
            continue
        recent_mean = float(np.mean(values))
        scale = abs(train_mean) if abs(train_mean) > 1e-9 else 1.0
        z_shift = (recent_mean - train_mean) / scale
        snapshot[feature] = {
            "train_mean": round(train_mean, 4),
            "recent_mean": round(recent_mean, 4),
            "z_shift": round(z_shift, 4),
            "flagged": bool(abs(z_shift) > DRIFT_FLAG_THRESHOLD),
        }
    return snapshot
