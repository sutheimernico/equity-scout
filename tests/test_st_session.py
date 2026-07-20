"""Session lane: settled-bar gate, ORB signal/fill mechanics, exits, idempotency."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from equity_scout.intraday_bars import settled_bars
from equity_scout.shortterm_book import LanePosition
from equity_scout.st_session import decide, opening_range

ET = "America/New_York"


def _bars(rows: list[tuple[float, float, float, float]], start: str = "09:30") -> pd.DataFrame:
    index = pd.date_range(f"2026-07-20 {start}", periods=len(rows), freq="15min", tz=ET)
    return pd.DataFrame(rows, index=index, columns=["open", "high", "low", "close"])


class TestSettledGate:
    def test_only_bars_older_than_the_delay_margin_pass(self) -> None:
        bars = _bars([(1, 1, 1, 1)] * 4)  # 09:30..10:15 starts, ends 09:45..10:30
        now = datetime(2026, 7, 20, 14, 20, tzinfo=timezone.utc)  # 10:20 ET
        settled = settled_bars(bars, now)
        # settle cutoff 10:00 ET: bars ending 09:45 and 10:00 pass, 10:15/10:30 do not
        assert len(settled) == 2

    def test_empty_frame_passes_through(self) -> None:
        empty = pd.DataFrame()
        assert settled_bars(empty, datetime.now(timezone.utc)).empty


def test_opening_range_needs_two_bars() -> None:
    assert opening_range(_bars([(100, 101, 99, 100)])) is None
    assert opening_range(_bars([(100, 101, 99, 100), (100, 102, 98, 101)])) == (102.0, 98.0)


def test_breakout_fills_at_next_bar_open_and_targets() -> None:
    # OR = 102/98 (range 4). Bar3 closes above 102 -> signal; bar4 open fills; bar5 hits target.
    bars = _bars([
        (100, 101, 99, 100), (100, 102, 98, 101),  # opening range
        (101, 103, 100, 102.5),                     # breakout close > 102
        (103, 104, 102, 103.5),                     # fill at open 103
        (104, 108, 103, 107.5),                     # high 108 >= target 103+4=107
    ])
    actions, marker = decide(
        "SPY", bars, None, or_range=(102.0, 98.0), last_processed=None, traded_today=False,
    )
    assert [a.kind for a in actions] == ["buy", "sell"]
    assert actions[0].price == pytest.approx(103.0)
    assert actions[1].price == pytest.approx(107.0)  # pessimistic: target, never better
    assert "Ziel" in actions[1].reason
    assert marker == bars.index[-1].isoformat()


def test_signal_on_newest_bar_is_carried_to_the_next_run() -> None:
    bars_run1 = _bars([
        (100, 101, 99, 100), (100, 102, 98, 101), (101, 103, 100, 102.5),
    ])
    actions1, marker1 = decide(
        "SPY", bars_run1, None, or_range=(102.0, 98.0), last_processed=None, traded_today=False,
    )
    assert actions1 == []  # fill bar not settled yet — nothing booked
    assert marker1 == bars_run1.index[-2].isoformat()  # signal bar left unprocessed
    bars_run2 = _bars([
        (100, 101, 99, 100), (100, 102, 98, 101), (101, 103, 100, 102.5), (103, 104, 102, 103.5),
    ])
    actions2, _ = decide(
        "SPY", bars_run2, None, or_range=(102.0, 98.0), last_processed=marker1, traded_today=False,
    )
    assert [a.kind for a in actions2] == ["buy"]
    assert actions2[0].price == pytest.approx(103.0)


def test_stop_fills_pessimistically_and_entry_bar_can_stop_itself() -> None:
    # entry at 103, stop = 103 - 2 = 101; the very entry bar trades down through it
    bars = _bars([
        (100, 101, 99, 100), (100, 102, 98, 101), (101, 103, 100, 102.5),
        (103, 103.5, 100.5, 101.0),  # fill 103, low 100.5 <= stop 101 -> same-bar stop
    ])
    actions, _ = decide(
        "SPY", bars, None, or_range=(102.0, 98.0), last_processed=None, traded_today=False,
    )
    assert [a.kind for a in actions] == ["buy", "sell"]
    assert actions[1].price == pytest.approx(101.0)
    assert "Stop" in actions[1].reason


def test_open_position_is_flattened_on_the_last_session_bar() -> None:
    position = LanePosition(qty=10, entry_price=103.0, opened_at="2026-07-20T10:15:00")
    bars = _bars([(103, 104, 102.5, 103.2)], start="15:45")
    actions, _ = decide(
        "SPY", bars, position, or_range=(102.0, 98.0), last_processed=None, traded_today=True,
    )
    assert [a.kind for a in actions] == ["sell"]
    assert actions[0].price == pytest.approx(103.2)
    assert "Session-Ende" in actions[0].reason


def test_no_second_entry_after_a_trade_today() -> None:
    bars = _bars([
        (100, 101, 99, 100), (100, 102, 98, 101), (101, 103, 100, 102.5), (103, 104, 102, 103.5),
    ])
    actions, _ = decide(
        "SPY", bars, None, or_range=(102.0, 98.0), last_processed=None, traded_today=True,
    )
    assert actions == []


def test_reprocessing_the_same_bars_is_a_no_op() -> None:
    bars = _bars([
        (100, 101, 99, 100), (100, 102, 98, 101), (101, 103, 100, 102.5), (103, 104, 102, 103.5),
    ])
    actions1, marker = decide(
        "SPY", bars, None, or_range=(102.0, 98.0), last_processed=None, traded_today=False,
    )
    position = LanePosition(qty=10, entry_price=103.0, opened_at="t")
    actions2, marker2 = decide(
        "SPY", bars, position, or_range=(102.0, 98.0), last_processed=marker, traded_today=True,
    )
    assert actions1 and actions2 == []
    assert marker2 == marker
