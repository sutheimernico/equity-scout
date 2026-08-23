""""How long until this means anything?" (v16 wave 3). The verdicts must be honest at the
edges: too few trades, an effect too small to ever resolve, and a real effect that resolves.
"""
from __future__ import annotations

import pytest

from equity_scout.significance import (
    MIN_TRADES_FOR_A_TEST,
    assess_trades,
    bonferroni_alpha,
    required_trades,
)


def test_too_few_trades_is_stated_not_guessed():
    verdict = assess_trades([10.0, -5.0, 3.0])
    assert verdict.verdict == "zu wenige Trades"
    assert verdict.p_value is None and verdict.trades_needed is None
    assert str(MIN_TRADES_FOR_A_TEST) in verdict.note


def test_a_clear_consistent_edge_is_called_positive():
    """Twenty trades averaging +10 with little spread: unmistakable."""
    verdict = assess_trades([9.0, 11.0, 10.0, 12.0, 8.0] * 4)
    assert verdict.verdict == "positiv"
    assert verdict.is_significant
    assert verdict.mean == pytest.approx(10.0)
    # Even when it IS significant, the note must not oversell a fat-tailed sample.
    assert "optimistisch" in verdict.note


def test_a_clear_consistent_loss_is_called_negative():
    verdict = assess_trades([-9.0, -11.0, -10.0, -12.0, -8.0] * 4)
    assert verdict.verdict == "negativ"
    assert verdict.is_significant


def test_noise_around_zero_says_how_many_trades_are_missing():
    """The session lane's actual situation: a small mean against a large spread."""
    pnls = [12.0, -13.0, 10.0, -11.0, 9.0, -8.0, 14.0, -15.0, 11.0, -9.0] * 3
    verdict = assess_trades(pnls)
    assert verdict.verdict in ("noch nicht aussagekräftig", "kein messbarer Effekt")
    assert not verdict.is_significant
    if verdict.trades_needed is not None:
        assert verdict.trades_needed > verdict.n
        assert verdict.trades_missing == verdict.trades_needed - verdict.n
        assert "fehlen" in verdict.note


def test_an_effect_too_small_to_ever_resolve_says_so_instead_of_a_silly_number():
    """At mean->0 the required sample size diverges. "No measurable effect" is more useful
    than "needs 4 million trades"."""
    pnls = [50.0, -50.0] * 20 + [0.01]
    verdict = assess_trades(pnls)
    assert verdict.verdict == "kein messbarer Effekt"
    assert verdict.trades_needed is None
    assert "Rauschen" in verdict.note


def test_required_trades_grows_as_the_effect_shrinks():
    big = required_trades(mean=10.0, stdev=10.0)
    small = required_trades(mean=1.0, stdev=10.0)
    assert big is not None and small is not None
    assert small > big  # a tenth of the effect needs ~100x the trades
    assert big >= MIN_TRADES_FOR_A_TEST


def test_required_trades_refuses_impossible_inputs():
    assert required_trades(mean=1.0, stdev=0.0) is None
    assert required_trades(mean=0.0, stdev=10.0) is None
    assert required_trades(mean=float("nan"), stdev=10.0) is None


def test_identical_trades_are_reported_as_untestable_not_as_certainty():
    """Zero spread would divide by zero and read as infinite confidence — refuse instead."""
    verdict = assess_trades([5.0] * 10)
    assert verdict.verdict == "kein messbarer Effekt"
    assert verdict.t_stat is None
    assert "identisch" in verdict.note


def test_non_finite_values_are_dropped_rather_than_poisoning_the_mean():
    verdict = assess_trades([10.0, float("nan"), 11.0, 9.0, 12.0, 8.0, float("inf")])
    assert verdict.n == 5  # the two junk values are gone
    assert verdict.mean == pytest.approx(10.0)


def test_bonferroni_corrects_for_looking_at_many_books():
    """Sixteen books at 0.05 produce roughly one 'significant' result from noise alone."""
    assert bonferroni_alpha(16) == pytest.approx(0.05 / 16)
    assert bonferroni_alpha(1) == pytest.approx(0.05)
    assert bonferroni_alpha(0) == pytest.approx(0.05)  # never divides by zero


def test_a_stricter_alpha_makes_a_borderline_result_not_significant():
    """The correction has to actually bite, otherwise it is decoration."""
    pnls = [6.0, 4.0, 7.0, 3.0, 5.0, 8.0, 2.0, 6.0, 4.0, 5.0]
    assert assess_trades(pnls, alpha=0.05).is_significant
    strict = assess_trades(pnls, alpha=bonferroni_alpha(16))
    assert strict.alpha < 0.05
    assert strict.trades_needed is not None and strict.trades_needed > 0


def test_a_significant_result_is_always_positive_or_negative():
    """The invariant the phone cockpit depends on (found while reviewing 2026-08-23).

    `frontend/src/lanes.ts::verdictLine` renders a settled verdict as a binary — "verdient
    Geld" for "positiv", "verliert Geld" for everything else — and gates that on
    `is_significant`. That is only honest while `is_significant` implies a DIRECTIONAL
    verdict. Add an equivalence test later ("significantly no effect") and the cockpit would
    silently tell Nico a lane loses money when the finding is that it does neither.

    This test is the tripwire: if a future verdict can be significant without being
    directional, it fails here, and the frontend has to be taught the third case.
    """
    directional = {"positiv", "negativ"}
    cases = [
        [0.5] * (MIN_TRADES_FOR_A_TEST - 1),            # too few trades
        [1.0] * (MIN_TRADES_FOR_A_TEST + 5),            # no spread at all
        [2.0, -1.9, 2.1, -2.0, 1.8, -1.7, 2.2, -2.1, 1.9, -1.8, 2.0, -1.9],  # noise
        [1.0, 1.2, 0.9, 1.1, 1.05, 0.95, 1.15, 0.85, 1.0, 1.1, 0.9, 1.2],    # clear positive
        [-1.0, -1.2, -0.9, -1.1, -1.05, -0.95, -1.15, -0.85, -1.0, -1.1, -0.9, -1.2],
    ]
    seen = set()
    for pnls in cases:
        result = assess_trades(pnls)
        seen.add(result.verdict)
        if result.is_significant:
            assert result.verdict in directional, (
                f"significant but not directional: {result.verdict!r} — "
                "frontend/src/lanes.ts renders this as 'verliert Geld'"
            )
    # The cases must actually exercise both sides, or the assertion above proves nothing.
    assert directional <= seen, f"cases never produced a directional verdict: {seen}"
