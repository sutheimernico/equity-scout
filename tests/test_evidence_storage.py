"""Evidence event store: idempotent recording + window queries."""
from __future__ import annotations

from equity_scout.evidence.base import SOURCE_13F, SOURCE_CONGRESS, EvidenceEvent
from equity_scout.evidence.storage import events_in_window, record_events

NOW = "2026-07-07T12:00:00+00:00"


def _event(
    source: str = SOURCE_CONGRESS,
    ticker: str = "NVDA",
    event_key: str = "pelosi-2026-06-20-purchase",
    event_date: str = "2026-06-20",
    details: dict | None = None,
) -> EvidenceEvent:
    return EvidenceEvent(
        source=source,
        ticker=ticker,
        event_key=event_key,
        event_date=event_date,
        details=details or {"politician": "Nancy Pelosi", "transaction_type": "purchase"},
    )


def test_record_events_returns_only_new_rows(tmp_path):
    db = str(tmp_path / "test.db")
    first = record_events(db, [_event()], now=NOW)
    assert len(first) == 1

    # Same (source, ticker, event_key) again + one genuinely new event.
    second = record_events(
        db, [_event(), _event(event_key="tuberville-2026-06-25-purchase")], now=NOW
    )
    assert [e.event_key for e in second] == ["tuberville-2026-06-25-purchase"]


def test_events_in_window_filters_by_date_ticker_and_exclusion(tmp_path):
    db = str(tmp_path / "test.db")
    record_events(
        db,
        [
            _event(),  # NVDA, 2026-06-20 — inside a 30-day window
            _event(ticker="MSFT", event_key="old", event_date="2026-01-05"),  # too old
            _event(source=SOURCE_13F, ticker="OXY", event_key="brk-2026q1",
                   event_date="2026-06-30", details={"fund": "Berkshire Hathaway"}),
        ],
        now=NOW,
    )

    all_recent = events_in_window(db, window_days=30, now=NOW)
    assert set(all_recent) == {"NVDA", "OXY"}
    assert all_recent["NVDA"][0]["details"]["politician"] == "Nancy Pelosi"

    only_nvda = events_in_window(db, window_days=30, now=NOW, tickers=["nvda"])
    assert set(only_nvda) == {"NVDA"}

    without_nvda = events_in_window(db, window_days=30, now=NOW, exclude_tickers=["NVDA"])
    assert set(without_nvda) == {"OXY"}


def test_events_in_window_handles_datetime_event_dates(tmp_path):
    db = str(tmp_path / "test.db")
    record_events(
        db,
        [_event(event_key="with-time", event_date="2026-07-01T09:30:00+00:00")],
        now=NOW,
    )
    assert "NVDA" in events_in_window(db, window_days=10, now=NOW)
