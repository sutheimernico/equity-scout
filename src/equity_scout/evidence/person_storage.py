"""Persisted person track-record scores.

Unlike the append-only event store, scores are DERIVED state: each refresh replaces a
(person, source) row wholesale — history lives in the underlying calls/prices, not
here. `computed_at` says how fresh the measurement is.
"""
from __future__ import annotations

import sqlite3
from dataclasses import asdict

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.evidence.person_track import PersonScore


def init_person_scores_db(db_path: str = DEFAULT_DB_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS person_scores (
                person TEXT NOT NULL,
                source TEXT NOT NULL,
                n_calls INTEGER NOT NULL,
                n_unresolvable INTEGER NOT NULL,
                hit_rate_short REAL,
                hit_rate_long REAL,
                mean_abnormal_short REAL,
                mean_abnormal_long REAL,
                weighted_score REAL,
                scoreable INTEGER NOT NULL,
                computed_at TEXT NOT NULL,
                PRIMARY KEY (person, source)
            )"""
        )


def save_person_scores(
    db_path: str, scores: list[PersonScore], *, now: str
) -> int:
    """Upsert every score; returns the row count written."""
    init_person_scores_db(db_path)
    with sqlite3.connect(db_path) as conn:
        for score in scores:
            row = asdict(score)
            conn.execute(
                """INSERT OR REPLACE INTO person_scores
                   (person, source, n_calls, n_unresolvable, hit_rate_short,
                    hit_rate_long, mean_abnormal_short, mean_abnormal_long,
                    weighted_score, scoreable, computed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["person"], row["source"], row["n_calls"], row["n_unresolvable"],
                    row["hit_rate_short"], row["hit_rate_long"],
                    row["mean_abnormal_short"], row["mean_abnormal_long"],
                    row["weighted_score"], int(row["scoreable"]), now,
                ),
            )
    return len(scores)


def load_person_scores(db_path: str) -> list[dict]:
    """All rows, scoreable first, best weighted_score first within that."""
    init_person_scores_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM person_scores"
            " ORDER BY scoreable DESC, weighted_score DESC NULLS LAST, n_calls DESC"
        ).fetchall()
    return [{**dict(row), "scoreable": bool(row["scoreable"])} for row in rows]


def person_score_index(db_path: str) -> dict[tuple[str, str], dict]:
    """(person, source) -> score row, for annotating alerts/pitches in one lookup."""
    return {
        (row["person"], row["source"]): row for row in load_person_scores(db_path)
    }
