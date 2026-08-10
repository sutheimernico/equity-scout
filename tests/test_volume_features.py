"""Point-in-time volume features (v17c). The expensive mistake this guards against is a window
that includes `as_of` itself — a model trained on the rebalance day's own volume produces a
beautiful backtest and is worthless live.
"""
from __future__ import annotations

import pandas as pd
import pytest

from equity_scout.ml.volume_features import (
    NEUTRAL,
    VOLUME_FEATURE_COLUMNS,
    MIN_BASELINE_OBS,
    VolumeIndex,
)

DATES = pd.bdate_range("2026-01-01", periods=40)


def _index(volumes: dict[str, list[float]], closes: dict[str, list[float]]) -> VolumeIndex:
    return VolumeIndex(
        volumes=pd.DataFrame(volumes, index=DATES),
        closes=pd.DataFrame(closes, index=DATES),
    )


def _steady(level: float = 1_000_000.0, n: int = 40) -> list[float]:
    return [level * (1.05 if i % 2 else 0.95) for i in range(n)]


def test_the_window_never_includes_the_as_of_day_itself():
    """The one mistake that would invalidate everything: on rebalance day the session is not
    over, so its volume is not knowable. A 50x spike ON as_of must not move the features."""
    vols = _steady(n=39) + [50_000_000.0]  # the spike sits on the LAST date
    idx = _index({"AAA": vols}, {"AAA": [100.0] * 40})

    # as_of == the spike's own date -> the spike is invisible
    blind = idx.features("AAA", DATES[-1])
    assert blind["vol_ratio_20d"] == pytest.approx(1.0, abs=0.15)

    # one day later the spike IS in the past and shows up
    seeing = idx.features("AAA", DATES[-1] + pd.Timedelta(days=1))
    assert seeing["vol_ratio_20d"] > 40


def test_features_are_relative_so_the_model_cannot_learn_market_cap():
    """An absolute share count would teach the model "SPY is big", which is not behaviour."""
    idx = _index(
        {"BIG": _steady(50_000_000.0), "SMALL": _steady(50_000.0)},
        {"BIG": [100.0 + i for i in range(40)], "SMALL": [10.0 + i * 0.1 for i in range(40)]},
    )
    as_of = DATES[-1] + pd.Timedelta(days=1)
    big, small = idx.features("BIG", as_of), idx.features("SMALL", as_of)
    for column in VOLUME_FEATURE_COLUMNS:
        assert big[column] == pytest.approx(small[column], rel=0.05), column


def test_obv_uses_price_direction_not_just_volume():
    up = [100.0 + i for i in range(40)]
    down = [100.0 - i * 0.5 for i in range(40)]
    idx = _index({"UP": _steady(), "DOWN": _steady()}, {"UP": up, "DOWN": down})
    as_of = DATES[-1] + pd.Timedelta(days=1)
    assert idx.features("UP", as_of)["vol_obv_20d"] > 5
    assert idx.features("DOWN", as_of)["vol_obv_20d"] < -5


def test_a_thin_history_gets_neutral_values_rather_than_being_dropped():
    """Dropping would silently shrink the training set for exactly the young and illiquid
    tickers whose behaviour is most interesting."""
    short_dates = DATES[:MIN_BASELINE_OBS - 2]
    idx = VolumeIndex(
        volumes=pd.DataFrame({"NEW": _steady(n=len(short_dates))}, index=short_dates),
        closes=pd.DataFrame({"NEW": [100.0] * len(short_dates)}, index=short_dates),
    )
    assert idx.features("NEW", DATES[-1]) == NEUTRAL


def test_an_unknown_ticker_is_neutral_not_an_error():
    idx = _index({"AAA": _steady()}, {"AAA": [100.0] * 40})
    assert idx.features("ZZZ", DATES[-1]) == NEUTRAL


def test_a_null_or_tz_aware_as_of_raises_instead_of_shifting_every_window():
    idx = _index({"AAA": _steady()}, {"AAA": [100.0] * 40})
    with pytest.raises(ValueError, match="null"):
        idx.features("AAA", None)
    with pytest.raises(ValueError, match="tz-naive"):
        idx.features("AAA", pd.Timestamp("2026-02-02", tz="UTC"))


def test_coverage_is_the_number_to_read_before_any_auc_comparison():
    """The P3 evidence run looked like a +0.003 improvement until coverage turned out to be
    2.5 %. Same trap, so the same guard exists here."""
    idx = _index({"AAA": _steady(), "BBB": _steady()}, {"AAA": [100.0] * 40, "BBB": [100.0] * 40})
    assert idx.coverage(["AAA", "BBB"]) == pytest.approx(1.0)
    assert idx.coverage(["AAA", "ZZZ"]) == pytest.approx(0.5)
    assert idx.coverage([]) == 0.0


def test_five_day_ratio_separates_a_busy_week_from_a_single_day():
    one_day = _steady(n=39) + [1_000_000.0]
    busy_week = _steady(n=34) + [4_000_000.0] * 5 + [1_000_000.0]
    idx = _index(
        {"ONE": one_day, "WEEK": busy_week},
        {"ONE": [100.0] * 40, "WEEK": [100.0] * 40},
    )
    as_of = DATES[-1] + pd.Timedelta(days=1)
    assert idx.features("WEEK", as_of)["vol_ratio_5d"] > 2.0
    assert idx.features("ONE", as_of)["vol_ratio_5d"] == pytest.approx(1.0, abs=0.15)
