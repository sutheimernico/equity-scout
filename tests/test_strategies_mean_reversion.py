"""Mean reversion (v16 T3). Three things must hold or the family is worthless: it buys losers
(not winners), it refuses to trade in a downtrend, and it normalises by volatility so it does
not degenerate into "hold the most volatile asset".

All series are DETERMINISTIC (alternating steps plus drift) rather than random. A first draft
used seeded random walks and one filler happened to land a higher z-score than the asset under
test — the assertion then measured the seed, not the behaviour.
"""
from __future__ import annotations

import pandas as pd
import pytest

from equity_scout.market import MarketView, PricePanel
from equity_scout.strategies.base import weights_dict
from equity_scout.strategies.mean_reversion import MeanReversionStrategy

NEXT = pd.Timestamp("2099-01-01")
DAYS = 260


def _wobble(*, drift: float, wobble: float, n: int = DAYS) -> list[float]:
    """Deterministic path with a known daily stdev (~`wobble`) and a steady drift."""
    prices, price = [], 100.0
    for i in range(n):
        step = drift + (wobble if i % 2 else -wobble)
        price *= 1.0 + step
        prices.append(price)
    return prices


def _rising(n: int = DAYS, per_day: float = 0.0006) -> list[float]:
    """Trend WITH volatility — a perfectly smooth series reads as a stale feed and is
    deliberately refused by the strategy, which would make it unrankable rather than strong."""
    return _wobble(drift=per_day, wobble=0.004, n=n)


def _falling(n: int = DAYS, per_day: float = 0.0006) -> list[float]:
    return _wobble(drift=-per_day, wobble=0.004, n=n)


def _dip(depth: float, *, wobble: float = 0.004, n: int = DAYS) -> list[float]:
    """A series that wobbles flat, then drops `depth` over its last three days."""
    prices = _wobble(drift=0.0, wobble=wobble, n=n - 3)
    price = prices[-1]
    for _ in range(3):
        price *= 1.0 - depth / 3.0
        prices.append(price)
    return prices


def _view(extra: dict[str, list[float]], *, market: list[float] | None = None) -> MarketView:
    data = {"SPY": market if market is not None else _rising(), "BIL": _rising(per_day=0.00008)}
    data.update(extra)
    panel = PricePanel(pd.DataFrame(data, index=pd.bdate_range("2023-01-02", periods=DAYS)))
    return MarketView(panel, panel.dates[-1] + pd.Timedelta(days=1))


def _fillers(k: int) -> dict[str, list[float]]:
    """Rankable but NOT oversold: they wobble (so they have measurable vol) and end above
    their own mean (so their z-score is negative)."""
    return {f"N{i}": _rising(per_day=0.001) for i in range(k)}


def test_it_buys_the_oversold_names_not_the_strong_ones():
    extra = _fillers(5)
    extra["DEEP"] = _dip(0.12)
    extra["STRONG"] = _rising(per_day=0.002)
    strategy = MeanReversionStrategy(universe=tuple(extra), top_n=1, min_rankable=3)
    held = weights_dict(strategy.decide(NEXT, _view(extra)))
    assert "DEEP" in held, held
    assert "STRONG" not in held


def test_a_downtrending_market_stops_it_trading_entirely():
    """"Fell hardest" in a bear market selects the names that keep falling."""
    extra = {f"D{i}": _dip(0.05) for i in range(6)}
    strategy = MeanReversionStrategy(universe=tuple(extra), top_n=2, min_rankable=3)
    held = weights_dict(strategy.decide(NEXT, _view(extra, market=_falling())))
    assert held == {"BIL": 1.0}


def test_it_normalises_by_volatility_so_the_wildest_asset_does_not_always_win():
    """A calm name 3 % below its mean is a stronger signal than a wild one 5 % below.
    Without the z-score this strategy silently becomes a volatility bet."""
    extra = _fillers(5)
    extra["CALM_DIP"] = _dip(0.03, wobble=0.002)   # smaller drop, very quiet series
    extra["WILD_DIP"] = _dip(0.05, wobble=0.02)    # bigger drop, but noisy anyway
    strategy = MeanReversionStrategy(universe=tuple(extra), top_n=1, min_rankable=3)
    held = weights_dict(strategy.decide(NEXT, _view(extra)))
    assert "CALM_DIP" in held, held
    assert "WILD_DIP" not in held


def test_nothing_oversold_means_cash_not_the_least_overbought_name():
    extra = {f"U{i}": _rising(per_day=0.001 + i * 0.0002) for i in range(6)}
    strategy = MeanReversionStrategy(universe=tuple(extra), top_n=2, min_rankable=3)
    held = weights_dict(strategy.decide(NEXT, _view(extra)))
    assert held == {"BIL": 1.0}


def test_unfilled_slots_stay_in_cash_instead_of_concentrating():
    extra = _fillers(5)
    extra["ONE_DIP"] = _dip(0.10)
    strategy = MeanReversionStrategy(universe=tuple(extra), top_n=3, min_rankable=3)
    held = weights_dict(strategy.decide(NEXT, _view(extra)))
    assert held["ONE_DIP"] == pytest.approx(1 / 3)  # one third, not the whole book
    assert sum(held.values()) == pytest.approx(1 / 3)


def test_an_unestablished_trend_is_not_treated_as_an_uptrend():
    short = pd.DataFrame(
        {"SPY": _rising(n=50), "BIL": _rising(n=50, per_day=0.00008),
         "A": _dip(0.1, n=50), "B": _dip(0.1, n=50), "C": _dip(0.1, n=50)},
        index=pd.bdate_range("2024-01-01", periods=50),
    )
    panel = PricePanel(short)
    view = MarketView(panel, panel.dates[-1] + pd.Timedelta(days=1))
    strategy = MeanReversionStrategy(universe=("A", "B", "C"), top_n=2, min_rankable=3)
    assert weights_dict(strategy.decide(NEXT, view)) == {"BIL": 1.0}


def test_a_stale_feed_is_refused_rather_than_scored_as_a_huge_dip():
    """A repeated price has zero measured vol; dividing by it would manufacture an enormous
    z-score and hand the whole book to a broken series."""
    extra = _fillers(5)
    extra["DEEP"] = _dip(0.12)
    extra["BROKEN"] = [100.0] * DAYS
    strategy = MeanReversionStrategy(universe=tuple(extra), top_n=1, min_rankable=3)
    held = weights_dict(strategy.decide(NEXT, _view(extra)))
    assert "BROKEN" not in held
    assert "DEEP" in held
