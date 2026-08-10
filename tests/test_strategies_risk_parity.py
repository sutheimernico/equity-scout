"""Naive risk parity (v16 T4): holds everything, sizes by inverse volatility, caps any single
asset, and never routes freed weight to cash — it makes no market call by construction.
"""
from __future__ import annotations

import pandas as pd
import pytest

from equity_scout.market import MarketView, PricePanel
from equity_scout.strategies.base import weights_dict
from equity_scout.strategies.risk_parity import RiskParityStrategy

NEXT = pd.Timestamp("2099-01-01")
DAYS = 200


def _wobble(vol_daily: float, n: int = DAYS) -> list[float]:
    """Deterministic series with a known daily stdev — no seeds, no flaky assertions."""
    prices, price = [], 100.0
    for i in range(n):
        price *= 1.0 + (vol_daily if i % 2 else -vol_daily)
        prices.append(price)
    return prices


def _view(vols: dict[str, float]) -> MarketView:
    panel = PricePanel(pd.DataFrame(
        {t: _wobble(v) for t, v in vols.items()},
        index=pd.bdate_range("2024-01-01", periods=DAYS),
    ))
    return MarketView(panel, panel.dates[-1] + pd.Timedelta(days=1))


def test_it_holds_every_asset_and_weights_the_calm_ones_higher():
    vols = {"BOND": 0.002, "GOLD": 0.006, "EQ": 0.010, "COMMOD": 0.014}
    strategy = RiskParityStrategy(sleeve=tuple(vols), min_assets=4)
    held = weights_dict(strategy.decide(NEXT, _view(vols)))
    assert set(held) == set(vols)  # nothing is excluded — that is the family's whole point
    assert held["BOND"] > held["GOLD"] > held["EQ"] > held["COMMOD"]
    assert sum(held.values()) == pytest.approx(1.0)


def test_weights_are_inversely_proportional_to_volatility():
    """Twice the volatility must get half the weight — the actual parity claim."""
    vols = {"A": 0.004, "B": 0.008, "C": 0.008, "D": 0.008}
    strategy = RiskParityStrategy(sleeve=tuple(vols), min_assets=4, max_weight=1.0)
    held = weights_dict(strategy.decide(NEXT, _view(vols)))
    assert held["A"] == pytest.approx(2 * held["B"], rel=0.05)
    assert held["B"] == pytest.approx(held["C"], rel=0.02)


def test_a_single_calm_asset_cannot_take_over_the_book():
    """Without the cap, one asset in a quiet regime takes 70 %+ and "parity" stops being true."""
    vols = {"VERYCALM": 0.0006, "A": 0.02, "B": 0.02, "C": 0.02}
    strategy = RiskParityStrategy(sleeve=tuple(vols), min_assets=4, max_weight=0.40)
    held = weights_dict(strategy.decide(NEXT, _view(vols)))
    assert held["VERYCALM"] == pytest.approx(0.40)
    assert sum(held.values()) == pytest.approx(1.0)  # freed weight went to the others…
    assert all(w <= 0.40 + 1e-9 for w in held.values())  # …without breaching the cap


def test_freed_weight_goes_to_the_other_assets_not_to_cash():
    """Cash would be a market call, and this strategy makes none."""
    vols = {"VERYCALM": 0.0006, "A": 0.02, "B": 0.02, "C": 0.02}
    strategy = RiskParityStrategy(
        sleeve=tuple(vols), min_assets=4, max_weight=0.40, safe="BIL"
    )
    held = weights_dict(strategy.decide(NEXT, _view(vols)))
    assert "BIL" not in held
    assert sum(held.values()) == pytest.approx(1.0)


def test_a_stale_feed_is_dropped_rather_than_weighted_as_riskless():
    vols = {"A": 0.004, "B": 0.006, "C": 0.008, "D": 0.010}
    data = {t: _wobble(v) for t, v in vols.items()}
    data["BROKEN"] = [100.0] * DAYS
    panel = PricePanel(pd.DataFrame(data, index=pd.bdate_range("2024-01-01", periods=DAYS)))
    view = MarketView(panel, panel.dates[-1] + pd.Timedelta(days=1))
    strategy = RiskParityStrategy(sleeve=tuple(data), min_assets=4)
    held = weights_dict(strategy.decide(NEXT, view))
    assert "BROKEN" not in held
    assert sum(held.values()) == pytest.approx(1.0)


def test_too_few_priced_assets_fall_back_to_cash():
    vols = {"A": 0.004, "B": 0.006}
    strategy = RiskParityStrategy(
        sleeve=tuple(vols) + ("BIL",), min_assets=5, safe="BIL"
    )
    held = weights_dict(strategy.decide(NEXT, _view({**vols, "BIL": 0.0006})))
    assert held == {"BIL": 1.0}
