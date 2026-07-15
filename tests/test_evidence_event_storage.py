"""Persistence for classified beat/miss/guidance + 8-K category events (Strang B3):
idempotent by event_key, seen_at always injected (honest latency fields, never a
wall-clock call inside the storage layer)."""
from __future__ import annotations

from equity_scout.evidence.event_classifier import ClassifiedEvent
from equity_scout.evidence.event_storage import (
    init_classified_events_db,
    load_classified_events,
    save_classified_events,
)

SEEN_AT = "2026-07-15T09:00:00+00:00"


def _event(**overrides) -> ClassifiedEvent:
    base = dict(
        ticker="AAPL",
        event_type="beat",
        source="news",
        published_at="2026-07-10",
        detail="Apple beats estimates",
        event_key="news-AAPL-abc123",
    )
    base.update(overrides)
    return ClassifiedEvent(**base)


def test_init_creates_table_without_error(tmp_path):
    db = str(tmp_path / "ev.db")
    init_classified_events_db(db)
    init_classified_events_db(db)  # idempotent CREATE TABLE IF NOT EXISTS


def test_save_classified_events_inserts_and_returns_new_ones(tmp_path):
    db = str(tmp_path / "ev.db")
    inserted = save_classified_events(db, [_event()], seen_at=SEEN_AT)
    assert len(inserted) == 1
    rows = load_classified_events(db)
    assert len(rows) == 1
    row = rows[0]
    assert row["ticker"] == "AAPL"
    assert row["event_type"] == "beat"
    assert row["source"] == "news"
    assert row["published_at"] == "2026-07-10"
    assert row["seen_at"] == SEEN_AT
    assert row["detail"] == "Apple beats estimates"
    assert row["event_key"] == "news-AAPL-abc123"


def test_save_classified_events_is_idempotent_by_event_key(tmp_path):
    """Re-classifying the same fact (a re-collected headline/filing) must never
    duplicate the row or shift its original seen_at."""
    db = str(tmp_path / "ev.db")
    first = save_classified_events(db, [_event()], seen_at=SEEN_AT)
    assert len(first) == 1
    second = save_classified_events(
        db, [_event()], seen_at="2026-07-16T09:00:00+00:00"
    )
    assert second == []
    rows = load_classified_events(db)
    assert len(rows) == 1
    assert rows[0]["seen_at"] == SEEN_AT  # original collection time, not the re-run's


def test_save_classified_events_missing_published_at_stays_null(tmp_path):
    """A source without a published_at (e.g. an 8-K item with no acceptanceDateTime,
    or a dropped news pubDate) must be stored as honest NULL, never backfilled from
    seen_at."""
    db = str(tmp_path / "ev.db")
    save_classified_events(db, [_event(published_at=None)], seen_at=SEEN_AT)
    rows = load_classified_events(db)
    assert rows[0]["published_at"] is None
    assert rows[0]["seen_at"] == SEEN_AT


def test_load_classified_events_filters_by_ticker(tmp_path):
    db = str(tmp_path / "ev.db")
    save_classified_events(
        db,
        [
            _event(ticker="AAPL", event_key="k1"),
            _event(ticker="MSFT", event_key="k2"),
        ],
        seen_at=SEEN_AT,
    )
    assert {row["ticker"] for row in load_classified_events(db, ticker="MSFT")} == {"MSFT"}
    assert len(load_classified_events(db, ticker="aapl")) == 1  # case-insensitive


def test_load_classified_events_empty_db_returns_empty_list(tmp_path):
    db = str(tmp_path / "ev.db")
    assert load_classified_events(db) == []
