"""Alpaca IEX bars must satisfy the exact contract intraday_bars.fetch_bars satisfies:
tz-aware America/New_York index, lowercase open/high/low/close columns. st_session.decide()
must not be able to tell the two feeds apart."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from equity_scout.alpaca_data import (
    RANGE_BAR_MINUTES,
    TRIGGER_BAR_MINUTES,
    AlpacaDataError,
    complete_bars,
    parse_bars,
    regular_session_bars,
)


def _payload() -> dict:
    return {
        "bars": {
            "AAPL": [
                {"t": "2026-08-04T13:30:00Z", "o": 300.0, "h": 302.0, "l": 299.5,
                 "c": 301.0, "v": 1000},
                {"t": "2026-08-04T13:45:00Z", "o": 301.0, "h": 303.0, "l": 300.5,
                 "c": 302.5, "v": 1200},
            ]
        }
    }


def test_parse_yields_new_york_index_and_lowercase_columns() -> None:
    frames = parse_bars(_payload())
    frame = frames["AAPL"]
    assert str(frame.index.tz) == "America/New_York"
    assert frame.index[0].hour == 9 and frame.index[0].minute == 30
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
    assert frame["close"].iloc[-1] == 302.5


def test_empty_series_is_absent_not_zero() -> None:
    assert parse_bars({"bars": {"AAPL": []}}) == {}


def test_missing_bars_key_raises_loudly() -> None:
    with pytest.raises(AlpacaDataError, match="kein 'bars'"):
        parse_bars({"message": "forbidden"})


def test_complete_bars_drops_the_still_running_interval() -> None:
    frames = parse_bars(_payload())
    # 09:45 bar covers 09:45-10:00; at 09:52 it is not finished yet.
    now = datetime(2026, 8, 4, 9, 52, tzinfo=ZoneInfo("America/New_York"))
    kept = complete_bars(frames["AAPL"], now, bar_minutes=RANGE_BAR_MINUTES)
    assert len(kept) == 1
    assert kept.index[-1].minute == 30


def test_complete_bars_keeps_a_just_finished_interval() -> None:
    frames = parse_bars(_payload())
    now = datetime(2026, 8, 4, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    assert len(complete_bars(frames["AAPL"], now, bar_minutes=RANGE_BAR_MINUTES)) == 2


def test_the_gate_follows_the_resolution_it_is_given() -> None:
    """Design decision 5: the lane runs two resolutions at once — a 15-minute range and a
    1-minute trigger. The completeness gate must therefore take its interval from the
    caller. Judged as 1-minute bars, both rows above finished long ago; judged as
    15-minute bars at 09:52, the second one has not.
    """
    frames = parse_bars(_payload())
    now = datetime(2026, 8, 4, 9, 52, tzinfo=ZoneInfo("America/New_York"))
    assert len(complete_bars(frames["AAPL"], now, bar_minutes=TRIGGER_BAR_MINUTES)) == 2
    assert len(complete_bars(frames["AAPL"], now, bar_minutes=RANGE_BAR_MINUTES)) == 1


def test_complete_bars_on_an_empty_frame_is_empty_not_an_error() -> None:
    frames = parse_bars(_payload())
    empty = frames["AAPL"].iloc[:0]
    now = datetime(2026, 8, 4, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    assert complete_bars(empty, now, bar_minutes=TRIGGER_BAR_MINUTES).empty


NY = ZoneInfo("America/New_York")


def _frame(*stamps: str) -> pd.DataFrame:
    """Bars at the given New-York wall-clock times, one minute apart in intent."""
    index = pd.DatetimeIndex([pd.Timestamp(s, tz=NY) for s in stamps])
    return pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1},
        index=index,
    )


def test_regular_session_drops_the_premarket_prints() -> None:
    """The gate that keeps `opening_range` meaningful.

    yfinance handed the other feed a regular-session-only frame for free (period="1d",
    prepost off). Alpaca returns every print in the requested window, and `st_session
    .opening_range` takes the FIRST TWO BARS it is given — on a raw Alpaca frame that would
    be a 07:xx pre-market range, and every stop and target derives from it.
    """
    bars = _frame("2026-08-04 07:15", "2026-08-04 09:29", "2026-08-04 09:30",
                  "2026-08-04 09:31", "2026-08-04 16:00", "2026-08-04 18:30")
    kept = regular_session_bars(bars)
    assert [str(t.time()) for t in kept.index] == ["09:30:00", "09:31:00"]


def test_regular_session_keeps_one_day_only() -> None:
    """A multi-day window must not splice yesterday's tail onto today's opening range."""
    bars = _frame("2026-08-03 15:55", "2026-08-04 09:30", "2026-08-04 09:31")
    kept = regular_session_bars(bars)
    assert [str(t.date()) for t in kept.index] == ["2026-08-04", "2026-08-04"]


def test_regular_session_can_be_pinned_to_a_given_day() -> None:
    bars = _frame("2026-08-03 09:30", "2026-08-04 09:30")
    kept = regular_session_bars(bars, session_date=date(2026, 8, 3))
    assert [str(t.date()) for t in kept.index] == ["2026-08-03"]


def test_regular_session_on_an_empty_frame_is_empty_not_an_error() -> None:
    assert regular_session_bars(pd.DataFrame()).empty


def test_parse_latest_trades_maps_price_and_time_and_skips_empty() -> None:
    """Gap-fade lane: the pre-market signal is the LATEST IEX trade per ticker. A ticker
    that has not printed pre-market is ABSENT, never a zero — absence means no signal."""
    from datetime import datetime, timezone

    from equity_scout.alpaca_data import parse_latest_trades

    payload = {"trades": {
        "NVDA": {"t": "2026-08-17T13:22:05.123456Z", "p": 97.5, "s": 100},
        "GONE": {},
    }}
    trades = parse_latest_trades(payload)
    assert set(trades) == {"NVDA"}
    price, at = trades["NVDA"]
    assert price == 97.5
    assert at == datetime(2026, 8, 17, 13, 22, 5, 123456, tzinfo=timezone.utc)


def test_parse_latest_trades_rejects_a_contract_break() -> None:
    import pytest

    from equity_scout.alpaca_data import AlpacaDataError, parse_latest_trades

    with pytest.raises(AlpacaDataError):
        parse_latest_trades({"error": "forbidden"})


def test_us_symbols_drops_exchange_suffixed_listings() -> None:
    """One foreign listing in the batch answers 400 for the WHOLE request, so the caller
    must never send them. Deliberately NOT the SEC collectors' cheaper `"." in ticker`
    rule (form4, edgar_8k): that one also drops US class shares, and a silently shrunken
    universe is exactly the failure this lane already had."""
    from equity_scout.alpaca_data import us_symbols

    tickers = ["MSFT", "0006.HK", "ALV.DE", "AAPL", "9984.T", "BRK.B"]
    assert us_symbols(tickers) == ["AAPL", "BRK.B", "MSFT"]


def test_us_symbols_keeps_the_class_share_dot() -> None:
    """BRK.B and BF.B are US listings whose dot is a share class, not an exchange —
    dropping them would silently shrink the tradable universe."""
    from equity_scout.alpaca_data import us_symbols

    assert us_symbols(["BF.B", "RDS.A", "ADAM"]) == ["ADAM", "BF.B", "RDS.A"]


def test_us_symbols_keeps_plain_tickers_that_spell_a_venue() -> None:
    """T is AT&T and L is Loews — both are US symbols whose whole name equals a Yahoo
    exchange suffix. The suffix only counts when there actually is a dot in front of it."""
    from equity_scout.alpaca_data import us_symbols

    assert us_symbols(["T", "L", "9984.T", "EZJ.L"]) == ["L", "T"]


class _FakeResponse:
    """Just enough of httpx.Response for the retry loop."""

    def __init__(self, status_code: int, *, text: str = "", payload: dict | None = None):
        self.status_code = status_code
        self.text = text
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


class _RecordingClient:
    """Answers 400 'invalid symbol' for every symbol in `bad`, 200 otherwise, and records
    which symbol lists it was asked about."""

    def __init__(self, bad: set[str], payload: dict):
        self.bad = bad
        self.payload = payload
        self.asked: list[list[str]] = []

    def get(self, url: str, params: dict) -> _FakeResponse:
        symbols = params["symbols"].split(",")
        self.asked.append(symbols)
        hit = next((s for s in symbols if s in self.bad), None)
        if hit is not None:
            return _FakeResponse(
                400, text=f'{{"message":"code=400, message=invalid symbol: {hit}"}}'
            )
        return _FakeResponse(200, payload=self.payload)


def test_a_delisted_symbol_is_dropped_instead_of_killing_the_batch(capsys) -> None:
    """`us_symbols` removes foreign listings; it cannot remove a US ticker that was delisted
    since the watchlist was built. Alpaca answers 400 for the WHOLE batch on one unknown
    symbol, so without this retry a single dead ticker costs every quote in the request —
    the failure that cost the gap-fade lane its first four trading days."""
    from equity_scout.alpaca_data import get_dropping_invalid_symbols

    client = _RecordingClient({"DEAD"}, {"trades": {}})
    payload = get_dropping_invalid_symbols(
        client, "http://x/trades/latest", {"feed": "iex"},
        ["AAPL", "DEAD", "MSFT"], label="GET /trades",
    )

    assert payload == {"trades": {}}
    assert client.asked == [["AAPL", "DEAD", "MSFT"], ["AAPL", "MSFT"]]
    assert "DEAD" in capsys.readouterr().err  # never silently shrink the universe


def test_several_dead_symbols_are_peeled_off_one_by_one(capsys) -> None:
    """Alpaca names one culprit per answer, so a batch with two dead tickers needs two
    retries. The cap exists so a systematically failing batch stays loud rather than
    degenerating into single-symbol requests."""
    from equity_scout.alpaca_data import get_dropping_invalid_symbols

    client = _RecordingClient({"DEAD", "GONE"}, {"bars": {}})
    get_dropping_invalid_symbols(
        client, "http://x/bars", {}, ["DEAD", "MSFT", "GONE"], label="GET /bars"
    )

    assert client.asked[-1] == ["MSFT"]
    warning = capsys.readouterr().err
    assert "DEAD" in warning and "GONE" in warning


def test_a_400_naming_a_symbol_we_never_sent_stays_loud() -> None:
    """Dropping something we did not request would turn an unknown error into a silently
    shrinking universe — the exact failure class this retry exists to prevent."""
    from equity_scout.alpaca_data import AlpacaDataError, get_dropping_invalid_symbols

    class _Stranger:
        def get(self, url: str, params: dict) -> _FakeResponse:
            return _FakeResponse(400, text='{"message":"invalid symbol: NOTOURS"}')

    with pytest.raises(AlpacaDataError, match="NOTOURS"):
        get_dropping_invalid_symbols(
            _Stranger(), "http://x/bars", {}, ["AAPL"], label="GET /bars"
        )


def test_a_non_400_error_is_never_treated_as_a_bad_symbol() -> None:
    """403 (wrong feed/plan) and 429 (rate limit) are conditions of the request, not of a
    symbol. Peeling symbols off them would hide the real cause behind an empty result."""
    from equity_scout.alpaca_data import AlpacaDataError, get_dropping_invalid_symbols

    class _Forbidden:
        def get(self, url: str, params: dict) -> _FakeResponse:
            return _FakeResponse(403, text="subscription does not permit sip")

    with pytest.raises(AlpacaDataError, match="403"):
        get_dropping_invalid_symbols(
            _Forbidden(), "http://x/bars", {}, ["AAPL"], label="GET /bars"
        )


def test_every_symbol_rejected_raises_instead_of_returning_nothing() -> None:
    """An empty remainder must not answer 200-with-no-data: 'no signal today' and 'we could
    not ask about anything' are different states and the lane treats them differently."""
    from equity_scout.alpaca_data import AlpacaDataError, get_dropping_invalid_symbols

    client = _RecordingClient({"DEAD", "GONE"}, {"bars": {}})
    with pytest.raises(AlpacaDataError, match="jedes angefragte Symbol"):
        get_dropping_invalid_symbols(
            client, "http://x/bars", {}, ["DEAD", "GONE"], label="GET /bars"
        )


def test_more_dead_symbols_than_the_cap_stays_loud() -> None:
    """Beyond the cap the batch is not worth decomposing further — a request that keeps
    failing is a defect to report, not a loop to run."""
    from equity_scout.alpaca_data import (
        MAX_INVALID_SYMBOL_RETRIES,
        AlpacaDataError,
        get_dropping_invalid_symbols,
    )

    dead = [f"D{i}" for i in range(MAX_INVALID_SYMBOL_RETRIES + 1)]
    client = _RecordingClient(set(dead), {"bars": {}})
    with pytest.raises(AlpacaDataError, match="immer noch 400"):
        get_dropping_invalid_symbols(
            client, "http://x/bars", {}, [*dead, "MSFT"], label="GET /bars"
        )


def test_the_culprit_is_matched_case_insensitively_but_dropped_as_sent() -> None:
    """We send what the watchlist holds; Alpaca echoes its own casing. Matching on the
    echoed string alone would fail to find the symbol and turn a fixable 400 into a hard
    error."""
    from equity_scout.alpaca_data import invalid_symbol

    assert invalid_symbol("invalid symbol: brk.b", ["BRK.B", "AAPL"]) == "BRK.B"
    assert invalid_symbol("some other 400", ["AAPL"]) is None


def test_fetch_latest_trades_actually_routes_through_the_retry(monkeypatch) -> None:
    """The wiring, not the helper: this repo has twice built a block that nothing ever
    passed through (the volume features sat unused for a week). A retry the fetchers do not
    call is worth nothing to the lane."""
    import equity_scout.alpaca_data as mod

    client = _RecordingClient({"DEAD"}, {"trades": {"AAPL": {"p": 10.0, "t":
                                                             "2026-08-21T12:00:00Z"}}})
    monkeypatch.setattr(mod, "auth_headers", lambda: {})
    monkeypatch.setattr(
        "httpx.Client",
        lambda **kwargs: type(
            "_Ctx", (), {"__enter__": lambda s: client, "__exit__": lambda *a: False}
        )(),
    )

    out = mod.fetch_latest_trades(["AAPL", "DEAD"])

    assert set(out) == {"AAPL"}
    assert client.asked == [["AAPL", "DEAD"], ["AAPL"]]


def test_fetch_bars_actually_routes_through_the_retry(monkeypatch) -> None:
    """Same wiring check for the bar feed, which the session and ignition lanes read."""
    import equity_scout.alpaca_data as mod

    client = _RecordingClient({"DEAD"}, _payload())
    monkeypatch.setattr(mod, "auth_headers", lambda: {})
    monkeypatch.setattr(
        "httpx.Client",
        lambda **kwargs: type(
            "_Ctx", (), {"__enter__": lambda s: client, "__exit__": lambda *a: False}
        )(),
    )

    out = mod.fetch_bars(
        ["AAPL", "DEAD"],
        now=datetime(2026, 8, 4, 14, 0, tzinfo=ZoneInfo("UTC")),
        bar_minutes=RANGE_BAR_MINUTES,
    )

    assert set(out) == {"AAPL"}
    assert client.asked == [["AAPL", "DEAD"], ["AAPL"]]
