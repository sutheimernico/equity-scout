"""The adoption gate: paired comparison, trial-count hurdle, monthly brake, readable refusals."""
from __future__ import annotations

import pandas as pd
import pytest

from equity_scout.exits import ExitRules
from equity_scout.lane_adoption import critical_t, evaluate_adoption

TIGHT = ExitRules(profit_target=0.05, stop_loss=0.03, max_holding_days=7)
WIDE = ExitRules(profit_target=0.05, stop_loss=0.05, max_holding_days=14)


def _world(n_events: int, dip: float, *, spread: float = 0.02) -> tuple[dict, list]:
    """n events that dip by roughly `dip` and then recover to roughly +6 %.

    A tight stop sells into the dip, a wide one survives it — a setting where the wide rule is
    genuinely better. The per-event variation is deliberate: with identical events every paired
    difference is the same, the variance is zero and no test is possible. That is a property of
    the sample, not of the rules, and the first version of this fixture got it wrong.
    """
    closes, events = {}, []
    for i in range(n_events):
        wobble = spread * ((i % 5) - 2) / 2  # -spread .. +spread, deterministic
        series = pd.Series(
            [100.0, 100.0, 100.0 * (1 + dip + wobble), 106.0 + 100 * wobble, 106.0],
            index=pd.bdate_range("2026-01-01", periods=5),
        )
        closes[f"T{i}"] = series
        events.append((f"T{i}", series.index[0]))
    return closes, events


def test_a_real_improvement_on_enough_events_is_adopted() -> None:
    closes, events = _world(60, dip=-0.04)  # -4 %: trips the 3 % stop, not the 5 % one
    verdict = evaluate_adoption(closes, events, challenger=WIDE, incumbent=TIGHT, n_trials=36)
    assert verdict.adopt
    assert verdict.n_pairs == 60
    assert "Übernommen" in verdict.reason


def test_the_same_improvement_is_refused_when_too_few_events_back_it() -> None:
    closes, events = _world(10, dip=-0.04)
    verdict = evaluate_adoption(closes, events, challenger=WIDE, incumbent=TIGHT, n_trials=36)
    assert not verdict.adopt
    assert "Zu wenige" in verdict.reason


def test_the_monthly_brake_blocks_a_second_change() -> None:
    closes, events = _world(60, dip=-0.04)
    verdict = evaluate_adoption(closes, events, challenger=WIDE, incumbent=TIGHT, n_trials=36,
                                already_changed_this_month=True)
    assert not verdict.adopt
    assert "bereits angepasst" in verdict.reason


def test_identical_rules_are_never_adopted() -> None:
    closes, events = _world(60, dip=-0.04)
    verdict = evaluate_adoption(closes, events, challenger=TIGHT, incumbent=TIGHT, n_trials=36)
    assert not verdict.adopt


def test_no_difference_between_the_rules_is_refused_with_a_readable_reason() -> None:
    # A dip too small for either stop, and no wobble: both rules produce the identical trade.
    closes, events = _world(60, dip=-0.01, spread=0.0)
    verdict = evaluate_adoption(closes, events, challenger=WIDE, incumbent=TIGHT, n_trials=36)
    assert not verdict.adopt
    assert "identische" in verdict.reason


def test_a_constant_difference_is_refused_as_untestable_not_as_a_tie() -> None:
    """Every event showing the SAME difference means the sample says nothing about the spread.
    Refusing is right; calling it a tie would hide a data problem behind a verdict."""
    closes, events = _world(60, dip=-0.04, spread=0.0)
    verdict = evaluate_adoption(closes, events, challenger=WIDE, incumbent=TIGHT, n_trials=36)
    assert not verdict.adopt
    assert "keine Streuung" in verdict.reason
    assert verdict.mean_diff > 0  # the challenger IS better here - just not testably so


def test_the_hurdle_rises_with_the_number_of_combinations_searched() -> None:
    """Forty cells against one dataset always produce a winner."""
    assert critical_t(1) == pytest.approx(1.96)
    assert critical_t(36) > critical_t(4) > 1.96


def test_a_refusal_states_the_measured_t_and_the_bar_it_missed() -> None:
    """'Not adopted' has to be as readable afterwards as 'adopted', or a working brake looks
    the same as a broken search."""
    # Identical evidence to the adopted case, but searched across a far larger space: the same
    # advantage no longer suffices. That is exactly what the hurdle is supposed to express.
    closes, events = _world(32, dip=-0.04)
    verdict = evaluate_adoption(closes, events, challenger=WIDE, incumbent=TIGHT,
                                n_trials=10_000)
    assert not verdict.adopt
    assert "Hürde" in verdict.reason
    assert verdict.paired_t is not None and verdict.paired_t < verdict.hurdle_t
