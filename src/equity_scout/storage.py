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
                buckets TEXT NOT NULL,
                gate_stats TEXT NOT NULL DEFAULT '{}'
            );
            """
        )
        # Defensive migration for DBs created before gate_stats existed.
        cols = [r[1] for r in con.execute("PRAGMA table_info(runs)")]
        if "gate_stats" not in cols:
            con.execute("ALTER TABLE runs ADD COLUMN gate_stats TEXT NOT NULL DEFAULT '{}'")


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
            "INSERT INTO runs (created_at, universe_size, gated_out, buckets, gate_stats) "
            "VALUES (?, ?, ?, ?, ?)",
            (run.created_at, run.universe_size, json.dumps(run.gated_out), buckets_json,
             json.dumps(run.gate_stats)),
        )


def load_latest_run(db_path: str | Path) -> RunResult | None:
    with sqlite3.connect(db_path) as con:
        row = con.execute(
            "SELECT created_at, universe_size, gated_out, buckets, gate_stats FROM runs "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return None
    created_at, universe_size, gated_out, buckets, gate_stats = row
    parsed = json.loads(buckets)
    buckets_obj = {b: [_pick_from_dict(p) for p in picks] for b, picks in parsed.items()}
    return RunResult(
        created_at=created_at,
        universe_size=universe_size,
        gated_out=json.loads(gated_out),
        buckets=buckets_obj,
        gate_stats=json.loads(gate_stats),
    )


def load_run_summaries(db_path: str | Path, limit: int = 20) -> list[dict]:
    """Compact per-run summaries (newest first) for the history view — tickers only, no full picks."""
    with sqlite3.connect(db_path) as con:
        rows = con.execute(
            "SELECT created_at, universe_size, gated_out, buckets, gate_stats FROM runs "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    summaries: list[dict] = []
    for created_at, universe_size, gated_out, buckets, gate_stats in rows:
        parsed = json.loads(buckets)
        tickers = {b: [p["instrument"]["ticker"] for p in picks] for b, picks in parsed.items()}
        total_gated = json.loads(gate_stats).get("total_gated", len(json.loads(gated_out)))
        summaries.append({
            "created_at": created_at,
            "universe_size": universe_size,
            "total_gated": total_gated,
            "picks": tickers,
        })
    return summaries
