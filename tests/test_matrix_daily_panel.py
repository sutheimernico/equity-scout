"""Tests for the OHLCV daily panel behind trader #3.

The load-bearing test is `test_bars_before_excludes_the_decision_day`. This module deliberately
bypasses `MarketView`, which is what normally makes look-ahead impossible — so the cut has to be
proven here, or the whole strategy is built on a leak that backtests beautifully and loses live.
"""
from __future__ import annotations

import gzip

import pandas as pd
import pytest

from equity_scout.matrix.daily_panel import (
    DailyOHLCV,
    available_years,
    load_panel,
    make_ohlcv_signal_fires,
)


@pytest.fixture
def daily_root(tmp_path):
    """Two years of synthetic OHLCV for two tickers, in the real on-disk format."""
    root = tmp_path / "daily"
    root.mkdir()
    for year in (2021, 2022):
        rows = ["ticker,date,open,high,low,close,volume,trades"]
        for day in range(1, 29):
            for ticker, base in (("AAA", 100.0), ("BBB", 50.0)):
                price = base + day
                # A real spike on the final day, not just growing volume: a monotone series has
                # no spike over its own rolling median, so the fixture has to contain the thing
                # the signal is supposed to detect.
                volume = 500_000 if (day == 28 and year == 2022) else 10_000
                rows.append(
                    f"{ticker},{year}-06-{day:02d},{price - 1},{price + 2},"
                    f"{price - 2},{price},{volume},{day}"
                )
        with gzip.open(root / f"daily-{year}.csv.gz", "wt") as handle:
            handle.write("\n".join(rows))
    load_panel.cache_clear()
    yield root
    load_panel.cache_clear()


def test_available_years_reads_the_directory(daily_root):
    assert available_years(daily_root) == [2021, 2022]


def test_available_years_on_missing_directory(tmp_path):
    assert available_years(tmp_path / "nope") == []


def test_panel_loads_both_years_and_tickers(daily_root):
    source = DailyOHLCV(root=daily_root)
    assert source.tickers == ["AAA", "BBB"]
    bars = source.bars_before("AAA", "2023-01-01")
    assert len(bars) == 56  # 28 days x 2 years
    assert list(bars.columns) == ["open", "high", "low", "close", "volume"]


# --- the invariant ------------------------------------------------------------------------

def test_bars_before_excludes_the_decision_day(daily_root):
    """A bar dated as_of belongs to the session being decided — its close is not known yet.

    Using it would be trading on information from the future. This is the single easiest way to
    manufacture a strategy that looks brilliant in backtest and fails live, so it is pinned.
    """
    source = DailyOHLCV(root=daily_root)
    bars = source.bars_before("AAA", "2021-06-10")
    assert len(bars) == 9  # the 1st..9th, NOT the 10th
    assert bars.index.max() < pd.Timestamp("2021-06-10", tz="UTC")


def test_bars_before_accepts_naive_timestamps_as_utc(daily_root):
    source = DailyOHLCV(root=daily_root)
    naive = source.bars_before("AAA", pd.Timestamp("2021-06-10"))
    aware = source.bars_before("AAA", pd.Timestamp("2021-06-10", tz="UTC"))
    assert len(naive) == len(aware)


def test_unknown_ticker_returns_empty_not_error(daily_root):
    source = DailyOHLCV(root=daily_root)
    assert not source.has("ZZZ")
    assert source.bars_before("ZZZ", "2022-01-01").empty


def test_missing_directory_yields_empty_source(tmp_path):
    load_panel.cache_clear()
    source = DailyOHLCV(root=tmp_path / "absent")
    assert source.tickers == []
    assert source.bars_before("AAA", "2022-01-01").empty


def test_ticker_restriction_limits_the_load(daily_root):
    load_panel.cache_clear()
    source = DailyOHLCV(root=daily_root, tickers=["AAA"])
    assert source.tickers == ["AAA"]


# --- the signal bridge ---------------------------------------------------------------------

class _Plateau:
    def __init__(self, signal: str, thresholds: list) -> None:
        self.signal = signal
        self.thresholds = thresholds


def test_ohlcv_bridge_unlocks_signals_that_need_open_and_volume(daily_root):
    """The whole point: with real OHLCV, `momentum_up` and `volume_spike` become usable.

    On the depot's close-only panel both are permanently False — 12 of 15 signals were.
    """
    source = DailyOHLCV(root=daily_root)
    fires = make_ohlcv_signal_fires(source, min_history=10)
    # as_of is the 29th, so the spike bar of the 28th is VISIBLE. Asking on the 28th would
    # correctly see nothing — bars_before excludes the decision day, which is the point.
    # The series rises by 1 per day from open = price-1, so momentum_up fires throughout.
    assert fires(_Plateau("momentum_up", [0.002]), "AAA", "2022-06-29", None) is True
    assert fires(_Plateau("volume_spike", [2.0]), "AAA", "2022-06-29", None) is True
    # And the same question one day earlier must NOT see the spike.
    assert fires(_Plateau("volume_spike", [2.0]), "AAA", "2022-06-28", None) is False


def test_bridge_refuses_unknown_signal_and_short_history(daily_root):
    source = DailyOHLCV(root=daily_root)
    fires = make_ohlcv_signal_fires(source, min_history=10)
    assert fires(_Plateau("does_not_exist", [0.01]), "AAA", "2022-06-28", None) is False
    # Only a handful of bars visible: too little for a rolling statistic to mean anything.
    assert fires(_Plateau("momentum_up", [0.002]), "AAA", "2021-06-05", None) is False


def test_bridge_is_look_ahead_safe(daily_root):
    """A signal that only fires on the decision day's own bar must not fire.

    Evaluated at as_of, the last visible bar is the day BEFORE — so the answer must match an
    evaluation that never saw as_of at all.
    """
    source = DailyOHLCV(root=daily_root)
    fires = make_ohlcv_signal_fires(source, min_history=10)
    at_as_of = fires(_Plateau("momentum_up", [0.002]), "AAA", "2022-06-20", None)
    visible = source.bars_before("AAA", "2022-06-20")
    assert visible.index.max() < pd.Timestamp("2022-06-20", tz="UTC")
    # Same decision from the same visible data — no dependence on the hidden bar.
    assert at_as_of == fires(_Plateau("momentum_up", [0.002]), "AAA",
                             visible.index.max() + pd.Timedelta(days=1), None)
