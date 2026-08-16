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
from equity_scout.autotrader_engine import AutoDepotAccount, AutoDepotValuation, PendingOrders
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
                fill TEXT NOT NULL DEFAULT 'close',
                fill_price REAL,
                decided_as_of TEXT,
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
        _ensure_fill_columns(con)


def _ensure_fill_columns(con) -> None:
    """Idempotent migration (v13 O2): trade rows from before next-open fills keep their
    defaults — fill='close' (decided and filled on the same close), no fill price."""
    columns = {row[1] for row in con.execute("PRAGMA table_info(autotrader_trades)")}
    if "fill" not in columns:
        con.execute(
            "ALTER TABLE autotrader_trades ADD COLUMN fill TEXT NOT NULL DEFAULT 'close'"
        )
        con.execute("ALTER TABLE autotrader_trades ADD COLUMN fill_price REAL")
        con.execute("ALTER TABLE autotrader_trades ADD COLUMN decided_as_of TEXT")


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
        "last_marks": account.last_marks,
        "protection_regime": account.protection_regime,
        "pending_orders": (
            None if account.pending_orders is None else {
                "decided_as_of": account.pending_orders.decided_as_of,
                "targets": account.pending_orders.targets,
            }
        ),
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
        # missing key = a blob persisted before v13 R2 — no marks were ever recorded, so it
        # loads as empty and the next advance falls back to the pre-mark window logic once
        # per held position (see advance_depot's "mark init for N positions" log).
        last_marks={t: tuple(v) for t, v in d.get("last_marks", {}).items()},
        # missing key = a blob from before v16's redistributing cap. It loads as None and the
        # next advance stamps it, which is exactly right: that advance IS the break.
        protection_regime=d.get("protection_regime"),
        # missing key = a pre-v13-O2 blob: nothing was pending under the old same-close
        # fill convention — the first advance under the new code only decides, fills start
        # one advance later.
        pending_orders=(
            PendingOrders(
                decided_as_of=d["pending_orders"]["decided_as_of"],
                targets=d["pending_orders"]["targets"],
            )
            if d.get("pending_orders") else None
        ),
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
        "(created_at, ticker, delta_weight, notional, cost, fill, fill_price, decided_as_of)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                t.created_at, t.ticker, t.delta_weight, t.notional, t.cost,
                t.fill, t.fill_price, t.decided_as_of,
            )
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
            "SELECT created_at, ticker, delta_weight, notional, cost, fill, fill_price,"
            " decided_as_of FROM autotrader_trades"
            " ORDER BY created_at DESC, ticker ASC LIMIT ?",
            (limit,),
        ).fetchall()
    keys = (
        "created_at", "ticker", "delta_weight", "notional", "cost", "fill", "fill_price",
        "decided_as_of",
    )
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
    """Replace the month's sleeve allocation (weight + Sharpe estimate + mode per sleeve).

    The rows for a month are a COMPLETE picture of that month's allocation, so a sleeve
    that is no longer allocated has to lose its row. An upsert alone can only rewrite the
    names it still sees, and a dropped sleeve keeps its last weight forever — live on
    2026-08-16 the ML Long Bot still held 12.5 % of August after losing its champion, so
    the cockpit listed a sleeve that holds nothing and the weights summed to 112.5 %.

    An EMPTY allocation is not such a picture — it says "nothing to allocate", which is
    what a failed or skipped advance also looks like, so it deletes nothing.
    """
    init_autotrader_db(db_path)
    if not allocation.weights:
        return
    with db.connect(db_path) as con:
        names = list(allocation.weights)
        con.execute(
            "DELETE FROM autotrader_sleeve_weights WHERE month = ?"
            f" AND strategy_name NOT IN ({','.join('?' * len(names))})",
            (month, *names),
        )
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
