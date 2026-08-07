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
SUBMISSION.tsv, FORM_345_metadata.json, FORM_345_readme.htm. (2006q1, 17.3 MB, ships the
same eight TSVs but NO metadata.json/readme.htm.)

SURPRISE vs. the task's expectation: the owner name is NOT a column of NONDERIV_TRANS —
it lives in a THIRD member, REPORTINGOWNER.tsv. The join is a 3-way join on
ACCESSION_NUMBER, all inside the one ZIP (no extra request, no extra URL).

THE SCHEMA DRIFTS ACROSS YEARS: 2006q1's SUBMISSION.tsv has 13 columns, 2024q1's has 14
(AFF10B5ONE was added later). So the reader validates only the columns actually JOINED
(`_REQUIRED_COLUMNS`), never the full header — but it does validate them, because a
renamed join column would otherwise yield a silent "ok, 0 clusters" run that also
advances the cursor and skips that quarter forever.

  SUBMISSION.tsv (14 cols in 2024q1; 2006q1 lacks the trailing AFF10B5ONE):
    ACCESSION_NUMBER, FILING_DATE, PERIOD_OF_REPORT,
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
260 no_symbol, 3 real PIT violations (FILING_DATE < TRANS_DATE), 0 bad_shares.

Measured on 2006q1 (the oldest set, OTC-heavy): 171,549 transaction rows -> 12,454
purchases -> 339 clusters; 1,827 not_form4, 609 no_symbol, 6 PIT violations, 0 bad_shares,
45 boundary_candidates. Insider buying was ~2.4x more frequent then than in 2024q1, so the
early years carry a large share of the study's n — which is why the OTC suffix rule and
the collision-free event_key below are load-bearing, not cosmetic.

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
  `form4.py`'s unmapped tickers. The ONE exception is the OTC quotation suffix
  ".OB" (OTC Bulletin Board) / ".PK" (Pink Sheets): those name the same firm on the same
  ticker root, they are a venue tag rather than a share class, and `form4.py` would
  otherwise drop every dot-ticker as non-US. They are stripped (19 of 339 clusters in
  2006q1 depend on it — the OTC-heavy early years would be gutted without it).
* `rows` is the denominator and every row lands in exactly ONE PARTITION bucket; a
  malformed row is counted and skipped, never raised out of a multi-hour run (Task-2
  convention from `backfill_congress.py`). `bad_shares` is the one OVERLAY counter — such
  a row IS still a real insider buy (identity and dates are intact, only the size is
  garbled), so it stays a purchase with unknown size and is excluded from the partition
  sum. `rows == 0` on a structurally valid ZIP is never "ok": it returns `empty_quarter`
  and does NOT advance the cursor.

Trading-day windows use `np.busday_count` — weekdays, holidays IGNORED, the same
approximation `st_swing.py:55` already makes. The repo has no trading calendar, and a
cluster window is heuristic grouping, not a P&L measurement.

KNOWN CEILING — quarter boundaries: clustering runs per quarter FILE, and a file holds
the filings FILED in that quarter. A cluster whose members' filings straddle a quarter
boundary is therefore structurally invisible: neither file sees all of it, and no
stitching pass exists. `boundary_candidates` counts the tickers sitting at exactly
MIN_INSIDERS-1 distinct insiders in the file's trailing 10-trading-day edge, so Task 7 can
publish that ceiling as a number instead of a footnote. This is an UNDERCOUNT of clusters,
never an overcount — the study's n is a floor.

KNOWN BIAS — greedy non-overlap: the sweep anchors on the earliest unconsumed purchase
and takes the widest window from it, which systematically prefers the LOOSER cluster. If
four insiders buy on days 1, 9, 10 and 11, the anchor at day 1 swallows days 9 and 10 into
one 3-insider cluster and leaves day 11 orphaned — the tighter, arguably stronger trio of
days 9/10/11 is never emitted. The alternative (anchoring on every purchase) inflates n
5-fold with near-duplicates (902 vs 179 on 2024q1), which is the worse error for a base-
rate study, so the bias is accepted and recorded here rather than tuned away.
"""
from __future__ import annotations

import csv
import io
import os
import re
import statistics
import zipfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

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

# No base.py status fits "the ZIP parsed but held nothing"; local to this collector.
STATUS_EMPTY_QUARTER = "empty_quarter"

FIRST_QUARTER = "2006q1"  # oldest set the SEC publishes
HISTORY_FORM4_CURSOR_KEY = "history_form4_cursor"  # value = last COMPLETED quarter

SUBMISSION_MEMBER = "SUBMISSION.tsv"
OWNER_MEMBER = "REPORTINGOWNER.tsv"
TRANS_MEMBER = "NONDERIV_TRANS.tsv"

# ONLY the columns this module joins on. The full header drifts between years (2006q1's
# SUBMISSION has 13 columns, 2024q1's has 14), so requiring the whole header would break
# on valid data — but a RENAMED join column must fail loudly, not silently produce zero.
_REQUIRED_COLUMNS = {
    SUBMISSION_MEMBER: ("ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE",
                        "ISSUERTRADINGSYMBOL"),
    OWNER_MEMBER: ("ACCESSION_NUMBER", "RPTOWNERNAME"),
    TRANS_MEMBER: ("ACCESSION_NUMBER", "TRANS_CODE", "TRANS_ACQUIRED_DISP_CD", "TRANS_DATE",
                   "TRANS_SHARES", "TRANS_PRICEPERSHARE"),
}

DEFAULT_WINDOW_TRADING_DAYS = 10

_QUARTER_RE = re.compile(r"^(\d{4})q([1-4])$")
# One resolvable ticker: letters/digits plus the dot/dash share-class separators. Rejects
# every real 2024q1 junk value (see the layout block above).
_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,9}$")
_SYMBOL_PLACEHOLDERS = frozenset({"", "-", "--", "NONE"})
# Venue tags, not share classes: same firm, same ticker root (see the rules block).
_OTC_SUFFIXES = (".OB", ".PK")

# Locale-independent (strptime's %b follows LC_TIME) and ~3x faster on millions of rows.
_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

_BUY_TRANSACTION_CODE = "P"
_ACQUIRED_CODE = "A"
_FORM4_DOCUMENT_TYPE = "4"

# Coarse bands (the study conditions on the band, not on the exact dollar amount — same
# granularity as congress' disclosed `amount_range_label`).
_VALUE_BANDS = ((100_000.0, "<$100k"), (1_000_000.0, "$100k-$1M"), (10_000_000.0, "$1M-$10M"))
_VALUE_BAND_TOP = ">$10M"
_VALUE_BAND_UNKNOWN = "unbekannt"

# Partition buckets: rows == sum of all of these except "rows" itself.
_COUNT_KEYS = (
    "rows", "kept", "not_purchase", "no_submission", "not_form4", "no_symbol", "no_owner",
    "bad_date", "discarded_pit",
)
# Overlay counters: subsets of "kept", deliberately OUTSIDE the partition sum.
_OVERLAY_COUNT_KEYS = ("bad_shares",)


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
    """DD-MON-YYYY -> ISO, or None for anything the SEC ships malformed.

    Explicit month map rather than `strptime("%d-%b-%Y")`: `%b` resolves through LC_TIME,
    so the same ZIP would parse on one machine and silently fail on another with a
    non-English locale — turning every row into `bad_date`.
    """
    parts = (value or "").strip().upper().split("-")
    if len(parts) != 3:
        return None
    day, month, year = parts
    if month not in _MONTHS:
        return None
    try:
        return date(int(year), _MONTHS[month], int(day)).isoformat()
    except ValueError:  # impossible day ("31-FEB-2024"), non-numeric year/day
        return None


def _clean_symbol(value: str) -> str | None:
    symbol = (value or "").strip().upper()
    for suffix in _OTC_SUFFIXES:
        if symbol.endswith(suffix):
            symbol = symbol[: -len(suffix)]
            break
    if symbol in _SYMBOL_PLACEHOLDERS or not _SYMBOL_RE.match(symbol):
        return None
    return symbol


def _float_or_none(value: str) -> float | None:
    try:
        return float((value or "").strip())
    except ValueError:
        return None


def _value_band(total_value: float | None, *, complete: bool) -> str:
    """`complete` is False when any purchase in the cluster has no usable value — a
    partial sum must never masquerade as the cluster total."""
    if total_value is None or not complete:
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
    shares: float | None  # None when TRANS_SHARES is unparseable ("1,000", "abc")
    price: float | None  # None when the filing carries no price (27 of 5,954 P rows)
    value: float | None
    accession: str


def _tsv_rows(archive: zipfile.ZipFile, member: str):
    """Streaming DictReader over one ZIP member — the transaction table alone is ~12 MB
    per quarter, so it is never materialized as a list.

    `utf-8-sig` strips a BOM if one ever appears: with plain utf-8 the BOM would fuse onto
    the first header name, so ACCESSION_NUMBER would be keyed "﻿ACCESSION_NUMBER",
    every join would miss, and the run would report a cheerful zero. `QUOTE_NONE` because
    these are tab-separated dumps, not CSV: a single unbalanced `"` in a company name
    would otherwise make the reader swallow the rest of the member as one giant field.
    """
    with archive.open(member) as handle:
        reader = csv.DictReader(
            io.TextIOWrapper(handle, encoding="utf-8-sig", errors="replace", newline=""),
            delimiter="\t",
            quoting=csv.QUOTE_NONE,
        )
        missing = [
            column
            for column in _REQUIRED_COLUMNS[member]
            if column not in (reader.fieldnames or ())
        ]
        if missing:
            raise ValueError(f"{member} is missing joined column(s): {', '.join(missing)}")
        yield from reader


def purchases_from_quarter_zip(
    zip_bytes: bytes,
) -> tuple[list[InsiderPurchase], dict[str, int]]:
    """One quarter ZIP -> open-market insider purchases + per-bucket skip counters.

    Three-way join on ACCESSION_NUMBER (SUBMISSION x REPORTINGOWNER x NONDERIV_TRANS).
    Every NONDERIV_TRANS row is counted in `rows` and lands in exactly one PARTITION
    bucket, so `rows == sum(_COUNT_KEYS minus rows)` holds — the denominator the Task-7
    report needs. `bad_shares` is an OVERLAY on `kept`, not a bucket (see module rules).

    Raises ValueError when the ZIP is unreadable, a joined member is absent, or a joined
    COLUMN was renamed: those are broken downloads / schema drift, not row-level defects,
    and must never look like a quiet empty quarter. Corruption is only discovered
    mid-read (BadZipFile on a bad CRC, zlib.error on a flipped bit inside the DEFLATE
    stream, EOFError on a truncated one), so all of it is converted here — the caller
    must never see a raw decompression error crash a multi-hour backfill.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            return _purchases_from_archive(archive)
    except (zipfile.BadZipFile, csv.Error, zlib.error, EOFError) as err:
        # A rate-limit/error page is HTML, not a ZIP — say so, like form4.py:296.
        raise ValueError(f"Quartals-ZIP unlesbar (Rate-Limit-/Fehlerseite?): {err}") from err


def _purchases_from_archive(
    archive: zipfile.ZipFile,
) -> tuple[list[InsiderPurchase], dict[str, int]]:
    """The join itself; `purchases_from_quarter_zip` owns the corruption contract."""
    counts = dict.fromkeys(_COUNT_KEYS + _OVERLAY_COUNT_KEYS, 0)
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
        # An unparseable size does NOT void the fact: the insider, the ticker and both
        # dates are intact, and the cluster rule counts people, not dollars. The purchase
        # is kept with unknown size (value None, so it never fakes a $0 "priced" buy) and
        # flagged via the overlay counter.
        shares = _float_or_none(row.get("TRANS_SHARES", ""))
        if shares is None:
            counts["bad_shares"] += 1
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
                value=(shares * price) if (shares is not None and price is not None) else None,
                accession=accession,
            )
        )
    return purchases, counts


def _filing_lag_trading_days(purchase: InsiderPurchase) -> int:
    return int(np.busday_count(purchase.transaction_date, purchase.filing_date))


def _cluster_event(ticker: str, members: list[InsiderPurchase]) -> HistoricalEvent:
    insiders = sorted({purchase.insider for purchase in members})
    priced = [purchase.value for purchase in members if purchase.value is not None]
    complete = len(priced) == len(members)
    total_value = sum(priced) if priced else None
    known_shares = [p.shares for p in members if p.shares is not None]
    # T0 = the LAST filing of the cluster: only then was the FULL cluster knowable.
    t0 = max(purchase.filing_date for purchase in members)
    first_transaction_date = min(p.transaction_date for p in members)
    # Filing lag is a study DIMENSION, not a filter: a cluster disclosed 8 months late is
    # a different (and probably weaker) signal than one disclosed in 2 days, and Task 6
    # conditions on it. No cutoff is applied here — that would silently change the
    # population instead of letting the aggregation split it.
    lags = sorted(_filing_lag_trading_days(purchase) for purchase in members)
    return HistoricalEvent(
        source=SOURCE_INSIDER,
        person="",  # a cluster has no single person — names live in details (Decision 2)
        ticker=ticker,
        # `first_transaction_date` is part of the key because batch late-filings collide
        # without it: several disjoint clusters on one ticker can share both the last
        # filing date and the insider count (8 of 339 clusters lost on 2006q1), and
        # `record_historical_events`' INSERT OR IGNORE would drop the duplicates silently.
        event_key=f"{ticker}-{t0}-{first_transaction_date}-cluster{len(insiders)}",
        t0=t0,
        details={
            "insiders": insiders,
            "n_insiders": len(insiders),
            "n_purchases": len(members),
            "priced_purchases": len(priced),
            "total_shares": sum(known_shares) if len(known_shares) == len(members) else None,
            "total_value": total_value if complete else None,
            "value_band": _value_band(total_value, complete=complete),
            "first_transaction_date": first_transaction_date,
            "last_transaction_date": max(p.transaction_date for p in members),
            "first_filing_date": min(purchase.filing_date for purchase in members),
            "median_filing_lag_days": float(statistics.median(lags)),
            "max_filing_lag_days": lags[-1],
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


def count_boundary_candidates(
    purchases: list[InsiderPurchase],
    *,
    window_trading_days: int = DEFAULT_WINDOW_TRADING_DAYS,
    min_insiders: int = MIN_INSIDERS,
) -> int:
    """Tickers one insider short of a cluster in the file's trailing window.

    Quantifies the quarter-boundary ceiling (see the module docstring): clustering runs
    per quarter FILE, so a cluster whose filings straddle the boundary is invisible to
    both files. A ticker sitting at exactly `min_insiders - 1` distinct insiders in the
    last `window_trading_days` trading days of the file's transaction range is the
    population that a cross-file stitch could still promote — Task 7 reports it as the
    known undercount rather than as a footnote.

    Deliberately an ESTIMATE, not a correction: it neither adds events nor changes any
    key. The edge is measured from the file's latest transaction date, since the
    transaction range (not the filing range) is what the clustering window slides over.
    """
    if not purchases:
        return 0
    edge = max(purchase.transaction_date for purchase in purchases)
    trailing: dict[str, set[str]] = {}
    for purchase in purchases:
        if int(np.busday_count(purchase.transaction_date, edge)) <= window_trading_days:
            trailing.setdefault(purchase.ticker, set()).add(purchase.insider)
    return sum(1 for insiders in trailing.values() if len(insiders) == min_insiders - 1)


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
    `unconfigured` (nothing fetched, nothing written, never a fake), an unreachable
    download returns `fetch_failed`, and a non-ZIP / corrupt / schema-drifted one returns
    `parse_failed`. A structurally valid ZIP with ZERO transaction rows returns
    `empty_quarter` — no real quarter is empty, so that is a defect, not a success. The
    cursor advances ONLY on `ok`, so every other outcome is simply retried next run
    instead of silently skipping a quarter forever.

    `duplicate_key` counts clusters that still collide on the event_key after
    `first_transaction_date` was added to it — such a collision is dropped by
    `record_historical_events`' INSERT OR IGNORE, so it is counted here rather than
    vanishing into the events_new/events_seen difference.
    """
    counts: dict = {
        "quarter": quarter, "status": STATUS_OK, "detail": "", "url_fallback": 0,
        "clusters": 0, "duplicate_key": 0, "events_seen": 0, "events_new": 0,
        "boundary_candidates": 0,
        **dict.fromkeys(_COUNT_KEYS + _OVERLAY_COUNT_KEYS, 0),
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
    if row_counts["rows"] == 0:
        # A readable ZIP whose transaction table is empty is a broken publish, never a
        # real quarter — advancing past it would skip it permanently.
        counts["status"] = STATUS_EMPTY_QUARTER
        counts["detail"] = f"{TRANS_MEMBER} enthält 0 Zeilen — Quartal nicht übersprungen"
        return counts

    counts["boundary_candidates"] = count_boundary_candidates(purchases)
    events = cluster_events(purchases)
    counts["clusters"] = counts["events_seen"] = len(events)
    counts["duplicate_key"] = len(events) - len({(e.ticker, e.event_key) for e in events})
    counts["events_new"] = len(record_historical_events(db_path, events, now=now))
    set_state(db_path, key=HISTORY_FORM4_CURSOR_KEY, value=quarter)
    return counts
