"""EDGAR 13F collector: info-table parse, quarter diff, honest name matching."""
from __future__ import annotations

import json

import equity_scout.evidence.edgar as edgar
from equity_scout.evidence.base import STATUS_FETCH_FAILED, STATUS_OK, STATUS_UNCONFIGURED
from equity_scout.evidence.edgar import (
    Filing13F,
    Holding,
    build_name_matcher,
    collect_13f,
    diff_holdings,
    parse_info_table,
)

NOW = "2026-07-07T12:00:00+00:00"
_NS = 'xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable"'

INFO_TABLE_CURRENT = f"""<informationTable {_NS}>
  <infoTable>
    <nameOfIssuer>APPLE INC</nameOfIssuer><cusip>037833100</cusip><value>1000000</value>
    <shrsOrPrnAmt><sshPrnamt>500</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  </infoTable>
  <infoTable>
    <nameOfIssuer>OCCIDENTAL PETROLEUM CORP</nameOfIssuer><cusip>674599105</cusip><value>900</value>
    <shrsOrPrnAmt><sshPrnamt>200</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  </infoTable>
  <infoTable>
    <nameOfIssuer>SOME CALL OPTION</nameOfIssuer><cusip>111111111</cusip><value>1</value>
    <shrsOrPrnAmt><sshPrnamt>10</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
    <putCall>Call</putCall>
  </infoTable>
  <infoTable>
    <nameOfIssuer>SOME BOND</nameOfIssuer><cusip>222222222</cusip><value>1</value>
    <shrsOrPrnAmt><sshPrnamt>10</sshPrnamt><sshPrnamtType>PRN</sshPrnamtType></shrsOrPrnAmt>
  </infoTable>
</informationTable>"""

INFO_TABLE_PREVIOUS = f"""<informationTable {_NS}>
  <infoTable>
    <nameOfIssuer>APPLE INC</nameOfIssuer><cusip>037833100</cusip><value>800000</value>
    <shrsOrPrnAmt><sshPrnamt>100</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  </infoTable>
  <infoTable>
    <nameOfIssuer>EXITED CORP</nameOfIssuer><cusip>333333333</cusip><value>50</value>
    <shrsOrPrnAmt><sshPrnamt>10</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  </infoTable>
</informationTable>"""


def test_parse_info_table_skips_derivatives_and_principal_rows():
    holdings = parse_info_table(INFO_TABLE_CURRENT)
    assert [h.issuer for h in holdings] == ["APPLE INC", "OCCIDENTAL PETROLEUM CORP"]
    assert holdings[0].shares == 500.0


def _filing(holdings: list[Holding], period: str = "2026-03-31") -> Filing13F:
    return Filing13F(
        fund="Berkshire Hathaway", period=period, filed_at="2026-05-15",
        accession="0001067983-26-000001", holdings=holdings,
    )


def test_diff_reports_new_and_increased_but_never_exits():
    current = _filing(parse_info_table(INFO_TABLE_CURRENT))
    previous = _filing(parse_info_table(INFO_TABLE_PREVIOUS), period="2025-12-31")
    changes = {c["issuer"]: c["change"] for c in diff_holdings(current, previous)}
    assert changes == {
        "APPLE INC": "increased",  # 100 -> 500 shares
        "OCCIDENTAL PETROLEUM CORP": "new",
    }  # EXITED CORP does not appear — exits are not evidence


def test_diff_ignores_small_increases():
    current = _filing([Holding("APPLE INC", "037833100", 110.0, 1.0)])
    previous = _filing([Holding("APPLE INC", "037833100", 100.0, 1.0)], period="2025-12-31")
    assert diff_holdings(current, previous) == []


def test_name_matcher_exact_prefix_and_ambiguity():
    match = build_name_matcher(
        [("AAPL", "Apple"), ("OXY", "Occidental Petroleum"),
         ("AAL", "American Airlines Group"), ("AXP", "American Express")]
    )
    assert match("APPLE INC") == "AAPL"
    assert match("OCCIDENTAL PETROLEUM CORP") == "OXY"
    # Prefix in one direction, unambiguous: "AMERICAN AIRLINES" -> only AAL qualifies.
    assert match("AMERICAN AIRLINES GROUP INC") == "AAL"
    # Ambiguous first token alone must NOT match anything.
    assert match("AMERICAN") is None
    assert match("UNKNOWN ISSUER") is None


def test_collect_13f_without_user_agent_is_unconfigured():
    result = collect_13f(now=NOW, env={}, universe=[("AAPL", "Apple")])
    assert result.status == STATUS_UNCONFIGURED
    assert "EDGAR_USER_AGENT" in result.detail


def _fake_edgar(monkeypatch) -> dict[str, str]:
    monkeypatch.setattr(edgar, "TRACKED_FUNDS", {"Berkshire Hathaway": "0001067983"})
    submissions = {
        "filings": {"recent": {
            "form": ["10-K", "13F-HR", "13F-HR/A", "13F-HR"],
            "accessionNumber": ["x", "0001067983-26-000001", "y", "0001067983-25-000009"],
            "reportDate": ["2025-12-31", "2026-03-31", "2025-12-31", "2025-12-31"],
            "filingDate": ["2026-02-01", "2026-05-15", "2026-02-20", "2026-02-14"],
        }}
    }
    index = {"directory": {"item": [
        {"name": "primary_doc.xml"}, {"name": "form13fInfoTable.xml"},
    ]}}
    return {
        "https://data.sec.gov/submissions/CIK0001067983.json": json.dumps(submissions),
        "https://www.sec.gov/Archives/edgar/data/1067983/000106798326000001/index.json":
            json.dumps(index),
        "https://www.sec.gov/Archives/edgar/data/1067983/000106798326000001/form13fInfoTable.xml":
            INFO_TABLE_CURRENT,
        "https://www.sec.gov/Archives/edgar/data/1067983/000106798325000009/index.json":
            json.dumps(index),
        "https://www.sec.gov/Archives/edgar/data/1067983/000106798325000009/form13fInfoTable.xml":
            INFO_TABLE_PREVIOUS,
    }


def test_collect_13f_end_to_end_with_fake_transport(monkeypatch):
    urls = _fake_edgar(monkeypatch)
    result = collect_13f(
        now=NOW,
        env={"EDGAR_USER_AGENT": "test (test@example.com)"},
        universe=[("AAPL", "Apple"), ("OXY", "Occidental Petroleum")],
        http_get=lambda url: urls[url],
    )
    assert result.status == STATUS_OK
    by_ticker = {e.ticker: e for e in result.events}
    assert set(by_ticker) == {"AAPL", "OXY"}
    assert by_ticker["OXY"].details["change"] == "new"
    assert by_ticker["OXY"].event_date == "2026-05-15"  # public knowledge day, not quarter end
    assert by_ticker["AAPL"].event_key == "0001067983-2026-03-31"
    assert "0 holdings unmatched" in result.detail


def test_collect_13f_collapses_share_classes_per_ticker(monkeypatch):
    monkeypatch.setattr(edgar, "TRACKED_FUNDS", {"Berkshire Hathaway": "0001067983"})
    current = f"""<informationTable {_NS}>
      <infoTable>
        <nameOfIssuer>ALPHABET INC CL C</nameOfIssuer><cusip>02079K107</cusip><value>2</value>
        <shrsOrPrnAmt><sshPrnamt>200</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
      </infoTable>
      <infoTable>
        <nameOfIssuer>ALPHABET INC CL A</nameOfIssuer><cusip>02079K305</cusip><value>1</value>
        <shrsOrPrnAmt><sshPrnamt>50</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
      </infoTable>
    </informationTable>"""
    previous = f"""<informationTable {_NS}>
      <infoTable>
        <nameOfIssuer>ALPHABET INC CL C</nameOfIssuer><cusip>02079K107</cusip><value>1</value>
        <shrsOrPrnAmt><sshPrnamt>100</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
      </infoTable>
    </informationTable>"""
    urls = _fake_edgar(monkeypatch)
    urls[
        "https://www.sec.gov/Archives/edgar/data/1067983/000106798326000001/form13fInfoTable.xml"
    ] = current
    urls[
        "https://www.sec.gov/Archives/edgar/data/1067983/000106798325000009/form13fInfoTable.xml"
    ] = previous
    result = collect_13f(
        now=NOW, env={"EDGAR_USER_AGENT": "t (t@e.com)"},
        universe=[("GOOGL", "Alphabet")], http_get=lambda url: urls[url],
    )
    assert [(e.ticker, e.details["change"]) for e in result.events] == [("GOOGL", "increased")]


def test_collect_13f_skips_funds_whose_last_filing_is_stale(monkeypatch):
    urls = _fake_edgar(monkeypatch)
    submissions = json.loads(urls["https://data.sec.gov/submissions/CIK0001067983.json"])
    recent = submissions["filings"]["recent"]
    recent["filingDate"] = ["2026-02-01", "2025-11-03", "2025-10-20", "2025-08-14"]
    urls["https://data.sec.gov/submissions/CIK0001067983.json"] = json.dumps(submissions)

    result = collect_13f(
        now=NOW, env={"EDGAR_USER_AGENT": "t (t@e.com)"},
        universe=[("AAPL", "Apple")], http_get=lambda url: urls[url],
    )
    assert result.status == STATUS_OK
    assert result.events == []
    assert "1 funds stale" in result.detail


def test_collect_13f_total_transport_failure_degrades(monkeypatch):
    monkeypatch.setattr(edgar, "TRACKED_FUNDS", {"Berkshire Hathaway": "0001067983"})

    def broken(url: str) -> str:
        raise OSError("blocked")

    result = collect_13f(
        now=NOW, env={"EDGAR_USER_AGENT": "t (t@e.com)"},
        universe=[("AAPL", "Apple")], http_get=broken,
    )
    assert result.status == STATUS_FETCH_FAILED
    assert "Berkshire" in result.detail
