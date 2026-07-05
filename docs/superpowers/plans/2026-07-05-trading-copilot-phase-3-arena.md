# Trading Copilot — Phase 3: Two-Lane Execution & Arena Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two paper lanes trade side by side — lane "nico" executes only Nico's approved buy pitches, lane "autopilot" buys autonomously above the score threshold — with identical sizing, fill and exit rules, a persisted trade ledger, daily valuations vs SPY, and a `GET /api/arena` surface.

**Architecture:** Reuse `portfolio.py`'s proven mechanics (`Position`/`Portfolio`/`Valuation`/`new_portfolio`/`mark_to_market` are imported, NOT copied). New `lanes.py` holds the lane-specific engine as pure functions: rule-based exits (profit target / stop loss / max holding period) and buy execution from `BuyOrder`s, both emitting structured `TradeRecord`s — the first persisted trade ledger in the repo (fairness audit trail). `lane_storage.py` persists lane portfolios (JSON snapshot), day-keyed valuations (idempotent per lane+day) and the append-only trade log. `scripts/run_lanes.py` advances both lanes in one run against ONE shared price fetch (fairness by construction: same prices, same fill model, same run). Lane A's buy queue = decided "buy" pitches with no executed trade yet (the `lane_trades.pitch_id` link IS the Phase-2 "executed marker"); lane B's = latest watchlist entries in zone above threshold. Everything runs without Alpaca — the broker seam stays a `fetch_price` callable; Alpaca live paper wiring is a later Needs-Nico step.

**Tech Stack:** Python 3.11 stdlib + existing deps. **No new dependencies.**

**Spec:** `docs/superpowers/specs/2026-07-04-trading-copilot-design.md` (§7)
**Builds on:** Phase 1 (`radar_storage.load_latest_watchlist` incl. top-level `watchlist_id`), Phase 2 (`inbox_storage` pitches with `status`/`decided_at`, `get_pitch`)

**Conventions that bind every task** (unchanged): English code/docstrings, German user-facing strings with correct umlauts; pure functions + DI seams; `now`/`created_at` injected (datetime.now only in `main()`); imports top-of-file; gate `.venv/bin/python -m pytest && .venv/bin/ruff check .` before EVERY commit (baseline 284 passed — report true totals, never stack `-q`); strict TDD; one commit per task; include plan-doc checkbox edits in commits.

**Fairness invariant (the phase's core promise):** both lanes are advanced in the same run, from the same `prices` dict, with the same `position_fraction`, `fee_rate`, `slippage_bps` and `ExitRules`. Any change that lets the lanes see different prices or rules breaks the comparison and must not pass review.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/equity_scout/lanes.py` | create | lane engine: `ExitRules`, `BuyOrder`, `TradeRecord`, `apply_exits`, `execute_buys`, candidate selection helpers |
| `src/equity_scout/lane_storage.py` | create | SQLite: lane portfolios, day-keyed valuations, append-only `lane_trades` |
| `scripts/run_lanes.py` | create | CLI: advance both lanes (exits → buys → valuation) against one shared price fetch |
| `src/equity_scout/api.py` | modify | `GET /api/arena` |
| `tests/test_lanes.py` | create | exits, buys, fairness invariants |
| `tests/test_lane_storage.py` | create | round-trips, idempotency, append-only |
| `tests/test_run_lanes.py` | create | CLI end-to-end with fakes |
| `tests/test_api.py` | modify | arena endpoint |

Lane names are the string constants `"nico"` and `"autopilot"` (defined once in `lanes.py` as `LANE_NICO` / `LANE_AUTOPILOT`).

---

### Task 1: `TradeRecord`, `BuyOrder`, `ExitRules` + exit engine

**Files:**
- Create: `src/equity_scout/lanes.py`
- Test: `tests/test_lanes.py`

- [x] **Step 1: Write the failing tests**

```python
"""Lane engine tests — pure functions, synthetic portfolios, no network."""
from __future__ import annotations

from equity_scout.lanes import (
    LANE_AUTOPILOT,
    LANE_NICO,
    ExitRules,
    TradeRecord,
    apply_exits,
)
from equity_scout.models import Instrument
from equity_scout.portfolio import Portfolio, Position

NOW = "2026-07-05T14:00:00+00:00"
RULES = ExitRules()  # defaults: profit_target=0.20, stop_loss=0.15, max_holding_days=180


def _instrument(ticker: str) -> Instrument:
    return Instrument(ticker, f"{ticker} Corp", "", "", "", "")


def _portfolio(**positions: Position) -> Portfolio:
    return Portfolio(initial_capital=10_000.0, cash=5_000.0, positions=dict(positions))


def _position(ticker: str, cost: float, opened_at: str = "2026-06-01T14:00:00+00:00") -> Position:
    return Position(_instrument(ticker), shares=10.0, cost_basis=cost, opened_at=opened_at)


def test_exit_on_profit_target():
    portfolio = _portfolio(WIN=_position("WIN", cost=100.0))
    updated, trades = apply_exits(
        portfolio, {"WIN": 121.0}, now=NOW, lane=LANE_NICO, rules=RULES
    )
    assert "WIN" not in updated.positions
    assert len(trades) == 1
    trade = trades[0]
    assert isinstance(trade, TradeRecord)
    assert (trade.lane, trade.ticker, trade.side) == (LANE_NICO, "WIN", "sell")
    assert trade.fill_price < 121.0  # sells into slippage
    assert "Kursziel" in trade.reason
    assert updated.cash > portfolio.cash


def test_exit_on_stop_loss():
    portfolio = _portfolio(LOSE=_position("LOSE", cost=100.0))
    updated, trades = apply_exits(
        portfolio, {"LOSE": 84.0}, now=NOW, lane=LANE_AUTOPILOT, rules=RULES
    )
    assert "LOSE" not in updated.positions
    assert "Stop-Loss" in trades[0].reason


def test_exit_on_max_holding_days():
    old = _position("OLD", cost=100.0, opened_at="2025-12-01T14:00:00+00:00")
    updated, trades = apply_exits(
        _portfolio(OLD=old), {"OLD": 101.0}, now=NOW, lane=LANE_NICO, rules=RULES
    )
    assert "OLD" not in updated.positions
    assert "Haltedauer" in trades[0].reason


def test_holds_inside_all_rules_and_without_price():
    keep = _position("KEEP", cost=100.0)
    noprice = _position("DARK", cost=100.0)
    portfolio = _portfolio(KEEP=keep, DARK=noprice)
    updated, trades = apply_exits(
        portfolio, {"KEEP": 105.0}, now=NOW, lane=LANE_NICO, rules=RULES
    )
    assert set(updated.positions) == {"KEEP", "DARK"}
    assert trades == []
    assert updated.positions["KEEP"].last_price == 105.0  # refreshed for the dashboard


def test_exit_boundary_is_exclusive():
    at_target = _portfolio(EDGE=_position("EDGE", cost=100.0))
    updated, trades = apply_exits(
        at_target, {"EDGE": 120.0}, now=NOW, lane=LANE_NICO, rules=RULES
    )
    assert "EDGE" in updated.positions  # exactly +20% is NOT yet an exit (> not >=)
    assert trades == []
```

- [x] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_lanes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'equity_scout.lanes'`.

- [x] **Step 3: Write the implementation**

```python
"""Two-lane paper execution engine.

Lane "nico" trades only pitches Nico approved; lane "autopilot" trades the score
autonomously. FAIRNESS INVARIANT: both lanes are advanced in the same run with the
same prices dict, the same sizing/fee/slippage parameters and the same ExitRules —
the comparison is only honest if nothing here diverges per lane.

Reuses portfolio.py's Position/Portfolio mechanics (imported, not copied). Exits are
deliberately simple v1 rules (spec §7): profit target, stop loss, max holding period.
Every action emits a structured TradeRecord — the persisted audit trail that also
serves as the "pitch executed" marker via pitch_id.

PAPER ONLY. No real orders, ever.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from equity_scout.portfolio import Portfolio, Position

LANE_NICO = "nico"
LANE_AUTOPILOT = "autopilot"

DEFAULT_POSITION_FRACTION = 0.05
DEFAULT_FEE_RATE = 0.001
DEFAULT_SLIPPAGE_BPS = 5.0


@dataclass(frozen=True)
class ExitRules:
    """v1 exit rules (spec §7): deliberately simple and identical for both lanes."""

    profit_target: float = 0.20  # sell when price > cost_basis * (1 + target)
    stop_loss: float = 0.15  # sell when price < cost_basis * (1 - stop)
    max_holding_days: int = 180  # sell when held longer than this


@dataclass(frozen=True)
class BuyOrder:
    ticker: str
    name: str
    score: float
    reason: str  # German, shown in the trade log
    pitch_id: int | None  # set for lane "nico" (links back to the decided pitch)


@dataclass(frozen=True)
class TradeRecord:
    created_at: str
    lane: str
    ticker: str
    side: str  # "buy" | "sell"
    shares: float
    fill_price: float
    cost: float  # cash delta magnitude incl. fees (buy: spent; sell: proceeds)
    reason: str  # German
    pitch_id: int | None = None


def _held_days(opened_at: str, now: str) -> int:
    return (datetime.fromisoformat(now) - datetime.fromisoformat(opened_at)).days


def _exit_reason(position: Position, price: float, now: str, rules: ExitRules) -> str | None:
    if price > position.cost_basis * (1.0 + rules.profit_target):
        return f"Kursziel erreicht (+{rules.profit_target * 100:.0f} %)"
    if price < position.cost_basis * (1.0 - rules.stop_loss):
        return f"Stop-Loss ausgelöst (−{rules.stop_loss * 100:.0f} %)"
    if _held_days(position.opened_at, now) > rules.max_holding_days:
        return f"Maximale Haltedauer überschritten ({rules.max_holding_days} Tage)"
    return None


def apply_exits(
    portfolio: Portfolio,
    prices: dict[str, float],
    *,
    now: str,
    lane: str,
    rules: ExitRules,
    fee_rate: float = DEFAULT_FEE_RATE,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
) -> tuple[Portfolio, list[TradeRecord]]:
    """Sell every position that violates a rule; refresh last_price on the rest.

    A position without a current price is held untouched (cannot value a sale) —
    same stance as portfolio.advance.
    """
    slip = slippage_bps / 10_000.0
    cash = portfolio.cash
    positions = dict(portfolio.positions)
    trades: list[TradeRecord] = []
    for ticker in list(positions):
        price = prices.get(ticker)
        if price is None or price <= 0:
            continue
        reason = _exit_reason(positions[ticker], price, now, rules)
        if reason is None:
            positions[ticker] = replace(positions[ticker], last_price=price)
            continue
        fill = price * (1 - slip)
        proceeds = positions[ticker].shares * fill * (1 - fee_rate)
        cash += proceeds
        trades.append(
            TradeRecord(
                created_at=now, lane=lane, ticker=ticker, side="sell",
                shares=positions[ticker].shares, fill_price=round(fill, 4),
                cost=round(proceeds, 2), reason=reason,
            )
        )
        del positions[ticker]
    return replace(portfolio, cash=cash, positions=positions), trades
```

> **Deviation:** dropped the top-of-file `from equity_scout.models import Instrument` from
> Task 1's `lanes.py` — `apply_exits` doesn't use `Instrument` yet, only `execute_buys` does
> (Task 2), and ruff's F401 fails the required gate on an unused import. Re-added in Task 2
> when `execute_buys` is appended.

- [x] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_lanes.py -v` — expected: all PASS.

- [x] **Step 5: Gate and commit**

```bash
.venv/bin/python -m pytest && .venv/bin/ruff check .
git add src/equity_scout/lanes.py tests/test_lanes.py
git commit -m "feat: add lane exit engine with structured trade records"
```

---

### Task 2: Buy execution + candidate selection

**Files:**
- Modify: `src/equity_scout/lanes.py`
- Test: `tests/test_lanes.py`

- [x] **Step 1: Write the failing tests** (append)

```python
from equity_scout.lanes import BuyOrder, execute_buys, lane_b_orders
from equity_scout.portfolio import new_portfolio


def _order(ticker: str, pitch_id: int | None = None, score: float = 0.6) -> BuyOrder:
    return BuyOrder(ticker=ticker, name=f"{ticker} Corp", score=score,
                    reason="Testgrund", pitch_id=pitch_id)


def test_execute_buys_fills_with_slippage_and_links_pitch():
    portfolio = new_portfolio(initial_capital=10_000.0)
    updated, trades = execute_buys(
        portfolio, [_order("NEW", pitch_id=7)], {"NEW": 100.0}, now=NOW, lane=LANE_NICO
    )
    position = updated.positions["NEW"]
    assert position.cost_basis > 100.0  # buys fill above the quote
    assert abs(position.shares * position.cost_basis - 500.0) < 0.01  # 5% of capital
    assert updated.cash < 10_000.0 - 500.0  # fees on top
    trade = trades[0]
    assert (trade.side, trade.pitch_id) == ("buy", 7)


def test_execute_buys_skips_held_unpriced_and_underfunded():
    portfolio = new_portfolio(initial_capital=10_000.0)
    portfolio, _ = execute_buys(
        portfolio, [_order("HELD")], {"HELD": 100.0}, now=NOW, lane=LANE_NICO
    )
    poor = replace(portfolio, cash=100.0)
    updated, trades = execute_buys(
        poor,
        [_order("HELD"), _order("DARK"), _order("POOR")],
        {"HELD": 100.0, "POOR": 50.0},
        now=NOW,
        lane=LANE_NICO,
    )
    assert set(updated.positions) == {"HELD"}
    assert trades == []


def test_lane_b_orders_from_watchlist():
    watchlist = {
        "entries": [
            {"ticker": "YES", "name": "Yes Corp", "in_zone": True, "composite": 0.6,
             "zone_note": "In der Zone."},
            {"ticker": "HELD", "name": "Held Corp", "in_zone": True, "composite": 0.9,
             "zone_note": "In der Zone."},
            {"ticker": "LOW", "name": "Low Corp", "in_zone": True, "composite": 0.2,
             "zone_note": "In der Zone."},
            {"ticker": "OUT", "name": "Out Corp", "in_zone": False, "composite": 0.9,
             "zone_note": "Drüber."},
        ]
    }
    orders = lane_b_orders(watchlist, held_tickers={"HELD"}, threshold=0.45)
    assert [o.ticker for o in orders] == ["YES"]
    assert orders[0].pitch_id is None
    assert orders[0].score == 0.6
```

Also import `replace` at the top of the test file (`from dataclasses import replace`).

- [x] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_lanes.py -v` — expected: ImportError on `execute_buys`.

- [x] **Step 3: Write the implementation** (append to `lanes.py`)

```python
def execute_buys(
    portfolio: Portfolio,
    orders: list[BuyOrder],
    prices: dict[str, float],
    *,
    now: str,
    lane: str,
    position_fraction: float = DEFAULT_POSITION_FRACTION,
    fee_rate: float = DEFAULT_FEE_RATE,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
) -> tuple[Portfolio, list[TradeRecord]]:
    """Open a fixed-fraction position per order. Skips held/unpriced/underfunded.

    Same fill model as portfolio.advance: buys fill above the quote by slippage,
    fees on top of the position value. The skipped-order cases are silent by design —
    a pending pitch stays pending and is retried on the next run.
    """
    slip = slippage_bps / 10_000.0
    cash = portfolio.cash
    positions = dict(portfolio.positions)
    trades: list[TradeRecord] = []
    target_value = portfolio.initial_capital * position_fraction
    for order in orders:
        price = prices.get(order.ticker)
        if order.ticker in positions or not price or price <= 0:
            continue
        total_cost = target_value * (1 + fee_rate)
        if cash < total_cost:
            continue
        fill = price * (1 + slip)
        shares = target_value / fill
        cash -= total_cost
        instrument = Instrument(order.ticker, order.name, "", "", "", "")
        positions[order.ticker] = Position(instrument, shares, fill, now, last_price=price)
        trades.append(
            TradeRecord(
                created_at=now, lane=lane, ticker=order.ticker, side="buy",
                shares=round(shares, 4), fill_price=round(fill, 4),
                cost=round(total_cost, 2), reason=order.reason, pitch_id=order.pitch_id,
            )
        )
    return replace(portfolio, cash=cash, positions=positions), trades


def lane_b_orders(
    watchlist: dict, *, held_tickers: set[str], threshold: float
) -> list[BuyOrder]:
    """Autopilot candidates: in-zone watchlist entries at/above threshold, not held."""
    return [
        BuyOrder(
            ticker=entry["ticker"],
            name=entry.get("name", entry["ticker"]),
            score=entry["composite"],
            reason=f"Autopilot: Score {round(entry['composite'] * 100)}/100 — {entry['zone_note']}",
            pitch_id=None,
        )
        for entry in watchlist.get("entries", [])
        if entry["in_zone"] and entry["composite"] >= threshold
        and entry["ticker"] not in held_tickers
    ]
```

> **Deviation:** re-added `from equity_scout.models import Instrument` to `lanes.py`'s
> top-of-file imports here (removed in Task 1 — see that task's deviation note) since
> `execute_buys` now constructs `Instrument` for new positions.

- [x] **Step 4: Run tests to verify they pass** — `.venv/bin/python -m pytest tests/test_lanes.py -v`

- [x] **Step 5: Gate and commit**

```bash
.venv/bin/python -m pytest && .venv/bin/ruff check .
git add src/equity_scout/lanes.py tests/test_lanes.py
git commit -m "feat: add lane buy execution and autopilot candidate selection"
```

---

### Task 3: Lane persistence (`lane_storage.py`)

**Files:**
- Create: `src/equity_scout/lane_storage.py`
- Test: `tests/test_lane_storage.py`

Follows the repo storage idiom (raw sqlite3, idempotent init, JSON snapshot). Three tables:
`lane_portfolios(lane TEXT PRIMARY KEY, data TEXT, updated_at TEXT)`,
`lane_valuations(id PK, lane, valued_on TEXT, total_value REAL, total_return REAL, benchmark_value REAL, benchmark_return REAL, open_positions INTEGER, UNIQUE(lane, valued_on))` — `valued_on` is a DATE string (YYYY-MM-DD) so re-running the CLI on the same day is idempotent (INSERT OR REPLACE: the later run wins the day),
`lane_trades(id PK, created_at, lane, ticker, side, shares REAL, fill_price REAL, cost REAL, reason TEXT, pitch_id INTEGER)` — append-only, never UPDATE/DELETE.

- [x] **Step 1: Write the failing tests**

```python
"""Lane persistence: portfolio round-trip, day-idempotent valuations, append-only trades."""
from __future__ import annotations

import sqlite3

from equity_scout.lane_storage import (
    executed_pitch_ids,
    init_lane_db,
    load_lane_portfolio,
    load_lane_trades,
    load_lane_valuations,
    record_trades,
    save_lane_portfolio,
    save_lane_valuation,
)
from equity_scout.lanes import LANE_NICO, TradeRecord
from equity_scout.models import Instrument
from equity_scout.portfolio import Portfolio, Position, new_portfolio

NOW = "2026-07-05T14:00:00+00:00"


def _trade(ticker: str = "EXE", pitch_id: int | None = 7) -> TradeRecord:
    return TradeRecord(
        created_at=NOW, lane=LANE_NICO, ticker=ticker, side="buy", shares=5.5,
        fill_price=90.77, cost=500.5, reason="Grund", pitch_id=pitch_id,
    )


def test_lane_portfolio_round_trip_reconstructs_dataclasses(tmp_path):
    db = str(tmp_path / "lanes.db")
    portfolio = Portfolio(
        initial_capital=10_000.0,
        cash=9_499.5,
        positions={
            "EXE": Position(
                Instrument("EXE", "Expand Energy", "", "", "", ""),
                shares=5.5, cost_basis=90.77, opened_at=NOW, last_price=91.0,
            )
        },
        benchmark_shares=16.0,
    )
    save_lane_portfolio(db, LANE_NICO, portfolio, updated_at=NOW)
    loaded = load_lane_portfolio(db, LANE_NICO)
    assert loaded == portfolio  # full dataclass equality incl. nested Position/Instrument


def test_load_lane_portfolio_none_when_missing(tmp_path):
    db = str(tmp_path / "lanes.db")
    init_lane_db(db)
    assert load_lane_portfolio(db, LANE_NICO) is None


def test_lane_valuation_idempotent_per_day(tmp_path):
    db = str(tmp_path / "lanes.db")
    save_lane_valuation(
        db, LANE_NICO, valued_on="2026-07-05", total_value=10_100.0, total_return=0.01,
        benchmark_value=10_050.0, benchmark_return=0.005, open_positions=1,
    )
    save_lane_valuation(  # same day again — later run wins, no second row
        db, LANE_NICO, valued_on="2026-07-05", total_value=10_200.0, total_return=0.02,
        benchmark_value=10_050.0, benchmark_return=0.005, open_positions=1,
    )
    rows = load_lane_valuations(db, LANE_NICO)
    assert len(rows) == 1
    assert rows[0]["total_value"] == 10_200.0


def test_trades_append_only_and_executed_pitch_ids(tmp_path):
    db = str(tmp_path / "lanes.db")
    record_trades(db, [_trade(pitch_id=7), _trade(ticker="ABC", pitch_id=None)])
    record_trades(db, [_trade(ticker="DEF", pitch_id=9)])
    trades = load_lane_trades(db, LANE_NICO)
    assert [t["ticker"] for t in trades] == ["DEF", "ABC", "EXE"]  # newest first
    assert executed_pitch_ids(db, LANE_NICO) == {7, 9}
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM lane_trades").fetchone()[0] == 3
```

- [x] **Step 2: Run tests to verify they fail** — expected `ModuleNotFoundError`.

- [x] **Step 3: Write the implementation**

```python
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
```

- [x] **Step 4: Run tests to verify they pass** — `.venv/bin/python -m pytest tests/test_lane_storage.py -v`

- [x] **Step 5: Gate and commit**

```bash
.venv/bin/python -m pytest && .venv/bin/ruff check .
git add src/equity_scout/lane_storage.py tests/test_lane_storage.py
git commit -m "feat: persist lane portfolios, day-keyed valuations, and trade ledger"
```

---

### Task 4: Arena runner CLI (`scripts/run_lanes.py`)

**Files:**
- Create: `scripts/run_lanes.py`
- Test: `tests/test_run_lanes.py`

The CLI advances both lanes in one run. Sequence per run (shared `now`, shared `prices`):
1. Load or create both lane portfolios (`new_portfolio(initial_capital=10_000.0)` each).
2. Determine lane A's buy queue: pitches with `status == "buy"` whose id is NOT in `executed_pitch_ids(db, LANE_NICO)` → `BuyOrder(pitch_id=..., score=composite, reason="Freigegeben am {decided_at[:10]}: Pitch #{id}")` (read pitches via `inbox_storage.load_pitches(db, limit=1000)`).
3. Determine lane B's buy queue via `lane_b_orders(watchlist, held_tickers=..., threshold=...)` from `radar_storage.load_latest_watchlist`.
4. Fetch prices ONCE for the union: all open positions of both lanes + both buy queues + "SPY", via an injectable `fetch_price: Callable[[str], float | None]` (default: lazy yfinance spot quote — mirror how `entry.fetch_entry_history` isolates yfinance; a helper `_fetch_spot(ticker)` using `yf.Ticker(ticker).history(period="1d")` last close with `with_retry`, returning None on failure).
5. Per lane, identically: `apply_exits` → `execute_buys` → `mark_to_market(portfolio, prices, benchmark_price=prices.get("SPY"))` → `save_lane_portfolio` + `save_lane_valuation(valued_on=now[:10], ...)` + `record_trades`.
6. Print a German per-lane summary line (`Lane nico: 2 Käufe, 1 Verkauf, Wert 10.234,00 (+2,3 %) vs SPY +1,1 %`) — plain prints, format free.

`run_lanes(db_path, *, now, fetch_price, threshold, rules, position_fraction, fee_rate, slippage_bps) -> dict` (summary per lane: counts + valuation) so tests never touch argparse; `main()` is the thin argparse shell (`--db`, `--threshold` default 0.45, `--position-fraction`, `--profit-target`, `--stop-loss`, `--max-holding-days`, all defaulting to the module constants).

- [x] **Step 1: Write the failing tests** — cover: (a) end-to-end with fakes: seed a watchlist (via `radar_storage.save_watchlist`) + one decided buy pitch (via `inbox_storage.create_pitch` + `decide_pitch`) + fake `fetch_price` returning fixed prices; assert lane nico bought exactly the pitch ticker (trade row with pitch_id), lane autopilot bought the watchlist candidate, both lanes have a valuation row for `now[:10]`, both portfolios persisted; (b) idempotency: second `run_lanes` same day → no duplicate buys (pitch now executed, candidate now held), still one valuation row per lane (updated); (c) missing watchlist AND no pitches → run succeeds with zero trades (no crash); (d) `main()` happy path with monkeypatched `scripts.run_lanes._fetch_spot` (no network) + exit 0. Write complete test code following `tests/test_notify.py`'s established patterns (seeded DB, monkeypatch, capsys).

- [x] **Step 2: Run tests to verify they fail** — expected import error.

- [x] **Step 3: Write the implementation** — complete `scripts/run_lanes.py` per the sequence above. Fairness in code: ONE `now`, ONE `prices` dict, ONE parameter set, both lanes advanced by the same loop body (`for lane, portfolio, orders in ...`). No network at import time; yfinance behind the lazy `_fetch_spot`.

> **Deviations (Task 4):**
> 1. **Fairness dataclass:** the shared parameter set is a frozen `LaneParams(rules, position_fraction, fee_rate, slippage_bps)` built once in `run_lanes`; the loop `for lane, portfolio, orders in ((LANE_NICO, nico, lane_a), (LANE_AUTOPILOT, autopilot, lane_b))` advances both lanes with ONE `now` and ONE `prices` dict.
> 2. **Benchmark init (added):** the plan sequence (`apply_exits → execute_buys → mark_to_market`) never initialises `benchmark_shares`, so "vs SPY" would be a flat line forever. `run_lanes` now buys-and-holds SPY from day one (`benchmark_shares = initial_capital / spy` when 0.0, mirroring `portfolio.advance`) before `mark_to_market`, identically for both lanes; it persists via the JSON snapshot.
> 3. **Pitch has no `name` column:** `inbox_storage.load_pitches` rows carry no name, so lane A's `BuyOrder.name` falls back to the ticker (`pitch.get("name", pitch["ticker"])`).
> 4. **argparse scope:** per the plan's stated arg list, `main()` exposes `--db/--threshold/--position-fraction/--profit-target/--stop-loss/--max-holding-days` only; `fee_rate`/`slippage_bps` keep `LaneParams` defaults (no flags).
> 5. **Unpriced tickers dropped** from `prices` (not stored as `None`) so `mark_to_market`'s `prices.get(t, cost_basis)` fallback cannot return `None` and crash.

- [x] **Step 4: Run tests to verify they pass** — `.venv/bin/python -m pytest tests/test_run_lanes.py -v`

- [x] **Step 5: Gate and commit**

```bash
.venv/bin/python -m pytest && .venv/bin/ruff check .
git add scripts/run_lanes.py tests/test_run_lanes.py
git commit -m "feat: add arena runner advancing both lanes with shared prices"
```

---

### Task 5: `GET /api/arena`

**Files:**
- Modify: `src/equity_scout/api.py`
- Test: `tests/test_api.py` (append, existing style)

Response shape (mirrors `/api/forward`'s conventions, plus positions/trades like `/api/portfolio`):

```json
{
  "available": true,
  "lanes": [
    {
      "lane": "nico",
      "initial_capital": 10000.0,
      "total_value": 10234.0,
      "total_return": 0.0234,
      "benchmark_return": 0.011,
      "open_positions": [ {"ticker": "...", "name": "...", "shares": 5.5, "cost_basis": 90.77, "last_price": 91.0, "opened_at": "..."} ],
      "equity_curve": [["2026-07-05", 10234.0, 10110.0]],
      "trades": [ {"created_at": "...", "ticker": "...", "side": "buy", "shares": 5.5, "fill_price": 90.77, "cost": 500.5, "reason": "...", "pitch_id": 7} ]
    }
  ],
  "disclaimer": "..."
}
```

`available: false` + empty lanes when neither lane portfolio exists. Route as closure in `create_app`, before the StaticFiles mount, reading via `lane_storage` (`load_lane_portfolio`, `load_lane_valuations`, `load_lane_trades` with limit 50). Latest valuation supplies `total_value`/`total_return`/`benchmark_return`; equity_curve = `[[valued_on, total_value, benchmark_value], ...]`.

- [ ] **Step 1: Write the failing test** — empty DB → `{"available": false, "lanes": [], "disclaimer": ...}`; seeded lanes (save portfolio + two valuations + one trade per lane) → both lanes present with correct curve length, positions and trades shapes, disclaimer present.
- [ ] **Step 2: Run to verify it fails** (404).
- [ ] **Step 3: Implement the route.**
- [ ] **Step 4: Run tests** — all PASS.
- [ ] **Step 5: Gate and commit**

```bash
.venv/bin/python -m pytest && .venv/bin/ruff check .
git add src/equity_scout/api.py tests/test_api.py
git commit -m "feat: expose two-lane arena via GET /api/arena"
```

---

### Task 6: Phase gate

- [ ] **Step 1: Full gate** — `.venv/bin/python -m pytest && .venv/bin/ruff check .` (baseline 284 + new).
- [ ] **Step 2: Live smoke** — `python scripts/run_lanes.py --db equity_scout.db` (uses network for spot quotes; there are decided buy pitches only if Nico tapped one — zero lane-A buys is a VALID outcome; lane B should buy in-zone candidates unless already run today). Record observed output honestly. Then `curl`/TestClient `GET /api/arena` and record the shape.
- [ ] **Step 3: README** — extend the copilot README section with `run_lanes.py` and `/api/arena` (one command block + one sentence).
- [ ] **Step 4: Outcome section + AUTOPILOT_LOG line + commit** — `docs: record phase-3 arena outcome`.

---

## Self-review notes (spec coverage)

- Spec §7 lane A approved-only: Task 4 (buy queue = decided-buy pitches minus executed, via `lane_trades.pitch_id`).
- Spec §7 lane B autonomous above threshold: Task 2 (`lane_b_orders`) + Task 4.
- Spec §7 identical sizing/exit rules + fairness: single shared run in Task 4; parameters exist exactly once; the fairness invariant is stated in both the plan header and `lanes.py`'s docstring.
- Spec §7 simple rule-based exits (target/stop/time): Task 1 (`ExitRules`, exclusive boundaries).
- Spec §7 isolated ledgers vs SPY: Task 3 (per-lane tables, benchmark columns; SPY price from the same shared fetch).
- Spec §7 broker abstraction: the `fetch_price` seam; Alpaca live-paper adapter deliberately deferred (Needs Nico keys; internal sim keeps fills identical — the spec's stated invariant).
- Phase-2 follow-ups closed here: decision-time price (= fill price in `lane_trades`), executed marker (= `pitch_id` in `lane_trades`).
- Placeholder scan: Task 4/5 Step 1 describe test intent rather than full code — deliberate: the patterns are established in `tests/test_notify.py`/`tests/test_api.py` and earlier implementers proved they follow them; all production code is complete.
- Type consistency: `TradeRecord`/`BuyOrder`/`ExitRules` defined once in `lanes.py`; lane name constants single-sourced; `_portfolio_from_dict` is the only reconstruction path.
