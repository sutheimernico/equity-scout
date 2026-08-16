"""Persisted exit parameters per lane, with the history of how they got there (T11).

Until now a lane's knobs were module constants (`st_swing.PROFIT_TARGET` and friends). That is
fine as long as a human edits them and the change lands in a commit. Once the system may change
them itself (Nico's decision, 2026-08-16), two things become necessary:

1. **A place to write them** that is not source code, so a nightly job can act without a deploy.
2. **A history**, because a track record whose rules changed silently is unreadable afterwards.
   Every row records what changed, when, and on what evidence — a P&L curve without that is a
   number nobody can interpret six weeks later.

The constants stay the fallback: an empty table means "as shipped", never "no rules". A lane
must be able to run before anything has ever tuned it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from equity_scout import db
from equity_scout.exits import ExitRules


@dataclass(frozen=True)
class ParamChange:
    lane: str
    changed_at: str
    profit_target: float
    stop_loss: float
    max_days: int
    reason: str
    evidence: dict


def init_lane_params(db_path: str | Path) -> None:
    with db.connect(str(db_path)) as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS lane_params (
                lane TEXT PRIMARY KEY,
                profit_target REAL NOT NULL,
                stop_loss REAL NOT NULL,
                max_days INTEGER NOT NULL,
                changed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS lane_param_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lane TEXT NOT NULL,
                changed_at TEXT NOT NULL,
                profit_target REAL NOT NULL,
                stop_loss REAL NOT NULL,
                max_days INTEGER NOT NULL,
                reason TEXT NOT NULL,
                evidence TEXT NOT NULL
            );
            """
        )


def load_params(db_path: str | Path, lane: str, *, default: ExitRules) -> ExitRules:
    """The lane's current rules, or `default` when nothing was ever tuned."""
    init_lane_params(db_path)
    with db.connect(str(db_path)) as con:
        row = con.execute(
            "SELECT profit_target, stop_loss, max_days FROM lane_params WHERE lane = ?", (lane,)
        ).fetchone()
    if row is None:
        return default
    return ExitRules(profit_target=row[0], stop_loss=row[1], max_holding_days=int(row[2]))


def set_params(
    db_path: str | Path,
    lane: str,
    rules: ExitRules,
    *,
    reason: str,
    evidence: dict,
    now: str,
) -> None:
    """Write new rules AND the history row in one transaction.

    The two are written together on purpose: a parameter set whose history row is missing looks
    exactly like one that was never changed, and that is the one case where the track record
    silently lies.
    """
    init_lane_params(db_path)
    with db.connect(str(db_path)) as con:
        con.execute(
            "INSERT INTO lane_params (lane, profit_target, stop_loss, max_days, changed_at)"
            " VALUES (?, ?, ?, ?, ?) ON CONFLICT(lane) DO UPDATE SET"
            " profit_target = excluded.profit_target, stop_loss = excluded.stop_loss,"
            " max_days = excluded.max_days, changed_at = excluded.changed_at",
            (lane, rules.profit_target, rules.stop_loss, rules.max_holding_days, now),
        )
        con.execute(
            "INSERT INTO lane_param_history"
            " (lane, changed_at, profit_target, stop_loss, max_days, reason, evidence)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (lane, now, rules.profit_target, rules.stop_loss, rules.max_holding_days,
             reason, json.dumps(evidence, ensure_ascii=False)),
        )


def history(db_path: str | Path, lane: str) -> list[ParamChange]:
    """Newest first — the reader almost always wants "what changed last"."""
    init_lane_params(db_path)
    with db.connect(str(db_path)) as con:
        rows = con.execute(
            "SELECT lane, changed_at, profit_target, stop_loss, max_days, reason, evidence"
            " FROM lane_param_history WHERE lane = ? ORDER BY id DESC",
            (lane,),
        ).fetchall()
    return [
        ParamChange(
            lane=r[0], changed_at=r[1], profit_target=r[2], stop_loss=r[3],
            max_days=int(r[4]), reason=r[5], evidence=json.loads(r[6]),
        )
        for r in rows
    ]


def changed_this_month(db_path: str | Path, lane: str, *, month: str) -> bool:
    """One change per lane and calendar month — the brake from T12.

    Without it a nightly search may flip the rules every night, and no version of the lane ever
    accumulates enough trades to be judged. `month` is "YYYY-MM".
    """
    return any(change.changed_at.startswith(month) for change in history(db_path, lane))
