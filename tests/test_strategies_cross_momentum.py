"""Cross-sectional momentum (v16 T2). The skip-month is what makes this different from the
repo's other momentum strategies, so it gets a test that FAILS without it.
"""
from __future__ import annotations

import pandas as pd
import pytest

from equity_scout.market import MarketView, PricePanel
from equity_scout.strategies.base import weights_dict
from equity_scout.strategies.cross_momentum import CrossSectionalMomentumStrategy

NEXT = pd.Timestamp("2099-01-01")
DAYS = 300


def _path(monthly: dict[int, float], *, n: int = DAYS) -> list[float]:
    """Price path where `monthly[k]` is the simple return during the k-th month back from the
    end (0 = most recent 21 trading days). Unlisted months are flat."""
    prices = [100.0]
    for i in range(1, n):
        months_back = (n - 1 - i) // 21
        step = (1.0 + monthly.get(months_back, 0.0)) ** (1 / 21) - 1.0
        prices.append(prices[-1] * (1.0 + step))
    return prices


def _view(paths: dict[str, list[float]]) -> MarketView:
    panel = PricePanel(pd.DataFrame(paths, index=pd.bdate_range("2023-01-02", periods=DAYS)))
    return MarketView(panel, panel.dates[-1] + pd.Timedelta(days=1))


def _flat_universe(names: list[str]) -> dict[str, list[float]]:
    return {n: _path({}) for n in names}


def test_the_skip_month_excludes_the_most_recent_month_from_the_ranking():
    """STEADY rose 2 % in each of months 11..1 and was flat last month.
    SPIKE was flat for months 11..1 and jumped 25 % last month.

    On a plain 12-month return SPIKE wins. On 12-1 — what Jegadeesh & Titman measured, because
    the last month tends to reverse — STEADY must win.
    """
    paths = _flat_universe(["F1", "F2", "F3", "F4", "F5", "BIL", "IEF"])
    paths["STEADY"] = _path({m: 0.02 for m in range(1, 12)})
    paths["SPIKE"] = _path({0: 0.25})
    strategy = CrossSectionalMomentumStrategy(
        universe=tuple(paths), top_n=1, min_rankable=3
    )
    held = weights_dict(strategy.decide(NEXT, _view(paths)))
    assert "STEADY" in held, held
    assert "SPIKE" not in held

    # Counterfactual: with the skip disabled the spike DOES win — proving the test bites on
    # the skip logic itself and not on some incidental ordering.
    no_skip = CrossSectionalMomentumStrategy(
        universe=tuple(paths), top_n=1, skip_months=0, min_rankable=3
    )
    assert "SPIKE" in weights_dict(no_skip.decide(NEXT, _view(paths)))


def test_it_holds_the_top_n_equal_weighted():
    paths = _flat_universe(["BIL", "IEF", "F1", "F2"])
    for i, name in enumerate(["W1", "W2", "W3"], start=1):
        paths[name] = _path({m: 0.01 * i for m in range(1, 12)})
    strategy = CrossSectionalMomentumStrategy(universe=tuple(paths), top_n=2, min_rankable=3)
    held = weights_dict(strategy.decide(NEXT, _view(paths)))
    assert set(held) == {"W3", "W2"}  # the two strongest
    assert held["W3"] == pytest.approx(0.5)
    assert held["W2"] == pytest.approx(0.5)


def test_a_slot_below_the_cash_hurdle_goes_defensive_instead():
    """Relative strength inside a falling market is still a falling book."""
    paths = {n: _path({m: -0.02 for m in range(1, 12)}) for n in ["D1", "D2", "D3", "D4", "D5"]}
    paths["BIL"] = _path({m: 0.003 for m in range(1, 12)})  # cash quietly earns
    paths["IEF"] = _path({m: 0.001 for m in range(1, 12)})
    strategy = CrossSectionalMomentumStrategy(universe=tuple(paths), top_n=2, min_rankable=3)
    held = weights_dict(strategy.decide(NEXT, _view(paths)))
    assert held.get("IEF", 0.0) == pytest.approx(1.0)  # both slots failed the hurdle


def test_too_little_history_is_defensive_not_a_guess():
    short = pd.DataFrame(
        {t: [100.0] * 40 for t in ("A", "B", "C", "BIL", "IEF")},
        index=pd.bdate_range("2024-01-01", periods=40),
    )
    panel = PricePanel(short)
    view = MarketView(panel, panel.dates[-1] + pd.Timedelta(days=1))
    strategy = CrossSectionalMomentumStrategy(universe=("A", "B", "C"), min_rankable=3)
    held = weights_dict(strategy.decide(NEXT, view))
    assert set(held) <= {"IEF", "BIL"}
    assert sum(held.values()) == pytest.approx(1.0)
