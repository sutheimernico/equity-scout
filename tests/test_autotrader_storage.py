"""Storage: account round-trip, idempotent advance recording, loaders, sleeve upsert."""
from __future__ import annotations

import pytest

from equity_scout.autotrader_allocator import SleeveAllocation
from equity_scout.autotrader_engine import AutoDepotAccount, AutoDepotValuation, TradeRecord
from equity_scout.autotrader_protections import BreakerState, RiskEvent
from equity_scout.autotrader_storage import (
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
