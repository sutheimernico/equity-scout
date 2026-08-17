"""run_backtest with explicit rebalance dates (timing-luck study support)."""
import pandas as pd

from equity_scout.engine import run_backtest
from equity_scout.market import PricePanel
from equity_scout.strategies.base import TargetWeight


class AlwaysLong:
    name = "always-long"

    def decide(self, as_of, market):
        return [TargetWeight("AAA", 1.0)]


def _panel() -> PricePanel:
    dates = pd.bdate_range("2026-01-01", periods=60)
    closes = pd.DataFrame({"AAA": [100.0 + i for i in range(60)]}, index=dates)
    return PricePanel(closes)


def test_override_dates_are_the_only_rebalances():
    panel = _panel()
    override = pd.DatetimeIndex([panel.dates[10], panel.dates[40]])
    result = run_backtest(AlwaysLong(), panel, rebalance_dates=override)
    # only the FIRST override trades (the buy-in); date 40 has zero turnover on a held book
    assert [t.date for t in result.trades] == [panel.dates[10].date().isoformat()]
    assert result.weights_by_date.index.tolist() == [panel.dates[10], panel.dates[40]]


def test_default_behaviour_unchanged_without_override():
    panel = _panel()
    result = run_backtest(AlwaysLong(), panel)
    assert len(result.weights_by_date) >= 2  # monthly marks still happen
