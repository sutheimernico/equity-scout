"""Congress backfill collector: full per-filer purchase history -> HistoricalEvents."""
from __future__ import annotations

import json

from equity_scout.evidence.backfill_congress import (
    backfill_congress,
    events_from_filer_payload,
    filer_ids_from_trades,
)
from equity_scout.evidence.congress import FILER_URL_TEMPLATE, TRADES_URL
from equity_scout.evidence.historical_storage import unresolved_events

NOW = "2026-08-06T12:00:00+00:00"


def _trades_row(**overrides) -> dict:
    """One row of the capped, live trades.json feed (evidence/congress.py's source)."""
    row = {
        "id": "senate_abc_t0",
        "transaction_date": "2012-06-16",
        "filing_date": "2012-07-01",
        "ticker": "NVDA",
        "asset_name": "NVIDIA Corp (NVDA)",
        "asset_type": "ST",
        "transaction_type": "Purchase",
        "amount_range_label": "$15,001 - $50,000",
        "filer_id": "senate_jane_doe",
        "filer_name": "Jane Doe",
        "party": "D",
        "chamber": "senate",
        "branch": "congress",
    }
    row.update(overrides)
    return row


def _filer_trade(**overrides) -> dict:
    """One row of a per-filer full-history file (live-verified shape, 2026-08-06)."""
    row = {
        "filer_id": "senate_jane_doe",
        "transaction_type": "Purchase",
        "asset_type": "ST",
        "ticker": "NVDA",
        "filing_date": "2012-07-01",
        "notification_date": "2012-06-25",
        "transaction_date": "2012-06-16",
        "amount_range_label": "$15,001 - $50,000",
    }
    row.update(overrides)
    return row


def _filer_payload(trades: list[dict], *, name: str = "Jane Doe", chamber: str = "senate") -> dict:
    return {
        "filer": {"id": "senate_jane_doe", "full_name": name, "chamber": chamber},
        "trades": trades,
    }


def test_filer_ids_from_trades_extracts_distinct_ids_in_first_seen_order():
    payload = json.dumps(
        [
            _trades_row(filer_id="senate_jane_doe"),
            _trades_row(id="t1", filer_id="house_max_roe"),
            _trades_row(id="t2", filer_id="senate_jane_doe"),  # dup -> ignored
        ]
    )
    assert filer_ids_from_trades(payload) == ["senate_jane_doe", "house_max_roe"]


def test_filer_ids_from_trades_skips_missing_ids():
    payload = json.dumps([_trades_row(filer_id=None), _trades_row(id="t1", filer_id="")])
    assert filer_ids_from_trades(payload) == []


def test_events_from_filer_payload_keeps_purchases_and_counts_skips():
    payload = _filer_payload(
        [
            _filer_trade(),
            _filer_trade(transaction_type="Sale (Full)"),  # sales are not evidence
            _filer_trade(asset_type="Stock Option"),  # derivatives excluded
            _filer_trade(ticker=None),  # unresolvable
            _filer_trade(filing_date=None, notification_date=None),  # no knowable date
        ]
    )
    events, counters = events_from_filer_payload(payload, person="Jane Doe")

    assert [e.ticker for e in events] == ["NVDA"]
    assert events[0].person == "Jane Doe"
    assert events[0].source == "congress"
    assert events[0].t0 == "2012-07-01"  # filing date, not transaction date
    assert events[0].event_key == "senate_jane_doe-2012-06-16-purchase"
    assert events[0].details["chamber"] == "senate"
    assert events[0].details["amount_range"] == "$15,001 - $50,000"
    assert events[0].details["filer_id"] == "senate_jane_doe"
    assert counters == {
        "rows": 5, "kept": 1, "not_purchase": 1, "not_stock": 1, "no_ticker": 1, "no_date": 1,
    }


def test_events_from_filer_payload_falls_back_to_notification_date():
    payload = _filer_payload([_filer_trade(filing_date=None, notification_date="2012-06-28")])
    events, counters = events_from_filer_payload(payload, person="Jane Doe")
    assert events[0].t0 == "2012-06-28"
    assert counters["no_date"] == 0


def test_events_from_filer_payload_has_no_filing_age_bound():
    """Backfill wants the history — unlike the live collector, an old 2012 disclosure
    is kept even though it is 14 years before `NOW` (there is no `now` parameter at all
    to bound it with)."""
    events, _ = events_from_filer_payload(
        _filer_payload([_filer_trade(filing_date="2012-07-01")]), person="Jane Doe"
    )
    assert len(events) == 1
    assert events[0].t0 == "2012-07-01"


def test_events_from_filer_payload_collapses_same_filer_same_day_same_ticker():
    payload = _filer_payload(
        [_filer_trade(), _filer_trade(amount_range_label="$50,001 - $100,000")]
    )
    events, counters = events_from_filer_payload(payload, person="Jane Doe")
    assert len(events) == 1
    assert counters["kept"] == 1


def test_events_from_filer_payload_details_tolerate_missing_optional_fields():
    payload = {
        "filer": {"full_name": "No Chamber Guy"},  # no "chamber" key at all
        "trades": [_filer_trade(amount_range_label=None)],
    }
    events, _ = events_from_filer_payload(payload, person="No Chamber Guy")
    assert events[0].details["chamber"] is None
    assert events[0].details["committee"] is None
    assert events[0].details["amount_range"] is None


def test_backfill_congress_records_events_and_reports_counts(tmp_path):
    db = str(tmp_path / "test.db")
    filer_a = _filer_payload([_filer_trade()], name="Jane Doe")
    filer_b = _filer_payload(
        [
            _filer_trade(
                filer_id="house_max_roe", ticker="MSFT",
                transaction_date="2013-01-02", filing_date="2013-01-15",
            )
        ],
        name="Max Roe", chamber="house",
    )

    def http_get(url: str) -> str:
        if url == FILER_URL_TEMPLATE.format(filer_id="senate_jane_doe"):
            return json.dumps(filer_a)
        if url == FILER_URL_TEMPLATE.format(filer_id="house_max_roe"):
            return json.dumps(filer_b)
        raise AssertionError(f"unexpected url: {url}")

    counts = backfill_congress(
        db, now=NOW, http_get=http_get, filer_ids=["senate_jane_doe", "house_max_roe"]
    )
    assert counts == {"filers": 2, "events_new": 2, "events_seen": 2}
    assert {r["ticker"] for r in unresolved_events(db)} == {"NVDA", "MSFT"}


def test_backfill_congress_dedupes_on_rerun(tmp_path):
    db = str(tmp_path / "test.db")
    filer_a = _filer_payload([_filer_trade()])

    def http_get(url: str) -> str:
        return json.dumps(filer_a)

    first = backfill_congress(db, now=NOW, http_get=http_get, filer_ids=["senate_jane_doe"])
    assert first == {"filers": 1, "events_new": 1, "events_seen": 1}

    second = backfill_congress(db, now=NOW, http_get=http_get, filer_ids=["senate_jane_doe"])
    assert second == {"filers": 1, "events_new": 0, "events_seen": 1}


def test_backfill_congress_skips_broken_filer_without_aborting(tmp_path):
    db = str(tmp_path / "test.db")
    good_payload = _filer_payload(
        [_filer_trade(filer_id="house_max_roe", ticker="MSFT")], name="Max Roe"
    )

    def http_get(url: str) -> str:
        if url == FILER_URL_TEMPLATE.format(filer_id="senate_broken"):
            raise OSError("connection refused")
        return json.dumps(good_payload)

    counts = backfill_congress(
        db, now=NOW, http_get=http_get, filer_ids=["senate_broken", "house_max_roe"]
    )
    # The broken filer is still counted as attempted -- but contributes zero events,
    # and the working filer right after it is unaffected.
    assert counts == {"filers": 2, "events_new": 1, "events_seen": 1}
    assert {r["ticker"] for r in unresolved_events(db)} == {"MSFT"}


def test_backfill_congress_derives_filer_ids_from_trades_json_when_not_given(tmp_path):
    db = str(tmp_path / "test.db")
    trades_payload = json.dumps([_trades_row(filer_id="senate_jane_doe")])
    filer_payload = _filer_payload([_filer_trade()])

    def http_get(url: str) -> str:
        if url == TRADES_URL:
            return trades_payload
        if url == FILER_URL_TEMPLATE.format(filer_id="senate_jane_doe"):
            return json.dumps(filer_payload)
        raise AssertionError(f"unexpected url: {url}")

    counts = backfill_congress(db, now=NOW, http_get=http_get)
    assert counts == {"filers": 1, "events_new": 1, "events_seen": 1}
