"""SQLite snapshot persistence. Each run is one immutable row + its picks as JSON."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from equity_scout.models import Instrument, Pick, RunResult
from equity_scout.universe import country_of


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
            CREATE TABLE IF NOT EXISTS run_scores (
                run_id INTEGER NOT NULL,
                bucket TEXT NOT NULL,
                rank INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                name TEXT NOT NULL,
                region TEXT NOT NULL,
                country TEXT NOT NULL,
                sector TEXT NOT NULL,
                composite REAL NOT NULL,
                breakdown TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_run_scores_run ON run_scores (run_id);
            """
        )
        # Defensive migration for DBs created before gate_stats/data_quality existed.
        cols = [r[1] for r in con.execute("PRAGMA table_info(runs)")]
        if "gate_stats" not in cols:
            con.execute("ALTER TABLE runs ADD COLUMN gate_stats TEXT NOT NULL DEFAULT '{}'")
        if "data_quality" not in cols:
            con.execute("ALTER TABLE runs ADD COLUMN data_quality TEXT NOT NULL DEFAULT '{}'")


def _pick_from_dict(d: dict) -> Pick:
    d = dict(d)
    d["instrument"] = Instrument(**d["instrument"])
    return Pick(**d)


def save_run(db_path: str | Path, run: RunResult) -> int:
    """Persist one run; returns its row id (run_scores rows reference it)."""
    buckets_json = json.dumps(
        {b: [asdict(p) for p in picks] for b, picks in run.buckets.items()}
    )
    with sqlite3.connect(db_path) as con:
        cur = con.execute(
            "INSERT INTO runs (created_at, universe_size, gated_out, buckets, gate_stats, data_quality) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (run.created_at, run.universe_size, json.dumps(run.gated_out), buckets_json,
             json.dumps(run.gate_stats), json.dumps(run.data_quality)),
        )
        run_id = cur.lastrowid
    assert run_id is not None
    return run_id


def save_run_scores(db_path: str | Path, run_id: int, buckets: dict[str, list[Pick]]) -> None:
    """Persist the FULL cross-sectional ranking (~universe size), one row per pick.

    The runs table keeps only the top-N picks per bucket — far too few to filter by
    region/country/sector (the filter feature's whole point). Country is derived at
    write time so the API can filter with plain SQL."""
    rows = [
        (run_id, bucket, p.rank, p.instrument.ticker, p.instrument.name,
         p.instrument.region, country_of(p.instrument.region, p.instrument.ticker),
         p.instrument.sector, p.composite, json.dumps(p.breakdown))
        for bucket, picks in buckets.items()
        for p in picks
    ]
    with sqlite3.connect(db_path) as con:
        con.executemany(
            "INSERT INTO run_scores (run_id, bucket, rank, ticker, name, region, country,"
            " sector, composite, breakdown) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )


def load_run_scores(
    db_path: str | Path,
    run_id: int,
    *,
    region_codes: set[str] | None = None,
    country: str | None = None,
    sector: str | None = None,
) -> list[dict]:
    """Ranked rows for one run, optionally filtered (conditions ANDed). Ordered by
    bucket, then rank. [] when the run has no persisted ranking (pre-feature runs)."""
    query = ("SELECT bucket, rank, ticker, name, region, country, sector, composite,"
             " breakdown FROM run_scores WHERE run_id = ?")
    params: list = [run_id]
    if region_codes:
        placeholders = ",".join("?" for _ in region_codes)
        query += f" AND region IN ({placeholders})"
        params.extend(sorted(region_codes))
    if country:
        query += " AND country = ?"
        params.append(country)
    if sector:
        query += " AND lower(sector) = lower(?)"
        params.append(sector)
    query += " ORDER BY bucket, rank"
    with sqlite3.connect(db_path) as con:
        try:
            rows = con.execute(query, params).fetchall()
        except sqlite3.OperationalError:  # pre-feature DB without the table
            return []
    return [
        {"bucket": r[0], "rank": r[1], "ticker": r[2], "name": r[3], "region": r[4],
         "country": r[5], "sector": r[6], "composite": r[7], "breakdown": json.loads(r[8])}
        for r in rows
    ]


def latest_run_id(db_path: str | Path) -> int | None:
    with sqlite3.connect(db_path) as con:
        row = con.execute("SELECT id FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    return int(row[0]) if row else None


def run_has_scores(db_path: str | Path, run_id: int) -> bool:
    """False for pre-feature runs (no persisted full ranking) — the API reports the
    filter as unavailable instead of silently serving unfiltered data."""
    with sqlite3.connect(db_path) as con:
        try:
            row = con.execute(
                "SELECT 1 FROM run_scores WHERE run_id = ? LIMIT 1", (run_id,)
            ).fetchone()
        except sqlite3.OperationalError:
            return False
    return row is not None


def run_scores_facets(db_path: str | Path, run_id: int) -> dict:
    """Dropdown options: distinct countries and sectors of one run, with counts."""
    with sqlite3.connect(db_path) as con:
        try:
            countries = con.execute(
                "SELECT country, COUNT(*) FROM run_scores WHERE run_id = ? "
                "GROUP BY country ORDER BY COUNT(*) DESC, country", (run_id,)
            ).fetchall()
            sectors = con.execute(
                "SELECT sector, COUNT(*) FROM run_scores WHERE run_id = ? "
                "GROUP BY sector ORDER BY COUNT(*) DESC, sector", (run_id,)
            ).fetchall()
        except sqlite3.OperationalError:
            return {"countries": [], "sectors": []}
    return {
        "countries": [{"value": c, "count": n} for c, n in countries],
        "sectors": [{"value": s, "count": n} for s, n in sectors],
    }


def load_latest_run(db_path: str | Path) -> RunResult | None:
    with sqlite3.connect(db_path) as con:
        row = con.execute(
            "SELECT created_at, universe_size, gated_out, buckets, gate_stats, data_quality FROM runs "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return None
    created_at, universe_size, gated_out, buckets, gate_stats, data_quality = row
    parsed = json.loads(buckets)
    buckets_obj = {b: [_pick_from_dict(p) for p in picks] for b, picks in parsed.items()}
    return RunResult(
        created_at=created_at,
        universe_size=universe_size,
        gated_out=json.loads(gated_out),
        buckets=buckets_obj,
        gate_stats=json.loads(gate_stats),
        data_quality=json.loads(data_quality),
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
