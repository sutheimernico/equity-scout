"""Tests for the calendar-block bootstrap that replaces the pooled Stouffer t.

The decisive test is `test_correlated_tickers_expose_the_naive_t_as_inflated`: it constructs data
where the truth is known — one market move shared by many tickers — and checks that the
independence-assuming statistic overstates it while the bootstrap does not. That is the exact
failure that has kept the matrix hold-out shut since 2026-08-18.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from equity_scout.matrix.bootstrap import (
    MIN_BLOCKS,
    block_bootstrap,
    block_key,
    pool_trades,
)
from equity_scout.matrix.grid import trade_returns, trade_returns_with_times


def _stamps(start: str, periods: int, freq: str = "D") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=periods, freq=freq, tz="UTC")


# --- the core claim ----------------------------------------------------------------------

def test_correlated_tickers_expose_the_naive_t_as_inflated():
    """70 tickers reacting to the SAME 60 monthly market moves is ~60 observations, not 4200.

    The naive t treats every row as an independent draw and inflates accordingly. The block
    bootstrap resamples whole months, so the shared move stays shared.
    """
    rng = np.random.default_rng(7)
    n_months, n_tickers = 60, 70
    month_effect = rng.normal(2.0, 30.0, size=n_months)  # the shared move, in bp

    returns, stamps = [], []
    for month in range(n_months):
        # Each ticker's return is the month's move plus a little idiosyncratic noise: the
        # textbook shape of cross-sectionally correlated data.
        returns.append(month_effect[month] + rng.normal(0.0, 5.0, size=n_tickers))
        stamps.append(pd.date_range(f"2018-{month % 12 + 1:02d}-01", periods=n_tickers,
                                    freq="h", tz="UTC") + pd.DateOffset(years=month // 12))
    net = np.concatenate(returns)
    times = pd.DatetimeIndex(np.concatenate([s.to_numpy() for s in stamps]), tz="UTC")

    result = block_bootstrap(net, times, draws=500, seed=1)

    assert result.n_trades == n_months * n_tickers
    assert result.naive_t is not None and result.t is not None
    # The naive statistic is materially larger — that gap IS the bug being fixed.
    assert abs(result.naive_t) > abs(result.t)
    assert result.inflation_factor is not None and result.inflation_factor > 2.0
    # And the honest verdict on a mean of 2 bp with a 30 bp monthly swing: not significant.
    assert result.p_value is not None and result.p_value > 0.05


def test_a_genuinely_strong_effect_still_survives_the_bootstrap():
    """The fix must not simply reject everything — a real edge has to come through."""
    rng = np.random.default_rng(11)
    n_months, per_month = 80, 40
    returns, stamps = [], []
    for month in range(n_months):
        returns.append(rng.normal(25.0, 12.0, size=per_month))  # consistent, large edge
        stamps.append(pd.date_range("2016-01-01", periods=per_month, freq="h", tz="UTC")
                      + pd.DateOffset(months=month))
    net = np.concatenate(returns)
    times = pd.DatetimeIndex(np.concatenate([s.to_numpy() for s in stamps]), tz="UTC")

    result = block_bootstrap(net, times, draws=500, seed=2)
    assert result.p_value is not None and result.p_value < 0.01
    assert result.ci_low_bp is not None and result.ci_low_bp > 0  # CI excludes zero
    assert result.mean_net_bp == pytest.approx(25.0, abs=2.0)


def test_a_losing_cell_is_reported_as_losing():
    rng = np.random.default_rng(3)
    net = rng.normal(-15.0, 10.0, size=1200)
    times = _stamps("2018-01-01", 1200, freq="6h")
    result = block_bootstrap(net, times, draws=300, seed=3)
    assert result.mean_net_bp is not None and result.mean_net_bp < 0
    assert result.p_value is not None and result.p_value > 0.9  # decisively not positive
    assert result.ci_high_bp is not None and result.ci_high_bp < 0


# --- honest refusals ---------------------------------------------------------------------

def test_too_few_calendar_blocks_refuses_to_estimate():
    """A refusal must be distinguishable from a rejection: t/p are None, the mean still reports."""
    net = np.full(500, 20.0)
    times = _stamps("2020-01-01", 500, freq="h")  # 500 hours = 1 month
    result = block_bootstrap(net, times, draws=100, seed=4)
    assert result.n_blocks < MIN_BLOCKS
    assert result.mean_net_bp == 20.0
    assert result.t is None and result.p_value is None


def test_empty_sample_is_handled():
    result = block_bootstrap(np.empty(0), pd.DatetimeIndex([], tz="UTC"))
    assert result.n_trades == 0 and result.mean_net_bp is None


def test_zero_variance_sample_does_not_divide_by_zero():
    """A constant return series has no standard error — report the mean, refuse the t."""
    net = np.full(600, 7.0)
    times = _stamps("2018-01-01", 600, freq="D")  # ~20 months
    result = block_bootstrap(net, times, draws=100, seed=5)
    assert result.mean_net_bp == 7.0
    assert result.std_error_bp == 0.0
    assert result.t is None


# --- determinism and blocking -------------------------------------------------------------

def test_same_seed_reproduces_the_number_exactly():
    """A reported statistic has to be reproducible, or it cannot be defended later."""
    rng = np.random.default_rng(9)
    net = rng.normal(5.0, 20.0, size=2000)
    times = _stamps("2017-01-01", 2000, freq="12h")
    first = block_bootstrap(net, times, draws=200, seed=42)
    second = block_bootstrap(net, times, draws=200, seed=42)
    assert first.t == second.t and first.p_value == second.p_value
    third = block_bootstrap(net, times, draws=200, seed=43)
    assert third.t != first.t  # a different seed must actually resample differently


def test_block_key_groups_by_calendar_month():
    keys = block_key(pd.DatetimeIndex(
        ["2026-01-05", "2026-01-28", "2026-02-02"], tz="UTC"))
    assert keys[0] == keys[1] != keys[2]


def test_weekly_blocks_produce_more_blocks_than_monthly():
    times = _stamps("2020-01-01", 400, freq="D")
    monthly = block_bootstrap(np.ones(400), times, draws=50, block="M")
    weekly = block_bootstrap(np.ones(400), times, draws=50, block="W")
    assert weekly.n_blocks > monthly.n_blocks


def test_pool_trades_concatenates_without_weighting():
    a = (np.array([1.0, 2.0]), _stamps("2020-01-01", 2))
    b = (np.array([3.0]), _stamps("2020-03-01", 1))
    empty = (np.empty(0), pd.DatetimeIndex([], tz="UTC"))
    net, times = pool_trades([a, empty, b])
    assert list(net) == [1.0, 2.0, 3.0]
    assert len(times) == 3


def test_pool_trades_handles_all_empty():
    net, times = pool_trades([(np.empty(0), pd.DatetimeIndex([], tz="UTC"))])
    assert len(net) == 0 and len(times) == 0


# --- the grid seam ------------------------------------------------------------------------

def test_trade_returns_with_times_matches_trade_returns():
    """The timestamped variant must not change WHICH trades happen — only add their times."""
    index = _stamps("2020-01-01", 40)
    bars = pd.DataFrame({"close": np.linspace(100.0, 140.0, 40)}, index=index)
    signal = pd.Series([i % 5 == 0 for i in range(40)], index=index)

    plain = trade_returns(bars, signal, hold_bars=3)
    withtimes, stamps = trade_returns_with_times(bars, signal, hold_bars=3)

    assert np.allclose(plain, withtimes)
    assert len(stamps) == len(plain)
    assert stamps[0] == index[0]  # first entry is the first firing bar


def test_trade_returns_with_times_on_no_signal():
    index = _stamps("2020-01-01", 10)
    bars = pd.DataFrame({"close": np.ones(10) * 50.0}, index=index)
    returns, stamps = trade_returns_with_times(
        bars, pd.Series([False] * 10, index=index), hold_bars=2)
    assert len(returns) == 0 and len(stamps) == 0


# --- the short side ------------------------------------------------------------------------

def test_short_cell_pays_costs_instead_of_being_credited_with_them():
    """The trap this guards: net_short = -(gross - cost) would hand the short the costs the long
    paid, turning every losing long into a winning short. Correct is -gross - cost."""
    from equity_scout.matrix.grid import cell_from_returns

    gross = np.full(300, -30.0)  # the long loses 30 bp gross
    long_cell = cell_from_returns(gross, cost_bps=10.0, min_trades=100, side="long")
    short_cell = cell_from_returns(gross, cost_bps=10.0, min_trades=100, side="short")

    assert long_cell["net_bp"] == pytest.approx(-40.0)   # -30 - 10
    assert short_cell["net_bp"] == pytest.approx(20.0)   # +30 - 10, NOT +40
    assert short_cell["net_bp"] != -long_cell["net_bp"]


def test_short_cell_reports_gross_from_its_own_side():
    from equity_scout.matrix.grid import cell_from_returns
    cell = cell_from_returns(np.full(300, -25.0), cost_bps=5.0, min_trades=100, side="short")
    assert cell["gross_bp"] == pytest.approx(25.0)
    assert cell["net_bp"] == pytest.approx(20.0)
    assert cell["hit_rate"] == 1.0  # every trade profitable on the short side


def test_unknown_side_is_rejected():
    from equity_scout.matrix.grid import cell_from_returns
    with pytest.raises(ValueError, match="side"):
        cell_from_returns(np.ones(300), cost_bps=5.0, min_trades=100, side="sideways")
