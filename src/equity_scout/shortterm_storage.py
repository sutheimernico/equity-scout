"""SQLite persistence for the short-term arena lanes (vision v11).

House idiom (forward_storage/autotrader_storage): one JSON blob per lane book, flat
timeseries tables keyed by natural-unique columns so idempotent re-runs never
double-count, and a tiny per-lane KV for engine markers (last processed bar etc.)."""
from __future__ import annotations

import json
from equity_scout import db
from pathlib import Path

from equity_scout.shortterm_book import LaneBook, LanePosition, LaneValuation, TradeFill

DEFAULT_SHORTTERM_DB_PATH = "shortterm.db"

LANES = ("swing", "session", "crypto")


def init_shortterm_db(db_path: str | Path) -> None:
    with db.connect(db_path) as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS st_books (
                lane TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS st_valuations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lane TEXT NOT NULL,
                created_at TEXT NOT NULL,
                equity REAL NOT NULL,
                total_return REAL NOT NULL,
                cash REAL NOT NULL,
                open_positions INTEGER NOT NULL,
                benchmark_return REAL,
                UNIQUE (lane, created_at)
            );
            CREATE TABLE IF NOT EXISTS st_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lane TEXT NOT NULL,
                executed_at TEXT NOT NULL,
                ticker TEXT NOT NULL,
                side TEXT NOT NULL,
                qty REAL NOT NULL,
                price REAL NOT NULL,
                fees REAL NOT NULL,
                reason TEXT NOT NULL,
                realized_pnl REAL,
                UNIQUE (lane, ticker, executed_at, side)
            );
            CREATE TABLE IF NOT EXISTS st_state (
                lane TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (lane, key)
            );
            """
        )


def _to_json(book: LaneBook) -> str:
    return json.dumps({
        "lane": book.lane,
        "initial_capital": book.initial_capital,
        "cash": book.cash,
        "benchmark_ticker": book.benchmark_ticker,
        "benchmark_entry_price": book.benchmark_entry_price,
        "positions": {
            t: {"qty": p.qty, "entry_price": p.entry_price, "opened_at": p.opened_at}
            for t, p in book.positions.items()
        },
    })


def _from_json(blob: str) -> LaneBook:
    d = json.loads(blob)
    return LaneBook(
        lane=d["lane"],
        initial_capital=d["initial_capital"],
        cash=d["cash"],
        benchmark_ticker=d["benchmark_ticker"],
        benchmark_entry_price=d.get("benchmark_entry_price"),
        positions={
            t: LanePosition(qty=p["qty"], entry_price=p["entry_price"], opened_at=p["opened_at"])
            for t, p in d.get("positions", {}).items()
        },
    )


def save_book(db_path: str | Path, book: LaneBook, *, updated_at: str) -> None:
    init_shortterm_db(db_path)
    with db.connect(db_path) as con:
        con.execute(
            "INSERT INTO st_books (lane, data, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(lane) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
            (book.lane, _to_json(book), updated_at),
        )


def load_book(db_path: str | Path, lane: str) -> LaneBook | None:
    init_shortterm_db(db_path)
    with db.connect(db_path) as con:
        row = con.execute("SELECT data FROM st_books WHERE lane = ?", (lane,)).fetchone()
    return _from_json(row[0]) if row else None


def append_valuation(db_path: str | Path, snap: LaneValuation) -> None:
    init_shortterm_db(db_path)
    with db.connect(db_path) as con:
        con.execute(
            "INSERT OR IGNORE INTO st_valuations "
            "(lane, created_at, equity, total_return, cash, open_positions, benchmark_return)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (snap.lane, snap.created_at, snap.equity, snap.total_return, snap.cash,
             snap.open_positions, snap.benchmark_return),
        )


def load_valuations(db_path: str | Path, lane: str) -> list[dict]:
    init_shortterm_db(db_path)
    with db.connect(db_path) as con:
        rows = con.execute(
            "SELECT created_at, equity, total_return, cash, open_positions, benchmark_return"
            " FROM st_valuations WHERE lane = ? ORDER BY created_at ASC",
            (lane,),
        ).fetchall()
    keys = ("created_at", "equity", "total_return", "cash", "open_positions", "benchmark_return")
    return [dict(zip(keys, row)) for row in rows]


def append_trades(db_path: str | Path, fills: list[TradeFill]) -> None:
    init_shortterm_db(db_path)
    with db.connect(db_path) as con:
        con.executemany(
            "INSERT OR IGNORE INTO st_trades "
            "(lane, executed_at, ticker, side, qty, price, fees, reason, realized_pnl)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (f.lane, f.executed_at, f.ticker, f.side, f.qty, f.price, f.fees, f.reason,
                 f.realized_pnl)
                for f in fills
            ],
        )


def load_trades(db_path: str | Path, lane: str, *, limit: int = 200) -> list[dict]:
    init_shortterm_db(db_path)
    with db.connect(db_path) as con:
        rows = con.execute(
            "SELECT executed_at, ticker, side, qty, price, fees, reason, realized_pnl"
            " FROM st_trades WHERE lane = ? ORDER BY executed_at DESC, id DESC LIMIT ?",
            (lane, limit),
        ).fetchall()
    keys = ("executed_at", "ticker", "side", "qty", "price", "fees", "reason", "realized_pnl")
    return [dict(zip(keys, row)) for row in rows]


def get_lane_state(db_path: str | Path, lane: str, key: str) -> str | None:
    init_shortterm_db(db_path)
    with db.connect(db_path) as con:
        row = con.execute(
            "SELECT value FROM st_state WHERE lane = ? AND key = ?", (lane, key)
        ).fetchone()
    return row[0] if row else None


def set_lane_state(db_path: str | Path, lane: str, key: str, value: str) -> None:
    init_shortterm_db(db_path)
    with db.connect(db_path) as con:
        con.execute(
            "INSERT INTO st_state (lane, key, value) VALUES (?, ?, ?)"
            " ON CONFLICT(lane, key) DO UPDATE SET value = excluded.value",
            (lane, key, value),
        )
