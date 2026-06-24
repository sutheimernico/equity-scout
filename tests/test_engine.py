import pandas as pd
import pytest

from equity_scout.engine import run_backtest
from equity_scout.market import PricePanel
from equity_scout.strategies.sixty_forty import SixtyFortyStrategy


class _Hold:
    """Test strategy: always 100% in one ticker."""

    name = "hold"

    def __init__(self, ticker: str) -> None:
        self.ticker = ticker

    def decide(self, as_of, market, state):
        return {self.ticker: 1.0}


def _panel(prices_by_ticker: dict[str, list[float]]) -> PricePanel:
    n = len(next(iter(prices_by_ticker.values())))
    return PricePanel(pd.DataFrame(prices_by_ticker, index=pd.bdate_range("2021-01-01", periods=n)))


def test_flat_market_only_costs_the_initial_buy():
    panel = _panel({"A": [100.0] * 65})  # ~3 months, flat
    result = run_backtest(_Hold("A"), panel, cost_bps=10)
    assert result.equity.iloc[-1] == pytest.approx(0.999)  # one buy at 10bps, no returns after
    assert result.total_turnover == pytest.approx(1.0)
    assert len(result.trades) == 1


def test_equity_is_flat_until_the_first_rebalance():
    prices = [100.0 * 1.001**i for i in range(65)]
    panel = _panel({"A": prices})
    result = run_backtest(_Hold("A"), panel, cost_bps=0)
    first_rebalance = panel.rebalance_dates()[0]
    idx = panel.dates.get_loc(first_rebalance)
    assert (result.equity.iloc[: idx + 1] == 1.0).all()  # nothing invested yet
    assert result.equity.iloc[idx + 1] > 1.0  # grows only after the buy


def test_buy_and_hold_tracks_the_asset_from_first_rebalance():
    prices = [100.0 * 1.001**i for i in range(65)]
    panel = _panel({"A": prices})
    result = run_backtest(_Hold("A"), panel, cost_bps=0)
    idx = panel.dates.get_loc(panel.rebalance_dates()[0])
    expected = prices[-1] / prices[idx]  # buy-and-hold total return from the buy point
    assert result.equity.iloc[-1] == pytest.approx(expected, rel=1e-9)


def test_higher_costs_reduce_terminal_equity():
    prices = [100.0 * 1.001**i for i in range(65)]
    panel = _panel({"A": prices})
    free = run_backtest(_Hold("A"), panel, cost_bps=0).equity.iloc[-1]
    pricey = run_backtest(_Hold("A"), panel, cost_bps=20).equity.iloc[-1]
    assert pricey < free


def test_rebalancing_generates_turnover_beyond_the_initial_buy():
    # SPY drifts up, IEF flat → monthly rebalance trims SPY back to 60% → extra turnover + trades
    panel = _panel({"SPY": [100.0 * 1.002**i for i in range(65)], "IEF": [100.0] * 65})
    result = run_backtest(SixtyFortyStrategy(stock="SPY", bond="IEF"), panel, cost_bps=0)
    assert result.total_turnover > 1.0
    assert len(result.trades) >= 2
