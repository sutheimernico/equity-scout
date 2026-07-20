"""SEC EDGAR 8-K collector: near-realtime public disclosures (earnings, material events).

Same free + official source (data.sec.gov submissions API) and the same SEC Fair
Access UA contract as 13F/Form4: EDGAR_USER_AGENT must be set via env, read through
edgar.resolve_user_agent — without it this collector reports itself `unconfigured`,
exactly like the other two, and the chain continues.

Ticker -> CIK reuses form4.fetch_ticker_cik_map (SEC's own company_tickers.json) — the
same honest-gap philosophy: a ticker without a CIK match is counted, never guessed.

Only items 2.02 (Results of Operations), 7.01 (Reg FD Disclosure) and 8.01 (Other
Events) become evidence — the near-realtime, market-moving items; the many purely
administrative 8-K items (5.02 exec changes, 5.03 charter amendments, 5.07 vote
results, ...) are noise for this stream. Live-checked against a real submissions
payload (2026-07-16): the "recent" filings array already carries each filing's
`items` (comma-separated item codes) AND its `acceptanceDateTime` (precise UTC
timestamp), so — unlike the 13F/Form4 collectors — no fetch/parse of the actual
filing document is needed at all: fewer moving parts, no new HTML/XML format to
trust. event_date is the filing date (T0 for every other EDGAR collector here); the
finer acceptanceDateTime is preserved verbatim in details["published_at"] for later
latency work (Strang B3/B4) — this collector does not itself measure or classify
latency.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime, timedelta

from equity_scout.evidence.base import (
    SOURCE_8K,
    STATUS_FETCH_FAILED,
    STATUS_OK,
    STATUS_UNCONFIGURED,
    CollectorResult,
    EvidenceEvent,
)
from equity_scout.evidence.edgar import resolve_user_agent
from equity_scout.evidence.form4 import fetch_ticker_cik_map

# New information is the FILING (public disclosure), same bounding rule as
# congress.py/form4.py. 8-K's legal deadline is 4 business days after the triggering
# event; this window only bounds how far back "current" reaches in the submissions
# API's "recent" list, not a freshness claim — same default as form4.py for
# consistency (no reason to pick a different number without evidence either needs it).
DEFAULT_MAX_FILING_AGE_DAYS = 30

_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

TRACKED_ITEMS = {"2.02", "7.01", "8.01"}


def _http_get_with_agent(user_agent: str) -> Callable[[str], str]:
    def get(url: str) -> str:
        import httpx

        response = httpx.get(
            url, timeout=30.0, follow_redirects=True, headers={"User-Agent": user_agent}
        )
        response.raise_for_status()
        return response.text

    return get


def recent_8k_metas(
    cik: str, http_get: Callable[[str], str], *, now: str, max_filing_age_days: int
) -> list[dict]:
    """Recent 8-K filings for one issuer CIK that carry >=1 tracked item, bounded to
    the filing window — same submissions API + cutoff pattern as recent_form4_metas,
    filtered to form "8-K" AND a tracked item instead of form "4"."""
    data = json.loads(http_get(_SUBMISSIONS_URL.format(cik=cik)))
    recent = data.get("filings", {}).get("recent", {})
    cutoff = datetime.fromisoformat(now).replace(tzinfo=None) - timedelta(
        days=max_filing_age_days
    )
    metas = []
    for form, accession, filing_date, items, accepted in zip(
        recent.get("form", []),
        recent.get("accessionNumber", []),
        recent.get("filingDate", []),
        recent.get("items", []),
        recent.get("acceptanceDateTime", []),
        strict=False,
    ):
        if form != "8-K":
            continue
        if datetime.fromisoformat(filing_date) < cutoff:
            continue
        tracked = [i for i in (items or "").split(",") if i.strip() in TRACKED_ITEMS]
        if not tracked:
            continue
        metas.append(
            {"accession": accession, "filed_at": filing_date, "items": tracked, "accepted_at": accepted}
        )
    return metas


def collect_8k(
    *,
    now: str,
    env: dict | None = None,
    tickers: list[str],
    http_get: Callable[[str], str] | None = None,
    max_filing_age_days: int = DEFAULT_MAX_FILING_AGE_DAYS,
) -> CollectorResult:
    """8-K filings (items 2.02/7.01/8.01) for the tracked tickers, degrading like Form4.

    Per-ticker failures (no CIK match, one submissions fetch error) are counted and
    reported but never kill the sweep; only a complete wipe-out of every ticker we
    COULD map to a CIK degrades the whole source to fetch_failed.
    """
    env = env if env is not None else dict(os.environ)
    if http_get is None:
        user_agent = resolve_user_agent(env)
        if user_agent is None:
            return CollectorResult(
                SOURCE_8K,
                STATUS_UNCONFIGURED,
                detail="EDGAR_USER_AGENT fehlt in .env — SEC verlangt Kontakt im User-Agent",
            )
        http_get = _http_get_with_agent(user_agent)

    if not tickers:
        return CollectorResult(SOURCE_8K, STATUS_OK, detail="keine Ticker — nichts zu prüfen")

    try:
        cik_map = fetch_ticker_cik_map(http_get)
    except Exception as err:  # noqa: BLE001 — every transport/JSON failure becomes a status
        return CollectorResult(
            SOURCE_8K, STATUS_FETCH_FAILED, detail=f"Ticker-CIK-Mapping fehlgeschlagen: {err}"
        )

    events: list[EvidenceEvent] = []
    unmapped: list[str] = []
    ticker_errors: list[str] = []
    attempted = 0
    tickers_ok = 0
    non_us = 0
    for ticker in tickers:
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
            metas = recent_8k_metas(
                cik, http_get, now=now, max_filing_age_days=max_filing_age_days
            )
            for meta in metas:
                events.append(
                    EvidenceEvent(
                        source=SOURCE_8K,
                        ticker=ticker.upper(),
                        event_key=meta["accession"],
                        event_date=meta["filed_at"],
                        details={
                            "items": meta["items"],
                            "filing_date": meta["filed_at"],
                            "published_at": meta["accepted_at"],
                        },
                    )
                )
        except Exception as err:  # noqa: BLE001 — degrade per ticker, never crash the sweep
            ticker_errors.append(f"{ticker}: {err}")
            continue
        tickers_ok += 1

    if attempted > 0 and tickers_ok == 0:
        return CollectorResult(
            SOURCE_8K, STATUS_FETCH_FAILED, detail="; ".join(ticker_errors) or "no tickers"
        )

    detail = (
        f"{tickers_ok}/{len(tickers)} Ticker geprüft -> {len(events)} Ereignisse; "
        f"{len(unmapped)} ohne CIK-Mapping; {non_us} nicht-US übersprungen"
    )
    if ticker_errors:
        detail += f"; Fehler: {'; '.join(ticker_errors)}"
    return CollectorResult(SOURCE_8K, STATUS_OK, events=events, detail=detail)
