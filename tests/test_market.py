import pandas as pd
import pytest

from equity_scout.market import MarketView, PricePanel


def _panel(prices_by_ticker: dict[str, list[float]], start: str = "2021-01-01") -> PricePanel:
    n = len(next(iter(prices_by_ticker.values())))
    idx = pd.bdate_range(start, periods=n)
    return PricePanel(pd.DataFrame(prices_by_ticker, index=idx))


def test_view_reveals_only_data_before_as_of():
    # Each day's price equals its index, so a leaked future price is detectable by value.
    panel = _panel({"AAA": [float(i) for i in range(100)]})
    as_of = panel.dates[50]
    view = MarketView(panel, as_of)
    assert view.latest_date == panel.dates[49]  # strictly before as_of
    assert view.latest_date < as_of
    assert view.last_price("AAA") == 49.0  # NOT 50.0 — the as_of price is invisible


def test_trailing_return_matches_known_series():
    prices = [100.0 + i for i in range(260)]
    panel = _panel({"AAA": prices})
    view = MarketView(panel, panel.dates[-1] + pd.Timedelta(days=1))  # whole series visible
    expected_1m = prices[-1] / prices[-1 - 21] - 1
    expected_12m = prices[-1] / prices[-1 - 252] - 1
    assert view.trailing_return("AAA", 1) == pytest.approx(expected_1m)
    assert view.trailing_return("AAA", 12) == pytest.approx(expected_12m)


def test_trailing_return_none_without_enough_history():
    panel = _panel({"AAA": [100.0] * 30})
    view = MarketView(panel, panel.dates[-1] + pd.Timedelta(days=1))
    assert view.trailing_return("AAA", 12) is None  # needs 252+ days


def test_flat_prices_have_zero_return_and_vol():
    panel = _panel({"AAA": [100.0] * 60})
    view = MarketView(panel, panel.dates[-1] + pd.Timedelta(days=1))
    assert view.trailing_return("AAA", 1) == pytest.approx(0.0)
    assert view.realised_vol("AAA", 21) == pytest.approx(0.0)


def test_rebalance_dates_are_month_ends_in_the_panel():
    panel = _panel({"AAA": [100.0] * 65}, start="2021-01-01")  # ~3 months of business days
    rebal = panel.rebalance_dates("ME")
    assert all(d in set(panel.dates) for d in rebal)
    # each rebalance date is the last panel date of its month
    for d in rebal:
        same_month = [x for x in panel.dates if (x.year, x.month) == (d.year, d.month)]
        assert d == max(same_month)
