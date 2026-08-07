"""Form 4 cluster backfill: SEC quarterly Form 345 data sets -> HistoricalEvents.

Fixture ZIPs use the REAL member names and column headers of the SEC quarterly data set,
copied verbatim from 2024q1_form345.zip (live-verified 2026-08-07) — see the module
docstring of `evidence/backfill_form4.py` for the recorded layout.
"""
from __future__ import annotations

import io
import zipfile
import zlib

import pytest

from equity_scout.evidence import backfill_form4
from equity_scout.evidence.aggregate import MIN_INSIDERS
from equity_scout.evidence.backfill_form4 import (
    HISTORY_FORM4_CURSOR_KEY,
    QUARTER_URL,
    QUARTER_URL_NEW_PATH,
    backfill_form4_quarter,
    cluster_events,
    count_boundary_candidates,
    next_quarter,
    next_quarter_to_backfill,
    purchases_from_quarter_zip,
)
from equity_scout.evidence.base import SOURCE_INSIDER
from equity_scout.state_storage import get_state, set_state

NOW = "2026-08-07T12:00:00+00:00"

SUBMISSION_COLUMNS = [
    "ACCESSION_NUMBER", "FILING_DATE", "PERIOD_OF_REPORT", "DATE_OF_ORIG_SUB",
    "NO_SECURITIES_OWNED", "NOT_SUBJECT_SEC16", "FORM3_HOLDINGS_REPORTED",
    "FORM4_TRANS_REPORTED", "DOCUMENT_TYPE", "ISSUERCIK", "ISSUERNAME",
    "ISSUERTRADINGSYMBOL", "REMARKS", "AFF10B5ONE",
]
OWNER_COLUMNS = [
    "ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNERNAME", "RPTOWNER_RELATIONSHIP",
    "RPTOWNER_TITLE", "RPTOWNER_TXT", "RPTOWNER_STREET1", "RPTOWNER_STREET2",
    "RPTOWNER_CITY", "RPTOWNER_STATE", "RPTOWNER_ZIPCODE", "RPTOWNER_STATE_DESC",
    "FILE_NUMBER",
]
TRANS_COLUMNS = [
    "ACCESSION_NUMBER", "NONDERIV_TRANS_SK", "SECURITY_TITLE", "SECURITY_TITLE_FN",
    "TRANS_DATE", "TRANS_DATE_FN", "DEEMED_EXECUTION_DATE", "DEEMED_EXECUTION_DATE_FN",
    "TRANS_FORM_TYPE", "TRANS_CODE", "EQUITY_SWAP_INVOLVED", "EQUITY_SWAP_TRANS_CD_FN",
    "TRANS_TIMELINESS", "TRANS_TIMELINESS_FN", "TRANS_SHARES", "TRANS_SHARES_FN",
    "TRANS_PRICEPERSHARE", "TRANS_PRICEPERSHARE_FN", "TRANS_ACQUIRED_DISP_CD",
    "TRANS_ACQUIRED_DISP_CD_FN", "SHRS_OWND_FOLWNG_TRANS", "SHRS_OWND_FOLWNG_TRANS_FN",
    "VALU_OWND_FOLWNG_TRANS", "VALU_OWND_FOLWNG_TRANS_FN", "DIRECT_INDIRECT_OWNERSHIP",
    "DIRECT_INDIRECT_OWNERSHIP_FN", "NATURE_OF_OWNERSHIP", "NATURE_OF_OWNERSHIP_FN",
]


def _submission(accession: str, **overrides) -> dict:
    row = {
        "ACCESSION_NUMBER": accession,
        "FILING_DATE": "31-JAN-2024",
        "PERIOD_OF_REPORT": "29-JAN-2024",
        "DOCUMENT_TYPE": "4",
        "ISSUERCIK": "0000700565",
        "ISSUERNAME": "FIRST MID BANCSHARES, INC.",
        "ISSUERTRADINGSYMBOL": "FMBH",
        "AFF10B5ONE": "0",
    }
    row.update(overrides)
    return row


def _owner(accession: str, name: str, **overrides) -> dict:
    row = {
        "ACCESSION_NUMBER": accession,
        "RPTOWNERCIK": "0001185191",
        "RPTOWNERNAME": name,
        "RPTOWNER_RELATIONSHIP": "Director",
        "RPTOWNER_CITY": "PONTE VEDRA",
        "RPTOWNER_STATE": "FL",
        "FILE_NUMBER": "001-40355",
    }
    row.update(overrides)
    return row


def _trans(accession: str, **overrides) -> dict:
    row = {
        "ACCESSION_NUMBER": accession,
        "NONDERIV_TRANS_SK": "7975190",
        "SECURITY_TITLE": "Common Stock",
        "TRANS_DATE": "29-JAN-2024",
        "TRANS_FORM_TYPE": "4",
        "TRANS_CODE": "P",
        "EQUITY_SWAP_INVOLVED": "false",
        "TRANS_SHARES": "1000.0",
        "TRANS_PRICEPERSHARE": "25.0",
        "TRANS_ACQUIRED_DISP_CD": "A",
        "SHRS_OWND_FOLWNG_TRANS": "10000.0",
        "DIRECT_INDIRECT_OWNERSHIP": "D",
    }
    row.update(overrides)
    return row


def _tsv(columns: list[str], rows: list[dict]) -> bytes:
    lines = ["\t".join(columns)]
    lines += ["\t".join(str(row.get(column, "")) for column in columns) for row in rows]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _quarter_zip(
    submissions: list[dict], owners: list[dict], transactions: list[dict], *, omit: str = ""
) -> bytes:
    """One quarter ZIP with the three members the collector joins (plus a stray member,
    as the real ZIP carries DERIV_*/FOOTNOTES/README next to them)."""
    members = {
        "SUBMISSION.tsv": _tsv(SUBMISSION_COLUMNS, submissions),
        "REPORTINGOWNER.tsv": _tsv(OWNER_COLUMNS, owners),
        "NONDERIV_TRANS.tsv": _tsv(TRANS_COLUMNS, transactions),
        "FOOTNOTES.tsv": b"ACCESSION_NUMBER\tFOOTNOTE_ID\tFOOTNOTE_TXT\n",
    }
    members.pop(omit, None)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def _counts(**overrides) -> dict:
    base = {
        "rows": 0, "kept": 0, "not_purchase": 0, "no_submission": 0, "not_form4": 0,
        "no_symbol": 0, "no_owner": 0, "bad_date": 0, "discarded_pit": 0,
        "bad_shares": 0,  # OVERLAY on kept, deliberately outside the partition sum
    }
    base.update(overrides)
    return base


def _simple_zip() -> bytes:
    return _quarter_zip(
        [_submission("acc-1")], [_owner("acc-1", "TREACE JAMES T")], [_trans("acc-1")]
    )


# --- purchases_from_quarter_zip -------------------------------------------------------


def test_purchase_joins_symbol_owner_and_filing_date() -> None:
    purchases, counts = purchases_from_quarter_zip(_simple_zip())

    assert counts == _counts(rows=1, kept=1)
    assert len(purchases) == 1
    purchase = purchases[0]
    assert purchase.ticker == "FMBH"
    assert purchase.insider == "TREACE JAMES T"
    # SEC ships DD-MON-YYYY; everything downstream (t0, panels) is ISO.
    assert purchase.transaction_date == "2024-01-29"
    assert purchase.filing_date == "2024-01-31"
    assert purchase.shares == 1000.0
    assert purchase.price == 25.0
    assert purchase.value == 25_000.0
    assert purchase.accession == "acc-1"


def test_non_purchase_codes_and_disposals_are_counted_not_kept() -> None:
    transactions = [
        _trans("acc-1", TRANS_CODE="S", TRANS_ACQUIRED_DISP_CD="D"),
        _trans("acc-1", TRANS_CODE="A"),  # award, not an open-market buy
        _trans("acc-1", TRANS_CODE="M"),
        # code P with a DISPOSAL flag exists in the real data (40 rows in 2024q1) —
        # same P+A rule as form4.py, so it must not become a "purchase".
        _trans("acc-1", TRANS_ACQUIRED_DISP_CD="D"),
    ]
    purchases, counts = purchases_from_quarter_zip(
        _quarter_zip([_submission("acc-1")], [_owner("acc-1", "A B")], transactions)
    )

    assert purchases == []
    assert counts == _counts(rows=4, not_purchase=4)


def test_form5_and_amendments_are_counted_not_form4() -> None:
    submissions = [
        _submission("acc-5", DOCUMENT_TYPE="5"),
        _submission("acc-a", DOCUMENT_TYPE="4/A"),
        _submission("acc-3", DOCUMENT_TYPE="3"),
    ]
    owners = [_owner(acc, "A B") for acc in ("acc-5", "acc-a", "acc-3")]
    transactions = [_trans(acc) for acc in ("acc-5", "acc-a", "acc-3")]
    purchases, counts = purchases_from_quarter_zip(
        _quarter_zip(submissions, owners, transactions)
    )

    assert purchases == []
    assert counts == _counts(rows=3, not_form4=3)


def test_unusable_issuer_symbols_are_counted_never_guessed() -> None:
    """Real 2024q1 junk: placeholders, exchange-prefixed and dual-class symbols.

    A dual symbol ("GEF,GEF.B") is a real issuer but an unresolvable ticker — picking one
    class would be a guess, so it is a counted gap (260 rows of 2024q1), same philosophy
    as form4.py's unmapped tickers.
    """
    dirty = ["[ NONE ]", "N/A", "none", "NYSE:NYCB", "GEF,GEF.B", "BBXIA/B", "-", "", ".OB"]
    submissions = [
        _submission(f"acc-{i}", ISSUERTRADINGSYMBOL=symbol) for i, symbol in enumerate(dirty)
    ]
    owners = [_owner(f"acc-{i}", "A B") for i in range(len(dirty))]
    transactions = [_trans(f"acc-{i}") for i in range(len(dirty))]
    purchases, counts = purchases_from_quarter_zip(
        _quarter_zip(submissions, owners, transactions)
    )

    assert purchases == []
    assert counts == _counts(rows=len(dirty), no_symbol=len(dirty))


def test_orphan_transaction_and_missing_owner_are_counted() -> None:
    transactions = [_trans("acc-orphan"), _trans("acc-1")]
    purchases, counts = purchases_from_quarter_zip(
        _quarter_zip([_submission("acc-1")], [], transactions)
    )

    assert purchases == []
    assert counts == _counts(rows=2, no_submission=1, no_owner=1)


def test_malformed_dates_are_counted_not_raised() -> None:
    submissions = [_submission("acc-1"), _submission("acc-2", FILING_DATE="2024-01-31")]
    owners = [_owner("acc-1", "A B"), _owner("acc-2", "C D")]
    transactions = [_trans("acc-1", TRANS_DATE="31-FEB-2024"), _trans("acc-2")]
    purchases, counts = purchases_from_quarter_zip(
        _quarter_zip(submissions, owners, transactions)
    )

    assert purchases == []
    assert counts == _counts(rows=2, bad_date=2)


def test_filing_before_transaction_is_discarded_as_pit_violation() -> None:
    submissions = [_submission("acc-1", FILING_DATE="28-JAN-2024")]
    purchases, counts = purchases_from_quarter_zip(
        _quarter_zip(submissions, [_owner("acc-1", "A B")], [_trans("acc-1")])
    )

    assert purchases == []
    assert counts == _counts(rows=1, discarded_pit=1)


def test_row_counter_is_a_complete_partition() -> None:
    """`rows` is the denominator: every row lands in exactly one bucket (Task-2 rule)."""
    submissions = [
        _submission("acc-1"),
        _submission("acc-5", DOCUMENT_TYPE="5"),
        _submission("acc-sym", ISSUERTRADINGSYMBOL="N/A"),
        _submission("acc-noowner"),
        _submission("acc-baddate", FILING_DATE="oops"),
        _submission("acc-pit", FILING_DATE="28-JAN-2024"),
    ]
    owners = [
        _owner(acc, "A B") for acc in ("acc-1", "acc-5", "acc-sym", "acc-baddate", "acc-pit")
    ]
    transactions = [
        _trans("acc-1"),
        _trans("acc-1", TRANS_CODE="S", TRANS_ACQUIRED_DISP_CD="D"),
        _trans("acc-orphan"),
        _trans("acc-5"),
        _trans("acc-sym"),
        _trans("acc-noowner"),
        _trans("acc-baddate"),
        _trans("acc-pit"),
    ]
    purchases, counts = purchases_from_quarter_zip(
        _quarter_zip(submissions, owners, transactions)
    )

    assert len(purchases) == counts["kept"] == 1
    assert counts["rows"] == 8
    partition = {
        key: value for key, value in counts.items() if key not in ("rows", "bad_shares")
    }
    assert counts["rows"] == sum(partition.values())


def test_joint_filing_uses_only_the_first_reporting_owner() -> None:
    """A group filing (fund + affiliates + partners) is ONE decision, not five insiders.

    Mirrors form4.py's live rule (only the first reportingOwner block is read) — counting
    all five co-filers would manufacture a "cluster" out of a single group purchase.
    """
    owners = [
        _owner("acc-1", "RA CAPITAL MANAGEMENT, L.P."),
        _owner("acc-1", "RA Capital Healthcare Fund LP"),
        _owner("acc-1", "Shah Rajeev M."),
    ]
    purchases, counts = purchases_from_quarter_zip(
        _quarter_zip([_submission("acc-1")], owners, [_trans("acc-1")])
    )

    assert counts == _counts(rows=1, kept=1)
    assert [p.insider for p in purchases] == ["RA CAPITAL MANAGEMENT, L.P."]


def test_missing_member_raises_instead_of_returning_a_silent_zero() -> None:
    zip_bytes = _quarter_zip(
        [_submission("acc-1")], [_owner("acc-1", "A B")], [_trans("acc-1")],
        omit="REPORTINGOWNER.tsv",
    )
    with pytest.raises(ValueError, match="REPORTINGOWNER.tsv"):
        purchases_from_quarter_zip(zip_bytes)


def _crc_corrupt_zip() -> bytes:
    """A structurally valid ZIP whose transaction member fails its CRC only mid-read —
    what a truncated/garbled multi-MB download looks like."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("SUBMISSION.tsv", _tsv(SUBMISSION_COLUMNS, [_submission("acc-1")]))
        archive.writestr("REPORTINGOWNER.tsv", _tsv(OWNER_COLUMNS, [_owner("acc-1", "A B")]))
        archive.writestr("NONDERIV_TRANS.tsv", _tsv(TRANS_COLUMNS, [_trans("acc-1")]))
    raw = bytearray(buffer.getvalue())
    offset = raw.index(b"NONDERIV_TRANS_SK\tSECURITY_TITLE")
    raw[offset] ^= 0xFF  # stored bytes now disagree with the recorded CRC
    return bytes(raw)


def test_corruption_discovered_mid_read_becomes_a_value_error(tmp_path) -> None:
    with pytest.raises(ValueError, match="unlesbar"):
        purchases_from_quarter_zip(_crc_corrupt_zip())

    counts = backfill_form4_quarter(
        str(tmp_path / "scout.db"), "2024q1", now=NOW,
        http_get_bytes=lambda _url: _crc_corrupt_zip(),
    )
    assert counts["status"] == "parse_failed"


# --- cluster_events -------------------------------------------------------------------


def _purchases_zip(rows: list[tuple[str, str, str, str]], symbol: str = "FMBH") -> bytes:
    """(accession, insider, TRANS_DATE, FILING_DATE) tuples -> one-purchase-per-filing ZIP."""
    submissions = [
        _submission(acc, ISSUERTRADINGSYMBOL=symbol, FILING_DATE=filed)
        for acc, _, _, filed in rows
    ]
    owners = [_owner(acc, name) for acc, name, _, _ in rows]
    transactions = [_trans(acc, TRANS_DATE=traded) for acc, _, traded, _ in rows]
    return _quarter_zip(submissions, owners, transactions)


def _purchases(rows: list[tuple[str, str, str, str]], symbol: str = "FMBH") -> list:
    purchases, _ = purchases_from_quarter_zip(_purchases_zip(rows, symbol))
    return purchases


def test_three_distinct_insiders_inside_the_window_become_one_cluster_event() -> None:
    purchases = _purchases([
        ("a1", "Alpha A", "01-FEB-2024", "02-FEB-2024"),
        ("a2", "Beta B", "05-FEB-2024", "07-FEB-2024"),
        ("a3", "Gamma C", "08-FEB-2024", "12-FEB-2024"),
    ])

    events = cluster_events(purchases)

    assert len(events) == 1
    event = events[0]
    assert event.source == SOURCE_INSIDER
    assert event.person == ""  # cluster has no single person (plan Decision 2)
    assert event.ticker == "FMBH"
    # T0 is the LAST filing of the cluster — only then were all three buys knowable.
    assert event.t0 == "2024-02-12"
    assert event.event_key == "FMBH-2024-02-12-2024-02-01-cluster3"
    assert event.details["insiders"] == ["Alpha A", "Beta B", "Gamma C"]
    assert event.details["n_insiders"] == 3
    assert event.details["n_purchases"] == 3
    assert event.details["first_transaction_date"] == "2024-02-01"
    assert event.details["last_transaction_date"] == "2024-02-08"
    assert event.details["value_band"] == "<$100k"  # 3 x 1000 x 25.0 = 75k
    # Filing lag in TRADING days: 01->02 Feb = 1, 05->07 Feb = 2, 08->12 Feb = 2.
    assert event.details["median_filing_lag_days"] == 2.0
    assert event.details["max_filing_lag_days"] == 2


def test_two_insiders_are_not_a_cluster() -> None:
    purchases = _purchases([
        ("a1", "Alpha A", "01-FEB-2024", "02-FEB-2024"),
        ("a2", "Beta B", "05-FEB-2024", "07-FEB-2024"),
    ])

    assert cluster_events(purchases) == []
    assert MIN_INSIDERS == 3  # the imported threshold, never a local redefinition


def test_one_insider_buying_three_times_is_not_a_cluster() -> None:
    purchases = _purchases([
        ("a1", "Alpha A", "01-FEB-2024", "02-FEB-2024"),
        ("a2", "Alpha A", "02-FEB-2024", "05-FEB-2024"),
        ("a3", "Alpha A", "05-FEB-2024", "07-FEB-2024"),
    ])

    assert cluster_events(purchases) == []


def test_window_counts_trading_days_not_calendar_days() -> None:
    """01-FEB..15-FEB-2024 is 14 calendar but exactly 10 trading days apart."""
    inside = _purchases([
        ("a1", "Alpha A", "01-FEB-2024", "02-FEB-2024"),
        ("a2", "Beta B", "08-FEB-2024", "09-FEB-2024"),
        ("a3", "Gamma C", "15-FEB-2024", "16-FEB-2024"),
    ])
    outside = _purchases([
        ("a1", "Alpha A", "01-FEB-2024", "02-FEB-2024"),
        ("a2", "Beta B", "08-FEB-2024", "09-FEB-2024"),
        ("a3", "Gamma C", "16-FEB-2024", "19-FEB-2024"),
    ])

    assert len(cluster_events(inside)) == 1
    assert cluster_events(outside) == []


def test_separate_windows_on_one_ticker_yield_separate_non_overlapping_clusters() -> None:
    purchases = _purchases([
        ("a1", "Alpha A", "01-FEB-2024", "02-FEB-2024"),
        ("a2", "Beta B", "02-FEB-2024", "05-FEB-2024"),
        ("a3", "Gamma C", "05-FEB-2024", "06-FEB-2024"),
        ("b1", "Delta D", "01-APR-2024", "02-APR-2024"),
        ("b2", "Epsilon E", "02-APR-2024", "03-APR-2024"),
        ("b3", "Zeta F", "03-APR-2024", "04-APR-2024"),
    ])

    events = cluster_events(purchases)

    assert [e.t0 for e in events] == ["2024-02-06", "2024-04-04"]
    assert [e.event_key for e in events] == [
        "FMBH-2024-02-06-2024-02-01-cluster3", "FMBH-2024-04-04-2024-04-01-cluster3"
    ]


def test_clusters_are_grouped_per_ticker() -> None:
    purchases = _purchases([
        ("a1", "Alpha A", "01-FEB-2024", "02-FEB-2024"),
        ("a2", "Beta B", "02-FEB-2024", "05-FEB-2024"),
    ]) + _purchases([
        ("b1", "Gamma C", "01-FEB-2024", "02-FEB-2024"),
    ], symbol="TOL")

    # Three insiders overall, but never three on the SAME ticker.
    assert cluster_events(purchases) == []


def test_value_band_reports_unknown_when_no_purchase_carries_a_price() -> None:
    zip_bytes = _quarter_zip(
        [_submission(acc, FILING_DATE=filed) for acc, filed in
         (("a1", "02-FEB-2024"), ("a2", "05-FEB-2024"), ("a3", "06-FEB-2024"))],
        [_owner("a1", "Alpha A"), _owner("a2", "Beta B"), _owner("a3", "Gamma C")],
        [_trans(acc, TRANS_DATE="01-FEB-2024", TRANS_PRICEPERSHARE="")
         for acc in ("a1", "a2", "a3")],
    )
    purchases, _ = purchases_from_quarter_zip(zip_bytes)

    event = cluster_events(purchases)[0]

    assert event.details["value_band"] == "unbekannt"
    assert event.details["priced_purchases"] == 0
    assert event.details["total_value"] is None


def test_value_band_scales_with_the_cluster_total() -> None:
    zip_bytes = _quarter_zip(
        [_submission(acc, FILING_DATE=filed) for acc, filed in
         (("a1", "02-FEB-2024"), ("a2", "05-FEB-2024"), ("a3", "06-FEB-2024"))],
        [_owner("a1", "Alpha A"), _owner("a2", "Beta B"), _owner("a3", "Gamma C")],
        [_trans(acc, TRANS_DATE="01-FEB-2024", TRANS_SHARES="100000.0",
                TRANS_PRICEPERSHARE="25.0") for acc in ("a1", "a2", "a3")],
    )
    purchases, _ = purchases_from_quarter_zip(zip_bytes)

    event = cluster_events(purchases)[0]

    assert event.details["total_value"] == 7_500_000.0
    assert event.details["value_band"] == "$1M-$10M"


def test_min_insiders_is_configurable_for_sensitivity_runs() -> None:
    purchases = _purchases([
        ("a1", "Alpha A", "01-FEB-2024", "02-FEB-2024"),
        ("a2", "Beta B", "05-FEB-2024", "07-FEB-2024"),
    ])

    assert len(cluster_events(purchases, min_insiders=2)) == 1


# --- backfill_form4_quarter -----------------------------------------------------------


def _cluster_zip() -> bytes:
    return _purchases_zip([
        ("a1", "Alpha A", "01-FEB-2024", "02-FEB-2024"),
        ("a2", "Beta B", "05-FEB-2024", "07-FEB-2024"),
        ("a3", "Gamma C", "08-FEB-2024", "12-FEB-2024"),
    ])


def test_unconfigured_user_agent_returns_early_without_writing(tmp_path) -> None:
    db_path = str(tmp_path / "scout.db")

    counts = backfill_form4_quarter(db_path, "2024q1", now=NOW, env={})

    assert counts["status"] == "unconfigured"
    assert "EDGAR_USER_AGENT" in counts["detail"]
    assert counts["events_new"] == 0
    assert get_state(db_path, key=HISTORY_FORM4_CURSOR_KEY) is None


def test_quarter_run_records_clusters_and_advances_the_cursor(tmp_path) -> None:
    db_path = str(tmp_path / "scout.db")
    requested: list[str] = []

    def http_get_bytes(url: str) -> bytes:
        requested.append(url)
        return _cluster_zip()

    counts = backfill_form4_quarter(
        db_path, "2024q1", now=NOW, http_get_bytes=http_get_bytes
    )

    assert requested == [QUARTER_URL.format(quarter="2024q1")]
    assert counts["status"] == "ok"
    assert counts["rows"] == 3
    assert counts["kept"] == 3
    assert counts["clusters"] == counts["events_seen"] == counts["events_new"] == 1
    assert counts["duplicate_key"] == 0
    assert counts["url_fallback"] == 0
    assert get_state(db_path, key=HISTORY_FORM4_CURSOR_KEY) == "2024q1"


def test_rerunning_a_quarter_is_idempotent(tmp_path) -> None:
    db_path = str(tmp_path / "scout.db")

    def http_get_bytes(_url: str) -> bytes:
        return _cluster_zip()

    backfill_form4_quarter(db_path, "2024q1", now=NOW, http_get_bytes=http_get_bytes)
    counts = backfill_form4_quarter(db_path, "2024q1", now=NOW, http_get_bytes=http_get_bytes)

    assert counts["events_seen"] == 1
    assert counts["events_new"] == 0


def test_newest_quarter_falls_back_to_the_second_sec_path(tmp_path) -> None:
    """2026q2 lives under /files/datastandardsinnovation/, older quarters do not
    (live-verified 2026-08-07: 404 vs 200 on either path)."""
    db_path = str(tmp_path / "scout.db")
    requested: list[str] = []

    def http_get_bytes(url: str) -> bytes:
        requested.append(url)
        if url == QUARTER_URL.format(quarter="2026q2"):
            raise OSError("404 Not Found")
        return _cluster_zip()

    counts = backfill_form4_quarter(
        db_path, "2026q2", now=NOW, http_get_bytes=http_get_bytes
    )

    assert requested == [
        QUARTER_URL.format(quarter="2026q2"),
        QUARTER_URL_NEW_PATH.format(quarter="2026q2"),
    ]
    assert counts["status"] == "ok"
    assert counts["url_fallback"] == 1
    assert counts["events_new"] == 1


def test_both_urls_failing_is_a_counted_fetch_failure_that_keeps_the_cursor(
    tmp_path,
) -> None:
    db_path = str(tmp_path / "scout.db")
    set_state(db_path, key=HISTORY_FORM4_CURSOR_KEY, value="2023q4")

    def http_get_bytes(_url: str) -> bytes:
        raise OSError("connection reset")

    counts = backfill_form4_quarter(db_path, "2024q1", now=NOW, http_get_bytes=http_get_bytes)

    assert counts["status"] == "fetch_failed"
    assert "connection reset" in counts["detail"]
    assert counts["events_new"] == 0
    assert get_state(db_path, key=HISTORY_FORM4_CURSOR_KEY) == "2023q4"


def test_non_zip_payload_is_a_parse_failure_not_a_crash(tmp_path) -> None:
    """A rate-limit/error page is HTML, not a ZIP — say so, like form4.py:296."""
    db_path = str(tmp_path / "scout.db")

    def http_get_bytes(_url: str) -> bytes:
        return b"<html><body>Your request rate has exceeded the SEC limit</body></html>"

    counts = backfill_form4_quarter(db_path, "2024q1", now=NOW, http_get_bytes=http_get_bytes)

    assert counts["status"] == "parse_failed"
    assert get_state(db_path, key=HISTORY_FORM4_CURSOR_KEY) is None


def test_batch_late_filings_do_not_collide_on_event_key(tmp_path) -> None:
    """Regression: two disjoint clusters on one ticker, both filed in the same batch.

    Without `first_transaction_date` in the key both would be "FMBH-2024-03-20-cluster3"
    and INSERT OR IGNORE would silently drop one (8 of 339 clusters lost on real 2006q1).
    """
    db_path = str(tmp_path / "scout.db")
    zip_bytes = _purchases_zip([
        ("a1", "Alpha A", "01-FEB-2024", "20-MAR-2024"),
        ("a2", "Beta B", "02-FEB-2024", "20-MAR-2024"),
        ("a3", "Gamma C", "05-FEB-2024", "20-MAR-2024"),
        ("b1", "Delta D", "01-MAR-2024", "20-MAR-2024"),
        ("b2", "Epsilon E", "04-MAR-2024", "20-MAR-2024"),
        ("b3", "Zeta F", "05-MAR-2024", "20-MAR-2024"),
    ])

    counts = backfill_form4_quarter(
        db_path, "2024q1", now=NOW, http_get_bytes=lambda _url: zip_bytes
    )

    assert counts["clusters"] == 2
    assert counts["duplicate_key"] == 0
    assert counts["events_new"] == 2  # both survive; neither is swallowed by the other


def test_invalid_quarter_string_is_rejected(tmp_path) -> None:
    with pytest.raises(ValueError, match="quarter"):
        backfill_form4_quarter(
            str(tmp_path / "scout.db"), "2024-Q1", now=NOW, http_get_bytes=lambda _url: b""
        )


# --- quarter cursor -------------------------------------------------------------------


def test_next_quarter_wraps_the_year() -> None:
    assert next_quarter("2024q1") == "2024q2"
    assert next_quarter("2024q4") == "2025q1"


def test_cursor_starts_at_the_first_published_quarter(tmp_path) -> None:
    db_path = str(tmp_path / "scout.db")

    assert next_quarter_to_backfill(db_path, now=NOW) == "2006q1"


def test_cursor_resumes_after_the_last_completed_quarter(tmp_path) -> None:
    db_path = str(tmp_path / "scout.db")
    set_state(db_path, key=HISTORY_FORM4_CURSOR_KEY, value="2024q4")

    assert next_quarter_to_backfill(db_path, now=NOW) == "2025q1"


def test_cursor_stops_at_the_last_fully_elapsed_quarter(tmp_path) -> None:
    """SEC publishes a quarter only after it ends: on 2026-08-07 the newest set is 2026q2."""
    db_path = str(tmp_path / "scout.db")
    set_state(db_path, key=HISTORY_FORM4_CURSOR_KEY, value="2026q1")
    assert next_quarter_to_backfill(db_path, now=NOW) == "2026q2"

    set_state(db_path, key=HISTORY_FORM4_CURSOR_KEY, value="2026q2")
    assert next_quarter_to_backfill(db_path, now=NOW) is None


def test_first_quarter_of_a_year_resumes_into_the_prior_years_q4() -> None:
    """January..March: the last FULLY elapsed quarter is the previous year's q4."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db_path = f"{tmp}/scout.db"
        set_state(db_path, key=HISTORY_FORM4_CURSOR_KEY, value="2025q3")
        assert next_quarter_to_backfill(db_path, now="2026-01-15T09:00:00+00:00") == "2025q4"

        set_state(db_path, key=HISTORY_FORM4_CURSOR_KEY, value="2025q4")
        assert next_quarter_to_backfill(db_path, now="2026-01-15T09:00:00+00:00") is None
        # ...but by April 2026q1 has elapsed and the run continues.
        assert next_quarter_to_backfill(db_path, now="2026-04-01T09:00:00+00:00") == "2026q1"


# --- hardening: reader contract, corruption, schema drift -----------------------------


def test_otc_quotation_suffixes_are_stripped_to_the_ticker_root() -> None:
    """`.OB`/`.PK` are venue tags, not share classes — dropping them would gut the
    OTC-heavy early years (19 of 339 clusters on real 2006q1)."""
    submissions = [
        _submission("acc-1", ISSUERTRADINGSYMBOL="ABCD.OB"),
        _submission("acc-2", ISSUERTRADINGSYMBOL="efgh.pk"),
    ]
    owners = [_owner("acc-1", "Alpha A"), _owner("acc-2", "Beta B")]
    transactions = [_trans("acc-1"), _trans("acc-2")]
    purchases, counts = purchases_from_quarter_zip(
        _quarter_zip(submissions, owners, transactions)
    )

    assert counts == _counts(rows=2, kept=2)
    assert sorted(p.ticker for p in purchases) == ["ABCD", "EFGH"]


def test_unbalanced_quote_does_not_swallow_the_rest_of_the_member() -> None:
    """These are tab-separated dumps, not CSV: with default quoting a single leading `"`
    in a name makes the reader eat every following row as one field."""
    submissions = [_submission("acc-1"), _submission("acc-2")]
    owners = [_owner("acc-1", '"Big Fund LP'), _owner("acc-2", "Beta B")]
    transactions = [_trans("acc-1"), _trans("acc-2")]
    purchases, counts = purchases_from_quarter_zip(
        _quarter_zip(submissions, owners, transactions)
    )

    assert counts == _counts(rows=2, kept=2)
    assert [p.insider for p in purchases] == ['"Big Fund LP', "Beta B"]


def test_month_names_parse_without_depending_on_the_system_locale() -> None:
    """`strptime("%b")` resolves through LC_TIME — the same ZIP would parse here and turn
    into all-bad_date on a machine with a non-English locale."""
    months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
              "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    submissions = [
        _submission(f"acc-{i}", FILING_DATE=f"15-{month}-2024", PERIOD_OF_REPORT="")
        for i, month in enumerate(months)
    ]
    owners = [_owner(f"acc-{i}", f"Insider {i}") for i in range(len(months))]
    transactions = [
        _trans(f"acc-{i}", TRANS_DATE=f"15-{month}-2024") for i, month in enumerate(months)
    ]
    purchases, counts = purchases_from_quarter_zip(
        _quarter_zip(submissions, owners, transactions)
    )

    assert counts == _counts(rows=12, kept=12)
    assert [p.transaction_date[5:7] for p in purchases] == [
        f"{i:02d}" for i in range(1, 13)
    ]


def test_unparseable_share_count_keeps_the_purchase_but_voids_its_value() -> None:
    """The cluster rule counts PEOPLE, not dollars: a garbled size must not delete a real
    insider from a cluster, but it must never be read as a $0 priced buy either."""
    submissions = [_submission("acc-1"), _submission("acc-2")]
    owners = [_owner("acc-1", "Alpha A"), _owner("acc-2", "Beta B")]
    transactions = [
        _trans("acc-1", TRANS_SHARES="1,000"),  # thousands separator
        _trans("acc-2", TRANS_SHARES="abc"),
    ]
    purchases, counts = purchases_from_quarter_zip(
        _quarter_zip(submissions, owners, transactions)
    )

    assert counts == _counts(rows=2, kept=2, bad_shares=2)
    assert [p.shares for p in purchases] == [None, None]
    assert [p.value for p in purchases] == [None, None]
    # `bad_shares` is an overlay, NOT a partition bucket — it must not break the identity.
    partition = {
        key: value for key, value in counts.items() if key not in ("rows", "bad_shares")
    }
    assert counts["rows"] == sum(partition.values())


def test_partially_priced_cluster_reports_no_total_and_an_unknown_band() -> None:
    """A partial sum must never masquerade as the cluster total."""
    submissions = [
        _submission(acc, FILING_DATE=filed)
        for acc, filed in (("a1", "02-FEB-2024"), ("a2", "05-FEB-2024"), ("a3", "06-FEB-2024"))
    ]
    owners = [_owner("a1", "Alpha A"), _owner("a2", "Beta B"), _owner("a3", "Gamma C")]
    transactions = [
        _trans("a1", TRANS_DATE="01-FEB-2024"),
        _trans("a2", TRANS_DATE="01-FEB-2024"),
        _trans("a3", TRANS_DATE="01-FEB-2024", TRANS_PRICEPERSHARE=""),  # unpriced
    ]
    purchases, _ = purchases_from_quarter_zip(
        _quarter_zip(submissions, owners, transactions)
    )

    event = cluster_events(purchases)[0]

    assert event.details["n_purchases"] == 3
    assert event.details["priced_purchases"] == 2
    assert event.details["total_value"] is None
    assert event.details["value_band"] == "unbekannt"


def test_filing_lag_is_recorded_per_cluster_without_any_cutoff() -> None:
    """Lag is a study DIMENSION (Task 6 conditions on it), never a filter — a cluster
    disclosed 8 months late is still recorded, just flagged as slow."""
    purchases = _purchases([
        ("a1", "Alpha A", "01-FEB-2024", "02-FEB-2024"),   # 1 trading day
        ("a2", "Beta B", "01-FEB-2024", "08-FEB-2024"),    # 5 trading days
        ("a3", "Gamma C", "01-FEB-2024", "01-OCT-2024"),   # ~173 trading days
    ])

    event = cluster_events(purchases)[0]

    assert event.details["median_filing_lag_days"] == 5.0
    assert event.details["max_filing_lag_days"] == 173
    assert event.t0 == "2024-10-01"  # the slow filing still sets T0


def test_boundary_candidates_counts_tickers_one_insider_short_at_the_file_edge() -> None:
    """The quarter-boundary ceiling as a number: 2 insiders in the trailing window is a
    cluster that a cross-file stitch could still promote (MIN_INSIDERS == 3)."""
    edge = _purchases([
        ("a1", "Alpha A", "20-MAR-2024", "21-MAR-2024"),
        ("a2", "Beta B", "22-MAR-2024", "25-MAR-2024"),
    ])
    already_clustered = _purchases([
        ("b1", "Delta D", "20-MAR-2024", "21-MAR-2024"),
        ("b2", "Epsilon E", "21-MAR-2024", "22-MAR-2024"),
        ("b3", "Zeta F", "22-MAR-2024", "25-MAR-2024"),
    ], symbol="TOL")
    old = _purchases([
        ("c1", "Eta G", "05-JAN-2024", "08-JAN-2024"),
        ("c2", "Theta H", "08-JAN-2024", "09-JAN-2024"),
    ], symbol="AAPL")

    # Only FMBH sits at exactly MIN_INSIDERS-1 in the trailing 10-trading-day edge:
    # TOL already has 3, and AAPL's pair is months before the edge.
    assert count_boundary_candidates(edge + already_clustered + old) == 1
    assert count_boundary_candidates([]) == 0
    assert MIN_INSIDERS == 3


def _deflate_corrupt_zip() -> bytes:
    """A structurally valid ZIP whose transaction member's DEFLATE stream is garbage —
    what a bit-rotted multi-MB download looks like (raises zlib.error, not BadZipFile)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SUBMISSION.tsv", _tsv(SUBMISSION_COLUMNS, [_submission("acc-1")]))
        archive.writestr("REPORTINGOWNER.tsv", _tsv(OWNER_COLUMNS, [_owner("acc-1", "A B")]))
        archive.writestr(
            "NONDERIV_TRANS.tsv",
            _tsv(TRANS_COLUMNS, [_trans(f"acc-{i}") for i in range(200)]),
        )
    raw = bytearray(buffer.getvalue())
    with zipfile.ZipFile(io.BytesIO(bytes(raw))) as probe:
        info = probe.getinfo("NONDERIV_TRANS.tsv")
    header = raw[info.header_offset:info.header_offset + 30]
    start = (
        info.header_offset + 30
        + int.from_bytes(header[26:28], "little")
        + int.from_bytes(header[28:30], "little")
    )
    raw[start:start + info.compress_size] = b"\x00" * info.compress_size
    return bytes(raw)


def test_deflate_corruption_becomes_a_value_error_not_a_raw_zlib_error(tmp_path) -> None:
    zip_bytes = _deflate_corrupt_zip()

    # The fixture really does exercise the zlib path (not the CRC/BadZipFile one).
    with pytest.raises(zlib.error):
        zipfile.ZipFile(io.BytesIO(zip_bytes)).read("NONDERIV_TRANS.tsv")

    with pytest.raises(ValueError, match="unlesbar"):
        purchases_from_quarter_zip(zip_bytes)

    counts = backfill_form4_quarter(
        str(tmp_path / "scout.db"), "2024q1", now=NOW, http_get_bytes=lambda _url: zip_bytes
    )
    assert counts["status"] == "parse_failed"
    assert get_state(str(tmp_path / "scout.db"), key=HISTORY_FORM4_CURSOR_KEY) is None


def test_truncated_stream_eof_becomes_a_value_error(monkeypatch, tmp_path) -> None:
    """zipfile raises a bare EOFError when a DEFLATE stream stops before its end marker;
    it must not fly out of a multi-hour backfill."""
    def boom(_archive, _member):
        raise EOFError("Compressed file ended before the end-of-stream marker was reached")
        yield  # pragma: no cover — generator marker

    monkeypatch.setattr(backfill_form4, "_tsv_rows", boom)

    with pytest.raises(ValueError, match="unlesbar"):
        purchases_from_quarter_zip(_simple_zip())

    counts = backfill_form4_quarter(
        str(tmp_path / "scout.db"), "2024q1", now=NOW, http_get_bytes=lambda _url: _simple_zip()
    )
    assert counts["status"] == "parse_failed"


def test_renamed_join_column_fails_loudly_instead_of_reporting_zero(tmp_path) -> None:
    """Silent drift is the dangerous failure: an ok/0-cluster run ALSO advances the
    cursor, so the quarter would be skipped forever."""
    columns = [
        "ISSUER_TRADING_SYMBOL" if c == "ISSUERTRADINGSYMBOL" else c
        for c in SUBMISSION_COLUMNS
    ]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SUBMISSION.tsv", _tsv(columns, [_submission("acc-1")]))
        archive.writestr("REPORTINGOWNER.tsv", _tsv(OWNER_COLUMNS, [_owner("acc-1", "A B")]))
        archive.writestr("NONDERIV_TRANS.tsv", _tsv(TRANS_COLUMNS, [_trans("acc-1")]))
    zip_bytes = buffer.getvalue()

    with pytest.raises(ValueError, match="ISSUERTRADINGSYMBOL"):
        purchases_from_quarter_zip(zip_bytes)

    db_path = str(tmp_path / "scout.db")
    counts = backfill_form4_quarter(
        db_path, "2024q1", now=NOW, http_get_bytes=lambda _url: zip_bytes
    )
    assert counts["status"] == "parse_failed"
    assert get_state(db_path, key=HISTORY_FORM4_CURSOR_KEY) is None


def test_columns_absent_in_older_quarters_are_not_required() -> None:
    """Real drift: 2006q1's SUBMISSION.tsv has 13 columns, 2024q1's has 14 (AFF10B5ONE).
    Only the JOINED columns may be required."""
    columns = [c for c in SUBMISSION_COLUMNS if c != "AFF10B5ONE"]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SUBMISSION.tsv", _tsv(columns, [_submission("acc-1")]))
        archive.writestr("REPORTINGOWNER.tsv", _tsv(OWNER_COLUMNS, [_owner("acc-1", "A B")]))
        archive.writestr("NONDERIV_TRANS.tsv", _tsv(TRANS_COLUMNS, [_trans("acc-1")]))

    purchases, counts = purchases_from_quarter_zip(buffer.getvalue())

    assert counts == _counts(rows=1, kept=1)
    assert purchases[0].ticker == "FMBH"


def test_byte_order_mark_does_not_break_the_join() -> None:
    """With plain utf-8 a BOM fuses onto the first header name, so ACCESSION_NUMBER is
    keyed "﻿ACCESSION_NUMBER", every join misses and the run reports a cheerful 0."""
    bom = "﻿".encode()
    members = {
        "SUBMISSION.tsv": bom + _tsv(SUBMISSION_COLUMNS, [_submission("acc-1")]),
        "REPORTINGOWNER.tsv": bom + _tsv(OWNER_COLUMNS, [_owner("acc-1", "TREACE JAMES T")]),
        "NONDERIV_TRANS.tsv": bom + _tsv(TRANS_COLUMNS, [_trans("acc-1")]),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)

    purchases, counts = purchases_from_quarter_zip(buffer.getvalue())

    assert counts == _counts(rows=1, kept=1)
    assert purchases[0].ticker == "FMBH"
    assert purchases[0].insider == "TREACE JAMES T"


def test_empty_quarter_is_loud_and_holds_the_cursor(tmp_path) -> None:
    """No real quarter has zero transactions — treating it as `ok` would advance the
    cursor and skip that quarter permanently."""
    db_path = str(tmp_path / "scout.db")
    set_state(db_path, key=HISTORY_FORM4_CURSOR_KEY, value="2023q4")
    zip_bytes = _quarter_zip([_submission("acc-1")], [_owner("acc-1", "A B")], [])

    counts = backfill_form4_quarter(
        db_path, "2024q1", now=NOW, http_get_bytes=lambda _url: zip_bytes
    )

    assert counts["status"] == "empty_quarter"
    assert counts["rows"] == 0
    assert counts["events_new"] == 0
    assert get_state(db_path, key=HISTORY_FORM4_CURSOR_KEY) == "2023q4"


def test_successful_run_reports_the_boundary_ceiling(tmp_path) -> None:
    counts = backfill_form4_quarter(
        str(tmp_path / "scout.db"), "2024q1", now=NOW,
        http_get_bytes=lambda _url: _cluster_zip(),
    )

    assert counts["status"] == "ok"
    assert counts["bad_shares"] == 0
    # The cluster's own 3 insiders sit in the trailing window, so it is not a candidate.
    assert counts["boundary_candidates"] == 0
