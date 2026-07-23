"""Forward paper trading: drift, cost, idempotency, and storage round-trip."""
from __future__ import annotations

import json
import sqlite3

import pandas as pd
import pytest

from equity_scout.exits import ExitRules
from equity_scout.forward_paper import ForwardAccount, PositionEntry, _asset_return, advance_account
from equity_scout.forward_storage import (
    append_exit,
    append_valuation,
    init_forward_db,
    load_account,
    load_all_accounts,
    load_exits,
    load_valuations,
    save_account,
)
from equity_scout.market import PricePanel
from equity_scout.strategies.base import TargetWeight


class _Fixed:
    """A test strategy that always returns the given fixed weights (panel tickers only)."""

    def __init__(self, weights: dict[str, float], name: str = "fixed") -> None:
        self.name = name
        self._weights = weights

    def decide(self, as_of, market):  # noqa: ANN001 - matches the Strategy protocol
        return [TargetWeight(t, w) for t, w in self._weights.items()]


class _FixedSigned:
    """Like _Fixed, but emits explicit long/short TargetWeights — needed to test the short-sign
    correction in the exit check (a short profits when price falls)."""

    def __init__(self, weights: dict[str, tuple[float, str]], name: str = "signed") -> None:
        self.name = name
        self._weights = weights

    def decide(self, as_of, market):  # noqa: ANN001 - matches the Strategy protocol
        return [TargetWeight(t, w, side=side) for t, (w, side) in self._weights.items()]


def _flat_panel(prices: dict[str, float], n: int, start: str = "2025-01-01") -> PricePanel:
    """A panel of `n` business days where every ticker is flat at its given price — deterministic
    enough to hit exact exit-rule thresholds without fighting the wavy fixture's noise."""
    idx = pd.bdate_range(start, periods=n)
    return PricePanel(pd.DataFrame({t: [p] * n for t, p in prices.items()}, index=idx))


class _Recorder:
    """Records what `decide` was actually shown, so the look-ahead boundary is testable."""

    def __init__(self, name: str = "recorder") -> None:
        self.name = name
        self.seen_as_of: list = []
        self.seen_latest_visible: list = []

    def decide(self, as_of, market):  # noqa: ANN001 - matches the Strategy protocol
        self.seen_as_of.append(as_of)
        self.seen_latest_visible.append(market.latest_date)
        return []


def _sub_panel(panel: PricePanel, n: int) -> PricePanel:
    return PricePanel(panel.closes.iloc[:n])


def test_first_advance_buys_in_and_charges_buildup_cost(wavy_panel: PricePanel) -> None:
    account = ForwardAccount.fresh("fixed", initial_capital=10_000.0, benchmark_ticker="SPY")
    advanced, valuation = advance_account(account, _Fixed({"SPY": 1.0}), wavy_panel, costs_bps=10.0)

    # one-way turnover from cash to 100% SPY is 1.0 → cost = 10 bps once
    assert advanced.equity == pytest.approx(10_000.0 * (1 - 0.001))
    assert advanced.weights == {"SPY": 1.0}
    assert advanced.benchmark_equity == 10_000.0  # benchmark starts flat, no drift yet
    assert advanced.last_as_of == wavy_panel.dates[-1].date().isoformat()
    assert valuation is not None
    assert valuation.total_return == pytest.approx(-0.001)
    assert valuation.benchmark_return == pytest.approx(0.0)


def test_second_advance_drifts_equity_with_realised_return(wavy_panel: PricePanel) -> None:
    early, late = _sub_panel(wavy_panel, 1000), _sub_panel(wavy_panel, 1100)
    strat = _Fixed({"SPY": 1.0})

    acc1, _ = advance_account(ForwardAccount.fresh("fixed"), strat, early, costs_bps=10.0)
    acc2, val2 = advance_account(acc1, strat, late, costs_bps=10.0)

    closes = wavy_panel.closes["SPY"]
    spy_factor = closes.loc[: late.dates[-1]].iloc[-1] / closes.loc[: early.dates[-1]].iloc[-1]

    # same target → zero turnover on the second step, so only drift moves equity
    assert acc2.equity == pytest.approx(acc1.equity * spy_factor)
    assert acc2.benchmark_equity == pytest.approx(10_000.0 * spy_factor)
    assert val2 is not None
    assert val2.created_at == late.dates[-1].date().isoformat()


def test_decide_never_sees_todays_own_close(wavy_panel: PricePanel) -> None:
    """The backtest engine's MarketView(panel, date) excludes `date` itself (see engine.py); the
    forward account's decision must have the exact same boundary, or it gets a one-day look-ahead
    edge the backtest never had — this was the bug (MarketView(panel, today + 1 day))."""
    strat = _Recorder()
    today = wavy_panel.dates[-1]
    yesterday = wavy_panel.dates[-2]

    advance_account(ForwardAccount.fresh("recorder"), strat, wavy_panel)

    assert strat.seen_as_of == [today]  # matches the engine: as_of == the rebalance day itself
    assert strat.seen_latest_visible == [yesterday]  # but the data visible stops one day earlier


def test_advance_without_new_date_is_idempotent(wavy_panel: PricePanel) -> None:
    strat = _Fixed({"SPY": 1.0})
    acc1, _ = advance_account(ForwardAccount.fresh("fixed"), strat, wavy_panel)
    acc2, valuation = advance_account(acc1, strat, wavy_panel)

    assert valuation is None
    assert acc2 == acc1


def test_rebalance_turnover_costs_reduce_equity(wavy_panel: PricePanel) -> None:
    early, late = _sub_panel(wavy_panel, 1000), _sub_panel(wavy_panel, 1100)

    # hold SPY, then switch fully to VEU: one-way turnover = 2.0 → cost = 2 * 10 bps
    acc1, _ = advance_account(ForwardAccount.fresh("fixed"), _Fixed({"SPY": 1.0}), early)
    drifted_equity = acc1.equity * (
        wavy_panel.closes["SPY"].loc[: late.dates[-1]].iloc[-1]
        / wavy_panel.closes["SPY"].loc[: early.dates[-1]].iloc[-1]
    )
    acc2, _ = advance_account(acc1, _Fixed({"VEU": 1.0}), late, costs_bps=10.0)

    assert acc2.weights == {"VEU": 1.0}
    assert acc2.equity == pytest.approx(drifted_equity * (1 - 2 * 0.001))


def test_storage_round_trip_and_valuation_uniqueness(wavy_panel: PricePanel, tmp_path) -> None:
    db = tmp_path / "forward.db"
    init_forward_db(db)
    account, valuation = advance_account(ForwardAccount.fresh("fixed"), _Fixed({"SPY": 1.0}), wavy_panel)

    save_account(db, account, updated_at="2026-06-25")
    assert load_account(db, "fixed") == account
    assert load_all_accounts(db) == [account]

    assert valuation is not None
    append_valuation(db, "fixed", valuation)
    append_valuation(db, "fixed", valuation)  # same (strategy, date) — must be ignored
    rows = load_valuations(db, "fixed")
    assert len(rows) == 1
    assert rows[0]["equity"] == pytest.approx(account.equity)


def test_load_from_uninitialised_db_returns_empty(tmp_path) -> None:
    db = tmp_path / "empty.db"
    assert load_account(db, "fixed") is None
    assert load_all_accounts(db) == []
    assert load_valuations(db, "fixed") == []


# --- _asset_return: None vs 0% contract (v13 R2) -------------------------------------------


def test_asset_return_is_none_when_ticker_column_is_missing() -> None:
    panel = _series_panel({"HELD": [100.0, 105.0]})
    assert _asset_return(panel.closes, "GHOST", panel.dates[0], panel.dates[-1]) is None


def test_asset_return_is_none_when_the_window_has_only_stale_rows() -> None:
    """A gap (NaN) on `end`'s own date: the on/before resolution for `end` still lands on the
    exact same row as `start` — no row strictly newer than `start` exists yet."""
    nan = float("nan")
    idx = pd.bdate_range("2025-01-01", periods=3)
    closes = pd.DataFrame({"GAP": [100.0, nan, nan]}, index=idx)
    assert _asset_return(closes, "GAP", idx[0], idx[2]) is None


def test_asset_return_is_correct_when_a_fresh_row_exists() -> None:
    panel = _series_panel({"HELD": [100.0, 105.0, 120.0]})
    r = _asset_return(panel.closes, "HELD", panel.dates[0], panel.dates[-1])
    assert r == pytest.approx(0.20)


# --- Trade lifecycle: entry tracking + exits (plan v7, strand A2) --------------------------


def _series_panel(prices: dict[str, list[float]], start: str = "2025-01-01") -> PricePanel:
    """A panel with an explicit day-by-day price path per ticker — for engineering an exact
    return since entry, sliced day-by-day via `_sub_panel` like the wavy-panel tests above."""
    n = len(next(iter(prices.values())))
    idx = pd.bdate_range(start, periods=n)
    return PricePanel(pd.DataFrame(prices, index=idx))


def test_first_advance_opens_a_tracked_entry() -> None:
    panel = _series_panel({"NEW": [50.0]})
    account, _ = advance_account(ForwardAccount.fresh("fixed"), _Fixed({"NEW": 1.0}), panel)

    assert account.positions == {
        "NEW": PositionEntry(entry_price=50.0, opened_at=panel.dates[-1].date().isoformat())
    }


def test_entry_price_and_date_survive_drift_while_held() -> None:
    """A position that never trips an exit rule keeps its ORIGINAL entry, even though its weight
    drifts with the realised return on every advance."""
    panel = _series_panel({"HOLD": [100.0, 105.0, 108.0]})
    strat = _Fixed({"HOLD": 1.0})
    opened_at = _sub_panel(panel, 1).dates[-1].date().isoformat()

    acc1, _ = advance_account(ForwardAccount.fresh("fixed"), strat, _sub_panel(panel, 1))
    acc2, _ = advance_account(acc1, strat, _sub_panel(panel, 2))
    acc3, _ = advance_account(acc2, strat, _sub_panel(panel, 3))

    assert acc3.positions["HOLD"] == PositionEntry(entry_price=100.0, opened_at=opened_at)


def test_profit_target_exit_closes_position_and_blocks_same_day_reentry() -> None:
    """WIN rallies 30% since entry (> the 20% profit target). `_Fixed` keeps proposing WIN every
    advance (it has no notion of holdings, like the ML bots) — without the re-entry block this
    would just close and immediately reopen at the same weight."""
    panel = _series_panel({"WIN": [100.0, 130.0]})
    strat = _Fixed({"WIN": 1.0})
    acc1, _ = advance_account(ForwardAccount.fresh("fixed"), strat, _sub_panel(panel, 1))

    acc2, val2 = advance_account(acc1, strat, panel)

    assert val2 is not None
    assert len(val2.exits) == 1
    exit_event = val2.exits[0]
    assert exit_event.ticker == "WIN"
    assert "Kursziel" in exit_event.reason
    assert exit_event.entry_price == 100.0
    assert exit_event.exit_price == 130.0
    assert exit_event.return_pct == pytest.approx(0.30)
    assert acc2.weights == {}  # blocked from re-entry this same advance
    assert acc2.positions == {}


def test_stop_loss_exit_closes_position() -> None:
    panel = _series_panel({"LOSE": [100.0, 82.0]})
    strat = _Fixed({"LOSE": 1.0})
    acc1, _ = advance_account(ForwardAccount.fresh("fixed"), strat, _sub_panel(panel, 1))

    acc2, val2 = advance_account(acc1, strat, panel)

    assert len(val2.exits) == 1
    assert "Stop-Loss" in val2.exits[0].reason
    assert acc2.weights == {}


def test_max_holding_days_exit_closes_position() -> None:
    panel = _flat_panel({"OLD": 100.0}, n=300)  # flat price: only the holding period can trigger
    strat = _Fixed({"OLD": 1.0})
    acc1, _ = advance_account(ForwardAccount.fresh("fixed"), strat, _sub_panel(panel, 1))

    acc2, val2 = advance_account(acc1, strat, panel)

    assert len(val2.exits) == 1
    assert "Haltedauer" in val2.exits[0].reason
    assert acc2.weights == {}
    assert acc2.positions == {}


def test_short_position_profits_from_a_falling_price() -> None:
    """A short's return is sign-flipped: DROP falling 21% is a WIN for a short holder, so it hits
    the PROFIT target — not the stop loss a naive (unsigned) return would report."""
    panel = _series_panel({"DROP": [100.0, 79.0]})
    strat = _FixedSigned({"DROP": (1.0, "short")})
    acc1, _ = advance_account(ForwardAccount.fresh("fixed"), strat, _sub_panel(panel, 1))

    acc2, val2 = advance_account(acc1, strat, panel)

    assert len(val2.exits) == 1
    exit_event = val2.exits[0]
    assert "Kursziel" in exit_event.reason
    assert exit_event.return_pct == pytest.approx(0.21)
    assert acc2.weights == {}


def test_short_position_loses_from_a_rising_price() -> None:
    """Symmetric case: RISE rising 16% against a short position is a LOSS — stop loss, not
    profit target."""
    panel = _series_panel({"RISE": [100.0, 116.0]})
    strat = _FixedSigned({"RISE": (1.0, "short")})
    acc1, _ = advance_account(ForwardAccount.fresh("fixed"), strat, _sub_panel(panel, 1))

    acc2, val2 = advance_account(acc1, strat, panel)

    assert len(val2.exits) == 1
    exit_event = val2.exits[0]
    assert "Stop-Loss" in exit_event.reason
    assert exit_event.return_pct == pytest.approx(-0.16)
    assert acc2.weights == {}


def test_custom_exit_rules_are_honoured() -> None:
    panel = _series_panel({"WIN": [100.0, 106.0]})
    strat = _Fixed({"WIN": 1.0})
    tight = ExitRules(profit_target=0.05, stop_loss=0.05, max_holding_days=180)
    acc1, _ = advance_account(ForwardAccount.fresh("fixed"), strat, _sub_panel(panel, 1), exit_rules=tight)

    acc2, val2 = advance_account(acc1, strat, panel, exit_rules=tight)

    assert len(val2.exits) == 1
    assert "Kursziel" in val2.exits[0].reason


def test_holding_inside_all_thresholds_has_no_exit() -> None:
    panel = _series_panel({"MID": [100.0, 105.0]})
    strat = _Fixed({"MID": 1.0})
    acc1, _ = advance_account(ForwardAccount.fresh("fixed"), strat, _sub_panel(panel, 1))

    acc2, val2 = advance_account(acc1, strat, panel)

    assert val2 is not None
    assert val2.exits == ()
    assert acc2.weights == {"MID": 1.0}
    assert "MID" in acc2.positions


# --- Storage: entry tracking + exit log persistence + backward compatibility ---------------


def test_storage_round_trip_preserves_positions(tmp_path) -> None:
    db = tmp_path / "forward.db"
    init_forward_db(db)
    panel = _series_panel({"NEW": [50.0]})
    account, _ = advance_account(ForwardAccount.fresh("fixed"), _Fixed({"NEW": 1.0}), panel)

    save_account(db, account, updated_at="2026-06-25")

    assert load_account(db, "fixed") == account
    assert load_account(db, "fixed").positions == account.positions


def test_load_account_without_positions_field_is_backward_compatible(tmp_path) -> None:
    """Simulates a DB written before plan v7 A2 (the real forward_paper.db in the repo root has
    rows exactly like this) — no "positions" key in the JSON blob. Must load with an empty
    entry-tracking map, not KeyError."""
    db = tmp_path / "old.db"
    init_forward_db(db)
    old_blob = json.dumps({
        "strategy_name": "old", "initial_capital": 10_000.0, "equity": 11_000.0,
        "benchmark_ticker": "SPY", "benchmark_equity": 10_500.0, "last_as_of": "2026-01-01",
        "weights": {"SPY": 1.0},
    })
    with sqlite3.connect(db) as con:
        con.execute(
            "INSERT INTO forward_accounts (strategy_name, data, updated_at) VALUES (?, ?, ?)",
            ("old", old_blob, "2026-01-01"),
        )

    account = load_account(db, "old")

    assert account is not None
    assert account.positions == {}
    assert account.weights == {"SPY": 1.0}


def test_exit_event_persists_and_is_idempotent_per_day(tmp_path) -> None:
    db = tmp_path / "forward.db"
    init_forward_db(db)
    panel = _series_panel({"WIN": [100.0, 130.0]})
    strat = _Fixed({"WIN": 1.0})
    acc1, _ = advance_account(ForwardAccount.fresh("fixed"), strat, _sub_panel(panel, 1))
    _, val2 = advance_account(acc1, strat, panel)

    exit_event = val2.exits[0]
    append_exit(db, "fixed", exit_event)
    append_exit(db, "fixed", exit_event)  # same (strategy, ticker, date) — must be ignored

    rows = load_exits(db, "fixed")
    assert len(rows) == 1
    assert rows[0]["ticker"] == "WIN"
    assert "Kursziel" in rows[0]["reason"]


def test_load_exits_from_uninitialised_db_returns_empty(tmp_path) -> None:
    db = tmp_path / "empty.db"
    assert load_exits(db, "fixed") == []
