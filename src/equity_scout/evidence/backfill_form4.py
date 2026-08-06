"""Insider-CLUSTER backfill from the SEC's quarterly "Form 345" data sets (2006q1 ->).

Same source family and the same SEC Fair Access contract as `evidence/form4.py` (a
contact `EDGAR_USER_AGENT` is REQUIRED; without it this collector reports itself
`unconfigured` and writes nothing), but the bulk path instead of the per-issuer one: a
2006-> history via `form4.py`'s submissions API would be one HTTP call per company per
quarter, while the SEC publishes the very same Form 3/4/5 filings as ONE ZIP per quarter.
82 ZIPs cover 2006q1..2026q2 — hence the resumable one-quarter-at-a-time cursor
(`HISTORY_FORM4_CURSOR_KEY` in `app_state`).

Only CLUSTERS become events, never single buys: >= `MIN_INSIDERS` (imported from
`evidence/aggregate.py`, never redefined) DISTINCT insiders buying the same ticker inside
a 10-trading-day window — Cohen/Malloy/Pomorski (2012), the same rule the live alert path
already applies. Single large purchases are deliberately out of scope (backlog).

--- VERIFIED LAYOUT (live download of 2024q1_form345.zip, 2026-08-07) ------------------
URL: https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/
     {quarter}_form345.zip  for 2006q1..2026q1
     ...but the NEWEST quarter is published under a second path only:
     https://www.sec.gov/files/datastandardsinnovation/data/insider-transactions-data-sets/
     {quarter}_form345.zip  (2026q2: 404 on the first path, 200 on this one; 2024q1 the
     other way round) — so both are tried, the fallback is counted (`url_fallback`).

ZIP members (2024q1, 13.9 MB): DERIV_HOLDING.tsv, DERIV_TRANS.tsv, FOOTNOTES.tsv,
NONDERIV_HOLDING.tsv, NONDERIV_TRANS.tsv, OWNER_SIGNATURE.tsv, REPORTINGOWNER.tsv,
SUBMISSION.tsv, FORM_345_metadata.json, FORM_345_readme.htm.

SURPRISE vs. the task's expectation: the owner name is NOT a column of NONDERIV_TRANS —
it lives in a THIRD member, REPORTINGOWNER.tsv. The join is a 3-way join on
ACCESSION_NUMBER, all inside the one ZIP (no extra request, no extra URL).

  SUBMISSION.tsv (14 cols): ACCESSION_NUMBER, FILING_DATE, PERIOD_OF_REPORT,
    DATE_OF_ORIG_SUB, NO_SECURITIES_OWNED, NOT_SUBJECT_SEC16, FORM3_HOLDINGS_REPORTED,
    FORM4_TRANS_REPORTED, DOCUMENT_TYPE, ISSUERCIK, ISSUERNAME, ISSUERTRADINGSYMBOL,
    REMARKS, AFF10B5ONE
  REPORTINGOWNER.tsv (13 cols): ACCESSION_NUMBER, RPTOWNERCIK, RPTOWNERNAME,
    RPTOWNER_RELATIONSHIP, RPTOWNER_TITLE, RPTOWNER_TXT, RPTOWNER_STREET1,
    RPTOWNER_STREET2, RPTOWNER_CITY, RPTOWNER_STATE, RPTOWNER_ZIPCODE,
    RPTOWNER_STATE_DESC, FILE_NUMBER
  NONDERIV_TRANS.tsv (28 cols): ACCESSION_NUMBER, NONDERIV_TRANS_SK, SECURITY_TITLE,
    SECURITY_TITLE_FN, TRANS_DATE, TRANS_DATE_FN, DEEMED_EXECUTION_DATE,
    DEEMED_EXECUTION_DATE_FN, TRANS_FORM_TYPE, TRANS_CODE, EQUITY_SWAP_INVOLVED,
    EQUITY_SWAP_TRANS_CD_FN, TRANS_TIMELINESS, TRANS_TIMELINESS_FN, TRANS_SHARES,
    TRANS_SHARES_FN, TRANS_PRICEPERSHARE, TRANS_PRICEPERSHARE_FN,
    TRANS_ACQUIRED_DISP_CD, TRANS_ACQUIRED_DISP_CD_FN, SHRS_OWND_FOLWNG_TRANS,
    SHRS_OWND_FOLWNG_TRANS_FN, VALU_OWND_FOLWNG_TRANS, VALU_OWND_FOLWNG_TRANS_FN,
    DIRECT_INDIRECT_OWNERSHIP, DIRECT_INDIRECT_OWNERSHIP_FN, NATURE_OF_OWNERSHIP,
    NATURE_OF_OWNERSHIP_FN

Dates are DD-MON-YYYY ("31-JAN-2024"), NOT ISO — the readme confirms this for every DATE
column; everything downstream (t0, price panels) is ISO, so they are converted here.

Measured on 2024q1: 67,671 submissions (61,366 form "4", 1,122 "4/A", 3,884 "3", 1,139
"5"), 1,473 accessions with more than one reporting owner, 111,404 non-derivative
transaction rows, TRANS_CODE distribution F 27,522 / S 27,191 / A 25,674 / M 17,653 /
P 5,954 / rest small. Of the 5,954 "P" rows, 40 carry TRANS_ACQUIRED_DISP_CD "D". The
pipeline below keeps 5,240 purchases -> 179 clusters, and counts 411 not_form4,
260 no_symbol, 3 real PIT violations (FILING_DATE < TRANS_DATE).

--- Rules (each mirrors an existing repo decision) -------------------------------------
* P + A only (`form4.py:209`): code "P" AND acquired-code "A"; everything else is a
  different signal.
* DOCUMENT_TYPE "4" only (`form4.py:120`): amendments ("4/A") restate transactions the
  original already reported and would double-count; Form 5 is the late/annual catch-all.
* First reporting owner only (`form4.py:192-196`): a group filing (fund + affiliates +
  partners, 1,473 accessions in 2024q1) is ONE decision. Counting its five co-filers as
  five insiders would manufacture clusters out of single group purchases.
* PIT guard (`form4.py:299-310`): FILING_DATE < TRANS_DATE is impossible; such rows are
  discarded and counted (`discarded_pit`), never silently misdated.
* Unusable ISSUERTRADINGSYMBOL is a counted gap, never a guess: placeholders
  ("[ NONE ]", "N/A", "-"), exchange prefixes ("NYSE:NYCB") and dual-class listings
  ("GEF,GEF.B") cannot be resolved to one ticker — same honesty rule as
  `form4.py`'s unmapped tickers.
* `rows` is the denominator and every row lands in exactly ONE bucket; a malformed row is
  counted and skipped, never raised out of a multi-hour run (Task-2 convention from
  `backfill_congress.py`).

Trading-day windows use `np.busday_count` — weekdays, holidays IGNORED, the same
approximation `st_swing.py:55` already makes. The repo has no trading calendar, and a
cluster window is heuristic grouping, not a P&L measurement.
"""
from __future__ import annotations

import csv
import io
import os
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from equity_scout.evidence.aggregate import MIN_INSIDERS
from equity_scout.evidence.base import (
    SOURCE_INSIDER,
    STATUS_FETCH_FAILED,
    STATUS_OK,
    STATUS_PARSE_FAILED,
    STATUS_UNCONFIGURED,
)
from equity_scout.evidence.edgar import resolve_user_agent
from equity_scout.evidence.form4 import _REQUEST_PAUSE_S
from equity_scout.evidence.historical_storage import HistoricalEvent, record_historical_events
from equity_scout.state_storage import get_state, set_state

_DATA_SET_PATH = "insider-transactions-data-sets/{quarter}_form345.zip"
QUARTER_URL = f"https://www.sec.gov/files/structureddata/data/{_DATA_SET_PATH}"
# Newest quarter only (live-verified 2026-08-07) — SEC moved the publishing path.
QUARTER_URL_NEW_PATH = f"https://www.sec.gov/files/datastandardsinnovation/data/{_DATA_SET_PATH}"

FIRST_QUARTER = "2006q1"  # oldest set the SEC publishes
HISTORY_FORM4_CURSOR_KEY = "history_form4_cursor"  # value = last COMPLETED quarter

SUBMISSION_MEMBER = "SUBMISSION.tsv"
OWNER_MEMBER = "REPORTINGOWNER.tsv"
TRANS_MEMBER = "NONDERIV_TRANS.tsv"

DEFAULT_WINDOW_TRADING_DAYS = 10

_QUARTER_RE = re.compile(r"^(\d{4})q([1-4])$")
# One resolvable ticker: letters/digits plus the dot/dash share-class separators. Rejects
# every real 2024q1 junk value (see the layout block above).
_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,9}$")
_SYMBOL_PLACEHOLDERS = frozenset({"", "-", "--", "NONE"})

_BUY_TRANSACTION_CODE = "P"
_ACQUIRED_CODE = "A"
_FORM4_DOCUMENT_TYPE = "4"

# Coarse bands (the study conditions on the band, not on the exact dollar amount — same
# granularity as congress' disclosed `amount_range_label`).
_VALUE_BANDS = ((100_000.0, "<$100k"), (1_000_000.0, "$100k-$1M"), (10_000_000.0, "$1M-$10M"))
_VALUE_BAND_TOP = ">$10M"
_VALUE_BAND_UNKNOWN = "unbekannt"

_COUNT_KEYS = (
    "rows", "kept", "not_purchase", "no_submission", "not_form4", "no_symbol", "no_owner",
    "bad_date", "discarded_pit",
)


def _http_get_bytes_with_agent(user_agent: str) -> Callable[[str], bytes]:
    """Binary sibling of `form4._http_get_with_agent` (ZIPs, not XML), same politeness."""

    def get(url: str) -> bytes:
        import time

        import httpx

        time.sleep(_REQUEST_PAUSE_S)
        response = httpx.get(
            url, timeout=120.0, follow_redirects=True, headers={"User-Agent": user_agent}
        )
        response.raise_for_status()
        return response.content

    return get


def _iso_date(value: str) -> str | None:
    """DD-MON-YYYY -> ISO, or None for anything the SEC ships malformed."""
    try:
        return datetime.strptime(value.strip(), "%d-%b-%Y").date().isoformat()
    except (ValueError, AttributeError):
        return None


def _clean_symbol(value: str) -> str | None:
    symbol = (value or "").strip().upper()
    if symbol in _SYMBOL_PLACEHOLDERS or not _SYMBOL_RE.match(symbol):
        return None
    return symbol


def _float_or_none(value: str) -> float | None:
    try:
        return float((value or "").strip())
    except ValueError:
        return None


def _value_band(total_value: float | None) -> str:
    if total_value is None:
        return _VALUE_BAND_UNKNOWN
    for upper, label in _VALUE_BANDS:
        if total_value < upper:
            return label
    return _VALUE_BAND_TOP


@dataclass(frozen=True)
class InsiderPurchase:
    ticker: str
    insider: str
    transaction_date: str  # ISO, the trade day
    filing_date: str  # ISO, the day it became publicly knowable
    shares: float
    price: float | None  # None when the filing carries no price (27 of 5,954 P rows)
    value: float | None
    accession: str


def _tsv_rows(archive: zipfile.ZipFile, member: str):
    """Streaming DictReader over one ZIP member — the transaction table alone is ~12 MB
    per quarter, so it is never materialized as a list."""
    with archive.open(member) as handle:
        yield from csv.DictReader(
            io.TextIOWrapper(handle, encoding="utf-8", errors="replace", newline=""),
            delimiter="\t",
        )


def purchases_from_quarter_zip(
    zip_bytes: bytes,
) -> tuple[list[InsiderPurchase], dict[str, int]]:
    """One quarter ZIP -> open-market insider purchases + per-bucket skip counters.

    Three-way join on ACCESSION_NUMBER (SUBMISSION x REPORTINGOWNER x NONDERIV_TRANS).
    Every NONDERIV_TRANS row is counted in `rows` and lands in exactly one other bucket,
    so `rows == sum(other buckets)` holds — the denominator the Task-7 report needs.

    Raises ValueError when the ZIP is unreadable or a joined member is absent: that is a
    broken download, not a row-level defect, and must not look like a quiet empty quarter.
    A truncated download only fails mid-read, so the corruption errors are converted here
    too — the caller must never see a raw BadZipFile crash a multi-hour backfill.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            return _purchases_from_archive(archive)
    except (zipfile.BadZipFile, csv.Error) as err:
        # A rate-limit/error page is HTML, not a ZIP — say so, like form4.py:296.
        raise ValueError(f"Quartals-ZIP unlesbar (Rate-Limit-/Fehlerseite?): {err}") from err


def _purchases_from_archive(
    archive: zipfile.ZipFile,
) -> tuple[list[InsiderPurchase], dict[str, int]]:
    """The join itself; `purchases_from_quarter_zip` owns the corruption contract."""
    counts = dict.fromkeys(_COUNT_KEYS, 0)
    missing = [
        member
        for member in (SUBMISSION_MEMBER, OWNER_MEMBER, TRANS_MEMBER)
        if member not in archive.namelist()
    ]
    if missing:
        raise ValueError(f"quarter ZIP is missing {', '.join(missing)}")

    # Only the three joined columns are kept per submission — a quarter has ~68k of
    # them and the other 11 columns are never read.
    submissions: dict[str, tuple[str, str, str]] = {
        row.get("ACCESSION_NUMBER", ""): (
            (row.get("DOCUMENT_TYPE") or "").strip(),
            row.get("ISSUERTRADINGSYMBOL") or "",
            row.get("FILING_DATE") or "",
        )
        for row in _tsv_rows(archive, SUBMISSION_MEMBER)
    }
    owners: dict[str, str] = {}
    for row in _tsv_rows(archive, OWNER_MEMBER):
        # setdefault = FIRST reporting owner wins (form4.py's live rule).
        name = (row.get("RPTOWNERNAME") or "").strip()
        if name:
            owners.setdefault(row.get("ACCESSION_NUMBER", ""), name)

    purchases: list[InsiderPurchase] = []
    for row in _tsv_rows(archive, TRANS_MEMBER):
        counts["rows"] += 1
        if (
            (row.get("TRANS_CODE") or "").strip() != _BUY_TRANSACTION_CODE
            or (row.get("TRANS_ACQUIRED_DISP_CD") or "").strip() != _ACQUIRED_CODE
        ):
            counts["not_purchase"] += 1
            continue
        accession = row.get("ACCESSION_NUMBER", "")
        submission = submissions.get(accession)
        if submission is None:
            counts["no_submission"] += 1
            continue
        document_type, raw_symbol, raw_filing_date = submission
        if document_type != _FORM4_DOCUMENT_TYPE:
            counts["not_form4"] += 1
            continue
        ticker = _clean_symbol(raw_symbol)
        if ticker is None:
            counts["no_symbol"] += 1
            continue
        insider = owners.get(accession)
        if not insider:
            counts["no_owner"] += 1
            continue
        transaction_date = _iso_date(row.get("TRANS_DATE", ""))
        filing_date = _iso_date(raw_filing_date)
        if transaction_date is None or filing_date is None:
            counts["bad_date"] += 1
            continue
        if filing_date < transaction_date:
            counts["discarded_pit"] += 1
            continue
        shares = _float_or_none(row.get("TRANS_SHARES", "")) or 0.0
        price = _float_or_none(row.get("TRANS_PRICEPERSHARE", ""))
        counts["kept"] += 1
        purchases.append(
            InsiderPurchase(
                ticker=ticker,
                insider=insider,
                transaction_date=transaction_date,
                filing_date=filing_date,
                shares=shares,
                price=price,
                value=(shares * price) if price is not None else None,
                accession=accession,
            )
        )
    return purchases, counts


def _cluster_event(ticker: str, members: list[InsiderPurchase]) -> HistoricalEvent:
    insiders = sorted({purchase.insider for purchase in members})
    priced = [purchase.value for purchase in members if purchase.value is not None]
    total_value = sum(priced) if priced else None
    # T0 = the LAST filing of the cluster: only then was the FULL cluster knowable.
    t0 = max(purchase.filing_date for purchase in members)
    return HistoricalEvent(
        source=SOURCE_INSIDER,
        person="",  # a cluster has no single person — names live in details (Decision 2)
        ticker=ticker,
        event_key=f"{ticker}-{t0}-cluster{len(insiders)}",
        t0=t0,
        details={
            "insiders": insiders,
            "n_insiders": len(insiders),
            "n_purchases": len(members),
            "priced_purchases": len(priced),
            "total_shares": sum(purchase.shares for purchase in members),
            "total_value": total_value,
            "value_band": _value_band(total_value),
            "first_transaction_date": min(p.transaction_date for p in members),
            "last_transaction_date": max(p.transaction_date for p in members),
            "first_filing_date": min(purchase.filing_date for purchase in members),
        },
    )


def cluster_events(
    purchases: list[InsiderPurchase],
    *,
    window_trading_days: int = DEFAULT_WINDOW_TRADING_DAYS,
    min_insiders: int = MIN_INSIDERS,
) -> list[HistoricalEvent]:
    """Purchases -> one `HistoricalEvent` per insider CLUSTER, per ticker.

    Greedy, NON-OVERLAPPING sweep per ticker: anchor on the earliest unconsumed purchase,
    take every purchase within `window_trading_days` TRADING days of it (np.busday_count,
    holidays ignored — see module docstring), and emit a cluster if it holds at least
    `min_insiders` DISTINCT insiders, consuming those purchases; otherwise drop the anchor
    and retry from the next purchase. Anchoring on EVERY purchase instead would emit one
    near-duplicate event per member and inflate the study's n (902 vs 179 on 2024q1).

    Ordering is fully deterministic (transaction date, filing date, insider, accession) so
    two runs over the same quarter produce byte-identical event keys.
    """
    by_ticker: dict[str, list[InsiderPurchase]] = {}
    for purchase in purchases:
        by_ticker.setdefault(purchase.ticker, []).append(purchase)

    events: list[HistoricalEvent] = []
    for ticker in sorted(by_ticker):
        ordered = sorted(
            by_ticker[ticker],
            key=lambda p: (p.transaction_date, p.filing_date, p.insider, p.accession),
        )
        start = 0
        while start < len(ordered):
            end = start
            while end < len(ordered) and (
                int(
                    np.busday_count(
                        ordered[start].transaction_date, ordered[end].transaction_date
                    )
                )
                <= window_trading_days
            ):
                end += 1
            members = ordered[start:end]
            if len({purchase.insider for purchase in members}) >= min_insiders:
                events.append(_cluster_event(ticker, members))
                start = end
            else:
                start += 1
    return events


def next_quarter(quarter: str) -> str:
    year, index = _parse_quarter(quarter)
    return f"{year + 1}q1" if index == 4 else f"{year}q{index + 1}"


def _parse_quarter(quarter: str) -> tuple[int, int]:
    match = _QUARTER_RE.match(quarter or "")
    if match is None:
        raise ValueError(f"quarter must look like '2024q1', got {quarter!r}")
    return int(match.group(1)), int(match.group(2))


def _latest_published_quarter(now: str) -> str:
    """The newest data set the SEC can have published: the last FULLY elapsed quarter."""
    today = datetime.fromisoformat(now).date()
    index = (today.month - 1) // 3 + 1  # 1..4, the quarter `now` sits in — still running
    return f"{today.year - 1}q4" if index == 1 else f"{today.year}q{index - 1}"


def next_quarter_to_backfill(db_path: str, *, now: str) -> str | None:
    """The quarter a resumable multi-year run should fetch next, or None when caught up.

    The cursor stores the last COMPLETED quarter; an unset cursor starts the run at
    `FIRST_QUARTER`. Quarters beyond the last fully elapsed one do not exist yet.
    """
    cursor = get_state(db_path, key=HISTORY_FORM4_CURSOR_KEY)
    candidate = FIRST_QUARTER if cursor is None else next_quarter(cursor)
    return candidate if candidate <= _latest_published_quarter(now) else None


def _fetch_quarter_zip(
    quarter: str, http_get_bytes: Callable[[str], bytes]
) -> tuple[bytes, int]:
    """(zip bytes, url_fallback flag). Both SEC paths are tried — neither serves every
    quarter (2024q1 only on the first, 2026q2 only on the second, live-verified)."""
    errors: list[str] = []
    for fallback, template in enumerate((QUARTER_URL, QUARTER_URL_NEW_PATH)):
        url = template.format(quarter=quarter)
        try:
            return http_get_bytes(url), fallback
        except Exception as err:  # noqa: BLE001 — every transport failure becomes a status
            errors.append(f"{url}: {err}")
    raise OSError("; ".join(errors))


def backfill_form4_quarter(
    db_path: str,
    quarter: str,
    *,
    now: str,
    env: dict | None = None,
    http_get_bytes: Callable[[str], bytes] | None = None,
) -> dict:
    """One quarterly SEC data set -> insider-cluster `HistoricalEvent`s, cursor advanced.

    Degrades like `form4.collect_form4`: a missing `EDGAR_USER_AGENT` returns
    `unconfigured` (nothing fetched, nothing written, never a fake), an unreachable or
    non-ZIP download returns `fetch_failed`/`parse_failed`. The cursor advances ONLY after
    a quarter was fully recorded, so a failed run is simply retried next time.

    `duplicate_key` counts clusters that collide on the plan-mandated event_key (two
    disjoint windows of equal size whose last filing lands on the same day) — such a
    collision is dropped by `record_historical_events`' INSERT OR IGNORE, so it is counted
    here rather than vanishing into the events_new/events_seen difference.
    """
    counts: dict = {
        "quarter": quarter, "status": STATUS_OK, "detail": "", "url_fallback": 0,
        "clusters": 0, "duplicate_key": 0, "events_seen": 0, "events_new": 0,
        **dict.fromkeys(_COUNT_KEYS, 0),
    }
    _parse_quarter(quarter)  # fail loudly on a typo before touching the network

    if http_get_bytes is None:
        user_agent = resolve_user_agent(env if env is not None else dict(os.environ))
        if user_agent is None:
            counts["status"] = STATUS_UNCONFIGURED
            counts["detail"] = (
                "EDGAR_USER_AGENT fehlt in .env — SEC verlangt Kontakt im User-Agent"
            )
            return counts
        http_get_bytes = _http_get_bytes_with_agent(user_agent)

    try:
        zip_bytes, counts["url_fallback"] = _fetch_quarter_zip(quarter, http_get_bytes)
    except Exception as err:  # noqa: BLE001 — a dead download is a status, not a crash
        counts["status"] = STATUS_FETCH_FAILED
        counts["detail"] = str(err)
        return counts

    try:
        purchases, row_counts = purchases_from_quarter_zip(zip_bytes)
    except ValueError as err:
        counts["status"] = STATUS_PARSE_FAILED
        counts["detail"] = str(err)
        return counts

    counts.update(row_counts)
    events = cluster_events(purchases)
    counts["clusters"] = counts["events_seen"] = len(events)
    counts["duplicate_key"] = len(events) - len({(e.ticker, e.event_key) for e in events})
    counts["events_new"] = len(record_historical_events(db_path, events, now=now))
    set_state(db_path, key=HISTORY_FORM4_CURSOR_KEY, value=quarter)
    return counts
