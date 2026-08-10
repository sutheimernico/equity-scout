"""Protections: per-rule behaviour, breaker hysteresis/cooldown path, chain composition."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from equity_scout.autotrader_protections import (
    BreakerState,
    ConcentrationCap,
    DrawdownBreaker,
    RegimeGate,
    RiskContext,
    VolTarget,
    apply_protections,
    default_protections,
)


def _ctx(**overrides) -> RiskContext:
    defaults = dict(as_of=pd.Timestamp("2026-07-20"))
    defaults.update(overrides)
    return RiskContext(**defaults)


def _returns(vol_daily: float, days: int = 40) -> pd.Series:
    rng = np.random.default_rng(3)
    return pd.Series(rng.normal(0.0, vol_daily, size=days))


class TestConcentrationCap:
    def test_clips_only_offenders_and_reports_them(self) -> None:
        weights = {"AAPL": 0.25, "MSFT": 0.05, "TSLA": -0.18}
        out, event = ConcentrationCap(cap=0.10).apply(weights, _ctx())
        assert out == {"AAPL": 0.10, "MSFT": 0.05, "TSLA": -0.10}
        assert event is not None
        assert "AAPL" in event.detail and "TSLA" in event.detail and "MSFT" not in event.detail

    def test_no_event_when_nothing_exceeds_the_cap(self) -> None:
        weights = {"AAPL": 0.08}
        out, event = ConcentrationCap(cap=0.10).apply(weights, _ctx())
        assert out == weights
        assert event is None

    def test_clipped_mass_stays_cash_by_default(self) -> None:
        """The live depot has run this way since 2026-07-16 — the default must not drift."""
        weights = {"AAPL": 0.25, "MSFT": 0.05}
        out, _ = ConcentrationCap(cap=0.10).apply(weights, _ctx())
        assert out == {"AAPL": 0.10, "MSFT": 0.05}
        assert sum(out.values()) == pytest.approx(0.15)  # 0.15 of the 0.30 became cash

    def test_redistribute_spreads_the_freed_weight_over_the_names_under_the_cap(self) -> None:
        """Measured 2026-08-10: eight sleeves looking through onto a shared ETF core pinned
        SPY/IEF/VEU at the cap and left 39.8 % in cash that no risk rule asked for.

        Sized so the headroom (0.12) exceeds the freed weight (0.04) — then the gross
        exposure is fully preserved and the split is visibly proportional.
        """
        weights = {"SPY": 0.14, "IEF": 0.06, "GLD": 0.02}
        out, event = ConcentrationCap(cap=0.10, redistribute=True).apply(weights, _ctx())
        assert out["SPY"] == pytest.approx(0.10)           # still capped
        assert sum(out.values()) == pytest.approx(0.22)    # gross preserved, not 0.18
        assert out["IEF"] == pytest.approx(0.09)           # 0.04 * 6/8 on top of 0.06
        assert out["GLD"] == pytest.approx(0.03)           # 0.04 * 2/8 on top of 0.02
        assert event is not None and "verteilt" in event.detail

    def test_freed_weight_beyond_the_available_headroom_stays_cash(self) -> None:
        """0.15 freed but only 0.12 of headroom: place what fits, keep the rest honest."""
        weights = {"SPY": 0.25, "IEF": 0.06, "GLD": 0.02}
        out, _ = ConcentrationCap(cap=0.10, redistribute=True).apply(weights, _ctx())
        assert all(w == pytest.approx(0.10) for w in out.values())  # all three at the cap
        assert sum(out.values()) == pytest.approx(0.30)  # 0.03 of the 0.33 remains cash

    def test_redistribution_never_pushes_a_name_past_the_cap(self) -> None:
        weights = {"SPY": 0.40, "IEF": 0.09}
        out, _ = ConcentrationCap(cap=0.10, redistribute=True).apply(weights, _ctx())
        assert all(abs(w) <= 0.10 + 1e-9 for w in out.values())
        # Everything that fits is placed; the rest honestly stays cash rather than breaching.
        assert sum(out.values()) == pytest.approx(0.20)

    def test_redistribution_respects_the_sign_of_a_short(self) -> None:
        weights = {"SPY": 0.30, "QQQ": -0.04}
        out, _ = ConcentrationCap(cap=0.10, redistribute=True).apply(weights, _ctx())
        assert out["SPY"] == pytest.approx(0.10)
        assert out["QQQ"] < -0.04  # a short grows MORE negative, never flips direction
        assert abs(out["QQQ"]) <= 0.10 + 1e-9


class TestRegimeGate:
    def test_red_halves_exposure(self) -> None:
        out, event = RegimeGate().apply({"SPY": 0.6}, _ctx(regime_level="red"))
        assert out == {"SPY": 0.3}
        assert event is not None

    @pytest.mark.parametrize("level", ["green", "yellow", "unknown", None])
    def test_non_red_levels_do_nothing(self, level) -> None:
        out, event = RegimeGate().apply({"SPY": 0.6}, _ctx(regime_level=level))
        assert out == {"SPY": 0.6}
        assert event is None


class TestVolTarget:
    def test_inactive_without_enough_history(self) -> None:
        out, event = VolTarget().apply({"SPY": 1.0}, _ctx(depot_returns=_returns(0.05, days=15)))
        assert out == {"SPY": 1.0}
        assert event is None

    def test_scales_down_when_vol_exceeds_target(self) -> None:
        ctx = _ctx(depot_returns=_returns(0.03))  # ~48% annualised, way over 12%
        out, event = VolTarget(target=0.12).apply({"SPY": 1.0}, ctx)
        assert 0.0 < out["SPY"] < 0.5
        assert event is not None
        assert event.protection == "vol_target"

    def test_never_scales_up_when_vol_is_below_target(self) -> None:
        ctx = _ctx(depot_returns=_returns(0.001))  # ~1.6% annualised, far below target
        out, event = VolTarget(target=0.12).apply({"SPY": 0.5}, ctx)
        assert out == {"SPY": 0.5}
        assert event is None


class TestDrawdownBreaker:
    def test_soft_threshold_halves_and_books_stage_change(self) -> None:
        ctx = _ctx(drawdown=0.11)
        out, event = DrawdownBreaker().apply({"SPY": 0.8}, ctx)
        assert out == {"SPY": 0.4}
        assert ctx.breaker == BreakerState(stage=1, changed_at="2026-07-20")
        assert event is not None and event.action == "stage_1"

    def test_hard_threshold_goes_flat_even_from_normal(self) -> None:
        ctx = _ctx(drawdown=0.25)
        out, event = DrawdownBreaker().apply({"SPY": 0.8, "IEF": 0.2}, ctx)
        assert out == {"SPY": 0.0, "IEF": 0.0}
        assert ctx.breaker.stage == 2
        assert event is not None and event.action == "stage_2"

    def test_persisting_stage_keeps_acting_but_stays_silent(self) -> None:
        ctx = _ctx(drawdown=0.12, breaker=BreakerState(stage=1, changed_at="2026-07-18"))
        out, event = DrawdownBreaker().apply({"SPY": 0.8}, ctx)
        assert out == {"SPY": 0.4}
        assert event is None  # no stage change, no spam — stage itself is surfaced elsewhere

    def test_recovery_blocked_during_cooldown(self) -> None:
        ctx = _ctx(drawdown=0.02, breaker=BreakerState(stage=1, changed_at="2026-07-15"))
        DrawdownBreaker(cooldown_days=14).apply({"SPY": 0.8}, ctx)
        assert ctx.breaker.stage == 1  # only 5 days since the stage move

    def test_recovery_is_one_stage_at_a_time_after_cooldown(self) -> None:
        ctx = _ctx(drawdown=0.02, breaker=BreakerState(stage=2, changed_at="2026-07-01"))
        out, event = DrawdownBreaker(cooldown_days=14).apply({"SPY": 0.8}, ctx)
        assert ctx.breaker.stage == 1  # 2 -> 1, never straight to 0
        assert out == {"SPY": 0.4}
        assert event is not None and event.action == "stage_1"

    def test_full_recovery_needs_drawdown_below_soft_recover(self) -> None:
        ctx = _ctx(drawdown=0.09, breaker=BreakerState(stage=1, changed_at="2026-07-01"))
        DrawdownBreaker(cooldown_days=14).apply({"SPY": 0.8}, ctx)
        assert ctx.breaker.stage == 1  # 9% is above the 8% recovery threshold — hysteresis
        ctx2 = _ctx(drawdown=0.05, breaker=BreakerState(stage=1, changed_at="2026-07-01"))
        DrawdownBreaker(cooldown_days=14).apply({"SPY": 0.8}, ctx2)
        assert ctx2.breaker.stage == 0

    def test_none_drawdown_is_a_no_op(self) -> None:
        ctx = _ctx(drawdown=None)
        out, event = DrawdownBreaker().apply({"SPY": 0.8}, ctx)
        assert out == {"SPY": 0.8}
        assert event is None


def test_chain_applies_in_order_and_collects_events() -> None:
    ctx = _ctx(regime_level="red", drawdown=0.11, depot_returns=None)
    weights = {"AAPL": 0.25, "SPY": 0.05}
    out, events = apply_protections(weights, default_protections(), ctx)
    # AAPL 0.25 -> cap 0.10; the freed 0.15 is REDISTRIBUTED (v16), which fills SPY's 0.05 of
    # headroom to 0.10 and leaves the remaining 0.10 as cash. Then: red gate x0.5 -> 0.05
    # each, breaker stage 1 x0.5 -> 0.025 each.
    assert out["AAPL"] == pytest.approx(0.025)
    assert out["SPY"] == pytest.approx(0.025)
    assert [e.protection for e in events] == ["concentration_cap", "regime_gate", "drawdown_breaker"]


def test_the_risk_layers_after_the_cap_still_see_the_full_redistributed_book() -> None:
    """Redistribution must not weaken downside control — it only removes the cash drag. The
    gate and breaker scale whatever the cap hands them, so a bigger book is scaled harder in
    absolute terms and lands at the same fraction of it."""
    weights = {"AAPL": 0.25, "SPY": 0.05}
    calm = _ctx(regime_level="green", drawdown=0.0, depot_returns=None)
    invested, _ = apply_protections(weights, default_protections(), calm)
    stressed, _ = apply_protections(
        weights, default_protections(), _ctx(regime_level="red", drawdown=0.11, depot_returns=None)
    )
    gross_calm = sum(invested.values())
    gross_stressed = sum(stressed.values())
    assert gross_calm == pytest.approx(0.20)      # cap + redistribution, nothing else fired
    assert gross_stressed == pytest.approx(0.05)  # red gate x0.5 then breaker x0.5
    assert gross_stressed == pytest.approx(gross_calm * 0.25)
