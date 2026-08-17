"""Panel vs. independent reference: catch a WRONG price before it books (pure logic)."""
import pandas as pd

from equity_scout.price_crosscheck import TOLERANCE, crosscheck


def _panel(close: float, date: str = "2026-08-14") -> pd.DataFrame:
    return pd.DataFrame({"SPY": [close]}, index=pd.DatetimeIndex([pd.Timestamp(date)]))


def test_matching_prices_pass():
    assert crosscheck(_panel(644.5), {"SPY": ("2026-08-14", 644.5)}) == []


def test_divergence_beyond_tolerance_is_reported():
    problems = crosscheck(_panel(644.5), {"SPY": ("2026-08-14", 700.0)})
    assert len(problems) == 1 and "SPY" in problems[0]


def test_date_mismatch_is_skipped_not_flagged():
    # the reference being one day behind (holiday, fetch lag) is not a divergence
    assert crosscheck(_panel(644.5, date="2026-08-15"), {"SPY": ("2026-08-14", 700.0)}) == []


def test_unknown_ticker_is_ignored():
    assert crosscheck(_panel(644.5), {"QQQ": ("2026-08-14", 1.0)}) == []


def test_tolerance_is_two_percent():
    assert TOLERANCE == 0.02
