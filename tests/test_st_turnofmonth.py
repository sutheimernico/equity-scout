"""Turn-of-month lane: calendar boundaries, one-decision-per-session, cost-charged backtest."""
from __future__ import annotations

import pandas as pd
import pytest

from equity_scout.st_turnofmonth import backtest, decide, is_entry_day, is_exit_day


def test_entry_day_is_the_third_to_last_business_day() -> None:
    # August 2026 ends on Monday the 31st; business days ... 27, 28, 31.
    assert is_entry_day(pd.Timestamp("2026-08-27"))
    assert not is_entry_day(pd.Timestamp("2026-08-28"))
    assert not is_entry_day(pd.Timestamp("2026-08-31"))


def test_exit_day_is_the_third_business_day() -> None:
    # September 2026 starts on a Tuesday: 1, 2, 3 -> the 3rd is the exit.
    assert is_exit_day(pd.Timestamp("2026-09-03"))
    assert not is_exit_day(pd.Timestamp("2026-09-02"))


def test_entry_only_when_flat_and_exit_only_when_holding() -> None:
    entry_day = pd.Timestamp("2026-08-27")
    assert decide(entry_day, 100.0, holding=False).kind == "buy"
    assert decide(entry_day, 100.0, holding=True) is None  # already in, no doubling up
    exit_day = pd.Timestamp("2026-09-03")
    assert decide(exit_day, 100.0, holding=True).kind == "sell"
    assert decide(exit_day, 100.0, holding=False) is None


def test_a_day_outside_the_window_does_nothing() -> None:
    assert decide(pd.Timestamp("2026-08-14"), 100.0, holding=False) is None
    assert decide(pd.Timestamp("2026-08-14"), 100.0, holding=True) is None


def test_the_calendar_decides_not_the_observed_sessions() -> None:
    """The rule must not need to know that no further session follows.

    Counting backwards through observed prices would make the entry day depend on data that
    only exists afterwards — a look-ahead that flatters every backtest built on it.
    """
    # A month whose last sessions are missing from the panel entirely: the calendar answer
    # is unchanged, because it never looked at the panel.
    assert is_entry_day(pd.Timestamp("2026-08-27"))


def test_backtest_charges_both_sides_and_reports_against_buy_and_hold() -> None:
    index = pd.bdate_range("2026-08-20", "2026-09-10")
    # Flat prices: a costless rule would return exactly 0, so whatever comes back is the fee.
    result = backtest(pd.Series(100.0, index=index), cost_bps=10.0)
    assert result["trades"] == 1
    assert result["strategy_return"] == pytest.approx(-0.002, abs=1e-4)  # 10 bps per side
    assert result["buy_and_hold"] == pytest.approx(0.0)


def test_backtest_counts_only_the_days_actually_held() -> None:
    index = pd.bdate_range("2026-08-20", "2026-09-10")
    result = backtest(pd.Series(100.0, index=index), cost_bps=0.0)
    # In the market from 27.08. to 03.09., flat the rest — well under half the window.
    assert 0.1 < result["days_in_market_share"] < 0.5


def test_too_short_a_series_reports_nothing_rather_than_zero() -> None:
    assert backtest(pd.Series(dtype=float))["strategy_return"] is None
