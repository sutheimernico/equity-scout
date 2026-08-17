"""Context conditions: no look-ahead, honest absence, and signals usable as conditions."""
import pandas as pd

from equity_scout.matrix.contexts import (
    CONTEXTS,
    NEWS_WINDOW_MINUTES,
    after_news,
    calm_market,
    first_hour,
    last_hour,
    recent_signal_gate,
    stressed_market,
    uptrend,
)


def _bars(n: int, start: str = "2024-01-02T14:30:00Z", step: float = 0.0) -> pd.DataFrame:
    index = pd.date_range(start, periods=n, freq="1min")
    closes = [100.0 + i * step for i in range(n)]
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes,
         "volume": [100] * n},
        index=index, dtype=float,
    )


def test_every_condition_is_registered_with_a_mask():
    assert "none" in CONTEXTS
    for name, spec in CONTEXTS.items():
        assert callable(spec.mask), name
        assert spec.description, name


def test_time_of_day_conditions_split_the_session():
    bars = _bars(400)  # 14:30Z -> 21:10Z, i.e. 09:30-16:10 ET
    assert first_hour(bars).sum() == 60  # 09:30-10:30
    assert last_hour(bars).iloc[-1]  # 16:00+ is inside "from 15:00"
    assert not first_hour(bars).iloc[-1]


def test_after_news_only_covers_the_window_after_a_wire_item():
    bars = _bars(120)
    stamps = pd.Series([pd.Timestamp("2024-01-02T14:40:00Z")])
    mask = after_news(bars, news_stamps=stamps)
    assert not mask.iloc[5]  # before the item
    assert mask.iloc[11]  # 14:41, inside the window
    assert mask.iloc[10 + NEWS_WINDOW_MINUTES]  # last minute inside
    assert not mask.iloc[11 + NEWS_WINDOW_MINUTES]  # just outside


def test_after_news_without_news_is_all_false_not_all_true():
    bars = _bars(30)
    assert not after_news(bars, news_stamps=None).any()
    assert not after_news(bars, news_stamps=pd.Series([], dtype="datetime64[ns, UTC]")).any()


def test_vix_conditions_use_the_previous_session_close():
    bars = _bars(60, start="2024-01-03T14:30:00Z")
    vix = pd.Series([12.0, 30.0], index=pd.to_datetime(["2024-01-02", "2024-01-03"]))
    # the bar is on the 3rd, so the condition must read the 2nd's close (12 -> calm)
    assert calm_market(bars, vix_closes=vix).all()
    assert not stressed_market(bars, vix_closes=vix).any()


def test_vix_conditions_without_a_snapshot_never_hold():
    bars = _bars(10)
    assert not calm_market(bars, vix_closes=None).any()
    assert not stressed_market(bars, vix_closes=None).any()


def test_uptrend_uses_a_shifted_average_so_it_cannot_peek():
    rising = _bars(120, step=0.1)
    flat = _bars(120)
    assert uptrend(rising).iloc[-1]
    assert not uptrend(flat).iloc[-1]  # no trend, no claim


def test_a_signal_becomes_a_condition_that_holds_after_it_fired():
    bars = _bars(40)
    fired = pd.Series([False] * 40, index=bars.index)
    fired.iloc[10] = True
    gate = recent_signal_gate(lambda b, **_: fired, threshold=0.0, window_bars=5)
    mask = gate(bars)
    assert not mask.iloc[10]  # never the bar itself — the condition must precede the signal
    assert mask.iloc[11] and mask.iloc[15]
    assert not mask.iloc[16]  # window has passed
