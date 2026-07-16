"""Daily learning-curve snapshots (plan v7 strand C, task C1).

`champion_history` (model_registry.py) only appends on a champion FLIP — rare, so the dashboard
looked quiet most nights even while the model trained. This table persists ONE row per calendar
day instead: the current entry champion's `n_train`, plus `n_resolved`/`hit_rate`/`rank_ic` from
the trailing prediction-ledger window (`resolved_stats_windowed`). That makes daily training
visible even on nights the champion does not change.

Idempotent per day: `save_snapshot` upserts on `snapshot_date` (`ON CONFLICT ... DO UPDATE`), so
re-running on the same day overwrites the row instead of duplicating it. A metric that cannot be
determined on a given day (no champion yet, nothing resolved yet) is persisted as NULL — an
honest gap, never a fabricated 0.
"""
from __future__ import annotations

import sqlite3

from equity_scout.constants import DEFAULT_DB_PATH


def init_learning_curve_db(db_path: str = DEFAULT_DB_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS learning_curve (
                snapshot_date TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                n_train INTEGER,
                n_resolved INTEGER,
                hit_rate REAL,
                rank_ic REAL
            )"""
        )


def save_snapshot(
    db_path: str,
    *,
    snapshot_date: str,
    created_at: str,
    n_train: int | None,
    n_resolved: int | None,
    hit_rate: float | None,
    rank_ic: float | None,
) -> None:
    """Upsert one day's snapshot. Idempotent on `snapshot_date`: a second write for the same day
    (e.g. a re-run of the nightly job) overwrites the row rather than appending a duplicate."""
    init_learning_curve_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO learning_curve
                (snapshot_date, created_at, n_train, n_resolved, hit_rate, rank_ic)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_date) DO UPDATE SET
                    created_at = excluded.created_at,
                    n_train = excluded.n_train,
                    n_resolved = excluded.n_resolved,
                    hit_rate = excluded.hit_rate,
                    rank_ic = excluded.rank_ic""",
            (snapshot_date, created_at, n_train, n_resolved, hit_rate, rank_ic),
        )


def load_daily_curve(db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    """Every persisted snapshot, chronological (oldest first) — the daily learning-curve series.
    Empty list on an empty/uninitialized table, never a crash."""
    init_learning_curve_db(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT snapshot_date, created_at, n_train, n_resolved, hit_rate, rank_ic"
            " FROM learning_curve ORDER BY snapshot_date ASC"
        ).fetchall()
    return [
        {
            "snapshot_date": r[0],
            "created_at": r[1],
            "n_train": int(r[2]) if r[2] is not None else None,
            "n_resolved": int(r[3]) if r[3] is not None else None,
            "hit_rate": r[4],
            "rank_ic": r[5],
        }
        for r in rows
    ]
