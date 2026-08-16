"""Swing lane engine: bullish-event entries, exit rules, holding-period math."""
from __future__ import annotations

from equity_scout.shortterm_book import LaneBook, buy
from equity_scout.st_swing import check_exits, pick_entries


def _event(ticker: str, event_type: str, seen_at: str = "2026-07-20T12:00:00+00:00") -> dict:
    return {"ticker": ticker, "event_type": event_type, "seen_at": seen_at}


def test_pick_entries_takes_only_bullish_events_once_per_ticker() -> None:
    book = LaneBook.fresh("swing")
    events = [
        _event("AAPL", "beat"),
        _event("AAPL", "guidance_up"),  # same ticker — one entry only
        _event("MSFT", "miss"),  # bearish — long-only lane ignores it
        _event("NVDA", "guidance_up"),
    ]
    picks = pick_entries(events, book)
    assert [p["ticker"] for p in picks] == ["AAPL", "NVDA"]
    assert picks[0]["reason"] == "event: beat"


def test_pick_entries_skips_held_tickers_and_respects_slots() -> None:
    book = LaneBook.fresh("swing")
    book, _ = buy(book, "AAPL", 100.0, "t0", fraction=0.1, reason="x")
    events = [_event(t, "beat") for t in ("AAPL", "MSFT", "NVDA", "AMZN")]
    picks = pick_entries(events, book, max_positions=3)
    assert [p["ticker"] for p in picks] == ["MSFT", "NVDA"]  # AAPL held, 2 free slots


def test_pick_entries_full_book_yields_nothing() -> None:
    """v13 R7: with zero free slots the old cap check still returned one pick (it fired
    only after an append), so a full lane crept past max_positions run by run."""
    book = LaneBook.fresh("swing")
    for i, ticker in enumerate(("AAPL", "MSFT", "NVDA")):
        book, _ = buy(book, ticker, 100.0, f"t{i}", fraction=0.1, reason="x")
    assert pick_entries([_event("AMZN", "beat")], book, max_positions=3) == []


def test_check_exits_target_stop_and_max_holding() -> None:
    book = LaneBook.fresh("swing")
    book, _ = buy(book, "WIN", 100.0, "2026-07-18", fraction=0.1, reason="x", slippage_bps=0.0)
    book, _ = buy(book, "LOSE", 100.0, "2026-07-18", fraction=0.1, reason="x", slippage_bps=0.0)
    book, _ = buy(book, "OLD", 100.0, "2026-07-10", fraction=0.1, reason="x", slippage_bps=0.0)
    book, _ = buy(book, "HOLD", 100.0, "2026-07-18", fraction=0.1, reason="x", slippage_bps=0.0)
    prices = {"WIN": 106.0, "LOSE": 96.5, "OLD": 101.0, "HOLD": 101.0}
    exits = {e["ticker"]: e["reason"] for e in check_exits(book, prices, "2026-07-20")}
    assert "Gewinnziel" in exits["WIN"]
    assert "Stop" in exits["LOSE"]
    assert "Max-Haltedauer" in exits["OLD"]
    assert "HOLD" not in exits


def test_check_exits_holds_positions_without_a_price() -> None:
    book = LaneBook.fresh("swing")
    book, _ = buy(book, "GHOST", 100.0, "2026-07-01", fraction=0.1, reason="x")
    assert check_exits(book, {}, "2026-07-20") == []  # old position, but no price -> untouched


def test_pick_entries_skips_events_older_than_three_trading_days() -> None:
    from datetime import datetime, timezone

    events = [
        _event("OLDN", "beat", seen_at="2026-07-08T14:00:00+00:00"),
        _event("NEWN", "beat", seen_at="2026-07-17T14:00:00+00:00"),  # Fri before Mon
    ]
    book = LaneBook.fresh("swing")
    picks = pick_entries(events, book, now=datetime(2026, 7, 20, 18, 0, tzinfo=timezone.utc))
    assert [p["ticker"] for p in picks] == ["NEWN"]


def test_pick_entries_explained_names_why_candidates_fell_out() -> None:
    """The no-trade book: every examined-but-rejected opportunity comes back as data.
    Not logged: empty tickers, same-run duplicates (noise, not opportunities) and
    8-K types (directionless by design)."""
    from datetime import datetime, timezone

    from equity_scout.shortterm_book import buy
    from equity_scout.st_swing import pick_entries_explained

    now = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
    book = LaneBook.fresh("swing")
    book, _ = buy(book, "HELD", 100.0, "t0", fraction=0.1, reason="x")
    events = [
        _event("FRESH", "beat", "2026-07-21T12:00:00+00:00"),
        _event("HELD", "beat", "2026-07-21T12:00:00+00:00"),
        _event("STALE", "beat", "2026-07-10T12:00:00+00:00"),
        _event("NOISE", "unknown", "2026-07-21T12:00:00+00:00"),
        _event("MISS", "miss", "2026-07-21T12:00:00+00:00"),
        _event("FILING", "earnings_filed", "2026-07-21T12:00:00+00:00"),
        _event("", "beat", "2026-07-21T12:00:00+00:00"),
        _event("FRESH", "guidance_up", "2026-07-20T12:00:00+00:00"),  # same-run duplicate
    ]
    picks, rejections = pick_entries_explained(events, book, now=now)
    assert [p["ticker"] for p in picks] == ["FRESH"]
    by_ticker = {r["ticker"]: r for r in rejections}
    assert by_ticker["HELD"]["reason"] == "already_held"
    assert by_ticker["STALE"]["reason"] == "too_old"
    assert by_ticker["NOISE"]["reason"] == "not_bullish"
    assert by_ticker["MISS"]["reason"] == "not_bullish"
    assert "FILING" not in by_ticker
    assert "" not in by_ticker
    assert len([r for r in rejections if r["ticker"] == "FRESH"]) == 0
    # the rejection keeps the EVENT's timestamp: it is the stable idempotency key and the
    # honest start of any "what would have happened" simulation
    assert by_ticker["STALE"]["seen_at"] == "2026-07-10T12:00:00+00:00"
    assert by_ticker["NOISE"]["detail"].startswith("unknown")


def test_pick_entries_explained_marks_cap_losers() -> None:
    """Qualified events that only lose to the slot cap are the most interesting rows in
    the no-trade book — they measure whether MAX_POSITIONS is the binding constraint."""
    from datetime import datetime, timezone

    from equity_scout.st_swing import pick_entries_explained

    now = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
    book = LaneBook.fresh("swing")
    events = [
        _event("A", "beat", "2026-07-21T15:00:00+00:00"),
        _event("B", "beat", "2026-07-21T14:00:00+00:00"),
        _event("C", "beat", "2026-07-21T13:00:00+00:00"),
    ]
    picks, rejections = pick_entries_explained(events, book, now=now, max_positions=1)
    assert [p["ticker"] for p in picks] == ["A"]
    assert [(r["ticker"], r["reason"]) for r in rejections] == [
        ("B", "cap_full"), ("C", "cap_full"),
    ]


def test_pick_entries_explained_full_book_rejects_all_qualified() -> None:
    from datetime import datetime, timezone

    from equity_scout.shortterm_book import buy
    from equity_scout.st_swing import pick_entries_explained

    now = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
    book = LaneBook.fresh("swing")
    book, _ = buy(book, "X", 100.0, "t0", fraction=0.1, reason="x")
    picks, rejections = pick_entries_explained(
        [_event("A", "beat", "2026-07-21T15:00:00+00:00")], book, now=now, max_positions=1,
    )
    assert picks == []
    assert [(r["ticker"], r["reason"]) for r in rejections] == [("A", "cap_full")]


def test_pick_entries_stays_a_thin_wrapper() -> None:
    book = LaneBook.fresh("swing")
    events = [_event("AAPL", "beat"), _event("MSFT", "miss")]
    assert pick_entries(events, book) == [{
        "ticker": "AAPL", "reason": "event: beat", "seen_at": "2026-07-20T12:00:00+00:00",
    }]
