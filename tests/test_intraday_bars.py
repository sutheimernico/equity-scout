"""Intraday bars tz contract (v12 R8): the settle gate assumes tz-aware New-York times —
a naive index must fail loudly, never silently shift the session's clock."""
from __future__ import annotations

import pandas as pd
import pytest

from equity_scout.intraday_bars import IntradayDataError, ensure_new_york_tz


def _frame(index: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5}, index=index
    )


def test_naive_index_raises_loudly() -> None:
    frame = _frame(pd.date_range("2026-07-20 09:30", periods=3, freq="15min"))
    with pytest.raises(IntradayDataError, match="tz-naive"):
        ensure_new_york_tz(frame)


def test_utc_aware_index_is_converted_to_new_york() -> None:
    frame = _frame(pd.date_range("2026-07-20 13:30", periods=3, freq="15min", tz="UTC"))
    out = ensure_new_york_tz(frame)
    assert str(out.index.tz) == "America/New_York"
    assert out.index[0].hour == 9 and out.index[0].minute == 30
    assert out["close"].iloc[0] == 100.5


def test_new_york_index_passes_through() -> None:
    idx = pd.date_range("2026-07-20 09:30", periods=2, freq="15min", tz="America/New_York")
    out = ensure_new_york_tz(_frame(idx))
    assert list(out.index) == list(idx)
