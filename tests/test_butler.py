"""Monthly ETF core savings-plan block (v9 Anlage-Butler): pure budget-split math + rendering."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from equity_scout.butler import (
    build_core_plan,
    core_running_line,
    monthly_budget,
    render_core_block,
)
from equity_scout.market import PricePanel


def _series(annual_return: float, n: int, phase: float = 0.0,
            wave_amp: float = 0.015, wave_period: float = 90.0) -> list[float]:
    """Smoothly compounding price series (~annual_return trailing 12m return) with a small
    sinusoidal overlay so realised volatility isn't exactly zero (vol_target needs > 0) —
    same idiom as tests/test_strategies.py's _geom() helper plus conftest's wavy_panel."""
    g = (1 + annual_return) ** (1 / 252) - 1
    return [
        100.0 * (1 + g) ** i * (1 + wave_amp * math.sin(i / wave_period + phase))
        for i in range(n)
    ]


@pytest.fixture
def panel_fixture() -> PricePanel:
    """~14 months of daily history (290 bdays > the 253 a 12-month momentum lookback needs)
    for the Multi-Strategie-Mix components' full universe: GEM (SPY/VEU/IEF/BIL), DAA
    offensive/defensive/canary (+ VWO/TLT/BND/GLD), Permanent Portfolio (SPY/TLT/BIL/GLD),
    Vol-Targeting (SPY). SPY has the strongest trend so GEM/DAA can actually decide instead
    of defaulting to cash for lack of history."""
    n = 290
    idx = pd.bdate_range("2019-01-01", periods=n)
    returns_and_phase = {
        "SPY": (0.22, 0.0),
        "VEU": (0.09, 0.6),
        "VWO": (0.11, 1.2),
        "IEF": (0.03, 1.8),
        "TLT": (0.04, 2.4),
        "BND": (0.025, 3.0),
        "BIL": (0.015, 3.6),
        "GLD": (0.08, 4.2),
    }
    data = {t: _series(r, n, phase=phase) for t, (r, phase) in returns_and_phase.items()}
    return PricePanel(pd.DataFrame(data, index=idx))


def test_monthly_budget_default_and_parse(capsys):
    assert monthly_budget({}) == 500
    assert monthly_budget({"COPILOT_MONTHLY_BUDGET": "800"}) == 800
    assert monthly_budget({"COPILOT_MONTHLY_BUDGET": "quatsch"}) == 500
    assert "COPILOT_MONTHLY_BUDGET" in capsys.readouterr().err


def test_build_core_plan_splits_core_budget(panel_fixture):
    plan = build_core_plan(panel_fixture, monthly_budget_eur=500)
    assert plan is not None
    assert plan["core_budget"] == 400 and plan["satellite_budget"] == 100
    total = sum(p["amount_eur"] for p in plan["positions"]) + plan["cash_rest"]
    assert total == 400
    assert all(p["amount_eur"] >= 1 for p in plan["positions"])
    assert plan["positions"] == sorted(plan["positions"], key=lambda p: -p["amount_eur"])


def test_build_core_plan_none_on_broken_panel():
    assert build_core_plan(None, monthly_budget_eur=500) is None


def test_build_core_plan_rounding_sum_matches_core_budget_exactly(panel_fixture):
    # A "crooked" budget (333 -> core_budget = round(266.4) = 266) is the case most likely
    # to expose per-position round() overhang; the invariant (sum == core_budget, no
    # negative cash) must hold whichever way the roundings fall.
    plan = build_core_plan(panel_fixture, monthly_budget_eur=333)
    assert plan is not None
    assert plan["core_budget"] == 266
    assert plan["cash_rest"] >= 0
    assert sum(p["amount_eur"] for p in plan["positions"]) + plan["cash_rest"] == 266


def test_build_core_plan_reduces_largest_position_when_rounding_overshoots(monkeypatch):
    """Deterministic coverage of the ACHTUNG fix: three equal-ish weights whose rounded
    amounts sum above core_budget (100/3 -> 33.33 each -> round() gives 33+33+33=99, but a
    skewed split below forces an overshoot) must not yield a negative cash_rest."""
    import equity_scout.butler as butler_mod

    class _StubStrategy:
        name = "Multi-Strategie-Mix"

        def decide(self, as_of, market):
            from equity_scout.strategies.base import TargetWeight

            # 0.335 + 0.335 + 0.33 = 1.0 exactly, but round(33.5) + round(33.5) + round(33)
            # = 34 + 34 + 33 = 101 > core_budget (100) without the overhang fix.
            return [
                TargetWeight("SPY", 0.335),
                TargetWeight("VEU", 0.335),
                TargetWeight("IEF", 0.33),
            ]

    monkeypatch.setattr(butler_mod, "default_strategies", lambda: [_StubStrategy()])
    panel = PricePanel(pd.DataFrame({"SPY": [1.0], "VEU": [1.0], "IEF": [1.0]},
                                     index=pd.bdate_range("2026-01-01", periods=1)))
    plan = build_core_plan(panel, monthly_budget_eur=125)  # core_budget = round(125*0.8) = 100
    assert plan["core_budget"] == 100
    assert plan["cash_rest"] == 0
    assert sum(p["amount_eur"] for p in plan["positions"]) == 100
    # the largest position absorbed the 1 EUR overhang, not an arbitrary one
    assert plan["positions"][0]["amount_eur"] == 33


def test_render_core_block_plain_and_html(panel_fixture):
    plan = build_core_plan(panel_fixture, monthly_budget_eur=500)
    plain = render_core_block(plan, month_label="Juli", html=False)
    assert "Monats-Sparplan Juli" in plain and "Kern (80 % = 400 €)" in plain
    assert "Keine Anlageberatung" in plain
    html_out = render_core_block(plan, month_label="Juli", html=True)
    assert "<b>" in html_out


def test_core_running_line_plain_and_html():
    plain = core_running_line(html=False)
    assert "Sparplan-Kern" in plain and "<" not in plain
    html_out = core_running_line(html=True)
    assert "Sparplan-Kern" in html_out
