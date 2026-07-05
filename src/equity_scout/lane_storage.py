"""SQLite persistence for the two-lane arena.

Repo storage idiom (raw sqlite3, idempotent init, JSON snapshots). lane_trades is
append-only — it is BOTH the fairness audit trail and the "pitch executed" marker
(a decided buy pitch with its id in lane_trades has been executed by lane "nico").
lane_valuations is day-keyed (YYYY-MM-DD) with INSERT OR REPLACE: re-running the
CLI within one day updates that day's row instead of appending a duplicate.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.lanes import TradeRecord
from equity_scout.models import Instrument
from equity_scout.portfolio import Portfolio, Position

_TRADE_COLUMNS = "id, created_at, lane, ticker, side, shares, fill_price, cost, reason, pitch_id"


def init_lane_db(db_path: str = DEFAULT_DB_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS lane_portfolios (
                lane TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS lane_valuations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lane TEXT NOT NULL,
                valued_on TEXT NOT NULL,
                total_value REAL NOT NULL,
                total_return REAL NOT NULL,
                benchmark_value REAL NOT NULL,
                benchmark_return REAL NOT NULL,
                open_positions INTEGER NOT NULL,
                UNIQUE(lane, valued_on)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS lane_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                lane TEXT NOT NULL,
                ticker TEXT NOT NULL,
                side TEXT NOT NULL,
                shares REAL NOT NULL,
                fill_price REAL NOT NULL,
                cost REAL NOT NULL,
                reason TEXT NOT NULL,
                pitch_id INTEGER
            )"""
        )


def save_lane_portfolio(db_path: str, lane: str, portfolio: Portfolio, *, updated_at: str) -> None:
    init_lane_db(db_path)
    payload = json.dumps(asdict(portfolio), ensure_ascii=False)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO lane_portfolios (lane, data, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(lane) DO UPDATE SET data = excluded.data,"
            " updated_at = excluded.updated_at",
            (lane, payload, updated_at),
        )


def _portfolio_from_dict(raw: dict) -> Portfolio:
    positions = {
        ticker: Position(
            instrument=Instrument(**pos["instrument"]),
            shares=pos["shares"],
            cost_basis=pos["cost_basis"],
            opened_at=pos["opened_at"],
            last_price=pos.get("last_price"),
        )
        for ticker, pos in raw.get("positions", {}).items()
    }
    return Portfolio(
        initial_capital=raw["initial_capital"],
        cash=raw["cash"],
        positions=positions,
        benchmark_ticker=raw.get("benchmark_ticker", "SPY"),
        benchmark_shares=raw.get("benchmark_shares", 0.0),
    )


def load_lane_portfolio(db_path: str, lane: str) -> Portfolio | None:
    init_lane_db(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT data FROM lane_portfolios WHERE lane = ?", (lane,)
        ).fetchone()
    return _portfolio_from_dict(json.loads(row[0])) if row else None


def save_lane_valuation(
    db_path: str,
    lane: str,
    *,
    valued_on: str,
    total_value: float,
    total_return: float,
    benchmark_value: float,
    benchmark_return: float,
    open_positions: int,
) -> None:
    init_lane_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO lane_valuations"
            " (id, lane, valued_on, total_value, total_return, benchmark_value,"
            "  benchmark_return, open_positions)"
            " VALUES ((SELECT id FROM lane_valuations WHERE lane = ? AND valued_on = ?),"
            "         ?, ?, ?, ?, ?, ?, ?)",
            (lane, valued_on, lane, valued_on, total_value, total_return,
             benchmark_value, benchmark_return, open_positions),
        )


def load_lane_valuations(db_path: str, lane: str) -> list[dict]:
    init_lane_db(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT valued_on, total_value, total_return, benchmark_value,"
            " benchmark_return, open_positions FROM lane_valuations"
            " WHERE lane = ? ORDER BY valued_on",
            (lane,),
        ).fetchall()
    keys = ["valued_on", "total_value", "total_return", "benchmark_value",
            "benchmark_return", "open_positions"]
    return [dict(zip(keys, row)) for row in rows]


def record_trades(db_path: str, trades: list[TradeRecord]) -> None:
    if not trades:
        return
    init_lane_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO lane_trades (created_at, lane, ticker, side, shares,"
            " fill_price, cost, reason, pitch_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (t.created_at, t.lane, t.ticker, t.side, t.shares, t.fill_price,
                 t.cost, t.reason, t.pitch_id)
                for t in trades
            ],
        )


def load_lane_trades(db_path: str, lane: str, limit: int = 200) -> list[dict]:
    init_lane_db(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT {_TRADE_COLUMNS} FROM lane_trades WHERE lane = ?"
            " ORDER BY id DESC LIMIT ?",
            (lane, limit),
        ).fetchall()
    keys = [k.strip() for k in _TRADE_COLUMNS.split(",")]
    return [dict(zip(keys, row)) for row in rows]


def executed_pitch_ids(db_path: str, lane: str) -> set[int]:
    """Pitch ids lane `lane` has already executed a buy for (the executed marker)."""
    init_lane_db(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT pitch_id FROM lane_trades"
            " WHERE lane = ? AND side = 'buy' AND pitch_id IS NOT NULL",
            (lane,),
        ).fetchall()
    return {int(row[0]) for row in rows}
