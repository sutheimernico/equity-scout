"""SEC EDGAR 13F collector: what did the tracked famous funds change last quarter?

Free + official (data.sec.gov / www.sec.gov Archives), but the SEC REQUIRES a
User-Agent with contact info — read from env `EDGAR_USER_AGENT`; without it this
collector reports itself `unconfigured` and the chain continues (never faked).

Stateless by design: per fund the latest TWO 13F-HR filings are fetched and diffed
(new positions + share increases >= 25%). Re-collecting the same quarter reproduces
the same event keys, which the evidence store's UNIQUE key turns into a no-op — so
there is no local filing cache to migrate or corrupt. Structural honesty note for
every surface: 13F filings arrive up to 45 days AFTER quarter end, so a "new"
position may be ~4.5 months old — context, never an early signal.

Info tables carry CUSIP + SEC-style issuer names, no tickers, and free CUSIP maps do
not exist. We match normalized issuer names against the universe's company names and
only accept UNAMBIGUOUS matches; everything else is counted and reported by name —
an honest gap, never a guess. Amendments (13F-HR/A) are skipped in v1.
"""
from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from equity_scout.evidence.base import (
    SOURCE_13F,
    STATUS_FETCH_FAILED,
    STATUS_OK,
    STATUS_UNCONFIGURED,
    CollectorResult,
    EvidenceEvent,
)

# name -> zero-padded CIK, verified against EDGAR company search 2026-07-07.
TRACKED_FUNDS: dict[str, str] = {
    "Berkshire Hathaway": "0001067983",
    "Scion Asset Management": "0001649339",
    "Pershing Square": "0001336528",
    "Appaloosa": "0001656456",
    "Duquesne Family Office": "0001536411",
    "Third Point": "0001040273",
    "Baupost Group": "0001061768",
    "Himalaya Capital": "0001709323",
}

MIN_INCREASE = 0.25  # share increases below this are treated as noise, not conviction
# A quarterly filing batch stays "current" until the next one lands (~3 months + the
# 45-day filing delay). Older diffs (e.g. a fund that stopped filing) are history, not
# evidence — they must never enter the ledger with a fresh created_at.
MAX_FILED_AGE_DAYS = 120

_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_ARCHIVE_BASE = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}"

# Trailing corporate boilerplate stripped before matching; leading "THE" too.
_SUFFIX_TOKENS = {
    "INC", "CORP", "CORPORATION", "CO", "COMPANY", "PLC", "LTD", "LIMITED", "SA",
    "AG", "NV", "SE", "HOLDINGS", "HOLDING", "GROUP", "CL", "CLASS", "A", "B", "C",
    "COM", "NEW", "DEL", "&",
}


@dataclass(frozen=True)
class Holding:
    issuer: str
    cusip: str
    shares: float
    value: float  # as reported by the filer (USD for current filings)


@dataclass(frozen=True)
class Filing13F:
    fund: str
    period: str  # reportDate (quarter end)
    filed_at: str  # filingDate — the day the information became public
    accession: str
    holdings: list[Holding]


def resolve_user_agent(env: dict) -> str | None:
    agent = env.get("EDGAR_USER_AGENT", "").strip()
    return agent or None


def _http_get_with_agent(user_agent: str) -> Callable[[str], str]:
    def get(url: str) -> str:
        import httpx

        response = httpx.get(
            url, timeout=30.0, follow_redirects=True, headers={"User-Agent": user_agent}
        )
        response.raise_for_status()
        return response.text

    return get


def recent_13f_metas(cik: str, http_get: Callable[[str], str], limit: int = 2) -> list[dict]:
    """The latest `limit` 13F-HR filings (newest first) from the submissions API."""
    data = json.loads(http_get(_SUBMISSIONS_URL.format(cik=cik)))
    recent = data.get("filings", {}).get("recent", {})
    metas = []
    for form, accession, report_date, filing_date in zip(
        recent.get("form", []),
        recent.get("accessionNumber", []),
        recent.get("reportDate", []),
        recent.get("filingDate", []),
        strict=False,
    ):
        if form == "13F-HR":
            metas.append(
                {"accession": accession, "period": report_date, "filed_at": filing_date}
            )
        if len(metas) == limit:
            break
    return metas


def _archive_url(cik: str, accession: str, filename: str) -> str:
    return (
        _ARCHIVE_BASE.format(cik_int=int(cik), accession_nodash=accession.replace("-", ""))
        + f"/{filename}"
    )


def parse_info_table(xml_text: str) -> list[Holding]:
    """Namespace-tolerant info-table parse. Skips derivative rows (putCall) and
    principal-amount rows (PRN) — only genuine share positions become evidence."""
    root = ET.fromstring(xml_text)

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    if local(root.tag) != "informationTable":
        raise ValueError(f"not an information table: root tag {root.tag!r}")
    holdings: list[Holding] = []
    for info in root:
        if local(info.tag) != "infoTable":
            continue
        fields = {local(child.tag): child for child in info}
        if "putCall" in fields and (fields["putCall"].text or "").strip():
            continue
        amount = fields.get("shrsOrPrnAmt")
        if amount is None:
            continue
        amount_fields = {local(child.tag): (child.text or "").strip() for child in amount}
        if amount_fields.get("sshPrnamtType", "SH") != "SH":
            continue

        def text_of(name: str, default: str = "") -> str:
            element = fields.get(name)
            return (element.text or default).strip() if element is not None else default

        holdings.append(
            Holding(
                issuer=text_of("nameOfIssuer"),
                cusip=text_of("cusip"),
                shares=float(amount_fields.get("sshPrnamt") or 0.0),
                value=float(text_of("value", "0").replace(",", "") or 0.0),
            )
        )
    return holdings


def fetch_filing(
    fund: str, cik: str, meta: dict, http_get: Callable[[str], str]
) -> Filing13F:
    """Walk index.json for the accession and parse whichever XML is the info table.

    The info-table filename is NOT fixed across filers, so every non-primary XML is
    tried until one parses as an informationTable.
    """
    index = json.loads(http_get(_archive_url(cik, meta["accession"], "index.json")))
    xml_names = [
        item["name"]
        for item in index.get("directory", {}).get("item", [])
        if item.get("name", "").lower().endswith(".xml")
        and item.get("name", "").lower() != "primary_doc.xml"
    ]
    last_error: Exception | None = None
    for name in xml_names:
        try:
            holdings = parse_info_table(http_get(_archive_url(cik, meta["accession"], name)))
        except ValueError as err:
            last_error = err
            continue
        return Filing13F(
            fund=fund,
            period=meta["period"],
            filed_at=meta["filed_at"],
            accession=meta["accession"],
            holdings=holdings,
        )
    raise ValueError(
        f"no information table found in {meta['accession']} ({last_error})"
    )


def diff_holdings(
    current: Filing13F, previous: Filing13F, *, min_increase: float = MIN_INCREASE
) -> list[dict]:
    """Quarter-over-quarter conviction changes: new positions + share increases.

    Aggregated per CUSIP (filers may split one issuer over several rows). Exits are
    deliberately NOT evidence — mirrors the congress rule that only buys signal.
    """
    def aggregate(filing: Filing13F) -> dict[str, dict]:
        by_cusip: dict[str, dict] = {}
        for holding in filing.holdings:
            slot = by_cusip.setdefault(
                holding.cusip, {"issuer": holding.issuer, "shares": 0.0, "value": 0.0}
            )
            slot["shares"] += holding.shares
            slot["value"] += holding.value
        return by_cusip

    now_by_cusip, before_by_cusip = aggregate(current), aggregate(previous)
    changes: list[dict] = []
    for cusip, slot in now_by_cusip.items():
        before = before_by_cusip.get(cusip)
        if before is None:
            changes.append({"cusip": cusip, "issuer": slot["issuer"], "change": "new",
                            "shares": slot["shares"], "value": slot["value"]})
        elif before["shares"] > 0 and slot["shares"] >= before["shares"] * (1 + min_increase):
            changes.append({"cusip": cusip, "issuer": slot["issuer"], "change": "increased",
                            "shares": slot["shares"], "value": slot["value"],
                            "shares_before": before["shares"]})
    return changes


def _normalize(name: str) -> str:
    tokens = [t for t in "".join(
        ch if ch.isalnum() else " " for ch in name.upper()
    ).split() if t]
    while tokens and tokens[-1] in _SUFFIX_TOKENS:
        tokens.pop()
    if tokens and tokens[0] == "THE":
        tokens.pop(0)
    return " ".join(tokens)


def build_name_matcher(instruments: list[tuple[str, str]]) -> Callable[[str], str | None]:
    """(ticker, company_name) list -> matcher(issuer_name) -> ticker | None.

    Exact normalized match wins; otherwise a prefix match in either direction is
    accepted only when exactly ONE universe candidate qualifies — ambiguity is an
    honest non-match, never a guess.
    """
    exact: dict[str, str] = {}
    normalized: list[tuple[str, str]] = []
    for ticker, name in instruments:
        norm = _normalize(name)
        if norm:
            exact.setdefault(norm, ticker)
            normalized.append((norm, ticker))

    def match(issuer: str) -> str | None:
        norm = _normalize(issuer)
        if not norm:
            return None
        if norm in exact:
            return exact[norm]
        candidates = {
            ticker
            for uni_norm, ticker in normalized
            if uni_norm.startswith(norm + " ") or norm.startswith(uni_norm + " ")
        }
        return candidates.pop() if len(candidates) == 1 else None

    return match


def collect_13f(
    *,
    now: str,
    env: dict | None = None,
    universe: list[tuple[str, str]],
    http_get: Callable[[str], str] | None = None,
    max_filed_age_days: int = MAX_FILED_AGE_DAYS,
) -> CollectorResult:
    """Diff the latest two 13F-HRs of every tracked fund into evidence events.

    One fund failing is counted and reported but never kills the others; only a
    complete wipe-out (every fund failed) degrades the whole source to fetch_failed.
    """
    env = env if env is not None else dict(os.environ)
    if http_get is None:
        user_agent = resolve_user_agent(env)
        if user_agent is None:
            return CollectorResult(
                SOURCE_13F,
                STATUS_UNCONFIGURED,
                detail="EDGAR_USER_AGENT fehlt in .env — SEC verlangt Kontakt im User-Agent",
            )
        http_get = _http_get_with_agent(user_agent)

    match = build_name_matcher(universe)
    cutoff = datetime.fromisoformat(now).replace(tzinfo=None) - timedelta(
        days=max_filed_age_days
    )
    events: list[EvidenceEvent] = []
    unmatched: list[str] = []
    fund_errors: list[str] = []
    funds_diffed = 0
    stale_funds = 0
    for fund, cik in TRACKED_FUNDS.items():
        try:
            metas = recent_13f_metas(cik, http_get)
            if len(metas) < 2:
                fund_errors.append(f"{fund}: fewer than two 13F-HR filings")
                continue
            if datetime.fromisoformat(metas[0]["filed_at"]) < cutoff:
                # A fund that stopped filing: its last diff is history, not news.
                stale_funds += 1
                continue
            current = fetch_filing(fund, cik, metas[0], http_get)
            previous = fetch_filing(fund, cik, metas[1], http_get)
        except Exception as err:  # noqa: BLE001 — degrade per fund, never crash the sweep
            fund_errors.append(f"{fund}: {err}")
            continue
        funds_diffed += 1
        # Share classes of one issuer (e.g. GOOGL A + C) are separate CUSIPs that match
        # the same ticker: collapse to one event; "increased" wins over "new" because the
        # fund already held the name — a second class is an extension, not a discovery.
        per_ticker: dict[str, dict] = {}
        for change in diff_holdings(current, previous):
            ticker = match(change["issuer"])
            if ticker is None:
                unmatched.append(f"{fund}: {change['issuer']}")
                continue
            known = per_ticker.get(ticker)
            if known is None or (known["change"] == "new" and change["change"] == "increased"):
                per_ticker[ticker] = change
        for ticker, change in per_ticker.items():
            events.append(
                EvidenceEvent(
                    source=SOURCE_13F,
                    ticker=ticker,
                    event_key=f"{cik}-{current.period}",
                    event_date=current.filed_at,
                    details={
                        "fund": fund,
                        "period": current.period,
                        "filed_at": current.filed_at,
                        "change": change["change"],
                        "shares": change["shares"],
                        "reported_value": change["value"],
                    },
                )
            )
    if funds_diffed == 0 and stale_funds == 0:
        return CollectorResult(
            SOURCE_13F, STATUS_FETCH_FAILED, detail="; ".join(fund_errors) or "no funds"
        )
    detail = (
        f"{funds_diffed}/{len(TRACKED_FUNDS)} funds diffed -> {len(events)} events; "
        f"{len(unmatched)} holdings unmatched to universe; {stale_funds} funds stale"
    )
    if fund_errors:
        detail += f"; errors: {'; '.join(fund_errors)}"
    return CollectorResult(SOURCE_13F, STATUS_OK, events=events, detail=detail)
