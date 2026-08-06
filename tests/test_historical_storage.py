"""Historical catalyst event store: idempotent recording, read-back, one-way resolution."""
from __future__ import annotations

import pytest

from equity_scout.evidence.historical_storage import (
    HistoricalEvent,
    mark_resolved,
    mark_unresolvable,
    record_historical_events,
    unresolved_events,
)

NOW = "2026-08-06T12:00:00+00:00"


def _event(
    source: str = "congress",
    person: str = "Nancy Pelosi",
    ticker: str = "NVDA",
    event_key: str = "pelosi-2026-06-20-purchase",
    t0: str = "2026-06-20",
    details: dict | None = None,
) -> HistoricalEvent:
    return HistoricalEvent(
        source=source,
        person=person,
        ticker=ticker,
        event_key=event_key,
        t0=t0,
        details=details or {"transaction_type": "purchase"},
    )


def test_record_historical_events_returns_only_new_rows(tmp_path):
    db = str(tmp_path / "test.db")
    first = record_historical_events(db, [_event()], now=NOW)
    assert len(first) == 1

    # Same (source, ticker, event_key) again + one genuinely new event.
    second = record_historical_events(
        db, [_event(), _event(event_key="tuberville-2026-06-25-purchase")], now=NOW
    )
    assert [e.event_key for e in second] == ["tuberville-2026-06-25-purchase"]


def test_unresolved_events_excludes_resolved_and_unresolvable(tmp_path):
    db = str(tmp_path / "test.db")
    record_historical_events(
        db,
        [
            _event(event_key="k1"),
            _event(event_key="k2", ticker="MSFT"),
            _event(event_key="k3", ticker="DELISTEDCO"),
        ],
        now=NOW,
    )
    open_rows = unresolved_events(db)
    assert {r["event_key"] for r in open_rows} == {"k1", "k2", "k3"}
    assert open_rows[0]["ticker"] == "NVDA"
    assert open_rows[0]["person"] == "Nancy Pelosi"
    assert open_rows[0]["details"]["transaction_type"] == "purchase"

    k1_id = next(r["id"] for r in open_rows if r["event_key"] == "k1")
    k3_id = next(r["id"] for r in open_rows if r["event_key"] == "k3")

    mark_resolved(db, k1_id, {"r_1w": 0.01, "r_1m": 0.02}, now=NOW)
    mark_unresolvable(db, k3_id, "no_price_history", now=NOW)

    remaining = unresolved_events(db)
    assert {r["event_key"] for r in remaining} == {"k2"}


def test_unresolved_events_respects_limit(tmp_path):
    db = str(tmp_path / "test.db")
    record_historical_events(
        db, [_event(event_key="k1"), _event(event_key="k2", ticker="MSFT")], now=NOW
    )
    assert len(unresolved_events(db, limit=1)) == 1
    assert len(unresolved_events(db)) == 2


def test_mark_resolved_is_single_transition(tmp_path):
    db = str(tmp_path / "test.db")
    record_historical_events(db, [_event()], now=NOW)
    event_id = unresolved_events(db)[0]["id"]

    assert mark_resolved(
        db, event_id, {"r_1w": 0.01, "r_1m": 0.02, "r_3m": 0.03, "r_6m": 0.04, "r_12m": 0.05},
        now=NOW,
    )
    # A second attempt is refused; the first resolution stands.
    assert not mark_resolved(db, event_id, {"r_1w": -0.9}, now="2026-09-01T00:00:00+00:00")

    with pytest.raises(ValueError):
        mark_resolved(db, 999, {"r_1w": 0.0}, now=NOW)


def test_mark_resolved_refuses_empty_returns(tmp_path):
    db = str(tmp_path / "test.db")
    record_historical_events(db, [_event()], now=NOW)
    event_id = unresolved_events(db)[0]["id"]

    with pytest.raises(ValueError):
        mark_resolved(db, event_id, {}, now=NOW)
    # Refused before any write — the row is still open.
    assert unresolved_events(db) != []


def test_mark_resolved_accepts_partial_horizons(tmp_path):
    """Young events: only the elapsed windows are resolvable yet."""
    db = str(tmp_path / "test.db")
    record_historical_events(db, [_event()], now=NOW)
    event_id = unresolved_events(db)[0]["id"]

    assert mark_resolved(db, event_id, {"r_1w": 0.01}, now=NOW)
    assert unresolved_events(db) == []


def test_mark_unresolvable_is_single_transition(tmp_path):
    db = str(tmp_path / "test.db")
    record_historical_events(db, [_event()], now=NOW)
    event_id = unresolved_events(db)[0]["id"]

    assert mark_unresolvable(db, event_id, "no_price_history", now=NOW)
    # A second attempt is refused; the first reason stands.
    assert not mark_unresolvable(db, event_id, "panel_gap", now="2026-09-01T00:00:00+00:00")

    with pytest.raises(ValueError):
        mark_unresolvable(db, 999, "no_price_history", now=NOW)


def test_mark_resolved_and_mark_unresolvable_are_mutually_exclusive(tmp_path):
    db = str(tmp_path / "test.db")
    record_historical_events(db, [_event()], now=NOW)
    event_id = unresolved_events(db)[0]["id"]

    assert mark_unresolvable(db, event_id, "no_price_history", now=NOW)
    # Already terminal via unresolvable — a resolve attempt must not overwrite it.
    assert not mark_resolved(db, event_id, {"r_1w": 0.01}, now=NOW)
