"""Append-only predict-then-resolve ledger for external evidence sources.

Mirror of ml/prediction_ledger.py, honesty invariant #3 applied to evidence: every NEW
evidence event is logged BEFORE its outcome is knowable, with an implicit claim "this
kind of event precedes benchmark-beating forward returns". Once the horizon has elapsed
a resolver fills the REAL forward relative return — never a back-filled guess. Rows are
append-only; the single permitted mutation is one open→resolved transition per row.
`stats_by_source` turns "does congress-following work?" into a query, not an opinion.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.evidence.base import EvidenceEvent

DEFAULT_HORIZON_DAYS = 60  # calendar days — deliberate over-estimate of the trading window


def init_evidence_ledger(db_path: str = DEFAULT_DB_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS evidence_predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                source TEXT NOT NULL,
                ticker TEXT NOT NULL,
                event_key TEXT NOT NULL,
                horizon_days INTEGER NOT NULL,
                resolve_after TEXT NOT NULL,
                resolved_at TEXT,
                realized_relative_return REAL,
                label INTEGER,
                UNIQUE(source, ticker, event_key)
            )"""
        )


def log_evidence(
    db_path: str,
    events: list[EvidenceEvent],
    *,
    now: str,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> int:
    """Append one open row per event; the UNIQUE key makes re-logging a no-op, so a
    re-collected fact can never inflate the sample. Returns the number of new rows."""
    init_evidence_ledger(db_path)
    resolve_after = (datetime.fromisoformat(now) + timedelta(days=horizon_days)).isoformat()
    logged = 0
    with sqlite3.connect(db_path) as conn:
        for event in events:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO evidence_predictions"
                " (created_at, source, ticker, event_key, horizon_days, resolve_after)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (now, event.source, event.ticker, event.event_key, int(horizon_days),
                 resolve_after),
            )
            logged += cursor.rowcount
    return logged


def due_evidence(db_path: str, now: str) -> list[dict]:
    """Open rows whose resolve_after lies at or before `now` — real datetime compare,
    not lexical (offsets in ISO strings would otherwise resolve pre-due rows)."""
    init_evidence_ledger(db_path)
    now_dt = datetime.fromisoformat(now)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, created_at, source, ticker, event_key, horizon_days, resolve_after"
            " FROM evidence_predictions WHERE resolved_at IS NULL ORDER BY id"
        ).fetchall()
    return [
        {
            "id": int(r[0]),
            "created_at": r[1],
            "source": r[2],
            "ticker": r[3],
            "event_key": r[4],
            "horizon_days": int(r[5]),
            "resolve_after": r[6],
        }
        for r in rows
        if datetime.fromisoformat(r[6]) <= now_dt
    ]


def resolve_evidence(
    db_path: str,
    prediction_id: int,
    *,
    realized_relative_return: float,
    resolved_at: str,
) -> bool:
    """One guarded open→resolved transition. label = int(return beat the benchmark).
    A second resolution attempt finds no open row and is refused (first stands)."""
    init_evidence_ledger(db_path)
    with sqlite3.connect(db_path) as conn:
        exists = conn.execute(
            "SELECT 1 FROM evidence_predictions WHERE id = ?", (prediction_id,)
        ).fetchone()
        if exists is None:
            raise ValueError(f"unknown evidence prediction id: {prediction_id}")
        cursor = conn.execute(
            "UPDATE evidence_predictions"
            " SET resolved_at = ?, realized_relative_return = ?, label = ?"
            " WHERE id = ? AND resolved_at IS NULL",
            (
                resolved_at,
                float(realized_relative_return),
                int(realized_relative_return > 0.0),
                prediction_id,
            ),
        )
        return cursor.rowcount == 1


def stats_by_source(db_path: str) -> dict[str, dict]:
    """Per-source stats over RESOLVED rows only (plus the open count). hit_rate is the
    share of events whose forward return beat SPY; None until anything resolved."""
    init_evidence_ledger(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT source, resolved_at, realized_relative_return, label"
            " FROM evidence_predictions ORDER BY id"
        ).fetchall()
    stats: dict[str, dict] = {}
    for source, resolved_at, realized, label in rows:
        entry = stats.setdefault(
            source,
            {"n_resolved": 0, "n_open": 0, "hit_rate": None, "mean_relative_return": None,
             "_returns": []},
        )
        if resolved_at is None:
            entry["n_open"] += 1
        else:
            entry["n_resolved"] += 1
            entry["_returns"].append((float(realized), int(label)))
    for entry in stats.values():
        returns = entry.pop("_returns")
        if returns:
            entry["hit_rate"] = round(sum(lbl for _, lbl in returns) / len(returns), 4)
            entry["mean_relative_return"] = round(
                sum(ret for ret, _ in returns) / len(returns), 4
            )
    return stats
