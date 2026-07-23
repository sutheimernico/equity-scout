"""Engine: idempotency, look-ahead safety, netting, costs/trades, protections, margin floor."""
from __future__ import annotations

import pandas as pd
import pytest

from equity_scout.autotrader_allocator import SleeveAllocation
from equity_scout.autotrader_engine import (
    AutoDepotAccount,
    advance_depot,
    aggregate_targets,
)
from equity_scout.autotrader_protections import ConcentrationCap, DrawdownBreaker
from equity_scout.market import PricePanel
from equity_scout.strategies.base import TargetWeight


class _Fixed:
    """Canned strategy: always returns the same targets."""

    def __init__(self, name: str, targets: list[TargetWeight]) -> None:
        self.name = name
        self._targets = targets

    def decide(self, as_of, market):  # noqa: ANN001, ANN201 - Strategy protocol
        return self._targets


class _Recorder(_Fixed):
    """Records what the MarketView let it see."""

    def __init__(self) -> None:
        super().__init__("recorder", [TargetWeight("SPY", 1.0)])
        self.seen_latest = None

    def decide(self, as_of, market):  # noqa: ANN001, ANN201
        self.seen_latest = market.latest_date
        return super().decide(as_of, market)


def _panel(days: int, prices: dict[str, list[float]] | None = None) -> PricePanel:
    index = pd.bdate_range("2026-06-01", periods=days)
    data = prices or {}
    if "SPY" not in data:
        data["SPY"] = [100.0 + i for i in range(days)]
    frame = pd.DataFrame({t: p[:days] for t, p in data.items()}, index=index)
    return PricePanel(frame)


def _allocation(weights: dict[str, float], mode: str = "anchor") -> SleeveAllocation:
    return SleeveAllocation(weights=weights, mode=mode)


def test_advance_without_new_date_is_idempotent() -> None:
    panel = _panel(5)
    strategy = _Fixed("s", [TargetWeight("SPY", 1.0)])
    account = AutoDepotAccount.fresh()
    account, first = advance_depot(account, [strategy], _allocation({"s": 1.0}), panel)
    assert first is not None
    account2, second = advance_depot(account, [strategy], _allocation({"s": 1.0}), panel)
    assert second is None
    assert account2 == account


def test_decide_never_sees_todays_own_close() -> None:
    panel = _panel(5)
    recorder = _Recorder()
    advance_depot(AutoDepotAccount.fresh(), [recorder], _allocation({"recorder": 1.0}), panel)
    assert recorder.seen_latest == panel.dates[-2]


def test_long_and_short_on_the_same_ticker_net_out() -> None:
    long_sleeve = _Fixed("long", [TargetWeight("AAPL", 1.0)])
    short_sleeve = _Fixed("short", [TargetWeight("AAPL", 1.0, side="short")])
    allocation = _allocation({"long": 0.5, "short": 0.5})
    decisions = {s.name: s.decide(None, None) for s in (long_sleeve, short_sleeve)}
    assert aggregate_targets(allocation, decisions) == {}


def test_look_through_scales_by_sleeve_weight() -> None:
    a = _Fixed("a", [TargetWeight("SPY", 1.0)])
    b = _Fixed("b", [TargetWeight("SPY", 0.5), TargetWeight("IEF", 0.5)])
    allocation = _allocation({"a": 0.6, "b": 0.4})
    decisions = {s.name: s.decide(None, None) for s in (a, b)}
    targets = aggregate_targets(allocation, decisions)
    assert targets["SPY"] == pytest.approx(0.6 + 0.4 * 0.5)
    assert targets["IEF"] == pytest.approx(0.4 * 0.5)


def test_first_rebalance_charges_turnover_cost_and_books_trades() -> None:
    panel = _panel(5, {"SPY": [100, 101, 102, 103, 104], "IEF": [50, 50, 50, 50, 50]})
    strategy = _Fixed("s", [TargetWeight("SPY", 0.6), TargetWeight("IEF", 0.4)])
    account, valuation = advance_depot(
        AutoDepotAccount.fresh(initial_capital=100_000.0),
        [strategy], _allocation({"s": 1.0}), panel, protections=[],
    )
    assert valuation is not None
    # turnover 1.0 at 10 bps on 100k = 100 USD
    assert valuation.equity == pytest.approx(100_000.0 - 100.0)
    tickers = {t.ticker: t for t in valuation.trades}
    assert tickers["SPY"].delta_weight == pytest.approx(0.6)
    assert tickers["SPY"].notional == pytest.approx(60_000.0)
    assert tickers["SPY"].cost + tickers["IEF"].cost == pytest.approx(100.0)
    assert valuation.gross_exposure == pytest.approx(1.0)
    assert account.weights == {"SPY": pytest.approx(0.6), "IEF": pytest.approx(0.4)}


def test_protection_chain_shapes_the_final_book() -> None:
    panel = _panel(5)
    strategy = _Fixed("s", [TargetWeight("SPY", 1.0)])
    account, valuation = advance_depot(
        AutoDepotAccount.fresh(), [strategy], _allocation({"s": 1.0}), panel,
        protections=[ConcentrationCap(cap=0.10)],
    )
    assert valuation is not None
    assert account.weights == {"SPY": pytest.approx(0.10)}
    assert [e.protection for e in valuation.risk_events] == ["concentration_cap"]


def test_drawdown_breaker_state_persists_into_the_account() -> None:
    falling = _panel(6, {"SPY": [100, 100, 100, 100, 100, 80]})
    strategy = _Fixed("s", [TargetWeight("SPY", 1.0)])
    account = AutoDepotAccount.fresh()
    first_panel = PricePanel(falling.closes.iloc[:5])
    account, _ = advance_depot(account, [strategy], _allocation({"s": 1.0}), first_panel,
                               protections=[])
    account, valuation = advance_depot(
        account, [strategy], _allocation({"s": 1.0}), falling,
        protections=[DrawdownBreaker(soft=0.10, hard=0.30)],
    )
    assert valuation is not None
    assert valuation.drawdown == pytest.approx(0.2, abs=0.01)
    assert account.breaker.stage == 1
    assert account.weights["SPY"] == pytest.approx(0.5)


def test_short_book_wipe_floors_at_zero_and_stops_trading() -> None:
    prices = {"SPY": [100] * 6, "TSLA": [100, 100, 100, 100, 100, 250]}
    strategy = _Fixed("s", [TargetWeight("TSLA", 1.0, side="short")])
    account = AutoDepotAccount.fresh()
    first_panel = _panel(5, {t: p[:5] for t, p in prices.items()})
    account, _ = advance_depot(account, [strategy], _allocation({"s": 1.0}), first_panel,
                               protections=[])
    account, valuation = advance_depot(
        account, [strategy], _allocation({"s": 1.0}), _panel(6, prices), protections=[],
    )
    assert valuation is not None
    assert account.equity == 0.0
    assert account.weights == {}
    assert valuation.total_return == -1.0
    _, after = advance_depot(account, [strategy], _allocation({"s": 1.0}), _panel(6, prices))
    assert after is None  # dead depot never trades again


def test_fx_rate_produces_eur_equity_and_absence_stays_none() -> None:
    panel = _panel(5)
    strategy = _Fixed("s", [TargetWeight("SPY", 1.0)])
    _, with_fx = advance_depot(
        AutoDepotAccount.fresh(), [strategy], _allocation({"s": 1.0}), panel, fx_rate=0.9,
    )
    assert with_fx is not None
    assert with_fx.equity_eur == pytest.approx(with_fx.equity * 0.9)
    _, without_fx = advance_depot(
        AutoDepotAccount.fresh(), [strategy], _allocation({"s": 1.0}), panel,
    )
    assert without_fx is not None
    assert without_fx.equity_eur is None and without_fx.fx_rate is None


def test_sleeve_holdings_mirror_drops_exited_tickers_without_redistributing() -> None:
    """R5/P1 (review 2026-07-20): the depot mirrors an ML sleeve's POST-exit forward book —
    a ticker the sleeve book no longer holds contributes 0; freed weight sits in cash."""
    panel = _panel(5, {"SPY": [100.0] * 5, "AAPL": [50.0] * 5, "MSFT": [60.0] * 5})
    sleeve = _Fixed("ml", [TargetWeight("AAPL", 0.5), TargetWeight("MSFT", 0.5)])
    account, _ = advance_depot(
        AutoDepotAccount.fresh(), [sleeve], _allocation({"ml": 1.0}), panel,
        protections=[], sleeve_holdings={"ml": {"AAPL"}},
    )
    assert "MSFT" not in account.weights
    assert account.weights["AAPL"] == pytest.approx(0.5)  # not scaled up to fill the gap


def test_stale_series_books_zero_and_next_fresh_row_books_the_full_move() -> None:
    """Reviewer repro (v13 R2, the actual P0 fix): a lane's fresh price lands one panel date
    late (feed/chain timing). The window-based valuation used to resolve BOTH ends to the same
    stale row and silently lose the move forever — every following night booked 0.00. With
    per-position marks, the advance that still sees no price fresher than its mark books 0 and
    KEEPS the mark; the very next advance that finally sees the fresh row books the FULL move —
    nothing lost, just booked one day late."""
    nan = float("nan")
    prices = {
        "SPY": [100.0] * 7,
        "CRYPTO": [100.0, 100.0, 100.0, 100.0, 100.0, nan, 150.0],  # gap on day 6, +50% on day 7
    }
    full = _panel(7, prices)
    strategy = _Fixed("s", [TargetWeight("CRYPTO", 1.0)])
    allocation = _allocation({"s": 1.0})
    account = AutoDepotAccount.fresh()

    for n in range(1, 6):  # days 1-5: establish the position and its mark
        account, _ = advance_depot(
            account, [strategy], allocation, PricePanel(full.closes.iloc[:n]), protections=[],
        )
    equity_before_gap = account.equity
    mark_before_gap = account.last_marks["CRYPTO"]

    # day 6: CRYPTO's own feed has not updated (NaN) — no reading fresher than the mark exists.
    account, val6 = advance_depot(
        account, [strategy], allocation, PricePanel(full.closes.iloc[:6]), protections=[],
    )
    assert val6 is not None
    assert val6.equity == pytest.approx(equity_before_gap)  # booked zero this step
    assert account.last_marks["CRYPTO"] == mark_before_gap  # mark held untouched, not re-anchored

    # day 7: the fresh +50% row finally lands — the FULL move must book now.
    account, val7 = advance_depot(account, [strategy], allocation, full, protections=[])
    assert val7 is not None
    assert val7.equity == pytest.approx(equity_before_gap * 1.5)
    assert account.last_marks["CRYPTO"] == (full.dates[-1].date().isoformat(), 150.0)


def test_fresh_price_every_step_drifts_exactly_like_the_old_window_logic() -> None:
    """No staleness anywhere: the marks-based drift must reproduce the exact same arithmetic as
    the old [last, today] window resolution, day after day."""
    panel = _panel(4, {"SPY": [100.0] * 4, "AAPL": [50.0, 52.0, 49.0, 55.0]})
    strategy = _Fixed("s", [TargetWeight("AAPL", 1.0)])
    allocation = _allocation({"s": 1.0})
    account = AutoDepotAccount.fresh(initial_capital=10_000.0)

    account, _ = advance_depot(account, [strategy], allocation, PricePanel(panel.closes.iloc[:1]),
                                protections=[])
    after_buildup = account.equity  # one-way turnover cost from cash -> 100% AAPL

    account, val2 = advance_depot(account, [strategy], allocation, PricePanel(panel.closes.iloc[:2]),
                                   protections=[])
    assert val2.equity == pytest.approx(after_buildup * (52.0 / 50.0))

    account, val3 = advance_depot(account, [strategy], allocation, PricePanel(panel.closes.iloc[:3]),
                                   protections=[])
    assert val3.equity == pytest.approx(after_buildup * (49.0 / 50.0))

    account, val4 = advance_depot(account, [strategy], allocation, panel, protections=[])
    assert val4.equity == pytest.approx(after_buildup * (55.0 / 50.0))
    assert account.last_marks["AAPL"] == (panel.dates[-1].date().isoformat(), 55.0)


def test_legacy_blob_without_marks_initialises_on_first_advance_then_uses_them() -> None:
    """Migration (v13 R2): an account that already holds a position but predates `last_marks`
    (loaded as {}) values its first advance exactly like the old window logic and initialises
    the mark; the SECOND advance then uses that mark, mark-return arithmetic."""
    from dataclasses import replace

    panel = _panel(3, {"SPY": [100.0] * 3, "AAPL": [50.0, 60.0, 66.0]})
    strategy = _Fixed("s", [TargetWeight("AAPL", 1.0)])
    allocation = _allocation({"s": 1.0})

    legacy = replace(
        AutoDepotAccount.fresh(initial_capital=10_000.0),
        equity=10_000.0, weights={"AAPL": 1.0},
        last_as_of=panel.dates[0].date().isoformat(), last_marks={},
    )

    account, val2 = advance_depot(legacy, [strategy], allocation,
                                   PricePanel(panel.closes.iloc[:2]), protections=[])
    assert val2.equity == pytest.approx(10_000.0 * (60.0 / 50.0))  # same as the old window return
    assert account.last_marks["AAPL"] == (panel.dates[1].date().isoformat(), 60.0)

    account, val3 = advance_depot(account, [strategy], allocation, panel, protections=[])
    assert val3.equity == pytest.approx(val2.equity * (66.0 / 60.0))  # now driven by the mark
    assert account.last_marks["AAPL"] == (panel.dates[2].date().isoformat(), 66.0)


def test_sleeve_holdings_only_filters_listed_sleeves() -> None:
    panel = _panel(5, {"SPY": [100.0] * 5, "AAPL": [50.0] * 5})
    rule = _Fixed("rule", [TargetWeight("AAPL", 0.8)])
    account, _ = advance_depot(
        AutoDepotAccount.fresh(), [rule], _allocation({"rule": 1.0}), panel,
        protections=[], sleeve_holdings={"ml": set()},
    )
    assert account.weights["AAPL"] == pytest.approx(0.8)
