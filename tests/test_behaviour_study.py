"""W0 measuring instrument. The failure modes that would make every later result worthless:

- a forward window that starts on the decision day (look-ahead, and the most expensive mistake
  available here — it produces a beautiful backtest of a strategy nobody could have traded),
- overlapping windows treated as independent observations (turns noise into significance),
- a real effect the study fails to find (a false null result blocks a good indicator forever),
- an effect that flips sign across eras reported as a finding.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from equity_scout.behaviour_study import (
    MIN_INDEPENDENT_OBS,
    align,
    bucket_stats,
    extreme_stat,
    forward_drawdown,
    forward_return,
    forward_volatility,
    independent_subsample,
    minimum_detectable_effect,
    offset_robustness,
    residualise,
    study_signal,
    walk_forward_spreads,
)


def _dates(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2010-01-04", periods=n)


def _series(values: list[float]) -> pd.Series:
    return pd.Series(values, index=_dates(len(values)), dtype=float)


# --- the t+1 convention -------------------------------------------------------------------


def test_forward_return_starts_the_day_after_the_signal():
    # A signal read on day t can be acted on from t+1 at the earliest. Row t must therefore
    # measure px[t+2]/px[t+1] at horizon 1 - never px[t+1]/px[t].
    px = _series([100, 110, 121, 133.1, 146.41])
    fwd = forward_return(px, horizon_days=1)
    assert fwd.iloc[0] == pytest.approx(121 / 110 - 1.0)
    assert fwd.iloc[1] == pytest.approx(133.1 / 121 - 1.0)


def test_a_jump_on_the_decision_day_is_not_credited_to_that_day():
    # Prices are flat, then jump between day 10 and day 11. Whoever decides on the evening of
    # day 10 enters at the close of day 11 - after the jump - and earns nothing from it.
    px = _series([100.0] * 11 + [200.0] * 11)
    fwd = forward_return(px, horizon_days=1)
    assert fwd.iloc[10] == pytest.approx(0.0)  # decision day 10 -> enters post-jump
    assert fwd.iloc[9] == pytest.approx(1.0)   # decision day 9 -> holds through the jump


def test_the_tail_has_no_forward_value_instead_of_a_truncated_one():
    px = _series([100.0] * 10)
    fwd = forward_return(px, horizon_days=5)
    assert fwd.iloc[-6:].isna().all()


def test_forward_drawdown_is_never_positive_and_excludes_the_decision_day():
    # Day 0 is the high of the whole series. If the window wrongly included day 0, every later
    # drawdown would be measured against it and come out far too negative.
    px = _series([200.0] + [100.0, 99.0, 98.0, 101.0, 102.0] + [100.0] * 6)
    dd = forward_drawdown(px, horizon_days=4)
    assert dd.dropna().le(0.0).all()
    assert dd.iloc[0] == pytest.approx(98.0 / 100.0 - 1.0, abs=1e-9)


def test_forward_volatility_is_annualised_and_positive():
    rng = np.random.default_rng(7)
    px = _series(list(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300)))))
    vol = forward_volatility(px, horizon_days=21).dropna()
    assert (vol > 0).all()
    # ~1 % daily -> ~16 % annualised. Wide bounds: this asserts the scaling, not the draw.
    assert 0.05 < vol.median() < 0.40


# --- independence -------------------------------------------------------------------------


def test_independent_subsample_leaves_no_shared_days_between_windows():
    frame = pd.DataFrame(
        {"signal": range(100), "target": range(100)}, index=_dates(100), dtype=float
    )
    sub = independent_subsample(frame, horizon_days=21)
    positions = [frame.index.get_loc(ix) for ix in sub.index]
    gaps = np.diff(positions)
    assert (gaps >= 22).all()  # window t+1..t+22 must not touch the next sample's
    assert len(sub) == pytest.approx(100 / 22, abs=1)


def test_subsampling_is_reported_honestly_in_the_counts():
    rng = np.random.default_rng(3)
    n = 800
    idx = _dates(n)
    signal = pd.Series(rng.normal(size=n), index=idx)
    target = pd.Series(rng.normal(size=n), index=idx)
    study = study_signal(
        signal_name="s", target_name="t", signal=signal, target=target, horizon_days=21
    )
    assert study.n_overlapping == n
    assert study.n_independent < n / 20  # the number a verdict may rest on is much smaller


# --- does it find what is there, and only what is there -------------------------------------


def test_a_real_effect_is_found_and_reported_as_carrying():
    rng = np.random.default_rng(11)
    n = 3000
    idx = _dates(n)
    signal = rng.normal(size=n)
    # Deliberately strong: this test asks whether the machinery CAN find an effect, not how
    # small an effect it resolves.
    target = 0.04 * signal + rng.normal(0, 0.01, size=n)
    study = study_signal(
        signal_name="konstruiert",
        target_name="forward",
        signal=pd.Series(signal, index=idx),
        target=pd.Series(target, index=idx),
        horizon_days=21,
    )
    assert study.verdict == "trägt"
    assert study.spread is not None and study.spread > 0
    assert study.walk_forward_stable
    assert study.rank_ic_independent is not None and study.rank_ic_independent > 0.5


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_pure_noise_is_not_reported_as_a_finding(seed: int):
    rng = np.random.default_rng(seed)
    n = 3000
    idx = _dates(n)
    study = study_signal(
        signal_name="rauschen",
        target_name="forward",
        signal=pd.Series(rng.normal(size=n), index=idx),
        target=pd.Series(rng.normal(0, 0.02, size=n), index=idx),
        horizon_days=21,
    )
    assert study.verdict != "trägt"


def test_an_effect_that_flips_sign_across_eras_is_called_unstable_not_a_finding():
    rng = np.random.default_rng(23)
    n = 3000
    idx = _dates(n)
    signal = rng.normal(size=n)
    # Strong positive relation for two thirds of the history, reversed in the last third: pooled
    # it still looks significant, but it is exactly the shape of a data-mined artefact.
    slope = np.where(np.arange(n) < int(n * 2 / 3), 0.05, -0.05)
    target = slope * signal + rng.normal(0, 0.01, size=n)
    study = study_signal(
        signal_name="regime-wechsel",
        target_name="forward",
        signal=pd.Series(signal, index=idx),
        target=pd.Series(target, index=idx),
        horizon_days=21,
    )
    assert study.verdict == "instabil"
    assert not study.walk_forward_stable


def test_too_little_history_yields_no_verdict_rather_than_a_weak_one():
    idx = _dates(40)
    rng = np.random.default_rng(5)
    study = study_signal(
        signal_name="kurz",
        target_name="forward",
        signal=pd.Series(rng.normal(size=40), index=idx),
        target=pd.Series(rng.normal(size=40), index=idx),
        horizon_days=21,
    )
    assert study.n_independent < MIN_INDEPENDENT_OBS
    assert study.verdict == "zu wenig Historie"


# --- the asymmetry check ---------------------------------------------------------------------


def test_a_one_sided_effect_shows_up_in_one_tail_only():
    # Baker-Wurgler shape: nothing happens across the normal range, the top quintile alone is
    # followed by weak returns. An average over all buckets would dilute this away - and a check
    # that compared each tail against "everything else" would mirror the high-tail effect into
    # the low-tail result and report a two-sided effect that is not in the data.
    rng = np.random.default_rng(31)
    n = 2000
    idx = _dates(n)
    signal = rng.uniform(0, 1, size=n)
    target = np.where(signal > 0.8, -0.05, 0.0) + rng.normal(0, 0.01, size=n)
    frame = align(pd.Series(signal, index=idx), pd.Series(target, index=idx))
    high = extreme_stat(frame, "hoch")
    low = extreme_stat(frame, "niedrig")
    assert high is not None and low is not None
    assert high.difference < -0.03 and high.p_value is not None and high.p_value < 0.01
    assert abs(low.difference) < 0.01


# --- can this test see anything at all --------------------------------------------------------


def test_the_detectable_effect_shrinks_as_the_sample_grows():
    # The number that makes a null result readable: with more independent windows, a smaller
    # spread becomes visible. If it did not move with n, it would not be measuring power.
    rng = np.random.default_rng(53)
    small = pd.DataFrame({"signal": rng.normal(size=60), "target": rng.normal(0, 0.05, size=60)})
    large = pd.DataFrame({"signal": rng.normal(size=600), "target": rng.normal(0, 0.05, size=600)})
    mde_small = minimum_detectable_effect(small, alpha=0.05)
    mde_large = minimum_detectable_effect(large, alpha=0.05)
    assert mde_small is not None and mde_large is not None
    assert mde_large < mde_small / 2


def test_an_effect_below_the_detectable_size_is_not_claimed_as_absent():
    # A tiny real effect must come back as "kein Befund" AND with an MDE larger than the effect -
    # the pair of numbers that stops a null result from being read as proof of absence.
    rng = np.random.default_rng(59)
    n = 3000
    idx = _dates(n)
    signal = rng.normal(size=n)
    target = 0.0005 * signal + rng.normal(0, 0.05, size=n)
    study = study_signal(
        signal_name="winzig", target_name="forward",
        signal=pd.Series(signal, index=idx), target=pd.Series(target, index=idx),
        horizon_days=21,
    )
    assert study.verdict == "kein Befund"
    frame = align(pd.Series(signal, index=idx), pd.Series(target, index=idx))
    mde = minimum_detectable_effect(independent_subsample(frame, 21), alpha=0.05)
    assert mde is not None and mde > 0.01  # far larger than the 0.0005 slope in the data


def test_a_finding_that_only_holds_at_the_chosen_offset_is_rejected():
    # The verdict must not contradict the robustness sweep. Constructed so the signal relates to
    # the target only on the days offset 0 happens to sample - a pure artefact of that choice.
    n = 3000
    idx = _dates(n)
    rng = np.random.default_rng(67)
    positions = np.arange(n)
    signal = rng.normal(size=n)
    sampled_by_offset_zero = positions % 22 == 0
    target = np.where(sampled_by_offset_zero, 0.05 * signal, 0.0) + rng.normal(0, 0.01, size=n)
    study = study_signal(
        signal_name="nur-offset-0", target_name="forward",
        signal=pd.Series(signal, index=idx), target=pd.Series(target, index=idx),
        horizon_days=21,
    )
    assert study.verdict == "offset-abhängig"
    assert study.offset_share_significant is not None
    assert study.offset_share_significant < 0.5


def test_a_finding_present_at_only_one_offset_is_exposed_by_the_sweep():
    rng = np.random.default_rng(61)
    n = 2000
    idx = _dates(n)
    signal = pd.Series(rng.normal(size=n), index=idx)
    real = pd.Series(0.04 * signal.to_numpy() + rng.normal(0, 0.01, size=n), index=idx)
    noise = pd.Series(rng.normal(0, 0.02, size=n), index=idx)
    strong = offset_robustness(signal, real, 21, alpha=0.05)
    weak = offset_robustness(signal, noise, 21, alpha=0.05)
    assert strong["share_significant"] == 1.0 and strong["sign_agreement"] == 1.0
    assert weak["share_significant"] < 0.5


# --- does the candidate add anything to what is already built in ------------------------------


def test_a_candidate_that_only_restates_an_existing_signal_residualises_to_nothing():
    # Two fear gauges of course correlate. The question a build decision rests on is what is
    # LEFT once the one already in the traffic light is accounted for - and for a monotone
    # transform of it, the answer must be nothing.
    rng = np.random.default_rng(41)
    n = 1500
    idx = _dates(n)
    existing = pd.Series(np.abs(rng.normal(20, 8, size=n)), index=idx)
    candidate = existing * 1.7 + 3.0  # a repackaging, not a new observation
    residual = residualise(candidate, [existing])
    assert residual.abs().max() < 1e-9


def test_the_independent_part_of_a_candidate_survives_residualisation():
    rng = np.random.default_rng(43)
    n = 2000
    idx = _dates(n)
    existing = pd.Series(rng.normal(size=n), index=idx)
    own_part = rng.normal(size=n)
    candidate = pd.Series(existing.to_numpy() + own_part, index=idx)
    residual = residualise(candidate, [existing])
    # The residual must keep the candidate's own information and drop the borrowed part.
    assert abs(float(residual.corr(existing, method="spearman"))) < 0.05
    assert float(residual.corr(pd.Series(own_part, index=idx), method="spearman")) > 0.5


def test_residualising_against_nothing_returns_the_signal_unchanged():
    idx = _dates(30)
    signal = pd.Series(np.arange(30, dtype=float), index=idx)
    pd.testing.assert_series_equal(residualise(signal, []), signal)


# --- the plumbing ----------------------------------------------------------------------------


def test_align_drops_rows_where_either_side_is_missing():
    idx = _dates(5)
    signal = pd.Series([1.0, np.nan, 3.0, 4.0, np.inf], index=idx)
    target = pd.Series([0.1, 0.2, np.nan, 0.4, 0.5], index=idx)
    frame = align(signal, target)
    assert list(frame.index) == [idx[0], idx[3]]


def test_buckets_are_ordered_by_signal_and_partition_the_sample():
    idx = _dates(90)
    frame = pd.DataFrame(
        {"signal": np.arange(90, dtype=float), "target": np.arange(90, dtype=float)}, index=idx
    )
    stats = bucket_stats(frame, n_buckets=3)
    assert [s.label for s in stats] == ["niedrig", "mittel", "hoch"]
    assert sum(s.n for s in stats) == 90
    assert stats[0].signal_hi < stats[-1].signal_lo


def test_walk_forward_blocks_are_cut_on_time_not_shuffled():
    # First half rises with the signal, second half falls. A time cut must show both signs; a
    # shuffled cut would show three near-identical middling numbers.
    idx = _dates(600)
    signal = np.tile([0.0, 1.0], 300)
    target = np.concatenate([signal[:300] * 1.0, signal[300:] * -1.0])
    frame = pd.DataFrame({"signal": signal, "target": target}, index=idx)
    spreads = [s for s in walk_forward_spreads(frame, n_blocks=3) if s is not None]
    assert len(spreads) == 3
    assert spreads[0] > 0 and spreads[-1] < 0
