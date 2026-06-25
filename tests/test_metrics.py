import pandas as pd
import pytest

from equity_scout.metrics import (
    periodic_sharpe,
    annual_volatility,
    cagr,
    calmar,
    compute_metrics,
    deflated_sharpe_ratio,
    max_drawdown,
    probabilistic_sharpe_ratio,
    sharpe,
    sortino,
)


def test_cagr_doubling_over_one_year_is_100pct():
    equity = pd.Series([2 ** (i / 252) for i in range(253)])  # 1 -> 2 over 252 periods
    assert cagr(equity) == pytest.approx(1.0)


def test_max_drawdown_is_peak_to_trough():
    equity = pd.Series([1.0, 1.2, 0.9, 1.5])  # worst is 0.9 vs peak 1.2
    assert max_drawdown(equity) == pytest.approx(-0.25)


def test_calmar_is_cagr_over_maxdd():
    equity = pd.Series([2 ** (i / 252) for i in range(253)])
    assert calmar(equity) == pytest.approx(0.0)  # monotonic rise → no drawdown → 0 by convention


def test_zero_returns_have_zero_vol_and_sharpe():
    rets = pd.Series([0.0] * 100)
    assert annual_volatility(rets) == 0.0
    assert sharpe(rets) == 0.0


def test_sharpe_sign_tracks_mean():
    assert sharpe(pd.Series([0.01, -0.01] * 100)) == pytest.approx(0.0, abs=1e-9)
    assert sharpe(pd.Series([0.02, 0.00] * 100)) > 0
    assert sharpe(pd.Series([-0.02, 0.00] * 100)) < 0


def test_sortino_finite_and_positive_with_downside():
    assert sortino(pd.Series([0.02, -0.01] * 100)) > 0


def test_psr_is_half_for_zero_mean_and_rises_with_edge():
    flat = pd.Series([0.01, -0.01] * 100)
    good = pd.Series([0.02, 0.00] * 100)
    assert probabilistic_sharpe_ratio(flat) == pytest.approx(0.5, abs=0.02)
    assert probabilistic_sharpe_ratio(good) > probabilistic_sharpe_ratio(flat)


def test_dsr_degenerates_to_psr_for_one_trial_and_falls_with_more_trials():
    rets = pd.Series([0.02, 0.00] * 100)
    psr = probabilistic_sharpe_ratio(rets)
    own_sharpe = periodic_sharpe(rets)
    assert deflated_sharpe_ratio(rets, [own_sharpe]) == pytest.approx(psr)
    # a spread of competing trials raises the hurdle → DSR strictly below the naive PSR
    many = deflated_sharpe_ratio(rets, [0.0, 0.05, 0.10, 0.15, own_sharpe])
    assert many < psr


def test_compute_metrics_leaves_turnover_and_dsr_unset():
    equity = pd.Series([2 ** (i / 252) for i in range(253)])
    m = compute_metrics(equity)
    assert m.cagr == pytest.approx(1.0)
    assert m.max_drawdown == pytest.approx(0.0)
    assert m.annual_turnover is None and m.deflated_sharpe is None
