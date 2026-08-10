"""Behavioural volume signals (v17). The failure modes that matter: a baseline that includes
the spike it should detect, absolute volume compared across tickers, and a fabricated "average"
reading when there is no history.
"""
from __future__ import annotations

import pytest

from equity_scout.volume_signals import (
    MIN_BASELINE_OBS,
    on_balance_volume,
    read_volume,
)


def _flat(n: int, price: float = 100.0) -> list[float]:
    return [price] * n


def _steady_volume(n: int, level: float = 1_000_000.0) -> list[float]:
    # Alternating slightly so the median is well defined and not a degenerate constant.
    return [level * (1.05 if i % 2 else 0.95) for i in range(n)]


def test_an_ordinary_day_is_reported_as_unremarkable():
    reading = read_volume("SPY", _flat(30), _steady_volume(30))
    assert reading.ratio == pytest.approx(1.0, abs=0.15)
    assert not reading.is_spike
    assert "unauffällig" in reading.note


def test_a_volume_spike_is_detected_and_stated_direction_free():
    closes = _flat(30)
    volumes = _steady_volume(29) + [4_000_000.0]  # 4x a normal day, price unchanged
    reading = read_volume("SPY", closes, volumes)
    assert reading.is_spike
    assert reading.ratio > 3.5
    assert not reading.is_capitulation  # no price drop -> not capitulation
    assert "richtungsfrei" in reading.note.lower()


def test_the_baseline_excludes_today_so_a_spike_cannot_dampen_itself():
    """Comparing a day against a window that contains it is the classic way to make a signal
    disappear into its own average."""
    volumes = _steady_volume(29) + [10_000_000.0]
    reading = read_volume("X", _flat(30), volumes)
    # With today included in a 20-day median the ratio would be far below 10x.
    assert reading.ratio > 9.0


def test_capitulation_needs_both_the_volume_and_the_drop():
    base_v = _steady_volume(29)
    # Big drop on huge volume -> capitulation
    closes_down = _flat(29) + [94.0]  # -6 %
    reading = read_volume("X", closes_down, base_v + [5_000_000.0])
    assert reading.is_capitulation
    assert "Kapitulations-Signatur" in reading.note

    # Same drop on NORMAL volume -> not capitulation (nobody panicked, it just drifted)
    quiet = read_volume("X", closes_down, base_v + [1_000_000.0])
    assert not quiet.is_capitulation
    assert not quiet.is_spike

    # Huge volume but the price ROSE -> not capitulation
    up = read_volume("X", _flat(29) + [106.0], base_v + [5_000_000.0])
    assert up.is_spike and not up.is_capitulation


def test_too_little_history_returns_none_not_a_fabricated_average():
    """A default ratio of 1.0 would read as "perfectly normal" — the one value nobody ever
    questions, and therefore the worst possible lie."""
    short = read_volume("NEW", _flat(5), _steady_volume(5))
    assert short.ratio is None
    assert not short.is_spike
    assert str(MIN_BASELINE_OBS) in short.note


def test_mismatched_series_are_refused_rather_than_aligned():
    reading = read_volume("X", _flat(30), _steady_volume(20))
    assert reading.ratio is None and reading.volume is None
    assert "passen nicht zusammen" in reading.note


def test_obv_adds_up_day_volume_and_subtracts_down_day_volume():
    closes = [100.0, 101.0, 102.0, 101.0]     # up, up, down
    volumes = [0.0, 10.0, 20.0, 5.0]
    assert on_balance_volume(closes, volumes) == pytest.approx(10.0 + 20.0 - 5.0)


def test_obv_ignores_unchanged_closes_because_they_carry_no_direction():
    closes = [100.0, 100.0, 100.0]
    assert on_balance_volume(closes, [0.0, 50.0, 50.0]) == pytest.approx(0.0)


def test_obv_trend_is_normalised_so_it_compares_across_tickers():
    """Raw OBV depends on the ticker's share count; a small cap and SPY would be
    incomparable. Dividing by the ticker's own baseline makes "+3" mean the same thing for
    both: three average days of net buying volume."""
    up_closes = [100.0 + i for i in range(30)]  # every day an up-day
    big = read_volume("BIG", up_closes, _steady_volume(30, level=50_000_000.0))
    small = read_volume("SMALL", up_closes, _steady_volume(30, level=50_000.0))
    assert big.obv_trend is not None and small.obv_trend is not None
    assert big.obv_trend == pytest.approx(small.obv_trend, rel=0.02)
    assert big.volume != small.volume  # the absolute levels differ by 1000x


def test_a_dried_up_market_is_called_out_too():
    """Low participation matters as much as high: a move on 0.3x volume convinces nobody."""
    reading = read_volume("X", _flat(30), _steady_volume(29) + [250_000.0])
    assert reading.ratio is not None and reading.ratio < 0.5
    assert "kaum Beteiligung" in reading.note


def test_a_zero_volume_day_is_not_treated_as_missing_data():
    """A halted ticker or a holiday half-session really does trade nothing — that is a fact
    about behaviour, not a gap to be filled."""
    reading = read_volume("X", _flat(30), _steady_volume(29) + [0.0])
    assert reading.volume == 0.0
    assert reading.ratio == pytest.approx(0.0)
    assert not reading.is_spike


def test_market_behaviour_summarises_who_is_buying_and_who_is_selling():
    """Nico's question in one block. Built from the same readings, so the summary can never
    disagree with the per-ticker numbers below it."""
    from equity_scout.volume_signals import market_behaviour

    accumulated = [100.0 + i for i in range(30)]      # every day up -> positive OBV
    distributed = [100.0 - i * 0.5 for i in range(30)]  # every day down -> negative OBV
    closes = {"GLD": accumulated, "VNQ": distributed, "SPY": _flat(30)}
    volumes = {
        "GLD": _steady_volume(29) + [5_000_000.0],  # spike
        "VNQ": _steady_volume(30),
        "SPY": _steady_volume(30),
    }
    out = market_behaviour(closes, volumes, sleeve=("SPY", "GLD", "VNQ"))
    assert out["available"] is True
    assert "GLD" in out["summary"]                 # the spike is named
    assert "aufgesammelt: GLD" in out["summary"]   # highest OBV
    assert "abgegeben: VNQ" in out["summary"]      # lowest OBV
    assert out["caveat"]                            # the overreading warning travels along
    assert {r["ticker"] for r in out["readings"]} == {"SPY", "GLD", "VNQ"}


def test_market_behaviour_without_data_is_honest_rather_than_empty_looking():
    from equity_scout.volume_signals import market_behaviour

    out = market_behaviour({}, {})
    assert out["available"] is False
    assert out["readings"] == []


def test_capitulation_is_named_ahead_of_a_plain_spike_in_the_summary():
    """When people are panicking, that is the headline — not "unusual turnover"."""
    from equity_scout.volume_signals import market_behaviour

    out = market_behaviour(
        {"SPY": _flat(29) + [93.0], "GLD": _flat(30)},
        {"SPY": _steady_volume(29) + [6_000_000.0], "GLD": _steady_volume(30)},
        sleeve=("SPY", "GLD"),
    )
    assert "Kapitulation" in out["summary"]
    assert "SPY" in out["summary"]
