"""Runner: end-to-end advance on a synthetic panel, allocation reuse, dry-run, idempotency."""
from __future__ import annotations

import pandas as pd
import pytest

from equity_scout.autotrader_allocator import SleeveAllocation
from equity_scout.autotrader_storage import (
    load_depot,
    load_latest_sleeve_weights,
    load_trades,
    load_valuations,
    save_sleeve_weights,
)
from equity_scout.market import PricePanel
from equity_scout.strategies.base import TargetWeight
from scripts.run_autotrader import (
    advance_autotrader,
    depot_return_series,
    resolve_allocation,
)


class _Fixed:
    def __init__(self, name: str, targets: list[TargetWeight]) -> None:
        self.name = name
        self._targets = targets

    def decide(self, as_of, market):  # noqa: ANN001, ANN201 - Strategy protocol
        return self._targets


def _panel(days: int = 6) -> PricePanel:
    index = pd.bdate_range("2026-07-06", periods=days)
    return PricePanel(
        pd.DataFrame(
            {"SPY": [100.0 + i for i in range(days)], "IEF": [50.0] * days}, index=index
        )
    )


@pytest.fixture
def dbs(tmp_path):
    return str(tmp_path / "autotrader.db"), str(tmp_path / "forward.db")


def test_advance_persists_account_valuation_trades_and_weights(dbs) -> None:
    autotrader_db, forward_db = dbs
    strategies = [_Fixed("a", [TargetWeight("SPY", 0.5)]), _Fixed("b", [TargetWeight("IEF", 0.5)])]
    account, valuation = advance_autotrader(
        _panel(), strategies, autotrader_db=autotrader_db, forward_db=forward_db,
    )
    assert valuation is not None
    assert load_depot(autotrader_db) == account
    assert len(load_valuations(autotrader_db)) == 1
    assert {t["ticker"] for t in load_trades(autotrader_db)} == {"SPY", "IEF"}
    stored = load_latest_sleeve_weights(autotrader_db)
    # empty forward history -> honest anchor mode, equal sleeve weights
    assert {r["strategy_name"]: r["weight"] for r in stored} == {"a": 0.5, "b": 0.5}
    assert stored[0]["mode"] == "anchor"
    assert account.sleeve_mode == "anchor"


def test_second_advance_on_same_panel_is_idempotent(dbs) -> None:
    autotrader_db, forward_db = dbs
    strategies = [_Fixed("a", [TargetWeight("SPY", 0.5)])]
    advance_autotrader(_panel(), strategies, autotrader_db=autotrader_db, forward_db=forward_db)
    _, second = advance_autotrader(
        _panel(), strategies, autotrader_db=autotrader_db, forward_db=forward_db,
    )
    assert second is None
    assert len(load_valuations(autotrader_db)) == 1


def test_dry_run_persists_nothing(dbs) -> None:
    autotrader_db, forward_db = dbs
    strategies = [_Fixed("a", [TargetWeight("SPY", 0.5)])]
    _, valuation = advance_autotrader(
        _panel(), strategies, autotrader_db=autotrader_db, forward_db=forward_db, persist=False,
    )
    assert valuation is not None
    assert load_depot(autotrader_db) is None
    assert load_valuations(autotrader_db) == []


def test_resolve_allocation_reuses_same_month_same_sleeves(dbs) -> None:
    autotrader_db, forward_db = dbs
    as_of = pd.Timestamp("2026-07-13")
    stored = SleeveAllocation(weights={"a": 0.7, "b": 0.3}, mode="tilt", sharpes={"a": 1.0, "b": 0.1})
    save_sleeve_weights(autotrader_db, "2026-07", stored)
    allocation = resolve_allocation(autotrader_db, forward_db, ["a", "b"], as_of)
    assert allocation.weights == {"a": 0.7, "b": 0.3}
    assert allocation.mode == "tilt"


def test_resolve_allocation_recomputes_when_sleeve_set_changes(dbs) -> None:
    autotrader_db, forward_db = dbs
    as_of = pd.Timestamp("2026-07-13")
    save_sleeve_weights(
        autotrader_db, "2026-07", SleeveAllocation(weights={"a": 1.0}, mode="tilt")
    )
    allocation = resolve_allocation(autotrader_db, forward_db, ["a", "new_bot"], as_of)
    # no forward history in the tmp DB -> recompute lands on the honest anchor
    assert allocation.mode == "anchor"
    assert allocation.weights == {"a": 0.5, "new_bot": 0.5}
    assert {r["strategy_name"] for r in load_latest_sleeve_weights(autotrader_db)} == {"a", "new_bot"}


def test_depot_return_series_needs_two_valuations(dbs) -> None:
    autotrader_db, forward_db = dbs
    assert depot_return_series(autotrader_db) is None
    strategies = [_Fixed("a", [TargetWeight("SPY", 0.5)])]
    advance_autotrader(_panel(5), strategies, autotrader_db=autotrader_db, forward_db=forward_db)
    advance_autotrader(_panel(6), strategies, autotrader_db=autotrader_db, forward_db=forward_db)
    series = depot_return_series(autotrader_db)
    assert series is not None and len(series) == 1


def test_ml_sleeve_holdings_reads_post_exit_forward_books(tmp_path) -> None:
    """R5/P1: only the ML bots' books are mirrored; zero-weight = not held; a bot without
    a forward account yet stays unfiltered (exit info honestly unavailable)."""
    from equity_scout.forward_paper import ForwardAccount
    from equity_scout.forward_storage import init_forward_db, save_account
    from scripts.run_autotrader import ml_sleeve_holdings

    forward_db = str(tmp_path / "forward.db")
    init_forward_db(forward_db)
    save_account(forward_db, ForwardAccount(
        strategy_name="ML Long Bot", initial_capital=10_000.0, equity=10_000.0,
        benchmark_ticker="SPY", benchmark_equity=10_000.0, last_as_of="2026-07-18",
        weights={"AAPL": 0.3, "MSFT": 0.0},
    ), updated_at="2026-07-18")

    holdings = ml_sleeve_holdings(forward_db, ["ML Long Bot", "ML Short Bot", "GEM"])
    assert holdings == {"ML Long Bot": {"AAPL"}}
