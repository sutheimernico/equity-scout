"""SEC EDGAR Form 4 collector: corporate-insider OPEN-MARKET purchases.

Same free + official source as the 13F collector (data.sec.gov / www.sec.gov Archives)
and the same SEC Fair Access contract: a User-Agent with contact info is REQUIRED, read
from env `EDGAR_USER_AGENT` via edgar.resolve_user_agent — without it this collector
reports itself `unconfigured`, exactly like 13F, and the chain continues.

Scope is the current watchlist/radar tickers, not the full ~1200-stock universe: unlike
13F (fund-centric, needs the whole universe for name matching), Form 4 is a per-ISSUER
lookup (ticker -> CIK -> that company's own filings), so a full-universe sweep would mean
one submissions-API call per stock every run. The watchlist is small and is exactly
what the copilot is actively looking at — same "actively tracked only" scope the
news-theme collector already uses.

Only NON-DERIVATIVE transactions with transactionCode "P" (open-market purchase) AND
acquiredDisposedCode "A" (acquired) become evidence — sales, grants, gifts and option
exercises are a different signal and are excluded, mirroring the congress/13F "only buys
are evidence" rule. T0 = the FILING date (timestamp_known), never the transaction date
(timestamp_event): Form 4 has a legal 2-BUSINESS-DAY filing deadline, the fastest of the
four sources, but "fast" is still not "before" — the point-in-time invariant
(timestamp_known >= timestamp_event) is enforced per transaction; a violation (bad/
misparsed data) drops the event with a stderr log rather than silently misdating it.
"""
from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from lxml import etree

from equity_scout.evidence.base import (
    SOURCE_INSIDER,
    STATUS_FETCH_FAILED,
    STATUS_OK,
    STATUS_UNCONFIGURED,
    CollectorResult,
    EvidenceEvent,
)
from equity_scout.evidence.edgar import resolve_user_agent

# New information is the FILING (public disclosure), not the trade itself — same
# bounding rule as congress.py, applied to both the submissions-API scan AND the PIT
# check below.
DEFAULT_MAX_FILING_AGE_DAYS = 30

_TICKER_CIK_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_ARCHIVE_BASE = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}"

# Open-market purchase only: code "P" (buy) AND acquired-code "A" — everything else
# (sales "S", grants/awards "A"-code-but-non-"P", gifts "G", option exercises "M") is a
# different signal, same exclusion rule as congress.py/edgar.py's "only buys are evidence".
_BUY_TRANSACTION_CODE = "P"
_ACQUIRED_CODE = "A"


_REQUEST_PAUSE_S = 0.15  # SEC fair-access guideline is 10 req/s — stay well under it.


def _http_get_with_agent(user_agent: str) -> Callable[[str], str]:
    def get(url: str) -> str:
        import time

        import httpx

        time.sleep(_REQUEST_PAUSE_S)
        response = httpx.get(
            url, timeout=30.0, follow_redirects=True, headers={"User-Agent": user_agent}
        )
        response.raise_for_status()
        return response.text

    return get


def _archive_url(cik: str, accession: str, filename: str) -> str:
    return (
        _ARCHIVE_BASE.format(cik_int=int(cik), accession_nodash=accession.replace("-", ""))
        + f"/{filename}"
    )


def fetch_ticker_cik_map(http_get: Callable[[str], str]) -> dict[str, str]:
    """SEC's own ticker -> CIK index (company_tickers.json), fetched once per run.

    Zero-padded to 10 digits to match the submissions API's CIK path segment. Share
    classes (BRK.B-style) may not resolve via this direct uppercase match — an honest
    gap (counted as unmapped upstream), never a guess, same philosophy as edgar.py's
    name matcher.
    """
    payload = json.loads(http_get(_TICKER_CIK_URL))
    return {
        str(row["ticker"]).upper(): f"{int(row['cik_str']):010d}" for row in payload.values()
    }


def recent_form4_metas(
    cik: str, http_get: Callable[[str], str], *, now: str, max_filing_age_days: int
) -> list[dict]:
    """Recent Form 4 filings for one issuer CIK, bounded to the filing window — the
    same submissions API the 13F collector uses (recent_13f_metas), filtered to form "4".
    """
    data = json.loads(http_get(_SUBMISSIONS_URL.format(cik=cik)))
    recent = data.get("filings", {}).get("recent", {})
    cutoff = datetime.fromisoformat(now).replace(tzinfo=None) - timedelta(
        days=max_filing_age_days
    )
    metas = []
    for form, accession, filing_date, primary_doc in zip(
        recent.get("form", []),
        recent.get("accessionNumber", []),
        recent.get("filingDate", []),
        recent.get("primaryDocument", []),
        strict=False,
    ):
        if form != "4":
            continue
        if datetime.fromisoformat(filing_date) < cutoff:
            continue
        metas.append(
            {"accession": accession, "filed_at": filing_date, "primary_document": primary_doc}
        )
    return metas


@dataclass(frozen=True)
class InsiderTransaction:
    transaction_date: str
    shares: float
    price: float | None  # None when the filing carries no price (rare for code P)
    value: float | None  # shares * price, aggregated across same-day lots


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else tag


def _child(parent, name: str):
    for el in parent:
        if _local(el.tag) == name:
            return el
    return None


def _text_of(parent, name: str) -> str | None:
    """Leaf text, tolerant of the schema's ubiquitous footnote-carrying
    `<name><value>X</value><footnoteId .../></name>` wrapper as well as plain
    `<name>X</name>` leaves (relationship flags, issuer/owner identity)."""
    if parent is None:
        return None
    child = _child(parent, name)
    if child is None:
        return None
    value_el = _child(child, "value")
    text = value_el.text if value_el is not None else child.text
    return text.strip() if text else None


def _role_label(relationship) -> str:
    is_director = _text_of(relationship, "isDirector") == "1"
    is_officer = _text_of(relationship, "isOfficer") == "1"
    is_ten_pct = _text_of(relationship, "isTenPercentOwner") == "1"
    officer_title = _text_of(relationship, "officerTitle")
    parts = []
    if is_officer:
        parts.append(f"officer ({officer_title})" if officer_title else "officer")
    if is_director:
        parts.append("director")
    if is_ten_pct:
        parts.append("10% owner")
    return ", ".join(parts) if parts else "insider"


def parse_form4(xml_text: str) -> tuple[str, str, list[InsiderTransaction]]:
    """One filing's (insider name, role, open-market-buy transactions).

    Only the FIRST reportingOwner block is read (joint filings with several reporting
    owners are rare and would need a second person dimension the ledger does not model
    yet). Only nonDerivativeTable rows with code P + acquired A become transactions — a
    filing with none (an option grant, a sale, a gift) returns an empty list, not an
    error. Several same-day lots in one filing collapse into one transaction (shares
    summed, value summed), the same collapse rule as congress.py's same-filer-same-day.
    """
    root = etree.fromstring(xml_text.encode("utf-8"))
    if _local(root.tag) != "ownershipDocument":
        raise ValueError(f"not a Form 4 ownership document: root tag {root.tag!r}")

    reporting_owner = _child(root, "reportingOwner")
    if reporting_owner is None:
        raise ValueError("no reportingOwner in Form 4 document")
    owner_id = _child(reporting_owner, "reportingOwnerId")
    insider = _text_of(owner_id, "rptOwnerName") or "unbekannt"
    role = _role_label(_child(reporting_owner, "reportingOwnerRelationship"))

    by_date: dict[str, dict] = {}
    table = _child(root, "nonDerivativeTable")
    if table is not None:
        for tx in table:
            if _local(tx.tag) != "nonDerivativeTransaction":
                continue
            coding = _child(tx, "transactionCoding")
            code = _text_of(coding, "transactionCode")
            amounts = _child(tx, "transactionAmounts")
            acquired_disposed = _text_of(amounts, "transactionAcquiredDisposedCode")
            if code != _BUY_TRANSACTION_CODE or acquired_disposed != _ACQUIRED_CODE:
                continue
            date = _text_of(tx, "transactionDate")
            if date is None or amounts is None:
                continue
            shares_text = _text_of(amounts, "transactionShares")
            price_text = _text_of(amounts, "transactionPricePerShare")
            shares = float(shares_text) if shares_text else 0.0
            price = float(price_text) if price_text else None
            slot = by_date.setdefault(date, {"shares": 0.0, "value": 0.0, "has_price": False})
            slot["shares"] += shares
            if price is not None:
                slot["value"] += shares * price
                slot["has_price"] = True

    transactions = [
        InsiderTransaction(
            transaction_date=date,
            shares=slot["shares"],
            price=(slot["value"] / slot["shares"]) if slot["has_price"] and slot["shares"] else None,
            value=slot["value"] if slot["has_price"] else None,
        )
        for date, slot in by_date.items()
    ]
    return insider, role, transactions


def collect_form4(
    *,
    now: str,
    env: dict | None = None,
    watchlist_tickers: list[str],
    http_get: Callable[[str], str] | None = None,
    max_filing_age_days: int = DEFAULT_MAX_FILING_AGE_DAYS,
) -> CollectorResult:
    """Open-market insider buys for the current watchlist tickers, degrading like 13F.

    Per-ticker failures (no CIK match, one submissions/filing fetch error) are counted
    and reported but never kill the sweep; only a complete wipe-out of every ticker we
    COULD map to a CIK degrades the whole source to fetch_failed.
    """
    env = env if env is not None else dict(os.environ)
    if http_get is None:
        user_agent = resolve_user_agent(env)
        if user_agent is None:
            return CollectorResult(
                SOURCE_INSIDER,
                STATUS_UNCONFIGURED,
                detail="EDGAR_USER_AGENT fehlt in .env — SEC verlangt Kontakt im User-Agent",
            )
        http_get = _http_get_with_agent(user_agent)

    if not watchlist_tickers:
        return CollectorResult(SOURCE_INSIDER, STATUS_OK, detail="keine Watchlist — nichts zu prüfen")

    try:
        cik_map = fetch_ticker_cik_map(http_get)
    except Exception as err:  # noqa: BLE001 — every transport/JSON failure becomes a status
        return CollectorResult(
            SOURCE_INSIDER, STATUS_FETCH_FAILED, detail=f"Ticker-CIK-Mapping fehlgeschlagen: {err}"
        )

    events: list[EvidenceEvent] = []
    unmapped: list[str] = []
    ticker_errors: list[str] = []
    attempted = 0
    tickers_ok = 0
    discarded_pit = 0
    non_us = 0
    for ticker in watchlist_tickers:
        if "." in ticker:  # exchange-suffixed non-US listing — SEC can never map it
            non_us += 1
            continue
        cik = cik_map.get(ticker.upper())
        if cik is None:
            # unmapped now means "US ticker that SHOULD map" — a real CIK gap.
            unmapped.append(ticker)
            continue
        attempted += 1
        try:
            metas = recent_form4_metas(
                cik, http_get, now=now, max_filing_age_days=max_filing_age_days
            )
            for meta in metas:
                xml_text = http_get(_archive_url(cik, meta["accession"], meta["primary_document"]))
                if not xml_text.lstrip().startswith("<?xml"):
                    # A rate-limit/error page is HTML — say so instead of letting the
                    # XML parser produce a cryptic "tag mismatch" in ticker_errors.
                    raise ValueError("SEC lieferte kein XML (Rate-Limit-/Fehlerseite?)")
                insider, role, transactions = parse_form4(xml_text)
                for tx in transactions:
                    if datetime.fromisoformat(meta["filed_at"]) < datetime.fromisoformat(
                        tx.transaction_date
                    ):
                        discarded_pit += 1
                        print(
                            f"insider evidence: verworfen (PIT-Verstoß) {ticker} "
                            f"{meta['accession']} — Filing {meta['filed_at']} liegt vor "
                            f"Transaktion {tx.transaction_date}",
                            file=sys.stderr,
                        )
                        continue
                    events.append(
                        EvidenceEvent(
                            source=SOURCE_INSIDER,
                            ticker=ticker.upper(),
                            event_key=f"{meta['accession']}-{tx.transaction_date}",
                            event_date=meta["filed_at"],
                            details={
                                "insider": insider,
                                "role": role,
                                "transaction_date": tx.transaction_date,
                                "filing_date": meta["filed_at"],
                                "shares": tx.shares,
                                "price": tx.price,
                                "value": tx.value,
                            },
                        )
                    )
        except Exception as err:  # noqa: BLE001 — degrade per ticker, never crash the sweep
            ticker_errors.append(f"{ticker}: {err}")
            continue
        tickers_ok += 1

    if attempted > 0 and tickers_ok == 0:
        return CollectorResult(
            SOURCE_INSIDER, STATUS_FETCH_FAILED, detail="; ".join(ticker_errors) or "no tickers"
        )

    detail = (
        f"{tickers_ok}/{len(watchlist_tickers)} Ticker geprüft -> {len(events)} Ereignisse; "
        f"{len(unmapped)} ohne CIK-Mapping; {non_us} nicht-US übersprungen; "
        f"{discarded_pit} PIT-Verstöße verworfen"
    )
    if ticker_errors:
        detail += f"; Fehler: {'; '.join(ticker_errors)}"
    return CollectorResult(SOURCE_INSIDER, STATUS_OK, events=events, detail=detail)
