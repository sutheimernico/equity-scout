"""Engine tests — all offline on deterministic synthetic panels. No network, ever."""
from __future__ import annotations

import pandas as pd
import pytest

from equity_scout.engine import BacktestResult, run_backtest
from equity_scout.market import MarketView, PricePanel
from equity_scout.strategies.base import TargetWeight
from equity_scout.strategies.sixty_forty import SixtyFortyStrategy


class _Hold:
    """Test strategy: always 100% in one ticker."""

    name = "hold"

    def __init__(self, ticker: str) -> None:
        self.ticker = ticker

    def decide(self, as_of: pd.Timestamp, market: MarketView) -> list[TargetWeight]:
        return [TargetWeight(self.ticker, 1.0)]


class _Spy:
    """Records (as_of, latest visible date) on every decision, so a test can prove the engine
    never lets a strategy see data on or after the decision date."""

    name = "spy"

    def __init__(self, target: list[TargetWeight]) -> None:
        self.target = target
        self.seen: list[tuple[pd.Timestamp, pd.Timestamp | None]] = []

    def decide(self, as_of: pd.Timestamp, market: MarketView) -> list[TargetWeight]:
        self.seen.append((as_of, market.latest_date))
        return self.target


def _panel(prices_by_ticker: dict[str, list[float]], start: str = "2021-01-01") -> PricePanel:
    n = len(next(iter(prices_by_ticker.values())))
    return PricePanel(pd.DataFrame(prices_by_ticker, index=pd.bdate_range(start, periods=n)))


def test_engine_never_lets_strategy_see_data_on_or_after_decision_date():
    panel = _panel({"AAA": [100.0 + i for i in range(400)], "BBB": [50.0] * 400})
    spy = _Spy([TargetWeight("AAA", 0.5), TargetWeight("BBB", 0.5)])
    run_backtest(spy, panel)
    assert spy.seen, "strategy was never asked to decide"
    for as_of, latest in spy.seen:
        assert latest is not None
        assert latest < as_of  # the view is strictly in the past — no look-ahead


def test_flat_market_only_costs_the_initial_buy():
    panel = _panel({"A": [100.0] * 65})  # ~3 months, flat
    result = run_backtest(_Hold("A"), panel, costs_bps=10)
    assert isinstance(result, BacktestResult)
    assert result.equity.iloc[-1] == pytest.approx(0.999)  # one buy at 10bps, no returns after
    assert result.total_turnover == pytest.approx(1.0)
    assert len(result.trades) == 1


def test_equity_is_flat_until_the_first_rebalance():
    prices = [100.0 * 1.001**i for i in range(65)]
    panel = _panel({"A": prices})
    result = run_backtest(_Hold("A"), panel, costs_bps=0)
    first_rebalance = panel.rebalance_dates()[0]
    idx = panel.dates.get_loc(first_rebalance)
    assert (result.equity.iloc[: idx + 1] == 1.0).all()  # nothing invested yet
    assert result.equity.iloc[idx + 1] > 1.0  # grows only after the buy


def test_buy_and_hold_tracks_the_asset_from_first_rebalance():
    prices = [100.0 * 1.001**i for i in range(65)]
    panel = _panel({"A": prices})
    result = run_backtest(_Hold("A"), panel, costs_bps=0)
    idx = panel.dates.get_loc(panel.rebalance_dates()[0])
    expected = prices[-1] / prices[idx]  # buy-and-hold total return from the buy point
    assert result.equity.iloc[-1] == pytest.approx(expected, rel=1e-9)


def test_more_costs_strictly_lower_final_equity_when_trading_happens():
    # A momentum-flipping panel forces real turnover: AAA then BBB lead in alternating regimes.
    n = 500
    aaa = [100.0 * (1.02 if i < n // 2 else 0.99) ** i for i in range(n)]
    bbb = [100.0 * (0.99 if i < n // 2 else 1.02) ** i for i in range(n)]
    panel = _panel({"AAA": aaa, "BBB": bbb})

    class _Flip:
        name = "flip"

        def decide(self, as_of: pd.Timestamp, market: MarketView) -> list[TargetWeight]:
            ra = market.trailing_return("AAA", 3)
            rb = market.trailing_return("BBB", 3)
            if ra is None or rb is None:
                return [TargetWeight("AAA", 1.0)]
            return [TargetWeight("AAA" if ra >= rb else "BBB", 1.0)]

    finals = [
        run_backtest(_Flip(), panel, costs_bps=bps).equity.iloc[-1] for bps in (0, 5, 10, 20)
    ]
    assert finals == sorted(finals, reverse=True)  # strictly monotone down in cost
    assert finals[0] > finals[-1]


def test_sixty_forty_holds_target_weights_right_after_a_rebalance():
    # Flat prices → no drift between rebalances, so post-fill weights equal the target exactly.
    panel = _panel({"SPY": [100.0] * 300, "IEF": [100.0] * 300})
    result = run_backtest(SixtyFortyStrategy(), panel, costs_bps=0)
    first_rebal = result.weights_by_date.index[0]
    w = result.weights_by_date.loc[first_rebal]
    assert w["SPY"] == pytest.approx(0.60)
    assert w["IEF"] == pytest.approx(0.40)


def test_rebalancing_generates_turnover_beyond_the_initial_buy():
    # SPY drifts up, IEF flat → monthly rebalance trims SPY back to 60% → extra turnover + trades
    panel = _panel({"SPY": [100.0 * 1.002**i for i in range(65)], "IEF": [100.0] * 65})
    result = run_backtest(SixtyFortyStrategy(), panel, costs_bps=0)
    assert result.total_turnover > 1.0
    assert len(result.trades) >= 2
