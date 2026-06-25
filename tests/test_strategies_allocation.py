"""Tests for the allocation strategies (DCA, Vol-Targeting, Permanent, DAA). All offline."""
from __future__ import annotations

import pandas as pd
import pytest

from equity_scout.market import MarketView, PricePanel
from equity_scout.strategies.base import TargetWeight, weights_dict
from equity_scout.strategies.daa import DefensiveAssetAllocationStrategy, momentum_13612w
from equity_scout.strategies.dca import DCAStrategy
from equity_scout.strategies.ensemble import EnsembleStrategy
from equity_scout.strategies.permanent import PermanentPortfolioStrategy
from equity_scout.strategies.vol_target import VolatilityTargetStrategy


def _geom(ret_12m: float, n: int = 300) -> list[float]:
    g = (1 + ret_12m) ** (1 / 252) - 1
    return [100.0 * (1 + g) ** i for i in range(n)]


def _alternating(daily_vol: float, n: int = 300) -> list[float]:
    """Prices with a known realised vol: alternating +/- daily_vol returns → ann. vol ~ vol*sqrt(252)."""
    prices = [100.0]
    for i in range(n - 1):
        prices.append(prices[-1] * (1 + (daily_vol if i % 2 == 0 else -daily_vol)))
    return prices


def _panel(prices_by_ticker: dict[str, list[float]], start: str = "2020-01-01") -> PricePanel:
    n = len(next(iter(prices_by_ticker.values())))
    return PricePanel(pd.DataFrame(prices_by_ticker, index=pd.bdate_range(start, periods=n)))


def _view_all(panel: PricePanel) -> MarketView:
    return MarketView(panel, panel.dates[-1] + pd.Timedelta(days=1))


NEXT = pd.Timestamp("2099-01-01")


# --- Permanent Portfolio ---
def test_permanent_is_fixed_quarters():
    w = weights_dict(PermanentPortfolioStrategy().decide(NEXT, _view_all(_panel({"SPY": [1.0]}))))
    assert w == {"SPY": 0.25, "TLT": 0.25, "BIL": 0.25, "GLD": 0.25}


# --- Volatility Targeting ---
def test_vol_target_flat_market_goes_to_cash():
    view = _view_all(_panel({"SPY": [100.0] * 200}))
    assert VolatilityTargetStrategy().decide(NEXT, view) == []  # zero vol → no position


def test_vol_target_shrinks_position_as_vol_rises():
    calm = _view_all(_panel({"SPY": _alternating(0.005)}))
    rough = _view_all(_panel({"SPY": _alternating(0.02)}))
    w_calm = weights_dict(VolatilityTargetStrategy().decide(NEXT, calm))["SPY"]
    w_rough = weights_dict(VolatilityTargetStrategy().decide(NEXT, rough))["SPY"]
    assert w_rough < w_calm
    assert w_calm <= 1.0 and w_rough <= 1.0  # never levers up


def test_vol_target_caps_at_leverage_limit_when_calm():
    view = _view_all(_panel({"SPY": _alternating(0.001)}))  # ~1.6% ann vol << 10% target
    assert weights_dict(VolatilityTargetStrategy().decide(NEXT, view))["SPY"] == pytest.approx(1.0)


# --- DCA ---
def test_dca_phases_in_then_holds_full_target():
    panel = _panel({"SPY": [100.0] * 400, "IEF": [100.0] * 400}, start="2020-01-01")
    dca = DCAStrategy(tranches=12)
    early = MarketView(panel, pd.Timestamp("2020-02-15"))  # 1 month in → 2/12 invested
    late = MarketView(panel, pd.Timestamp("2021-06-15"))  # >12 months in → fully invested
    assert weights_dict(dca.decide(pd.Timestamp("2020-02-15"), early))["SPY"] == pytest.approx(0.6 * 2 / 12)
    assert weights_dict(dca.decide(pd.Timestamp("2021-06-15"), late)) == pytest.approx({"SPY": 0.6, "IEF": 0.4})


# --- DAA --- (explicit small universes so assertions are independent of the default basket)
def _daa_panel(trends: dict[str, float]) -> PricePanel:
    return _panel({ticker: _geom(ret) for ticker, ret in trends.items()})


_BASE = {"SPY": 0.10, "VEU": 0.08, "VWO": 0.06, "VNQ": 0.05, "IEF": 0.02, "BIL": 0.01, "GLD": 0.04, "BND": 0.03}


def _daa(top_n: int = 1, offensive=("SPY", "VEU"), defensive=("IEF", "GLD")):
    return DefensiveAssetAllocationStrategy(
        offensive=offensive, defensive=defensive, canary=("VWO", "BND"), top_n=top_n
    )


def test_momentum_13612w_sign_follows_trend():
    up = _view_all(_panel({"X": _geom(0.20)}))
    down = _view_all(_panel({"X": _geom(-0.20)}))
    assert momentum_13612w(up, "X") > 0
    assert momentum_13612w(down, "X") < 0


def test_daa_fully_offensive_when_canary_healthy():
    # both canary (VWO, BND) positive → cash fraction 0 → top-momentum offensive (SPY) at 100%
    view = _view_all(_daa_panel({**_BASE, "SPY": 0.30}))
    assert weights_dict(_daa(top_n=1).decide(NEXT, view)) == {"SPY": 1.0}


def test_daa_spreads_offensive_budget_over_top_n_equally():
    # canary healthy, top_n=2 over {SPY,VEU,VWO}: the two strongest each get half
    trends = {**_BASE, "SPY": 0.30, "VEU": 0.20, "VWO": 0.06}
    daa = _daa(top_n=2, offensive=("SPY", "VEU", "VWO"))
    assert weights_dict(daa.decide(NEXT, _view_all(_daa_panel(trends)))) == pytest.approx({"SPY": 0.5, "VEU": 0.5})


def test_daa_fully_defensive_when_both_canary_negative():
    trends = {**_BASE, "VWO": -0.20, "BND": -0.10, "GLD": 0.15}  # canary both down → cash fraction 1
    view = _view_all(_daa_panel(trends))
    assert weights_dict(_daa().decide(NEXT, view)) == {"GLD": 1.0}


def test_daa_half_defensive_when_one_canary_negative():
    trends = {**_BASE, "SPY": 0.30, "VWO": 0.15, "BND": -0.10, "GLD": 0.15}  # one canary down
    w = weights_dict(_daa(top_n=1).decide(NEXT, _view_all(_daa_panel(trends))))
    assert w == pytest.approx({"SPY": 0.5, "GLD": 0.5})


def test_daa_goes_to_cash_without_enough_history():
    short = _panel({t: [100.0] * 30 for t in _BASE})
    view = MarketView(short, short.dates[-1] + pd.Timedelta(days=1))
    assert weights_dict(_daa().decide(NEXT, view)) == {"BIL": 1.0}


# --- Ensemble (multi-strategy blend) ---
class _Fixed:
    def __init__(self, name: str, weights: dict[str, float]) -> None:
        self.name = name
        self._weights = weights

    def decide(self, as_of, market):
        return [TargetWeight(t, w) for t, w in self._weights.items()]


_ANY_VIEW = MarketView(_panel({"SPY": [100.0] * 5}), pd.Timestamp("2099-01-01"))


def test_ensemble_averages_components_equally():
    blend = EnsembleStrategy([_Fixed("A", {"SPY": 1.0}), _Fixed("B", {"IEF": 1.0})])
    assert weights_dict(blend.decide(NEXT, _ANY_VIEW)) == pytest.approx({"SPY": 0.5, "IEF": 0.5})


def test_ensemble_respects_custom_weights_and_overlap():
    # 75% of a (SPY) + 25% of b (50/50 SPY/IEF) → SPY 0.875, IEF 0.125
    blend = EnsembleStrategy(
        [_Fixed("A", {"SPY": 1.0}), _Fixed("B", {"SPY": 0.5, "IEF": 0.5})], weights=[0.75, 0.25]
    )
    assert weights_dict(blend.decide(NEXT, _ANY_VIEW)) == pytest.approx({"SPY": 0.875, "IEF": 0.125})
