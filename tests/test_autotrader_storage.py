"""Storage: account round-trip, idempotent advance recording, loaders, sleeve upsert."""
from __future__ import annotations

import json
import sqlite3

import pandas as pd
import pytest

from equity_scout.autotrader_allocator import SleeveAllocation
from equity_scout.autotrader_engine import (
    AutoDepotAccount,
    AutoDepotValuation,
    TradeRecord,
    advance_depot,
)
from equity_scout.autotrader_protections import BreakerState, RiskEvent
from equity_scout.autotrader_storage import (
    init_autotrader_db,
    load_depot,
    load_latest_sleeve_weights,
    load_risk_events,
    load_trades,
    load_valuations,
    persist_advance,
    record_advance,
    save_depot,
    save_sleeve_weights,
)
from equity_scout.market import PricePanel
from equity_scout.strategies.base import TargetWeight


@pytest.fixture
def db(tmp_path):
    return tmp_path / "autotrader.db"


def _valuation(day: str = "2026-07-20") -> AutoDepotValuation:
    return AutoDepotValuation(
        created_at=day, equity=99_900.0, total_return=-0.001,
        benchmark_equity=100_100.0, benchmark_return=0.001,
        gross_exposure=0.85, drawdown=0.02, equity_eur=89_910.0, fx_rate=0.9,
        trades=(
            TradeRecord(created_at=day, ticker="SPY", delta_weight=0.6, notional=60_000.0, cost=60.0),
            TradeRecord(created_at=day, ticker="IEF", delta_weight=0.25, notional=25_000.0, cost=25.0),
        ),
        risk_events=(
            RiskEvent(protection="vol_target", action="scale_0.85", detail="Vol über Ziel"),
        ),
    )


def test_account_round_trip_preserves_breaker_and_sleeves(db) -> None:
    account = AutoDepotAccount(
        initial_capital=100_000.0, equity=98_000.0, benchmark_ticker="SPY",
        benchmark_equity=101_000.0, peak_equity=103_000.0, last_as_of="2026-07-20",
        weights={"SPY": 0.4, "TSLA": -0.05},
        breaker=BreakerState(stage=1, changed_at="2026-07-18"),
        sleeve_weights={"gem": 0.6, "daa": 0.4}, sleeve_mode="tilt",
    )
    save_depot(db, account, updated_at="2026-07-20")
    assert load_depot(db) == account


def test_load_depot_on_fresh_db_is_none(db) -> None:
    assert load_depot(db) is None


def test_record_advance_is_idempotent_per_day(db) -> None:
    record_advance(db, _valuation())
    record_advance(db, _valuation())  # cron re-run — must not double-count
    assert len(load_valuations(db)) == 1
    assert len(load_trades(db)) == 2
    assert len(load_risk_events(db)) == 1


def test_loaders_return_expected_shapes_and_order(db) -> None:
    record_advance(db, _valuation("2026-07-17"))
    record_advance(db, _valuation("2026-07-20"))
    valuations = load_valuations(db)
    assert [v["created_at"] for v in valuations] == ["2026-07-17", "2026-07-20"]
    assert valuations[0]["equity_eur"] == pytest.approx(89_910.0)
    trades = load_trades(db, limit=3)
    assert trades[0]["created_at"] == "2026-07-20"  # newest first
    assert {t["ticker"] for t in trades[:2]} == {"IEF", "SPY"}
    events = load_risk_events(db)
    assert events[0]["protection"] == "vol_target"


def test_sleeve_weights_upsert_and_latest_month(db) -> None:
    june = SleeveAllocation(weights={"gem": 0.5, "daa": 0.5}, mode="anchor")
    save_sleeve_weights(db, "2026-06", june)
    july = SleeveAllocation(
        weights={"gem": 0.6, "daa": 0.4}, mode="tilt", sharpes={"gem": 1.2, "daa": 0.3}
    )
    save_sleeve_weights(db, "2026-07", july)
    save_sleeve_weights(db, "2026-07", july)  # upsert — no duplicates
    rows = load_latest_sleeve_weights(db)
    assert [r["strategy_name"] for r in rows] == ["gem", "daa"]
    assert rows[0]["month"] == "2026-07"
    assert rows[0]["mode"] == "tilt"
    assert rows[0]["sharpe"] == pytest.approx(1.2)


def test_latest_sleeve_weights_on_fresh_db_is_empty(db) -> None:
    assert load_latest_sleeve_weights(db) == []


def test_sleeve_that_left_the_depot_is_dropped_from_its_month(db) -> None:
    """A month's allocation is a complete picture, not a delta.

    Live on 2026-08-16: the ML Long Bot lost its champion and stopped being a sleeve, but
    its August row survived at the old 12.5 % — the upsert can only rewrite names it still
    sees. The cockpit then listed a sleeve that holds nothing and the weights summed to
    112.5 %.
    """
    with_bot = SleeveAllocation(
        weights={"gem": 0.5, "ML Long Bot": 0.5}, mode="anchor"
    )
    save_sleeve_weights(db, "2026-08", with_bot)
    without_bot = SleeveAllocation(weights={"gem": 0.6, "daa": 0.4}, mode="anchor")
    save_sleeve_weights(db, "2026-08", without_bot)
    rows = load_latest_sleeve_weights(db)
    assert [r["strategy_name"] for r in rows] == ["gem", "daa"]
    assert sum(r["weight"] for r in rows) == pytest.approx(1.0)


def test_empty_allocation_does_not_wipe_the_month(db) -> None:
    """An advance that produced no allocation says nothing — it must not erase the truth."""
    save_sleeve_weights(db, "2026-08", SleeveAllocation(weights={"gem": 1.0}, mode="anchor"))
    save_sleeve_weights(db, "2026-08", SleeveAllocation(weights={}, mode="anchor"))
    assert [r["strategy_name"] for r in load_latest_sleeve_weights(db)] == ["gem"]


def test_dropping_a_sleeve_leaves_other_months_untouched(db) -> None:
    save_sleeve_weights(db, "2026-07", SleeveAllocation(weights={"gem": 1.0}, mode="anchor"))
    save_sleeve_weights(db, "2026-08", SleeveAllocation(weights={"daa": 1.0}, mode="anchor"))
    rows = load_latest_sleeve_weights(db)
    assert [r["strategy_name"] for r in rows] == ["daa"]  # July's row is not collateral


def test_persist_advance_commits_account_and_rows_together(db) -> None:
    account = AutoDepotAccount.fresh()
    persist_advance(db, account, _valuation(), updated_at="2026-07-20")
    assert load_depot(db) == account
    assert len(load_valuations(db)) == 1
    assert len(load_trades(db)) == 2

    persist_advance(db, account, _valuation(), updated_at="2026-07-20")  # cron re-run
    assert len(load_valuations(db)) == 1


class _ExplodingTrade:
    """Stands in for a TradeRecord; blows up mid-write to simulate a crash."""

    created_at = "2026-07-20"
    ticker = "SPY"
    delta_weight = 0.6
    notional = 60_000.0

    @property
    def cost(self) -> float:
        raise RuntimeError("boom mid-persist")


def test_persist_advance_rolls_back_completely_on_mid_write_failure(db) -> None:
    """R3/P1 (review 2026-07-20): a crash between the timeseries rows and the account blob
    must not strand the day (guard set, rows lost, retry blocked) — all or nothing."""
    from dataclasses import replace

    broken = replace(_valuation(), trades=(_ExplodingTrade(),))
    with pytest.raises(RuntimeError):
        persist_advance(db, AutoDepotAccount.fresh(), broken, updated_at="2026-07-20")
    assert load_depot(db) is None
    assert load_valuations(db) == []
    assert load_trades(db) == []


def test_promoted_lanes_survive_the_account_round_trip(db) -> None:
    account = AutoDepotAccount.fresh()
    from dataclasses import replace

    account = replace(account, promoted_lanes=("crypto",))
    save_depot(db, account, updated_at="2026-07-21")
    assert load_depot(db).promoted_lanes == ("crypto",)


def test_marks_survive_the_account_round_trip(db) -> None:
    account = AutoDepotAccount.fresh()
    from dataclasses import replace

    account = replace(account, weights={"AAPL": 1.0}, last_marks={"AAPL": ("2026-07-20", 60.0)})
    save_depot(db, account, updated_at="2026-07-21")
    assert load_depot(db).last_marks == {"AAPL": ("2026-07-20", 60.0)}


class _Fixed:
    """Canned strategy: always returns the same targets (mirrors test_autotrader_engine.py)."""

    def __init__(self, name: str, targets: list[TargetWeight]) -> None:
        self.name = name
        self._targets = targets

    def decide(self, as_of, market):  # noqa: ANN001, ANN201 - Strategy protocol
        return self._targets


def _panel(prices: dict[str, list[float]]) -> PricePanel:
    n = len(next(iter(prices.values())))
    idx = pd.bdate_range("2026-06-01", periods=n)
    return PricePanel(pd.DataFrame(prices, index=idx))


def test_legacy_blob_without_last_marks_loads_cleanly_and_then_learns_marks(db) -> None:
    """A depot blob persisted before v13 R2 has no "last_marks" key at all — must load as {},
    not KeyError. The first advance after loading it initialises marks like the old window
    logic; the second advance then uses them (v13 R2 migration)."""
    init_autotrader_db(db)
    legacy_blob = json.dumps({
        "initial_capital": 10_000.0, "equity": 10_000.0, "benchmark_ticker": "SPY",
        "benchmark_equity": 10_000.0, "peak_equity": 10_000.0, "last_as_of": "2026-06-01",
        "weights": {"AAPL": 1.0}, "breaker": {"stage": 0, "changed_at": None},
        "sleeve_weights": {}, "sleeve_mode": "anchor", "promoted_lanes": [],
        # deliberately no "last_marks" key
    })
    with sqlite3.connect(db) as con:
        con.execute(
            "INSERT INTO autotrader_account (id, data, updated_at) VALUES (1, ?, ?)",
            (legacy_blob, "2026-06-01"),
        )

    account = load_depot(db)
    assert account is not None
    assert account.last_marks == {}

    panel = _panel({"SPY": [100.0] * 3, "AAPL": [50.0, 60.0, 66.0]})
    strategy = _Fixed("s", [TargetWeight("AAPL", 1.0)])
    allocation = SleeveAllocation(weights={"s": 1.0}, mode="anchor")

    account, val2 = advance_depot(
        account, [strategy], allocation, PricePanel(panel.closes.iloc[:2]), protections=[],
    )
    assert val2.equity == pytest.approx(10_000.0 * (60.0 / 50.0))  # old window logic, unchanged
    assert account.last_marks["AAPL"] == (panel.dates[1].date().isoformat(), 60.0)

    account, val3 = advance_depot(account, [strategy], allocation, panel, protections=[])
    assert val3.equity == pytest.approx(val2.equity * (66.0 / 60.0))  # now driven by the mark
    assert account.last_marks["AAPL"] == (panel.dates[2].date().isoformat(), 66.0)


def test_pending_orders_round_trip_and_legacy_blob_loads_none(db) -> None:
    """v13 O2: pending orders survive the blob round trip; a pre-v13 blob (no key) loads
    as None — nothing was pending under the old same-close fill convention."""
    from dataclasses import replace

    from equity_scout.autotrader_engine import PendingOrders
    from equity_scout import db as db_mod

    account = AutoDepotAccount.fresh()
    with_pending = replace(
        account, pending_orders=PendingOrders(
            decided_as_of="2026-07-23", targets={"SPY": 0.6, "IEF": 0.4},
        ),
    )
    save_depot(db, with_pending, updated_at="2026-07-23")
    loaded = load_depot(db)
    assert loaded.pending_orders == with_pending.pending_orders

    # simulate a legacy blob: strip the key the way an old writer would have left it
    with db_mod.connect(db) as con:
        row = con.execute("SELECT data FROM autotrader_account WHERE id = 1").fetchone()
        blob = json.loads(row[0])
        del blob["pending_orders"]
        con.execute("UPDATE autotrader_account SET data = ?", (json.dumps(blob),))
    assert load_depot(db).pending_orders is None


def test_trades_table_migrates_and_labels_legacy_rows_close(db) -> None:
    """v13 O2: a pre-v13 trades table gains the fill columns idempotently; its old rows
    read back as fill='close' (decided and filled on the same close), no fill price."""
    legacy = str(db).replace("autotrader.db", "legacy.db")
    with sqlite3.connect(legacy) as con:
        con.execute(
            "CREATE TABLE autotrader_trades ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,"
            " ticker TEXT NOT NULL, delta_weight REAL NOT NULL, notional REAL NOT NULL,"
            " cost REAL NOT NULL, UNIQUE (ticker, created_at))"
        )
        con.execute(
            "INSERT INTO autotrader_trades (created_at, ticker, delta_weight, notional, cost)"
            " VALUES ('2026-07-20', 'SPY', 0.6, 60000.0, 60.0)"
        )
    trades = load_trades(legacy)  # init_autotrader_db migrates on the way in
    assert trades[0]["fill"] == "close"
    assert trades[0]["fill_price"] is None
    assert trades[0]["decided_as_of"] is None
    # new rows carry the fill metadata
    record_advance(legacy, _valuation("2026-07-21"))
    newest = load_trades(legacy)[0]
    assert newest["created_at"] == "2026-07-21"
    assert newest["fill"] == "close"  # _valuation()'s TradeRecords use the default label
