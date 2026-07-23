"""SQLite persistence for forward paper accounts + their valuation and exit history.

Mirrors the `portfolio_storage` pattern: a JSON blob for the (small, evolving) account state, flat
timeseries tables for valuations and exits. Both are unique per (strategy, date [, ticker]) so
re-running the daily advance never double-counts a day.

Migration note (plan v7, strand A2): `positions` (per-ticker entry price/date) is a new key inside
the existing JSON blob, not a new SQL column — `forward_accounts` keeps the same three columns it
always had, so the already-populated `forward_paper.db` in the repo root needs no ALTER TABLE.
`_from_json` reads the key with `.get(..., {})` so a blob written before this key existed still
loads (empty entry-tracking map). `forward_exits` is a brand-new table (CREATE TABLE IF NOT
EXISTS, same idiom as `forward_valuations` and radar_storage's `signal_readings`), so an old DB
file just gains it empty on the next `init_forward_db` call — nothing to migrate there either.
`stale_days` (v13 R4, per-ticker no-fresh-price streak) is the same idiom again: one more key in
the same blob, `.get(..., {})` on the way back in, so a blob written before R4 loads with empty
counters rather than KeyError.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from equity_scout.forward_paper import ExitEvent, ForwardAccount, ForwardValuation, PositionEntry


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
            CREATE TABLE IF NOT EXISTS forward_exits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                ticker TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL NOT NULL,
                opened_at TEXT NOT NULL,
                return_pct REAL NOT NULL,
                held_days INTEGER NOT NULL,
                reason TEXT NOT NULL,
                UNIQUE (strategy_name, ticker, created_at)
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
        "positions": {
            ticker: {"entry_price": p.entry_price, "opened_at": p.opened_at}
            for ticker, p in account.positions.items()
        },
        "stale_days": account.stale_days,
    })


def _from_json(blob: str) -> ForwardAccount:
    d = json.loads(blob)
    positions = {
        ticker: PositionEntry(entry_price=p["entry_price"], opened_at=p["opened_at"])
        for ticker, p in d.get("positions", {}).items()  # .get: absent in pre-A2 blobs
    }
    return ForwardAccount(
        strategy_name=d["strategy_name"],
        initial_capital=d["initial_capital"],
        equity=d["equity"],
        benchmark_ticker=d["benchmark_ticker"],
        benchmark_equity=d["benchmark_equity"],
        last_as_of=d["last_as_of"],
        weights=d["weights"],
        positions=positions,
        stale_days=d.get("stale_days", {}),  # .get: absent in pre-R4 blobs
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


def append_exit(db_path: str | Path, strategy_name: str, exit_event: ExitEvent) -> None:
    """Insert one booked exit; a no-op if (strategy, ticker, date) already exists — same
    idempotent-daily-advance convention as append_valuation."""
    with sqlite3.connect(db_path) as con:
        con.execute(
            "INSERT OR IGNORE INTO forward_exits "
            "(strategy_name, created_at, ticker, entry_price, exit_price, opened_at,"
            " return_pct, held_days, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                strategy_name,
                exit_event.created_at,
                exit_event.ticker,
                exit_event.entry_price,
                exit_event.exit_price,
                exit_event.opened_at,
                exit_event.return_pct,
                exit_event.held_days,
                exit_event.reason,
            ),
        )


def load_exits(db_path: str | Path, strategy_name: str) -> list[dict]:
    with sqlite3.connect(db_path) as con:
        try:
            rows = con.execute(
                "SELECT created_at, ticker, entry_price, exit_price, opened_at, return_pct,"
                " held_days, reason FROM forward_exits WHERE strategy_name = ? ORDER BY created_at ASC",
                (strategy_name,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [
        {"created_at": c, "ticker": t, "entry_price": ep, "exit_price": xp, "opened_at": oa,
         "return_pct": rp, "held_days": hd, "reason": r}
        for c, t, ep, xp, oa, rp, hd, r in rows
    ]
