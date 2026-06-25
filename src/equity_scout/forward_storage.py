"""SQLite persistence for forward paper accounts + their valuation history.

Mirrors the `portfolio_storage` pattern: a JSON blob for the (small, evolving) account state, a flat
timeseries table for valuations. Valuations are unique per (strategy, date) so re-running the daily
advance never double-counts a day.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from equity_scout.forward_paper import ForwardAccount, ForwardValuation


def init_forward_db(db_path: str | Path) -> None:
    with sqlite3.connect(db_path) as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS forward_accounts (
                strategy_name TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS forward_valuations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                equity REAL NOT NULL,
                total_return REAL NOT NULL,
                benchmark_equity REAL NOT NULL,
                benchmark_return REAL NOT NULL,
                UNIQUE (strategy_name, created_at)
            );
            """
        )


def _to_json(account: ForwardAccount) -> str:
    return json.dumps({
        "strategy_name": account.strategy_name,
        "initial_capital": account.initial_capital,
        "equity": account.equity,
        "benchmark_ticker": account.benchmark_ticker,
        "benchmark_equity": account.benchmark_equity,
        "last_as_of": account.last_as_of,
        "weights": account.weights,
    })


def _from_json(blob: str) -> ForwardAccount:
    d = json.loads(blob)
    return ForwardAccount(
        strategy_name=d["strategy_name"],
        initial_capital=d["initial_capital"],
        equity=d["equity"],
        benchmark_ticker=d["benchmark_ticker"],
        benchmark_equity=d["benchmark_equity"],
        last_as_of=d["last_as_of"],
        weights=d["weights"],
    )


def save_account(db_path: str | Path, account: ForwardAccount, *, updated_at: str) -> None:
    with sqlite3.connect(db_path) as con:
        con.execute(
            "INSERT INTO forward_accounts (strategy_name, data, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(strategy_name) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
            (account.strategy_name, _to_json(account), updated_at),
        )


def load_account(db_path: str | Path, strategy_name: str) -> ForwardAccount | None:
    with sqlite3.connect(db_path) as con:
        try:
            row = con.execute(
                "SELECT data FROM forward_accounts WHERE strategy_name = ?", (strategy_name,)
            ).fetchone()
        except sqlite3.OperationalError:
            return None  # tables not created yet
    return _from_json(row[0]) if row else None


def load_all_accounts(db_path: str | Path) -> list[ForwardAccount]:
    with sqlite3.connect(db_path) as con:
        try:
            rows = con.execute(
                "SELECT data FROM forward_accounts ORDER BY strategy_name"
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [_from_json(r[0]) for r in rows]


def append_valuation(db_path: str | Path, strategy_name: str, valuation: ForwardValuation) -> None:
    """Insert a valuation; a no-op if (strategy, date) already exists (idempotent daily advance)."""
    with sqlite3.connect(db_path) as con:
        con.execute(
            "INSERT OR IGNORE INTO forward_valuations "
            "(strategy_name, created_at, equity, total_return, benchmark_equity, benchmark_return) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                strategy_name,
                valuation.created_at,
                valuation.equity,
                valuation.total_return,
                valuation.benchmark_equity,
                valuation.benchmark_return,
            ),
        )


def load_valuations(db_path: str | Path, strategy_name: str) -> list[dict]:
    with sqlite3.connect(db_path) as con:
        try:
            rows = con.execute(
                "SELECT created_at, equity, total_return, benchmark_equity, benchmark_return "
                "FROM forward_valuations WHERE strategy_name = ? ORDER BY created_at ASC",
                (strategy_name,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [
        {"created_at": c, "equity": e, "total_return": tr,
         "benchmark_equity": be, "benchmark_return": br}
        for c, e, tr, be, br in rows
    ]
