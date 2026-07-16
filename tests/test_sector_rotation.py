"""Sector rotation strategy: ranking, hurdle, skip-young-tickers, defensive floor."""
from __future__ import annotations

import pandas as pd
import pytest

from equity_scout.etf_universe import SECTOR_ETF_TICKERS
from equity_scout.market import MarketView, PricePanel
from equity_scout.strategies.base import weights_dict
from equity_scout.strategies.registry import default_strategies
from equity_scout.strategies.sector_rotation import SectorRotationStrategy

NEXT = pd.Timestamp("2099-01-01")


def _geom(ret_12m: float, n: int = 260) -> list[float]:
    g = (1 + ret_12m) ** (1 / 252) - 1
    return [100.0 * (1 + g) ** i for i in range(n)]


def _view(returns_12m: dict[str, float]) -> MarketView:
    panel = PricePanel(
        pd.DataFrame(
            {t: _geom(r) for t, r in returns_12m.items()},
            index=pd.bdate_range("2020-01-01", periods=260),
        )
    )
    return MarketView(panel, panel.dates[-1] + pd.Timedelta(days=1))


def _sector_returns(**overrides: float) -> dict[str, float]:
    """All 11 sectors flat by default, plus hurdle/safe legs; overrides set winners."""
    returns = {ticker: 0.02 for ticker in SECTOR_ETF_TICKERS}
    returns.update({"BIL": 0.01, "IEF": 0.0})
    returns.update(overrides)
    return returns


def test_top3_equal_weight_when_all_beat_the_hurdle():
    view = _view(_sector_returns(XLK=0.30, XLE=0.25, XLF=0.20))
    weights = weights_dict(SectorRotationStrategy().decide(NEXT, view))
    assert weights == pytest.approx({"XLK": 1 / 3, "XLE": 1 / 3, "XLF": 1 / 3})


def test_slot_failing_absolute_momentum_goes_to_bonds():
    # Two clear winners; every other sector sits below the T-bill hurdle.
    returns = {ticker: -0.05 for ticker in SECTOR_ETF_TICKERS}
    returns.update({"XLK": 0.30, "XLE": 0.25, "BIL": 0.01, "IEF": 0.0})
    view = _view(returns)
    weights = weights_dict(SectorRotationStrategy().decide(NEXT, view))
    assert weights == pytest.approx({"XLK": 1 / 3, "XLE": 1 / 3, "IEF": 1 / 3})


def test_all_slots_defensive_in_a_broad_downturn():
    returns = {ticker: -0.20 for ticker in SECTOR_ETF_TICKERS}
    returns.update({"BIL": 0.01, "IEF": 0.0})
    view = _view(returns)
    weights = weights_dict(SectorRotationStrategy().decide(NEXT, view))
    assert weights == pytest.approx({"IEF": 1.0})


def test_young_sectors_are_skipped_not_guessed():
    """XLC/XLRE missing from the panel entirely (pre-listing era): the remaining nine
    are still rankable, the strategy trades on."""
    returns = _sector_returns(XLK=0.30, XLV=0.25, XLI=0.20)
    del returns["XLC"], returns["XLRE"]
    view = _view(returns)
    weights = weights_dict(SectorRotationStrategy().decide(NEXT, view))
    assert weights == pytest.approx({"XLK": 1 / 3, "XLV": 1 / 3, "XLI": 1 / 3})


def test_too_few_rankable_sectors_sits_fully_defensive():
    view = _view({"XLK": 0.30, "XLF": 0.10, "BIL": 0.01, "IEF": 0.0})  # only 2 sectors
    weights = weights_dict(SectorRotationStrategy().decide(NEXT, view))
    assert weights == pytest.approx({"IEF": 1.0})


def test_defensive_falls_back_to_cash_proxy_without_bonds():
    returns = {ticker: -0.20 for ticker in SECTOR_ETF_TICKERS}
    returns["BIL"] = 0.01  # no IEF in the panel
    view = _view(returns)
    weights = weights_dict(SectorRotationStrategy().decide(NEXT, view))
    assert weights == pytest.approx({"BIL": 1.0})


def test_registered_in_default_strategies_but_not_in_the_blend():
    strategies = default_strategies()
    names = [s.name for s in strategies]
    assert "Sektor-Rotation (Top 3)" in names
    blend = next(s for s in strategies if "Mix" in s.name or "Blend" in s.name)
    members = getattr(blend, "strategies", getattr(blend, "members", []))
    assert all("Sektor" not in getattr(m, "name", "") for m in members)
