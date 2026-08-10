"""Crypto lane: Kraken parsing, completed-bar gate, Donchian entry/exit, idempotency."""
from __future__ import annotations

import pandas as pd
import pytest

from equity_scout.kraken_data import completed_bars, fetch_ohlc
from equity_scout.shortterm_book import LanePosition
from equity_scout.st_crypto import decide_pair


def _bars(closes: list[float], *, spread: float = 1.0) -> pd.DataFrame:
    # Daily bars since 2026-08-10 — the lane's timescale, see st_crypto's docstring.
    index = pd.date_range("2026-07-20 00:00", periods=len(closes), freq="1D", tz="UTC")
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + spread for c in closes],
            "low": [c - spread for c in closes],
            "close": closes,
        },
        index=index,
    )


class TestKrakenParsing:
    def test_fetch_parses_rows_and_none_on_error(self) -> None:
        payload = {
            "error": [],
            "result": {
                "XXBTZUSD": [[1752969600, "100.0", "101.0", "99.0", "100.5", "100.2", "3.2", 42]],
                "last": 1752969600,
            },
        }
        frame = fetch_ohlc("XBTUSD", get_json=lambda url: payload)
        assert frame is not None and len(frame) == 1
        assert frame.iloc[0]["close"] == pytest.approx(100.5)
        assert fetch_ohlc("XBTUSD", get_json=lambda url: None) is None
        assert fetch_ohlc("XBTUSD", get_json=lambda url: {"error": ["EGeneral"]}) is None

    def test_completed_bars_drops_the_running_bar(self) -> None:
        bars = _bars([100.0, 101.0, 102.0])
        assert len(completed_bars(bars)) == 2
        assert completed_bars(bars).index[-1] == bars.index[-2]


def test_entry_on_20_bar_breakout_only() -> None:
    flat = [100.0] * 21
    no_action, marker = decide_pair("BTC", _bars(flat), None, last_processed=None)
    assert no_action is None and marker is not None
    breakout = _bars([100.0] * 20 + [105.0])  # channel high = 101 -> 105 breaks out
    action, _ = decide_pair("BTC", breakout, None, last_processed=None)
    assert action is not None and action.kind == "buy"
    assert action.price == pytest.approx(105.0)
    assert "Donchian-20" in action.reason


def test_channel_exit_and_hard_stop() -> None:
    position = LanePosition(qty=0.1, entry_price=105.0, opened_at="t0")
    channel_break = _bars([100.0] * 20 + [97.0])  # low channel ~99 -> close 97 below it
    action, _ = decide_pair("BTC", channel_break, position, last_processed=None)
    assert action is not None and action.kind == "sell"
    # Hard stop = 105 * (1 - 0.15) = 89.25. The prior bars sit low enough that the channel
    # exit does NOT also trigger, so the reason proves which rule fired.
    stop_hit = _bars([85.0] * 20 + [89.0])
    action2, _ = decide_pair("BTC", stop_hit, position, last_processed=None)
    assert action2 is not None and "Stop" in action2.reason


def test_a_two_percent_dip_no_longer_exits_on_the_daily_timescale() -> None:
    """Regression for the 2026-08-10 rebuild: the old 2 % stop sat inside a single daily
    bar's normal range and would have replaced the channel exit instead of backstopping it."""
    position = LanePosition(qty=0.1, entry_price=105.0, opened_at="t0")
    # -2.4 % from entry, and above the 10-day low channel -> the lane must simply hold.
    dip = _bars([100.0] * 20 + [102.5])
    action, marker = decide_pair("BTC", dip, position, last_processed=None)
    assert action is None and marker is not None


def test_same_bar_is_never_judged_twice() -> None:
    breakout = _bars([100.0] * 20 + [105.0])
    action, marker = decide_pair("BTC", breakout, None, last_processed=None)
    assert action is not None
    repeat, marker2 = decide_pair("BTC", breakout, None, last_processed=marker)
    assert repeat is None and marker2 == marker


def test_too_little_history_is_a_no_op() -> None:
    action, marker = decide_pair("BTC", _bars([100.0] * 10), None, last_processed=None)
    assert action is None and marker is None
