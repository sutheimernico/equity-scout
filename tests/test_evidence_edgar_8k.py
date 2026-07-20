"""EDGAR 8-K collector: item filtering (2.02/7.01/8.01), CIK mapping, honest degrade."""
from __future__ import annotations

import json

from equity_scout.evidence.base import STATUS_FETCH_FAILED, STATUS_OK, STATUS_UNCONFIGURED
from equity_scout.evidence.edgar_8k import collect_8k, recent_8k_metas
from equity_scout.evidence.storage import record_events

NOW = "2026-07-07T12:00:00+00:00"


def _submissions(*, forms=None, accessions=None, filing_dates=None, items=None, accepted=None) -> dict:
    """Minimal data.sec.gov submissions payload with the 8-K-relevant fields."""
    forms = forms if forms is not None else ["10-K", "8-K", "8-K"]
    accessions = accessions if accessions is not None else [
        "x", "0000320193-26-000011", "0000320193-26-000005",
    ]
    filing_dates = filing_dates if filing_dates is not None else [
        "2026-02-01", "2026-06-30", "2026-06-01",
    ]
    items = items if items is not None else ["", "2.02,9.01", "5.02"]
    accepted = accepted if accepted is not None else [
        "2026-02-01T21:00:00.000Z", "2026-06-30T20:30:41.000Z", "2026-06-01T21:30:00.000Z",
    ]
    return {
        "filings": {
            "recent": {
                "form": forms,
                "accessionNumber": accessions,
                "filingDate": filing_dates,
                "items": items,
                "acceptanceDateTime": accepted,
            }
        }
    }


def _fake_urls(**kwargs) -> dict[str, str]:
    return {
        "https://www.sec.gov/files/company_tickers.json": json.dumps(
            {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
        ),
        "https://data.sec.gov/submissions/CIK0000320193.json": json.dumps(_submissions(**kwargs)),
    }


def test_collect_8k_without_user_agent_is_unconfigured():
    result = collect_8k(now=NOW, env={}, tickers=["AAPL"])
    assert result.status == STATUS_UNCONFIGURED
    assert "EDGAR_USER_AGENT" in result.detail


def test_collect_8k_without_tickers_is_a_no_op():
    result = collect_8k(now=NOW, env={"EDGAR_USER_AGENT": "t (t@e.com)"}, tickers=[])
    assert result.status == STATUS_OK
    assert result.events == []


def test_recent_8k_metas_keeps_only_tracked_items():
    metas = recent_8k_metas(
        "0000320193",
        lambda url: json.dumps(_submissions()),
        now=NOW,
        max_filing_age_days=30,
    )
    # Only the "2.02,9.01" filing carries a tracked item; the "5.02"-only filing (exec
    # change) and the "" (10-K, no items) filing are filtered out.
    assert [m["accession"] for m in metas] == ["0000320193-26-000011"]
    assert metas[0]["items"] == ["2.02"]
    assert metas[0]["accepted_at"] == "2026-06-30T20:30:41.000Z"


def test_recent_8k_metas_respects_max_filing_age_days():
    metas = recent_8k_metas(
        "0000320193",
        lambda url: json.dumps(_submissions(filing_dates=["2026-02-01", "2025-01-15", "2026-06-01"])),
        now=NOW,
        max_filing_age_days=30,
    )
    assert metas == []  # the only tracked-item filing is now far outside the window


def test_collect_8k_end_to_end_with_fake_transport():
    urls = _fake_urls()
    result = collect_8k(
        now=NOW,
        env={"EDGAR_USER_AGENT": "test (test@example.com)"},
        tickers=["AAPL"],
        http_get=lambda url: urls[url],
    )
    assert result.status == STATUS_OK
    assert len(result.events) == 1
    event = result.events[0]
    assert event.ticker == "AAPL"
    assert event.event_key == "0000320193-26-000011"
    assert event.event_date == "2026-06-30"  # the filing day
    assert event.details["items"] == ["2.02"]
    assert event.details["filing_date"] == "2026-06-30"
    assert event.details["published_at"] == "2026-06-30T20:30:41.000Z"
    assert "1/1 Ticker geprüft" in result.detail


def test_collect_8k_filters_out_untracked_items():
    urls = _fake_urls(items=["", "5.02", "5.07,9.01"])
    result = collect_8k(
        now=NOW,
        env={"EDGAR_USER_AGENT": "t (t@e.com)"},
        tickers=["AAPL"],
        http_get=lambda url: urls[url],
    )
    assert result.status == STATUS_OK
    assert result.events == []


def test_collect_8k_reports_multiple_tracked_items_on_one_filing():
    urls = _fake_urls(items=["", "7.01,8.01", "5.02"])
    result = collect_8k(
        now=NOW,
        env={"EDGAR_USER_AGENT": "t (t@e.com)"},
        tickers=["AAPL"],
        http_get=lambda url: urls[url],
    )
    assert len(result.events) == 1
    assert result.events[0].details["items"] == ["7.01", "8.01"]


def test_collect_8k_counts_tickers_without_cik_mapping():
    urls = _fake_urls()
    result = collect_8k(
        now=NOW,
        env={"EDGAR_USER_AGENT": "t (t@e.com)"},
        tickers=["AAPL", "NOPE"],
        http_get=lambda url: urls[url],
    )
    assert result.status == STATUS_OK
    assert len(result.events) == 1
    assert "1 ohne CIK-Mapping" in result.detail


def test_collect_8k_total_transport_failure_degrades():
    def broken(url: str) -> str:
        raise OSError("blocked")

    result = collect_8k(
        now=NOW, env={"EDGAR_USER_AGENT": "t (t@e.com)"}, tickers=["AAPL"], http_get=broken,
    )
    assert result.status == STATUS_FETCH_FAILED


def test_collect_8k_events_are_idempotent_via_the_ledger(tmp_path):
    """Re-collecting the same filing must never inflate the store — same dedup pattern
    (source, ticker, event_key) as congress.py / edgar.py / form4.py."""
    urls = _fake_urls()
    db = str(tmp_path / "ev.db")

    def collect():
        return collect_8k(
            now=NOW, env={"EDGAR_USER_AGENT": "t (t@e.com)"}, tickers=["AAPL"],
            http_get=lambda url: urls[url],
        )

    first = record_events(db, collect().events, now=NOW)
    assert len(first) == 1
    second = record_events(db, collect().events, now=NOW)
    assert second == []


def test_collect_8k_separates_non_us_tickers_from_cik_gaps():
    """v9: exchange-suffixed listings (9022.T) can never map to a SEC CIK — counting
    them as "ohne CIK-Mapping" buried genuine gaps under expected noise."""
    urls = _fake_urls()
    result = collect_8k(
        now=NOW,
        env={"EDGAR_USER_AGENT": "t (t@e.com)"},
        tickers=["AAPL", "9022.T"],
        http_get=lambda url: urls[url],
    )
    assert result.status == STATUS_OK
    assert "1 nicht-US übersprungen" in result.detail
    assert "0 ohne CIK-Mapping" in result.detail
