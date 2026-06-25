"""Forward paper trading: drift, cost, idempotency, and storage round-trip."""
from __future__ import annotations

import pytest

from equity_scout.forward_paper import ForwardAccount, advance_account
from equity_scout.forward_storage import (
    append_valuation,
    init_forward_db,
    load_account,
    load_all_accounts,
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
