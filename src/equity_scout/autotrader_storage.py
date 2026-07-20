"""SQLite persistence for the Auto-Depot (vision v10).

Mirrors the `forward_storage` pattern: one JSON blob for the (small, evolving) account state,
flat timeseries tables for valuations, trades, risk events, and the monthly sleeve weights.
Every timeseries row is UNIQUE per natural key so the idempotent daily advance never
double-counts a re-run; `record_advance` persists one advance atomically."""
from __future__ import annotations

import json
from equity_scout import db
from pathlib import Path

from equity_scout.autotrader_allocator import SleeveAllocation
from equity_scout.autotrader_engine import AutoDepotAccount, AutoDepotValuation
from equity_scout.autotrader_protections import BreakerState

DEFAULT_AUTOTRADER_DB_PATH = "autotrader.db"


def init_autotrader_db(db_path: str | Path) -> None:
    with db.connect(db_path) as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS autotrader_account (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                data TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS autotrader_valuations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL UNIQUE,
                equity REAL NOT NULL,
                total_return REAL NOT NULL,
                benchmark_equity REAL NOT NULL,
                benchmark_return REAL NOT NULL,
                gross_exposure REAL NOT NULL,
                drawdown REAL NOT NULL,
                equity_eur REAL,
                fx_rate REAL
            );
            CREATE TABLE IF NOT EXISTS autotrader_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                ticker TEXT NOT NULL,
                delta_weight REAL NOT NULL,
                notional REAL NOT NULL,
                cost REAL NOT NULL,
                UNIQUE (ticker, created_at)
            );
            CREATE TABLE IF NOT EXISTS autotrader_risk_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                protection TEXT NOT NULL,
                action TEXT NOT NULL,
                detail TEXT NOT NULL,
                UNIQUE (created_at, protection)
            );
            CREATE TABLE IF NOT EXISTS autotrader_sleeve_weights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                month TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                weight REAL NOT NULL,
                sharpe REAL,
                mode TEXT NOT NULL,
                UNIQUE (month, strategy_name)
            );
            """
        )


def _to_json(account: AutoDepotAccount) -> str:
    return json.dumps({
        "initial_capital": account.initial_capital,
        "equity": account.equity,
        "benchmark_ticker": account.benchmark_ticker,
        "benchmark_equity": account.benchmark_equity,
        "peak_equity": account.peak_equity,
        "last_as_of": account.last_as_of,
        "weights": account.weights,
        "breaker": {"stage": account.breaker.stage, "changed_at": account.breaker.changed_at},
        "sleeve_weights": account.sleeve_weights,
        "sleeve_mode": account.sleeve_mode,
        "promoted_lanes": list(account.promoted_lanes),
    })


def _from_json(blob: str) -> AutoDepotAccount:
    d = json.loads(blob)
    breaker = d.get("breaker", {})
    return AutoDepotAccount(
        initial_capital=d["initial_capital"],
        equity=d["equity"],
        benchmark_ticker=d["benchmark_ticker"],
        benchmark_equity=d["benchmark_equity"],
        peak_equity=d["peak_equity"],
        last_as_of=d["last_as_of"],
        weights=d["weights"],
        breaker=BreakerState(
            stage=breaker.get("stage", 0), changed_at=breaker.get("changed_at")
        ),
        sleeve_weights=d.get("sleeve_weights", {}),
        sleeve_mode=d.get("sleeve_mode", "anchor"),
        promoted_lanes=tuple(d.get("promoted_lanes", [])),
    )


def _upsert_account(con, account: AutoDepotAccount, updated_at: str) -> None:
    con.execute(
        "INSERT INTO autotrader_account (id, data, updated_at) VALUES (1, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
        (_to_json(account), updated_at),
    )


def _insert_advance_rows(con, valuation: AutoDepotValuation) -> None:
    con.execute(
        "INSERT OR IGNORE INTO autotrader_valuations "
        "(created_at, equity, total_return, benchmark_equity, benchmark_return,"
        " gross_exposure, drawdown, equity_eur, fx_rate) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            valuation.created_at, valuation.equity, valuation.total_return,
            valuation.benchmark_equity, valuation.benchmark_return,
            valuation.gross_exposure, valuation.drawdown,
            valuation.equity_eur, valuation.fx_rate,
        ),
    )
    con.executemany(
        "INSERT OR IGNORE INTO autotrader_trades "
        "(created_at, ticker, delta_weight, notional, cost) VALUES (?, ?, ?, ?, ?)",
        [
            (t.created_at, t.ticker, t.delta_weight, t.notional, t.cost)
            for t in valuation.trades
        ],
    )
    con.executemany(
        "INSERT OR IGNORE INTO autotrader_risk_events "
        "(created_at, protection, action, detail) VALUES (?, ?, ?, ?)",
        [
            (valuation.created_at, e.protection, e.action, e.detail)
            for e in valuation.risk_events
        ],
    )


def save_depot(db_path: str | Path, account: AutoDepotAccount, *, updated_at: str) -> None:
    init_autotrader_db(db_path)
    with db.connect(db_path) as con:
        _upsert_account(con, account, updated_at)


def persist_advance(
    db_path: str | Path,
    account: AutoDepotAccount,
    valuation: AutoDepotValuation | None,
    *,
    updated_at: str,
) -> None:
    """Persist one advance atomically (v12 R3, review 2026-07-20): the timeseries rows and
    the account blob — whose `last_as_of` is the idempotence guard — commit in ONE
    transaction. A crash in between can no longer strand a day (guard set, rows lost,
    retry blocked). The account write deliberately comes last."""
    init_autotrader_db(db_path)
    with db.connect(db_path) as con:
        if valuation is not None:
            _insert_advance_rows(con, valuation)
        _upsert_account(con, account, updated_at)


def load_depot(db_path: str | Path) -> AutoDepotAccount | None:
    init_autotrader_db(db_path)
    with db.connect(db_path) as con:
        row = con.execute("SELECT data FROM autotrader_account WHERE id = 1").fetchone()
    return _from_json(row[0]) if row else None


def record_advance(db_path: str | Path, valuation: AutoDepotValuation) -> None:
    """Persist one advance's timeseries rows. Every insert is INSERT OR IGNORE on the
    natural key, so re-running the same panel date is a no-op. Runner code should prefer
    `persist_advance` (rows + account in one transaction)."""
    init_autotrader_db(db_path)
    with db.connect(db_path) as con:
        _insert_advance_rows(con, valuation)


def record_events(db_path: str | Path, created_at: str, events) -> None:
    """Standalone risk-event rows — promotions/demotions happen outside an advance
    (v12 I3). INSERT OR IGNORE on (created_at, protection) keeps re-runs idempotent."""
    init_autotrader_db(db_path)
    with db.connect(db_path) as con:
        con.executemany(
            "INSERT OR IGNORE INTO autotrader_risk_events "
            "(created_at, protection, action, detail) VALUES (?, ?, ?, ?)",
            [(created_at, e.protection, e.action, e.detail) for e in events],
        )


def load_valuations(db_path: str | Path) -> list[dict]:
    init_autotrader_db(db_path)
    with db.connect(db_path) as con:
        rows = con.execute(
            "SELECT created_at, equity, total_return, benchmark_equity, benchmark_return,"
            " gross_exposure, drawdown, equity_eur, fx_rate"
            " FROM autotrader_valuations ORDER BY created_at ASC"
        ).fetchall()
    keys = (
        "created_at", "equity", "total_return", "benchmark_equity", "benchmark_return",
        "gross_exposure", "drawdown", "equity_eur", "fx_rate",
    )
    return [dict(zip(keys, row)) for row in rows]


def load_trades(db_path: str | Path, *, limit: int = 50) -> list[dict]:
    init_autotrader_db(db_path)
    with db.connect(db_path) as con:
        rows = con.execute(
            "SELECT created_at, ticker, delta_weight, notional, cost FROM autotrader_trades"
            " ORDER BY created_at DESC, ticker ASC LIMIT ?",
            (limit,),
        ).fetchall()
    keys = ("created_at", "ticker", "delta_weight", "notional", "cost")
    return [dict(zip(keys, row)) for row in rows]


def load_risk_events(db_path: str | Path, *, limit: int = 20) -> list[dict]:
    init_autotrader_db(db_path)
    with db.connect(db_path) as con:
        rows = con.execute(
            "SELECT created_at, protection, action, detail FROM autotrader_risk_events"
            " ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    keys = ("created_at", "protection", "action", "detail")
    return [dict(zip(keys, row)) for row in rows]


def save_sleeve_weights(db_path: str | Path, month: str, allocation: SleeveAllocation) -> None:
    """Upsert the month's sleeve allocation (weight + Sharpe estimate + mode per sleeve)."""
    init_autotrader_db(db_path)
    with db.connect(db_path) as con:
        con.executemany(
            "INSERT INTO autotrader_sleeve_weights (month, strategy_name, weight, sharpe, mode)"
            " VALUES (?, ?, ?, ?, ?) ON CONFLICT(month, strategy_name) DO UPDATE SET"
            " weight = excluded.weight, sharpe = excluded.sharpe, mode = excluded.mode",
            [
                (month, name, weight, allocation.sharpes.get(name), allocation.mode)
                for name, weight in allocation.weights.items()
            ],
        )


def load_latest_sleeve_weights(db_path: str | Path) -> list[dict]:
    init_autotrader_db(db_path)
    with db.connect(db_path) as con:
        row = con.execute("SELECT MAX(month) FROM autotrader_sleeve_weights").fetchone()
        if not row or row[0] is None:
            return []
        rows = con.execute(
            "SELECT month, strategy_name, weight, sharpe, mode FROM autotrader_sleeve_weights"
            " WHERE month = ? ORDER BY weight DESC, strategy_name ASC",
            (row[0],),
        ).fetchall()
    keys = ("month", "strategy_name", "weight", "sharpe", "mode")
    return [dict(zip(keys, r)) for r in rows]
