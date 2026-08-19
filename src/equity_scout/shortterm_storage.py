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

LANES = ("swing", "session", "crypto", "gapfade", "ignition")
LANE_LABELS = {
    "swing": "Event-Swing",
    "session": "Intraday-Session",
    "crypto": "Crypto",
    "gapfade": "Gap-Fade",
    "ignition": "Katalysator-Sprung",
}


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
            CREATE TABLE IF NOT EXISTS st_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lane TEXT NOT NULL,
                ticker TEXT NOT NULL,
                side TEXT NOT NULL,
                signalled_at TEXT NOT NULL,
                expected_price REAL NOT NULL,
                actual_price REAL,
                qty REAL NOT NULL,
                order_id TEXT NOT NULL,
                UNIQUE (order_id)
            );
            CREATE TABLE IF NOT EXISTS st_rejections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lane TEXT NOT NULL,
                ticker TEXT NOT NULL,
                seen_at TEXT NOT NULL,
                reason TEXT NOT NULL,
                ref_price REAL,
                detail TEXT,
                resolved_at TEXT,
                sim_return REAL,
                sim_exit_reason TEXT,
                UNIQUE (lane, ticker, seen_at, reason)
            );
            """
        )
        # PRAGMA table_info + ALTER TABLE idiom as storage.py's init_db. Existing rows keep
        # NULL: before 2026-08-10 nothing read the venue's equity, and back-filling it from
        # the book would invent the very number the column exists to stop us inventing.
        cols = {row[1] for row in con.execute("PRAGMA table_info(st_valuations)")}
        if "broker_equity" not in cols:
            con.execute("ALTER TABLE st_valuations ADD COLUMN broker_equity REAL")


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


def _upsert_book(con, book: LaneBook, updated_at: str) -> None:
    con.execute(
        "INSERT INTO st_books (lane, data, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(lane) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
        (book.lane, _to_json(book), updated_at),
    )


def _insert_valuation(con, snap: LaneValuation) -> None:
    con.execute(
        "INSERT OR IGNORE INTO st_valuations "
        "(lane, created_at, equity, total_return, cash, open_positions, benchmark_return,"
        " broker_equity) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (snap.lane, snap.created_at, snap.equity, snap.total_return, snap.cash,
         snap.open_positions, snap.benchmark_return, snap.broker_equity),
    )


def _insert_trades(con, fills: list[TradeFill]) -> None:
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


def _upsert_state(con, lane: str, key: str, value: str) -> None:
    con.execute(
        "INSERT INTO st_state (lane, key, value) VALUES (?, ?, ?)"
        " ON CONFLICT(lane, key) DO UPDATE SET value = excluded.value",
        (lane, key, value),
    )


def save_book(db_path: str | Path, book: LaneBook, *, updated_at: str) -> None:
    init_shortterm_db(db_path)
    with db.connect(db_path) as con:
        _upsert_book(con, book, updated_at)


def persist_lane_step(
    db_path: str | Path,
    book: LaneBook,
    *,
    updated_at: str,
    trades: list[TradeFill] | tuple = (),
    valuation: LaneValuation | None = None,
    state: list[tuple[str, str]] | tuple = (),
) -> None:
    """Persist one lane advance atomically (v12 R4, review 2026-07-20): fills, valuation,
    engine markers and the book blob commit in ONE transaction — an interrupt mid-persist
    can no longer strand a fill outside the audit trail or replay it as a fresh signal.
    The book (the lane's source of truth) deliberately writes last."""
    init_shortterm_db(db_path)
    with db.connect(db_path) as con:
        if valuation is not None:
            _insert_valuation(con, valuation)
        _insert_trades(con, list(trades))
        for key, value in state:
            _upsert_state(con, book.lane, key, value)
        _upsert_book(con, book, updated_at)


def load_book(db_path: str | Path, lane: str) -> LaneBook | None:
    init_shortterm_db(db_path)
    with db.connect(db_path) as con:
        row = con.execute("SELECT data FROM st_books WHERE lane = ?", (lane,)).fetchone()
    return _from_json(row[0]) if row else None


def append_valuation(db_path: str | Path, snap: LaneValuation) -> None:
    init_shortterm_db(db_path)
    with db.connect(db_path) as con:
        _insert_valuation(con, snap)


def load_valuations(db_path: str | Path, lane: str) -> list[dict]:
    init_shortterm_db(db_path)
    with db.connect(db_path) as con:
        rows = con.execute(
            "SELECT created_at, equity, total_return, cash, open_positions, benchmark_return,"
            " broker_equity FROM st_valuations WHERE lane = ? ORDER BY created_at ASC",
            (lane,),
        ).fetchall()
    keys = ("created_at", "equity", "total_return", "cash", "open_positions",
            "benchmark_return", "broker_equity")
    return [dict(zip(keys, row)) for row in rows]


def append_trades(db_path: str | Path, fills: list[TradeFill]) -> None:
    init_shortterm_db(db_path)
    with db.connect(db_path) as con:
        _insert_trades(con, fills)


def load_trades(db_path: str | Path, lane: str, *, limit: int | None = 200) -> list[dict]:
    """`limit=None` returns ALL trades — required wherever all-time aggregates are
    computed (promotion gate); any finite cap would silently understate them one day."""
    init_shortterm_db(db_path)
    with db.connect(db_path) as con:
        rows = con.execute(
            "SELECT executed_at, ticker, side, qty, price, fees, reason, realized_pnl"
            " FROM st_trades WHERE lane = ? ORDER BY executed_at DESC, id DESC LIMIT ?",
            (lane, -1 if limit is None else limit),  # SQLite: LIMIT -1 = unbounded
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
        _upsert_state(con, lane, key, value)


def clear_lane_state(db_path: str | Path, lane: str, prefix: str) -> int:
    """Drop every marker of one lane whose key starts with `prefix`; returns how many.

    Needed when a lane changes TIMESCALE (crypto, 2026-08-10): the bar markers are
    "newest bar already judged" watermarks, and a 15-minute stamp is newer than the newest
    completed DAILY bar — left in place it silently blocks every decision until the clock
    catches up (measured: the first daily run judged nothing for that reason).
    """
    init_shortterm_db(db_path)
    with db.connect(db_path) as con:
        cursor = con.execute(
            "DELETE FROM st_state WHERE lane = ? AND key LIKE ?", (lane, f"{prefix}%")
        )
        return cursor.rowcount


_EXECUTION_KEYS = (
    "lane", "ticker", "side", "signalled_at",
    "expected_price", "actual_price", "qty", "order_id",
)


def record_execution(
    db_path: str | Path,
    *,
    lane: str,
    ticker: str,
    side: str,
    signalled_at: str,
    expected_price: float,
    actual_price: float | None,
    qty: float,
    order_id: str,
) -> None:
    """One broker execution against the price the signal expected. The difference is this
    project's first MEASURED slippage — every other cost number in the codebase is a
    modelled estimate. Keyed by order_id so a re-run never double-counts."""
    init_shortterm_db(db_path)
    with db.connect(db_path) as con:
        con.execute(
            """INSERT OR IGNORE INTO st_executions
               (lane, ticker, side, signalled_at, expected_price, actual_price, qty, order_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (lane, ticker, side, signalled_at, expected_price, actual_price, qty, order_id),
        )


_REJECTION_KEYS = (
    "id", "lane", "ticker", "seen_at", "reason", "ref_price", "detail",
    "resolved_at", "sim_return", "sim_exit_reason",
)


def record_rejections(db_path: str | Path, rejections: list[dict]) -> None:
    """The no-trade book: every examined-but-not-traded opportunity, with its reason.

    Keyed by (lane, ticker, seen_at, reason) so a lane re-run over the same inputs never
    double-counts — the same idempotency contract as st_trades."""
    if not rejections:
        return
    init_shortterm_db(db_path)
    with db.connect(db_path) as con:
        con.executemany(
            "INSERT OR IGNORE INTO st_rejections"
            " (lane, ticker, seen_at, reason, ref_price, detail)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [
                (r["lane"], r["ticker"], r["seen_at"], r["reason"],
                 r.get("ref_price"), r.get("detail"))
                for r in rejections
            ],
        )


def load_open_rejections(db_path: str | Path, lane: str | None = None) -> list[dict]:
    init_shortterm_db(db_path)
    where = "resolved_at IS NULL" + ("" if lane is None else " AND lane = ?")
    params: tuple = () if lane is None else (lane,)
    with db.connect(db_path) as con:
        rows = con.execute(
            f"SELECT {', '.join(_REJECTION_KEYS)} FROM st_rejections"
            f" WHERE {where} ORDER BY seen_at ASC, id ASC",
            params,
        ).fetchall()
    return [dict(zip(_REJECTION_KEYS, row)) for row in rows]


def resolve_rejections(db_path: str | Path, resolutions: list[dict]) -> None:
    """resolutions: [{id, resolved_at, sim_return, sim_exit_reason}] — one transaction,
    because a nightly run may settle hundreds of rows at once."""
    if not resolutions:
        return
    init_shortterm_db(db_path)
    with db.connect(db_path) as con:
        con.executemany(
            "UPDATE st_rejections SET resolved_at = ?, sim_return = ?, sim_exit_reason = ?"
            " WHERE id = ?",
            [
                (r["resolved_at"], r.get("sim_return"), r["sim_exit_reason"], r["id"])
                for r in resolutions
            ],
        )


def load_resolved_rejections(
    db_path: str | Path, lane: str, *, since: str | None = None
) -> list[dict]:
    init_shortterm_db(db_path)
    where = "lane = ? AND resolved_at IS NOT NULL"
    params: list = [lane]
    if since is not None:
        where += " AND resolved_at >= ?"
        params.append(since)
    with db.connect(db_path) as con:
        rows = con.execute(
            f"SELECT {', '.join(_REJECTION_KEYS)} FROM st_rejections"
            f" WHERE {where} ORDER BY seen_at ASC, id ASC",
            params,
        ).fetchall()
    return [dict(zip(_REJECTION_KEYS, row)) for row in rows]


def load_executions(db_path: str | Path, lane: str) -> list[dict]:
    init_shortterm_db(db_path)
    with db.connect(db_path) as con:
        rows = con.execute(
            f"SELECT {', '.join(_EXECUTION_KEYS)} FROM st_executions"
            " WHERE lane = ? ORDER BY signalled_at",
            (lane,),
        ).fetchall()
    return [dict(zip(_EXECUTION_KEYS, row)) for row in rows]


def slippage_summary(db_path: str | Path, lane: str = "session") -> dict | None:
    """Mean and worst realised slippage in basis points, or None while nothing filled.
    Positive means the fill was WORSE than the signal price for that side."""
    # `is not None`, not truthiness: a 0.0 fill price is a broker anomaly worth seeing,
    # while None is an order that simply has not filled yet.
    rows = [r for r in load_executions(db_path, lane) if r["actual_price"] is not None]
    if not rows:
        return None
    bps = []
    for row in rows:
        direction = 1.0 if row["side"] == "buy" else -1.0
        bps.append(
            direction * (row["actual_price"] - row["expected_price"])
            / row["expected_price"] * 10_000.0
        )
    return {"n": len(bps), "mean_bps": sum(bps) / len(bps), "worst_bps": max(bps)}
