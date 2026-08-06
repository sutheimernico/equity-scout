"""Congress backfill collector: full per-filer purchase history -> HistoricalEvents."""
from __future__ import annotations

import json

import pytest

from equity_scout.evidence.backfill_congress import (
    FILERS_URL,
    backfill_congress,
    events_from_filer_payload,
    filer_ids_from_index,
    filer_ids_from_trades,
)
from equity_scout.evidence.congress import FILER_URL_TEMPLATE, TRADES_URL
from equity_scout.evidence.historical_storage import record_historical_events, unresolved_events

NOW = "2026-08-06T12:00:00+00:00"


def _counts(**overrides) -> dict:
    """Full shape of backfill_congress's return value, zeroed except for overrides."""
    base = {
        "filers": 0, "filers_failed": 0, "events_new": 0, "events_seen": 0,
        "index_fallback": 0, "seed_empty": 0, "rows": 0, "no_ticker": 0, "not_stock": 0,
        "no_date": 0, "malformed": 0, "duplicate": 0,
    }
    base.update(overrides)
    return base


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


def _filers_index_row(**overrides) -> dict:
    """One row of the mirror's full filer index (live-verified shape, 2026-08-06)."""
    row = {"id": "senate_jane_doe", "full_name": "Jane Doe", "branch": "congress",
           "chamber": "senate", "party": "D", "state": "CA"}
    row.update(overrides)
    return row


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


def test_filer_ids_from_trades_rejects_non_list_payload():
    with pytest.raises(ValueError):
        filer_ids_from_trades('{"not": "a list"}')


def test_filer_ids_from_index_extracts_distinct_ids_in_first_seen_order():
    payload = json.dumps(
        [
            _filers_index_row(),
            _filers_index_row(id="house_max_roe"),
            _filers_index_row(),  # dup -> ignored
        ]
    )
    assert filer_ids_from_index(payload) == ["senate_jane_doe", "house_max_roe"]


def test_filer_ids_from_index_rejects_non_list_payload():
    with pytest.raises(ValueError):
        filer_ids_from_index('{"not": "a list"}')


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
        "rows": 5, "kept": 1, "not_purchase": 1, "not_stock": 1, "no_ticker": 1,
        "no_date": 1, "malformed": 0, "duplicate": 0,
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


def test_events_from_filer_payload_collapse_keeps_earliest_t0_regardless_of_order():
    """A later-filed duplicate (e.g. an amendment) arriving FIRST in payload order must
    not anchor the fact's public date later than it really was -- the fix for the
    5.4%-of-events measured regression: earliest t0 wins, not first-seen."""
    payload = _filer_payload(
        [
            _filer_trade(filing_date="2012-07-11"),  # later filing, listed first
            _filer_trade(filing_date="2012-07-01"),  # earlier filing, listed second
        ]
    )
    events, counters = events_from_filer_payload(payload, person="Jane Doe")
    assert len(events) == 1
    assert events[0].t0 == "2012-07-01"
    assert counters["kept"] == 1
    assert counters["duplicate"] == 1


def test_events_from_filer_payload_details_tolerate_missing_optional_fields():
    payload = {
        "filer": {"full_name": "No Chamber Guy"},  # no "chamber"/"branch"/"party"/"state"
        "trades": [_filer_trade(amount_range_label=None)],
    }
    events, _ = events_from_filer_payload(payload, person="No Chamber Guy")
    assert events[0].details["chamber"] is None
    assert events[0].details["committee"] is None
    assert events[0].details["amount_range"] is None
    assert events[0].details["party"] is None
    assert events[0].details["state"] is None


def test_events_from_filer_payload_chamber_falls_back_to_branch():
    """Executive-branch filers (e.g. the President) have chamber=null but branch set --
    live-verified 2026-08-06 on oge_donald_trump."""
    payload = {
        "filer": {"full_name": "An Exec", "branch": "executive", "chamber": None,
                   "party": "R", "state": None},
        "trades": [_filer_trade()],
    }
    events, _ = events_from_filer_payload(payload, person="An Exec")
    assert events[0].details["chamber"] == "executive"
    assert events[0].details["party"] == "R"


def test_events_from_filer_payload_collapses_same_filer_same_day_same_ticker():
    payload = _filer_payload(
        [_filer_trade(), _filer_trade(amount_range_label="$50,001 - $100,000")]
    )
    events, counters = events_from_filer_payload(payload, person="Jane Doe")
    assert len(events) == 1
    assert counters["kept"] == 1
    assert counters["duplicate"] == 1


def test_events_from_filer_payload_survives_malformed_rows():
    payload = _filer_payload([None, 7, "not a dict", _filer_trade()])
    events, counters = events_from_filer_payload(payload, person="Jane Doe")
    assert len(events) == 1
    assert counters["rows"] == 4
    assert counters["malformed"] == 3


def test_events_from_filer_payload_survives_non_list_trades_field():
    """"trades": 5 -- a bare `payload.get("trades") or []` would still try to iterate
    the int and raise TypeError; the whole payload is malformed, no rows are counted."""
    events, counters = events_from_filer_payload({"filer": {}, "trades": 5}, person="Jane Doe")
    assert events == []
    assert counters["malformed"] == 1
    assert counters["rows"] == 0


def test_events_from_filer_payload_coerces_non_string_type_fields_instead_of_crashing():
    payload = _filer_payload([_filer_trade(asset_type=7), _filer_trade(transaction_type=1)])
    events, counters = events_from_filer_payload(payload, person="Jane Doe")
    assert events == []
    assert counters["not_stock"] == 1
    assert counters["not_purchase"] == 1


def test_events_from_filer_payload_prefers_caller_supplied_filer_id_for_event_key():
    row_no_filer_id = {k: v for k, v in _filer_trade().items() if k != "filer_id"}
    payload = _filer_payload([row_no_filer_id])
    events, _ = events_from_filer_payload(payload, person="Jane Doe", filer_id="senate_override")
    assert events[0].event_key == "senate_override-2012-06-16-purchase"
    assert events[0].details["filer_id"] == "senate_override"


def test_events_from_filer_payload_preserves_unicode_person_through_storage(tmp_path):
    db = str(tmp_path / "test.db")
    events, _ = events_from_filer_payload(
        _filer_payload([_filer_trade()], name="José E. Serrano"), person="José E. Serrano"
    )
    record_historical_events(db, events, now=NOW)
    rows = unresolved_events(db)
    assert rows[0]["person"] == "José E. Serrano"


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
    assert counts == _counts(filers=2, events_new=2, events_seen=2, rows=2)
    assert {r["ticker"] for r in unresolved_events(db)} == {"NVDA", "MSFT"}


def test_backfill_congress_dedupes_on_rerun(tmp_path):
    db = str(tmp_path / "test.db")
    filer_a = _filer_payload([_filer_trade()])

    def http_get(url: str) -> str:
        return json.dumps(filer_a)

    first = backfill_congress(db, now=NOW, http_get=http_get, filer_ids=["senate_jane_doe"])
    assert first == _counts(filers=1, events_new=1, events_seen=1, rows=1)

    second = backfill_congress(db, now=NOW, http_get=http_get, filer_ids=["senate_jane_doe"])
    assert second == _counts(filers=1, events_new=0, events_seen=1, rows=1)


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
    # The broken filer is still counted as attempted (and now as failed) -- but
    # contributes zero events, and the working filer right after it is unaffected.
    assert counts == _counts(filers=2, filers_failed=1, events_new=1, events_seen=1, rows=1)
    assert {r["ticker"] for r in unresolved_events(db)} == {"MSFT"}


def test_backfill_congress_falls_back_to_filer_id_as_person_when_name_missing(tmp_path):
    db = str(tmp_path / "test.db")
    payload = {"filer": {"id": "senate_jane_doe"}, "trades": [_filer_trade()]}  # no full_name

    def http_get(url: str) -> str:
        return json.dumps(payload)

    backfill_congress(db, now=NOW, http_get=http_get, filer_ids=["senate_jane_doe"])
    rows = unresolved_events(db)
    assert rows[0]["person"] == "senate_jane_doe"


def test_backfill_congress_keeps_cross_filer_identity_without_row_level_filer_id(tmp_path):
    """Two different filers buying the same ticker on the same transaction date must
    stay two distinct rows -- proves event identity comes from the caller's known
    filer_id (from the fetch URL), not a per-row fallback that could collide when
    different filers' own rows both lack filer_id."""
    db = str(tmp_path / "test.db")
    row_no_filer_id = {k: v for k, v in _filer_trade().items() if k != "filer_id"}
    payload_a = _filer_payload([row_no_filer_id], name="Filer A")
    payload_b = _filer_payload([row_no_filer_id], name="Filer B")

    def http_get(url: str) -> str:
        if url == FILER_URL_TEMPLATE.format(filer_id="filer_a"):
            return json.dumps(payload_a)
        if url == FILER_URL_TEMPLATE.format(filer_id="filer_b"):
            return json.dumps(payload_b)
        raise AssertionError(f"unexpected url: {url}")

    counts = backfill_congress(db, now=NOW, http_get=http_get, filer_ids=["filer_a", "filer_b"])
    assert counts["events_new"] == 2
    rows = unresolved_events(db)
    assert len(rows) == 2
    assert {r["details"]["filer_id"] for r in rows} == {"filer_a", "filer_b"}


def test_backfill_congress_seeds_from_full_filer_index_by_default(tmp_path):
    db = str(tmp_path / "test.db")
    index_payload = json.dumps([_filers_index_row()])
    filer_payload = _filer_payload([_filer_trade()])

    def http_get(url: str) -> str:
        if url == FILERS_URL:
            return index_payload
        if url == FILER_URL_TEMPLATE.format(filer_id="senate_jane_doe"):
            return json.dumps(filer_payload)
        raise AssertionError(f"unexpected url: {url}")

    counts = backfill_congress(db, now=NOW, http_get=http_get)
    assert counts == _counts(filers=1, events_new=1, events_seen=1, index_fallback=0, rows=1)


def test_backfill_congress_falls_back_to_trades_json_when_index_fetch_fails(tmp_path):
    db = str(tmp_path / "test.db")
    trades_payload = json.dumps([_trades_row(filer_id="senate_jane_doe")])
    filer_payload = _filer_payload([_filer_trade()])

    def http_get(url: str) -> str:
        if url == FILERS_URL:
            raise OSError("index gone")
        if url == TRADES_URL:
            return trades_payload
        if url == FILER_URL_TEMPLATE.format(filer_id="senate_jane_doe"):
            return json.dumps(filer_payload)
        raise AssertionError(f"unexpected url: {url}")

    counts = backfill_congress(db, now=NOW, http_get=http_get)
    assert counts == _counts(filers=1, events_new=1, events_seen=1, index_fallback=1, rows=1)


def test_backfill_congress_falls_back_when_index_is_valid_but_empty(tmp_path):
    """A valid-but-renamed-key filers.json parses to [] -- without this fallback the run
    would look like a successful no-op instead of a degraded one."""
    db = str(tmp_path / "test.db")
    trades_payload = json.dumps([_trades_row(filer_id="senate_jane_doe")])
    filer_payload = _filer_payload([_filer_trade()])

    def http_get(url: str) -> str:
        if url == FILERS_URL:
            return json.dumps([])
        if url == TRADES_URL:
            return trades_payload
        if url == FILER_URL_TEMPLATE.format(filer_id="senate_jane_doe"):
            return json.dumps(filer_payload)
        raise AssertionError(f"unexpected url: {url}")

    counts = backfill_congress(db, now=NOW, http_get=http_get)
    assert counts == _counts(filers=1, events_new=1, events_seen=1, index_fallback=1, rows=1)


def test_backfill_congress_counts_seed_empty_when_both_seeds_are_empty(tmp_path):
    """Neither seed yields a single filer -- the run must be loud about it, never a
    silent, filer-less "success" indistinguishable from "nothing new to backfill"."""
    db = str(tmp_path / "test.db")

    def http_get(url: str) -> str:
        if url == FILERS_URL:
            return json.dumps([])
        if url == TRADES_URL:
            return json.dumps([])
        raise AssertionError(f"unexpected url: {url}")

    counts = backfill_congress(db, now=NOW, http_get=http_get)
    assert counts == _counts(index_fallback=1, seed_empty=1)


def test_backfill_congress_surfaces_aggregated_skip_counters(tmp_path):
    """One filer whose payload hits every skip reason at least once -- deleting the
    aggregation loop that folds events_from_filer_payload's per-payload counters into
    backfill_congress's return value must break this test."""
    db = str(tmp_path / "test.db")
    payload = _filer_payload(
        [
            None,  # malformed
            _filer_trade(ticker=None),  # no_ticker
            _filer_trade(asset_type="Stock Option"),  # not_stock
            _filer_trade(filing_date=None, notification_date=None),  # no_date
            _filer_trade(),  # kept
            _filer_trade(),  # duplicate of the row above
        ]
    )

    def http_get(url: str) -> str:
        return json.dumps(payload)

    counts = backfill_congress(db, now=NOW, http_get=http_get, filer_ids=["senate_jane_doe"])
    assert counts == _counts(
        filers=1, events_new=1, events_seen=1, rows=6,
        no_ticker=1, not_stock=1, no_date=1, malformed=1, duplicate=1,
    )
