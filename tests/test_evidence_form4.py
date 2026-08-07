"""Form 4 insider collector: open-market buy filtering, PIT invariant, honest degrade."""
from __future__ import annotations

import json

import equity_scout.evidence.form4 as form4
from equity_scout.evidence.base import STATUS_FETCH_FAILED, STATUS_OK, STATUS_UNCONFIGURED
from equity_scout.evidence.form4 import collect_form4, parse_form4
from equity_scout.evidence.storage import record_events

NOW = "2026-07-07T12:00:00+00:00"


def _ownership_xml(
    *,
    owner_name: str = "COOK TIMOTHY D",
    is_director: str = "1",
    is_officer: str = "1",
    is_ten_pct: str = "0",
    officer_title: str = "Chief Executive Officer",
    transaction_date: str = "2026-06-30",
    transaction_code: str = "P",
    acquired_disposed: str = "A",
    shares: str = "1000",
    price: str = "150.5",
) -> str:
    return f"""<?xml version="1.0"?>
<ownershipDocument>
  <schemaVersion>X0508</schemaVersion>
  <documentType>4</documentType>
  <periodOfReport>{transaction_date}</periodOfReport>
  <issuer>
    <issuerCik>0000320193</issuerCik>
    <issuerName>Apple Inc.</issuerName>
    <issuerTradingSymbol>AAPL</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0001214156</rptOwnerCik>
      <rptOwnerName>{owner_name}</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>{is_director}</isDirector>
      <isOfficer>{is_officer}</isOfficer>
      <isTenPercentOwner>{is_ten_pct}</isTenPercentOwner>
      <officerTitle>{officer_title}</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>{transaction_date}</value></transactionDate>
      <transactionCoding>
        <transactionFormType>4</transactionFormType>
        <transactionCode>{transaction_code}</transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>{shares}</value></transactionShares>
        <transactionPricePerShare><value>{price}</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>{acquired_disposed}</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>50000</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""


def test_parse_form4_keeps_open_market_buy():
    insider, role, transactions = parse_form4(_ownership_xml())
    assert insider == "COOK TIMOTHY D"
    assert role == "officer (Chief Executive Officer), director"
    assert len(transactions) == 1
    tx = transactions[0]
    assert tx.transaction_date == "2026-06-30"
    assert tx.shares == 1000.0
    assert tx.price == 150.5
    assert tx.value == 150500.0


def test_parse_form4_ignores_sell():
    _, _, transactions = parse_form4(
        _ownership_xml(transaction_code="S", acquired_disposed="D")
    )
    assert transactions == []


def test_parse_form4_role_label_falls_back_to_insider_when_no_flags():
    _, role, _ = parse_form4(
        _ownership_xml(is_director="0", is_officer="0", is_ten_pct="0", officer_title="")
    )
    assert role == "insider"


def test_collect_form4_without_user_agent_is_unconfigured():
    result = collect_form4(now=NOW, env={}, watchlist_tickers=["AAPL"])
    assert result.status == STATUS_UNCONFIGURED
    assert "EDGAR_USER_AGENT" in result.detail


def test_collect_form4_without_watchlist_is_a_no_op():
    result = collect_form4(
        now=NOW, env={"EDGAR_USER_AGENT": "t (t@e.com)"}, watchlist_tickers=[]
    )
    assert result.status == STATUS_OK
    assert result.events == []


def _submissions(filing_date: str = "2026-07-01") -> dict:
    return {
        "filings": {
            "recent": {
                "form": ["10-K", "4", "8-K"],
                "accessionNumber": ["x", "0000320193-26-000123", "y"],
                "filingDate": ["2026-02-01", filing_date, "2026-06-01"],
                "primaryDocument": ["x.htm", "primary_doc.xml", "y.htm"],
            }
        }
    }


def _fake_urls(*, filing_date: str = "2026-07-01", xml: str | None = None) -> dict[str, str]:
    xml = xml if xml is not None else _ownership_xml()
    return {
        "https://www.sec.gov/files/company_tickers.json": json.dumps(
            {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
        ),
        "https://data.sec.gov/submissions/CIK0000320193.json": json.dumps(
            _submissions(filing_date=filing_date)
        ),
        "https://www.sec.gov/Archives/edgar/data/320193/000032019326000123/primary_doc.xml": xml,
    }


def test_collect_form4_strips_the_xsl_stylesheet_prefix():
    """Regression: since 2026-08 the SEC's submissions API emits primaryDocument as
    "xslF345X06/primarydocument.xml" — that path serves the HTML rendering, and the
    collector failed on EVERY US ticker with "SEC lieferte kein XML". The raw XML
    lives at the accession root, without the stylesheet prefix."""
    urls = _fake_urls()
    submissions = _submissions()
    submissions["filings"]["recent"]["primaryDocument"][1] = "xslF345X06/primary_doc.xml"
    urls["https://data.sec.gov/submissions/CIK0000320193.json"] = json.dumps(submissions)
    # Note: only the UNPREFIXED archive URL exists in the fake transport — requesting
    # the xsl path would KeyError and the run would degrade.
    result = collect_form4(
        now=NOW,
        env={"EDGAR_USER_AGENT": "test (test@example.com)"},
        watchlist_tickers=["AAPL"],
        http_get=lambda url: urls[url],
    )
    assert result.status == STATUS_OK
    assert len(result.events) == 1
    assert result.events[0].ticker == "AAPL"


def test_collect_form4_end_to_end_with_fake_transport():
    urls = _fake_urls()
    result = collect_form4(
        now=NOW,
        env={"EDGAR_USER_AGENT": "test (test@example.com)"},
        watchlist_tickers=["AAPL"],
        http_get=lambda url: urls[url],
    )
    assert result.status == STATUS_OK
    assert len(result.events) == 1
    event = result.events[0]
    assert event.ticker == "AAPL"
    assert event.event_date == "2026-07-01"  # the filing day, not the transaction day
    assert event.details["insider"] == "COOK TIMOTHY D"
    assert event.details["role"] == "officer (Chief Executive Officer), director"
    assert event.details["transaction_date"] == "2026-06-30"
    assert event.details["shares"] == 1000.0
    assert event.details["value"] == 150500.0
    assert "1/1 Ticker geprüft" in result.detail


def test_collect_form4_ignores_sell_transactions_end_to_end():
    urls = _fake_urls(xml=_ownership_xml(transaction_code="S", acquired_disposed="D"))
    result = collect_form4(
        now=NOW,
        env={"EDGAR_USER_AGENT": "t (t@e.com)"},
        watchlist_tickers=["AAPL"],
        http_get=lambda url: urls[url],
    )
    assert result.status == STATUS_OK
    assert result.events == []


def test_collect_form4_discards_pit_violation(capsys):
    # Filing date BEFORE the transaction date is structurally impossible for a real
    # filing — a stand-in for corrupted/misparsed data. Must be dropped, never trusted.
    urls = _fake_urls(filing_date="2026-06-20")
    result = collect_form4(
        now=NOW,
        env={"EDGAR_USER_AGENT": "t (t@e.com)"},
        watchlist_tickers=["AAPL"],
        http_get=lambda url: urls[url],
    )
    assert result.status == STATUS_OK
    assert result.events == []
    assert "1 PIT-Verstöße verworfen" in result.detail
    assert "PIT-Verstoß" in capsys.readouterr().err


def test_collect_form4_counts_tickers_without_cik_mapping():
    urls = _fake_urls()
    result = collect_form4(
        now=NOW,
        env={"EDGAR_USER_AGENT": "t (t@e.com)"},
        watchlist_tickers=["AAPL", "NOPE"],
        http_get=lambda url: urls[url],
    )
    assert result.status == STATUS_OK
    assert len(result.events) == 1
    assert "1 ohne CIK-Mapping" in result.detail


def test_collect_form4_total_transport_failure_degrades():
    def broken(url: str) -> str:
        raise OSError("blocked")

    result = collect_form4(
        now=NOW, env={"EDGAR_USER_AGENT": "t (t@e.com)"},
        watchlist_tickers=["AAPL"], http_get=broken,
    )
    assert result.status == STATUS_FETCH_FAILED


def test_collect_form4_events_are_idempotent_via_the_ledger(tmp_path):
    """Re-collecting the same filing must never inflate the store — same dedup
    pattern (source, ticker, event_key) as congress.py / edgar.py."""
    urls = _fake_urls()
    db = str(tmp_path / "ev.db")

    def collect():
        return collect_form4(
            now=NOW, env={"EDGAR_USER_AGENT": "t (t@e.com)"},
            watchlist_tickers=["AAPL"], http_get=lambda url: urls[url],
        )

    first = record_events(db, collect().events, now=NOW)
    assert len(first) == 1
    second = record_events(db, collect().events, now=NOW)
    assert second == []


def test_fetch_ticker_cik_map_zero_pads_cik():
    payload = json.dumps({"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}})
    cik_map = form4.fetch_ticker_cik_map(lambda url: payload)
    assert cik_map == {"AAPL": "0000320193"}


def test_collect_form4_reports_clean_error_for_html_response():
    """v9: an SEC rate-limit/error page is HTML, not XML — the per-ticker error must say
    that instead of leaking the XML parser's cryptic "tag mismatch"."""
    urls = _fake_urls(xml="<html><body>Request Rate Threshold Exceeded</body></html>")
    result = collect_form4(
        now=NOW,
        env={"EDGAR_USER_AGENT": "test (test@example.com)"},
        watchlist_tickers=["AAPL"],
        http_get=lambda url: urls[url],
    )
    assert "kein XML" in result.detail
    assert "tag mismatch" not in result.detail


def test_collect_form4_separates_non_us_tickers_from_cik_gaps():
    """v9: exchange-suffixed listings (9022.T) can never map to a SEC CIK — counting
    them as "ohne CIK-Mapping" buried genuine gaps under expected noise."""
    urls = _fake_urls()
    result = collect_form4(
        now=NOW,
        env={"EDGAR_USER_AGENT": "t (t@e.com)"},
        watchlist_tickers=["AAPL", "9022.T"],
        http_get=lambda url: urls[url],
    )
    assert result.status == STATUS_OK
    assert "1 nicht-US übersprungen" in result.detail
    assert "0 ohne CIK-Mapping" in result.detail
