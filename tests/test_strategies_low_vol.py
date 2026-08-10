"""Low-vol anomaly (v16 T1): picks by RISK, weights inversely to it, and refuses to rank
a stale feed as "calm" — that last one is the strategy's most damaging failure mode.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from equity_scout.market import MarketView, PricePanel
from equity_scout.strategies.base import weights_dict
from equity_scout.strategies.low_vol import LowVolatilityStrategy

NEXT = pd.Timestamp("2099-01-01")


def _series(vol_annual: float, n: int = 200, seed: int = 0) -> list[float]:
    """Random walk whose annualised daily-return stdev is approximately `vol_annual`."""
    rng = np.random.default_rng(seed)
    daily = vol_annual / np.sqrt(252)
    steps = rng.normal(0.0, daily, n)
    prices, price = [], 100.0
    for step in steps:
        price *= 1.0 + step
        prices.append(price)
    return prices


def _view(vols: dict[str, float], *, flat: tuple[str, ...] = ()) -> MarketView:
    data = {t: _series(v, seed=i) for i, (t, v) in enumerate(vols.items())}
    for t in flat:
        data[t] = [100.0] * 200  # a stale feed: repeats its last price, reads as zero risk
    panel = PricePanel(pd.DataFrame(data, index=pd.bdate_range("2024-01-01", periods=200)))
    return MarketView(panel, panel.dates[-1] + pd.Timedelta(days=1))


def _uni(vols: dict[str, float], *, flat: tuple[str, ...] = ()) -> tuple[str, ...]:
    return tuple(vols) + flat


def test_it_holds_the_calmest_assets_and_ignores_the_turbulent_ones():
    vols = {"CALM1": 0.05, "CALM2": 0.07, "MID1": 0.20, "MID2": 0.25,
            "WILD1": 0.60, "WILD2": 0.80}
    strategy = LowVolatilityStrategy(universe=_uni(vols), top_n=2, min_rankable=3)
    held = weights_dict(strategy.decide(NEXT, _view(vols)))
    assert set(held) == {"CALM1", "CALM2"}
    assert "WILD1" not in held and "MID1" not in held


def test_weights_are_inverse_to_volatility_not_equal():
    """Equal weights inside the calm set would discard the very signal it selects on."""
    vols = {"A": 0.05, "B": 0.10, "C": 0.30, "D": 0.35, "E": 0.40, "F": 0.50}
    strategy = LowVolatilityStrategy(universe=_uni(vols), top_n=2, min_rankable=3)
    held = weights_dict(strategy.decide(NEXT, _view(vols)))
    assert held["A"] > held["B"]  # the calmer of the two gets more
    assert sum(held.values()) == pytest.approx(1.0)


def test_a_stale_feed_is_never_ranked_as_the_calmest_asset():
    """A repeated last price has zero measured volatility. Ranking it first would put the
    entire book into a broken data feed — refuse it instead."""
    vols = {"A": 0.10, "B": 0.12, "C": 0.15, "D": 0.20, "E": 0.30, "F": 0.40}
    strategy = LowVolatilityStrategy(
        universe=_uni(vols, flat=("BROKEN",)), top_n=2, min_rankable=3
    )
    held = weights_dict(strategy.decide(NEXT, _view(vols, flat=("BROKEN",))))
    assert "BROKEN" not in held
    assert set(held) == {"A", "B"}


def test_too_few_rankable_assets_go_to_the_cash_proxy():
    vols = {"A": 0.10, "B": 0.12}
    strategy = LowVolatilityStrategy(
        universe=_uni(vols) + ("BIL",), top_n=3, min_rankable=6, safe="BIL"
    )
    view = _view({**vols, "BIL": 0.01})
    held = weights_dict(strategy.decide(NEXT, view))
    assert held == {"BIL": 1.0}


def test_it_never_looks_at_returns():
    """The point of the family: a rally in a turbulent asset must not attract this strategy.
    Same vols, wildly different drifts -> same selection."""
    vols = {"A": 0.05, "B": 0.07, "C": 0.30, "D": 0.35, "E": 0.40, "F": 0.50}
    strategy = LowVolatilityStrategy(universe=_uni(vols), top_n=2, min_rankable=3)
    calm_pick = set(weights_dict(strategy.decide(NEXT, _view(vols))))

    # Give the turbulent names a strong uptrend on top of their noise.
    data = {t: _series(v, seed=i) for i, (t, v) in enumerate(vols.items())}
    for t in ("C", "D", "E", "F"):
        data[t] = [p * (1.004 ** i) for i, p in enumerate(data[t])]
    panel = PricePanel(pd.DataFrame(data, index=pd.bdate_range("2024-01-01", periods=200)))
    trending = MarketView(panel, panel.dates[-1] + pd.Timedelta(days=1))
    assert set(weights_dict(strategy.decide(NEXT, trending))) == calm_pick
