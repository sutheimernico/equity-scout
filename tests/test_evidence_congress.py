"""Congress collector: purchase filtering, ticker resolution, honest skip counters."""
from __future__ import annotations

import json

from equity_scout.evidence.base import STATUS_FETCH_FAILED, STATUS_OK, STATUS_PARSE_FAILED
from equity_scout.evidence.congress import fetch_congress_trades, parse_congress_trades

NOW = "2026-07-07T12:00:00+00:00"


def _row(**overrides) -> dict:
    row = {
        "id": "senate_abc_t0",
        "transaction_date": "2026-06-16",
        "filing_date": "2026-07-01",
        "ticker": "NVDA",
        "asset_name": "NVIDIA Corp (NVDA)",
        "asset_type": "Stock",
        "transaction_type": "Purchase",
        "amount_range_label": "$15,001 - $50,000",
        "days_to_file": 15,
        "filer_id": "senate_jane_doe",
        "filer_name": "Jane Doe",
        "party": "D",
        "chamber": "senate",
        "branch": "congress",
    }
    row.update(overrides)
    return row


def test_parse_keeps_recent_purchases_and_counts_skips():
    payload = json.dumps(
        [
            _row(),
            # ticker null but derivable from the asset name (real senate-feed shape)
            _row(id="t1", filer_id="senate_max", filer_name="Max Roe", ticker=None,
                 asset_name="Citigroup New Inc (C)"),
            _row(id="t2", transaction_type="Sale (Full)"),  # sales are not evidence
            _row(id="t3", filing_date="2026-04-01"),  # outside the filing window
            _row(id="t4", ticker=None, asset_name="Some Municipal Bond Fund"),  # no ticker
            _row(id="t5", asset_type="Stock Option"),  # derivatives excluded
        ]
    )
    events, counters = parse_congress_trades(payload, now=NOW)

    assert [(e.ticker, e.details["politician"]) for e in events] == [
        ("NVDA", "Jane Doe"), ("C", "Max Roe"),
    ]
    assert events[0].event_key == "senate_jane_doe-2026-06-16-purchase"
    assert events[0].event_date == "2026-07-01"  # the disclosure day, not the trade day
    assert counters == {
        "rows": 6, "kept": 2, "no_ticker": 1, "not_purchase": 1, "not_stock": 1, "stale": 1,
    }


def test_parse_collapses_same_filer_same_day_same_ticker():
    payload = json.dumps(
        [_row(), _row(id="dup", amount_range_label="$50,001 - $100,000")]
    )
    events, counters = parse_congress_trades(payload, now=NOW)
    assert len(events) == 1
    assert counters["kept"] == 1


def test_fetch_wraps_transport_and_parse_failures_as_status():
    def broken_get(url: str) -> str:
        raise OSError("connection refused")

    result = fetch_congress_trades(now=NOW, http_get=broken_get)
    assert result.status == STATUS_FETCH_FAILED
    assert "connection refused" in result.detail

    result = fetch_congress_trades(now=NOW, http_get=lambda url: '{"not": "a list"}')
    assert result.status == STATUS_PARSE_FAILED


def test_fetch_ok_reports_counters_in_detail():
    payload = json.dumps([_row()])
    result = fetch_congress_trades(now=NOW, http_get=lambda url: payload)
    assert result.status == STATUS_OK
    assert len(result.events) == 1
    assert "1 purchases kept" in result.detail
