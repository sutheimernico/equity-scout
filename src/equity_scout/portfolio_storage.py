"""SQLite persistence for the paper portfolio (single current state) + its valuation history."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from equity_scout.models import Instrument
from equity_scout.portfolio import Portfolio, Position, Valuation


def init_portfolio_db(db_path: str | Path) -> None:
    with sqlite3.connect(db_path) as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS portfolio (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS valuations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                total_value REAL NOT NULL,
                total_return REAL NOT NULL,
                benchmark_return REAL NOT NULL,
                open_positions INTEGER NOT NULL
            );
            """
        )


def _to_json(portfolio: Portfolio) -> str:
    return json.dumps({
        "initial_capital": portfolio.initial_capital,
        "cash": portfolio.cash,
        "benchmark_ticker": portfolio.benchmark_ticker,
        "benchmark_shares": portfolio.benchmark_shares,
        "positions": {ticker: asdict(pos) for ticker, pos in portfolio.positions.items()},
    })


def _from_json(blob: str) -> Portfolio:
    data = json.loads(blob)
    positions = {
        ticker: Position(
            instrument=Instrument(**pos["instrument"]),
            shares=pos["shares"],
            cost_basis=pos["cost_basis"],
            opened_at=pos["opened_at"],
            last_price=pos.get("last_price"),
        )
        for ticker, pos in data["positions"].items()
    }
    return Portfolio(
        initial_capital=data["initial_capital"],
        cash=data["cash"],
        positions=positions,
        benchmark_ticker=data["benchmark_ticker"],
        benchmark_shares=data["benchmark_shares"],
    )


def save_portfolio(db_path: str | Path, portfolio: Portfolio) -> None:
    with sqlite3.connect(db_path) as con:
        con.execute(
            "INSERT INTO portfolio (id, data) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
            (_to_json(portfolio),),
        )


def load_portfolio(db_path: str | Path) -> Portfolio | None:
    with sqlite3.connect(db_path) as con:
        try:
            row = con.execute("SELECT data FROM portfolio WHERE id = 1").fetchone()
        except sqlite3.OperationalError:
            return None  # portfolio tables not created yet
    return _from_json(row[0]) if row else None


def append_valuation(db_path: str | Path, created_at: str, valuation: Valuation) -> None:
    with sqlite3.connect(db_path) as con:
        con.execute(
            "INSERT INTO valuations "
            "(created_at, total_value, total_return, benchmark_return, open_positions) "
            "VALUES (?, ?, ?, ?, ?)",
            (created_at, valuation.total_value, valuation.total_return,
             valuation.benchmark_return, valuation.open_positions),
        )


def latest_valuation_at(db_path: str | Path) -> str | None:
    """``created_at`` of the most recent recorded valuation, or None if none exist yet.

    Used to derive the dividend accrual span (days since the last run). Ordered by id DESC so it is
    correct regardless of row count — unlike ``load_valuations``, which returns the OLDEST N rows.
    """
    with sqlite3.connect(db_path) as con:
        try:
            row = con.execute(
                "SELECT created_at FROM valuations ORDER BY id DESC LIMIT 1"
            ).fetchone()
        except sqlite3.OperationalError:
            return None  # valuations table not created yet
    return row[0] if row else None


def load_valuations(db_path: str | Path, limit: int = 100) -> list[dict]:
    with sqlite3.connect(db_path) as con:
        try:
            rows = con.execute(
                "SELECT created_at, total_value, total_return, benchmark_return, open_positions "
                "FROM valuations ORDER BY id ASC LIMIT ?",
                (limit,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []  # valuations table not created yet
    return [
        {"created_at": c, "total_value": tv, "total_return": tr,
         "benchmark_return": br, "open_positions": op}
        for c, tv, tr, br, op in rows
    ]
