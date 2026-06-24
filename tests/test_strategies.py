import pandas as pd
import pytest

from equity_scout.market import MarketView, PricePanel
from equity_scout.strategies.base import AccountState, clip_weights
from equity_scout.strategies.dual_momentum import DualMomentumStrategy
from equity_scout.strategies.sixty_forty import SixtyFortyStrategy


def _geom(ret_12m: float, n: int = 260) -> list[float]:
    """Price series whose trailing 12-month (252 trading days) return ~= ret_12m."""
    g = (1 + ret_12m) ** (1 / 252) - 1
    return [100.0 * (1 + g) ** i for i in range(n)]


def _view(returns_12m: dict[str, float]) -> MarketView:
    panel = PricePanel(
        pd.DataFrame({t: _geom(r) for t, r in returns_12m.items()}, index=pd.bdate_range("2020-01-01", periods=260))
    )
    return MarketView(panel, panel.dates[-1] + pd.Timedelta(days=1))


STATE = AccountState()
NEXT = pd.Timestamp("2099-01-01")


def test_sixty_forty_is_fixed():
    weights = SixtyFortyStrategy().decide(NEXT, _view({"SPY": 0.1, "IEF": 0.0}), STATE)
    assert weights == {"SPY": 0.6, "IEF": 0.4}


def test_gem_picks_us_when_it_leads_and_beats_cash():
    view = _view({"SPY": 0.20, "VEU": 0.05, "BIL": 0.01, "IEF": 0.0})
    assert DualMomentumStrategy().decide(NEXT, view, STATE) == {"SPY": 1.0}


def test_gem_picks_international_when_it_leads():
    view = _view({"SPY": 0.05, "VEU": 0.20, "BIL": 0.01, "IEF": 0.0})
    assert DualMomentumStrategy().decide(NEXT, view, STATE) == {"VEU": 1.0}


def test_gem_goes_defensive_when_risk_assets_fail_absolute_momentum():
    # both risky assets below the T-bill hurdle → bonds
    view = _view({"SPY": -0.10, "VEU": -0.05, "BIL": 0.01, "IEF": 0.0})
    assert DualMomentumStrategy().decide(NEXT, view, STATE) == {"IEF": 1.0}


def test_gem_defensive_without_enough_history():
    panel = PricePanel(
        pd.DataFrame({t: [100.0] * 30 for t in ["SPY", "VEU", "BIL", "IEF"]},
                     index=pd.bdate_range("2020-01-01", periods=30))
    )
    view = MarketView(panel, panel.dates[-1] + pd.Timedelta(days=1))
    assert DualMomentumStrategy().decide(NEXT, view, STATE) == {"IEF": 1.0}


def test_clip_weights_drops_negatives_and_caps_at_one():
    assert clip_weights({"A": 0.6, "B": -0.1, "C": 0.0}) == {"A": 0.6}
    capped = clip_weights({"A": 0.8, "B": 0.8})  # sums to 1.6 → scale to 1.0
    assert capped == pytest.approx({"A": 0.5, "B": 0.5})
