"""SQLite snapshot persistence. Each run is one immutable row + its picks as JSON."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from equity_scout.models import Instrument, Pick, RunResult


def init_db(db_path: str | Path) -> None:
    with sqlite3.connect(db_path) as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                universe_size INTEGER NOT NULL,
                gated_out TEXT NOT NULL,
                buckets TEXT NOT NULL
            );
            """
        )


def _pick_from_dict(d: dict) -> Pick:
    d = dict(d)
    d["instrument"] = Instrument(**d["instrument"])
    return Pick(**d)


def save_run(db_path: str | Path, run: RunResult) -> None:
    buckets_json = json.dumps(
        {b: [asdict(p) for p in picks] for b, picks in run.buckets.items()}
    )
    with sqlite3.connect(db_path) as con:
        con.execute(
            "INSERT INTO runs (created_at, universe_size, gated_out, buckets) VALUES (?, ?, ?, ?)",
            (run.created_at, run.universe_size, json.dumps(run.gated_out), buckets_json),
        )


def load_latest_run(db_path: str | Path) -> RunResult | None:
    with sqlite3.connect(db_path) as con:
        row = con.execute(
            "SELECT created_at, universe_size, gated_out, buckets FROM runs "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return None
    created_at, universe_size, gated_out, buckets = row
    parsed = json.loads(buckets)
    buckets_obj = {b: [_pick_from_dict(p) for p in picks] for b, picks in parsed.items()}
    return RunResult(
        created_at=created_at,
        universe_size=universe_size,
        gated_out=json.loads(gated_out),
        buckets=buckets_obj,
    )
