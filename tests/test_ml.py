"""ML meta-model tests — all offline on deterministic synthetic panels."""
from __future__ import annotations

import numpy as np
import pandas as pd

from equity_scout.market import PricePanel
from equity_scout.ml.features import FEATURE_NAMES, primary_long_signal, regime_features
from equity_scout.ml.labeling import triple_barrier_labels
from equity_scout.ml.meta_model import _backtest_exposure, purged_walk_forward, run_meta_model


def _series(prices: list[float], start: str = "2020-01-01") -> pd.Series:
    return pd.Series(prices, index=pd.bdate_range(start, periods=len(prices)))


# --- Triple-barrier labeling ---
def test_label_is_one_when_profit_barrier_hit_first():
    prices = _series([100.0 * 1.02**i for i in range(8)])  # +2%/day → +5% within a few days
    labels = triple_barrier_labels(prices, prices.index[:1], horizon_days=6, profit_take=0.05, stop_loss=0.05)
    assert labels.iloc[0] == 1


def test_label_is_zero_when_stop_barrier_hit_first():
    prices = _series([100.0 * 0.98**i for i in range(8)])  # -2%/day → -5% first
    labels = triple_barrier_labels(prices, prices.index[:1], horizon_days=6, profit_take=0.05, stop_loss=0.05)
    assert labels.iloc[0] == 0


def test_time_barrier_uses_sign_of_final_return():
    prices = _series([100.0 + 0.1 * i for i in range(8)])  # drifts up slowly, never ±5%
    labels = triple_barrier_labels(prices, prices.index[:1], horizon_days=6, profit_take=0.05, stop_loss=0.05)
    assert labels.iloc[0] == 1  # ended higher


# --- Purged walk-forward (the leakage guard) ---
def test_walk_forward_folds_are_purged_and_ordered():
    events = pd.date_range("2008-01-31", periods=100, freq="ME")
    folds = list(purged_walk_forward(events, n_splits=4, embargo_days=21, horizon_days=21))
    assert len(folds) >= 3  # the earliest fold may be dropped by the min-train guard after purging
    for train, test in folds:
        assert train.max() < test.min()  # training strictly precedes the test block
        gap_days = (test.min() - train.max()).days
        assert gap_days >= 42  # purge + embargo (horizon 21 + embargo 21)


def test_walk_forward_yields_nothing_for_tiny_history():
    assert list(purged_walk_forward(pd.date_range("2020-01-31", periods=10, freq="ME"))) == []


def test_walk_forward_horizon_42_purges_by_exact_trading_day_position_on_real_calendar():
    """F1 regression: horizon_days=42 is a live point in the search space (ml/search.py
    HORIZON_DAYS). Naive calendar-day purging (`event - Timedelta(days=horizon+embargo)`) treats
    horizon_days as calendar days when it is actually a count of TRADING days — on a realistic
    calendar (weekends + US holidays) the true buffer shrinks to as little as ~3 calendar days
    around a holiday, letting a training label window bleed into the test block. This test proves
    the fix by checking exact trading-day positions (not by re-deriving the calendar arithmetic
    under test): for every training event in every fold, the position its (horizon + embargo)
    trading-day label window reaches must be strictly before the first test event's position."""
    from pandas.tseries.holiday import USFederalHolidayCalendar
    from pandas.tseries.offsets import CustomBusinessDay

    trading_days = pd.date_range(
        "2015-01-01", "2024-12-31", freq=CustomBusinessDay(calendar=USFederalHolidayCalendar())
    )
    events = trading_days[::15]  # a monthly-ish event cadence, like panel.rebalance_dates()
    horizon_days, embargo_days = 42, 21

    folds = list(
        purged_walk_forward(
            events,
            n_splits=4,
            embargo_days=embargo_days,
            horizon_days=horizon_days,
            trading_days=trading_days,
        )
    )
    assert folds  # the calendar is long enough to produce folds

    position = {date: i for i, date in enumerate(trading_days)}
    for train, test in folds:
        test_start_pos = position[test.min()]
        for event in train:
            label_window_end_pos = position[event] + horizon_days + embargo_days
            assert label_window_end_pos < test_start_pos  # no label window reaches the test block


def test_walk_forward_without_trading_days_falls_back_to_conservative_calendar_bound():
    """No `trading_days` supplied (e.g. a bare synthetic index) → the fallback must still be at
    least as wide as the naive horizon+embargo calendar-day span, never narrower."""
    events = pd.date_range("2008-01-31", periods=100, freq="ME")
    folds = list(purged_walk_forward(events, n_splits=4, embargo_days=21, horizon_days=42))
    assert len(folds) >= 1
    for train, test in folds:
        gap_days = (test.min() - train.max()).days
        assert gap_days >= 42 + 21  # at least as conservative as the naive (buggy) calendar span


# --- Features ---
def test_regime_features_shape_and_plausibility():
    n = 400
    data = {t: [100.0 * 1.0005**i for i in range(n)] for t in ["SPY", "VEU", "VWO", "VNQ"]}
    panel = PricePanel(pd.DataFrame(data, index=pd.bdate_range("2019-01-01", periods=n)))
    feats = regime_features(panel)
    assert list(feats.columns) == list(FEATURE_NAMES)
    assert feats["trend"].iloc[-1] > 0  # rising market is above its MA
    assert feats["drawdown"].iloc[-1] > -0.01  # monotone rise → ~no drawdown
    assert primary_long_signal(panel).iloc[-1]  # 12m momentum positive


# --- Exposure backtest ---
def test_exposure_one_tracks_asset_zero_stays_flat():
    n = 60
    panel = PricePanel(pd.DataFrame(
        {"SPY": [100.0 * 1.01**i for i in range(n)], "BIL": [100.0] * n},
        index=pd.bdate_range("2021-01-01", periods=n),
    ))
    full = _backtest_exposure(panel, pd.Series(1.0, index=panel.dates), "SPY", "BIL", 0)
    none = _backtest_exposure(panel, pd.Series(0.0, index=panel.dates), "SPY", "BIL", 0)
    assert full.iloc[-1] > 1.5  # ~1.01^59 fully invested
    assert none.iloc[-1] == 1.0  # flat in cash (BIL flat)


# --- End-to-end ---
def _wavy_panel(n: int = 2600) -> PricePanel:
    # Up-trending market with volatility waves so the primary signal turns on/off and labels vary.
    idx = pd.bdate_range("2008-01-01", periods=n)
    base = np.array([1.0003**i * (1 + 0.18 * np.sin(i / 70.0)) for i in range(n)])
    cols = {
        t: list(100.0 * base * (1 + 0.02 * np.sin(np.arange(n) / 90.0 + off)))
        for off, t in enumerate(["SPY", "VEU", "VWO", "VNQ"])
    }
    cols["BIL"] = list(100.0 * 1.00005 ** np.arange(n))
    return PricePanel(pd.DataFrame(cols, index=idx))


def test_run_meta_model_produces_oos_curve():
    result = run_meta_model(_wavy_panel())
    assert result.trained
    assert result.n_bets > 0
    assert len(result.equity) > 0 and result.equity.iloc[0] == 1.0
    assert 0.0 <= result.oos_hit_rate <= 1.0
    assert set(result.feature_importance) <= set(FEATURE_NAMES)
    # exposure is a valid weight series in [0, 1]
    assert result.exposure.between(0.0, 1.0).all()


def test_build_ml_report_shapes_oos_curve():
    from equity_scout.strategy_service import build_ml_report

    report = build_ml_report(_wavy_panel())
    assert report.trained
    assert report.metrics is not None
    assert report.equity[0][1] == 1.0  # re-based to 1 at the first OOS bet
    assert len(report.benchmark_equity) == len(report.equity)
    assert 0.0 <= report.avg_exposure <= 1.0
    assert set(report.feature_importance) <= set(FEATURE_NAMES)


def test_build_ml_report_honours_a_custom_config():
    from equity_scout.ml.meta_model import MetaConfig
    from equity_scout.strategy_service import build_ml_report

    narrow = MetaConfig(features=("vol", "trend"))
    report = build_ml_report(_wavy_panel(), narrow)
    assert report.trained
    assert set(report.feature_importance) <= {"vol", "trend"}


def test_run_meta_model_untrained_on_short_history():
    short = PricePanel(pd.DataFrame(
        {t: [100.0 + i for i in range(120)] for t in ["SPY", "VEU", "VWO", "VNQ", "BIL"]},
        index=pd.bdate_range("2022-01-01", periods=120),
    ))
    result = run_meta_model(short)
    assert result.trained is False
    assert result.n_bets == 0
