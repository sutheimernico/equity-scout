"""SQLite persistence for the catalyst radar (v16).

One table, three producers: the minute ignition scan (source `scan`), the market-wide news
sweep (source `news`) and the forward-looking calendar (source `calendar`). Everything the
radar sees lands here — including what it deliberately does NOT trade, because the whole
point of the radar is that Nico can SEE a move even where we have no edge to act on it.

House idiom (shortterm_storage/autotrader_storage): flat timeseries tables keyed by a
natural-unique column set so an idempotent re-run never double-counts. The radar runs every
minute, so idempotency is not a nicety here — without it a crash-rerun or an overlapping
cron firing would double every signal.

Own DB file (`catalysts.db`): the scan writes every minute while the nightly chain holds
long write transactions on equity_scout.db. Separate files mean a minute-cadence writer can
never block — or be blocked by — the research chain.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from equity_scout import db

DEFAULT_CATALYST_DB_PATH = "catalysts.db"

# Signal sources — one per detection layer.
SOURCE_SCAN = "scan"          # layer 1: it is happening NOW (price/volume ignition)
SOURCE_NEWS = "news"          # layer 2: it is becoming known (market-wide wire)
SOURCE_CALENDAR = "calendar"  # layer 3: it is coming up (known dated catalyst)

SOURCES = (SOURCE_SCAN, SOURCE_NEWS, SOURCE_CALENDAR)


def init_catalyst_db(db_path: str | Path) -> None:
    with db.connect(str(db_path)) as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS catalyst_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                ticker TEXT NOT NULL,
                kind TEXT NOT NULL,
                seen_at TEXT NOT NULL,
                dedup_key TEXT NOT NULL,
                score REAL NOT NULL,
                ref_price REAL,
                change_pct REAL,
                volume_ratio REAL,
                spread_bp REAL,
                detail TEXT NOT NULL,
                headline TEXT,
                url TEXT,
                due_date TEXT,
                alerted_at TEXT,
                traded_at TEXT,
                UNIQUE (dedup_key)
            );
            CREATE INDEX IF NOT EXISTS idx_catalyst_seen
                ON catalyst_signals (seen_at DESC);
            CREATE INDEX IF NOT EXISTS idx_catalyst_ticker
                ON catalyst_signals (ticker, seen_at DESC);

            CREATE TABLE IF NOT EXISTS catalyst_rejections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                ticker TEXT NOT NULL,
                reason TEXT NOT NULL,
                seen_at TEXT NOT NULL,
                detail TEXT NOT NULL,
                UNIQUE (source, ticker, reason, seen_at)
            );

            CREATE TABLE IF NOT EXISTS catalyst_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )


def record_signals(db_path: str | Path, signals: list[dict]) -> int:
    """Insert signals, skipping any whose dedup_key already exists. Returns rows written.

    The dedup_key is the caller's idempotency contract — the scan builds it from
    (ticker, trading day, bucketed move) so the same ignition re-detected a minute later
    updates nothing and alerts nothing, while a genuinely bigger move gets its own row.
    """
    if not signals:
        return 0
    written = 0
    with db.connect(str(db_path)) as con:
        for sig in signals:
            cur = con.execute(
                """
                INSERT OR IGNORE INTO catalyst_signals
                    (source, ticker, kind, seen_at, dedup_key, score, ref_price,
                     change_pct, volume_ratio, spread_bp, detail, headline, url, due_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sig["source"], sig["ticker"], sig["kind"], sig["seen_at"],
                    sig["dedup_key"], float(sig.get("score", 0.0)),
                    sig.get("ref_price"), sig.get("change_pct"),
                    sig.get("volume_ratio"), sig.get("spread_bp"),
                    sig.get("detail", ""), sig.get("headline"), sig.get("url"),
                    sig.get("due_date"),
                ),
            )
            written += cur.rowcount or 0
    return written


def record_rejections(db_path: str | Path, rejections: list[dict]) -> int:
    """Persist why a candidate did NOT become a signal — the calibration data.

    Without these rows a threshold can only ever be defended by argument. With them, the
    nightly review can answer "was -2 % the right bar?" from what actually got rejected.
    """
    if not rejections:
        return 0
    written = 0
    with db.connect(str(db_path)) as con:
        for rej in rejections:
            cur = con.execute(
                """
                INSERT OR IGNORE INTO catalyst_rejections
                    (source, ticker, reason, seen_at, detail)
                VALUES (?, ?, ?, ?, ?)
                """,
                (rej["source"], rej["ticker"], rej["reason"], rej["seen_at"],
                 rej.get("detail", "")),
            )
            written += cur.rowcount or 0
    return written


def load_signals(
    db_path: str | Path,
    *,
    since: str | None = None,
    source: str | None = None,
    min_score: float = 0.0,
    unalerted_only: bool = False,
    untraded_only: bool = False,
    limit: int = 200,
) -> list[dict]:
    """Newest first. `since` compares ISO-8601 strings, which sort chronologically."""
    clauses = ["score >= ?"]
    params: list[object] = [min_score]
    if since:
        clauses.append("seen_at >= ?")
        params.append(since)
    if source:
        clauses.append("source = ?")
        params.append(source)
    if unalerted_only:
        clauses.append("alerted_at IS NULL")
    if untraded_only:
        clauses.append("traded_at IS NULL")
    where = " AND ".join(clauses)
    with db.connect(str(db_path)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            f"SELECT * FROM catalyst_signals WHERE {where} "
            f"ORDER BY seen_at DESC, score DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_alerted(db_path: str | Path, signal_ids: list[int], *, now: str) -> None:
    if not signal_ids:
        return
    with db.connect(str(db_path)) as con:
        con.executemany(
            "UPDATE catalyst_signals SET alerted_at = ? WHERE id = ? AND alerted_at IS NULL",
            [(now, sid) for sid in signal_ids],
        )


def mark_traded(db_path: str | Path, signal_ids: list[int], *, now: str) -> None:
    if not signal_ids:
        return
    with db.connect(str(db_path)) as con:
        con.executemany(
            "UPDATE catalyst_signals SET traded_at = ? WHERE id = ? AND traded_at IS NULL",
            [(now, sid) for sid in signal_ids],
        )


def last_alert_at(db_path: str | Path, ticker: str) -> str | None:
    """Cooldown input: when did this ticker last trigger an alert?"""
    with db.connect(str(db_path)) as con:
        row = con.execute(
            "SELECT MAX(alerted_at) FROM catalyst_signals WHERE ticker = ? AND alerted_at IS NOT NULL",
            (ticker,),
        ).fetchone()
    return row[0] if row else None


def get_state(db_path: str | Path, key: str) -> str | None:
    with db.connect(str(db_path)) as con:
        row = con.execute("SELECT value FROM catalyst_state WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_state(db_path: str | Path, key: str, value: str) -> None:
    with db.connect(str(db_path)) as con:
        con.execute(
            "INSERT INTO catalyst_state (key, value) VALUES (?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def stats(db_path: str | Path, *, since: str | None = None) -> dict:
    """Counts per source/kind plus rejection reasons — the watchdog's and cockpit's summary."""
    where, params = ("WHERE seen_at >= ?", (since,)) if since else ("", ())
    with db.connect(str(db_path)) as con:
        by_source = dict(con.execute(
            f"SELECT source, COUNT(*) FROM catalyst_signals {where} GROUP BY source", params
        ).fetchall())
        by_kind = dict(con.execute(
            f"SELECT kind, COUNT(*) FROM catalyst_signals {where} GROUP BY kind "
            f"ORDER BY COUNT(*) DESC", params
        ).fetchall())
        rej = dict(con.execute(
            f"SELECT reason, COUNT(*) FROM catalyst_rejections {where} GROUP BY reason "
            f"ORDER BY COUNT(*) DESC", params
        ).fetchall())
        total = con.execute(
            f"SELECT COUNT(*) FROM catalyst_signals {where}", params
        ).fetchone()[0]
    return {
        "total": total, "by_source": by_source, "by_kind": by_kind,
        "rejections": rej,
    }


def export_json(db_path: str | Path, *, since: str | None = None, limit: int = 100) -> str:
    return json.dumps(load_signals(db_path, since=since, limit=limit), ensure_ascii=False)
