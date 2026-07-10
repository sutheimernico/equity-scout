"""US-congress trade collector (STOCK Act disclosures).

Source: the MIT-licensed kadoa-org/congress-trading-monitor mirror (House Clerk +
Senate eFD + OGE, refreshed daily; discovered + live-verified 2026-07-07) served as
static JSON via raw.githubusercontent.com — the official portals have no machine-
readable export. Only PURCHASES become evidence: a sale can mean rebalancing or
liquidity and is not a comparable signal. Structural honesty note carried to every
surface: members may file up to 45 days after trading — this is context, never an
early signal. §105(c) STOCK Act restricts commercial use of the underlying data;
fine for this private local tool, re-check before any publication.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime, timedelta

from equity_scout.evidence.base import (
    SOURCE_CONGRESS,
    STATUS_FETCH_FAILED,
    STATUS_OK,
    STATUS_PARSE_FAILED,
    CollectorResult,
    EvidenceEvent,
)

TRADES_URL = (
    "https://raw.githubusercontent.com/kadoa-org/congress-trading-monitor"
    "/main/public/data/trades.json"
)
# Per-filer FULL purchase history (trades.json is capped at 5000 rows ≈ 2 months —
# verified 2026-07-10); fetched per active filer only, for person track records.
FILER_URL_TEMPLATE = (
    "https://raw.githubusercontent.com/kadoa-org/congress-trading-monitor"
    "/main/public/data/filer/{filer_id}.json"
)
# New information is the FILING (public disclosure), not the trade itself — bound the
# collection window on filing_date so a first run cannot flood the ledger with history.
DEFAULT_MAX_FILING_AGE_DAYS = 30

# Trailing "(TICKER)" in asset_name, e.g. "Citigroup New Inc (C)" — the mirror leaves
# `ticker` null on many senate rows even when the name carries it.
_NAME_TICKER = re.compile(r"\(([A-Z][A-Z0-9.\-]{0,5})\)\s*$")


def _http_get_default(url: str) -> str:
    import httpx

    response = httpx.get(url, timeout=60.0, follow_redirects=True)
    response.raise_for_status()
    return response.text


def _resolve_ticker(row: dict) -> str | None:
    ticker = row.get("ticker")
    if ticker:
        return str(ticker).upper()
    match = _NAME_TICKER.search(row.get("asset_name") or "")
    return match.group(1) if match else None


def _is_recent(date_iso: str | None, now: str, max_age_days: int) -> bool:
    if not date_iso:
        return False
    filed = datetime.fromisoformat(date_iso).replace(tzinfo=None)
    cutoff = datetime.fromisoformat(now).replace(tzinfo=None) - timedelta(days=max_age_days)
    return filed >= cutoff


def parse_congress_trades(
    payload: str, *, now: str, max_filing_age_days: int = DEFAULT_MAX_FILING_AGE_DAYS
) -> tuple[list[EvidenceEvent], dict]:
    """Recent stock purchases as evidence events + honest counters for everything skipped.

    Kept: transaction_type containing "purchase", asset_type null/stock-like (options and
    other derivatives are a different signal and are excluded), filing_date inside the
    window, resolvable ticker. Event key collapses one filer's same-day purchases in one
    ticker into one fact — the alert-relevant unit is "a politician bought", not the row.
    """
    rows = json.loads(payload)
    if not isinstance(rows, list):
        raise ValueError("expected a JSON list of trades")
    events: list[EvidenceEvent] = []
    counters = {"rows": len(rows), "kept": 0, "no_ticker": 0, "not_purchase": 0,
                "not_stock": 0, "stale": 0}
    seen: set[tuple[str, str]] = set()
    for row in rows:
        transaction_type = (row.get("transaction_type") or "").lower()
        if "purchase" not in transaction_type:
            counters["not_purchase"] += 1
            continue
        asset_type = (row.get("asset_type") or "").lower()
        if asset_type and ("stock" not in asset_type or "option" in asset_type):
            counters["not_stock"] += 1
            continue
        if not _is_recent(row.get("filing_date"), now, max_filing_age_days):
            counters["stale"] += 1
            continue
        ticker = _resolve_ticker(row)
        if ticker is None:
            counters["no_ticker"] += 1
            continue
        event_key = f"{row.get('filer_id', 'unknown')}-{row.get('transaction_date', '')}-purchase"
        if (ticker, event_key) in seen:
            continue
        seen.add((ticker, event_key))
        counters["kept"] += 1
        events.append(
            EvidenceEvent(
                source=SOURCE_CONGRESS,
                ticker=ticker,
                event_key=event_key,
                event_date=row.get("filing_date") or row.get("transaction_date") or "",
                details={
                    "politician": row.get("filer_name"),
                    # keyed id of the mirror's per-filer history file (person scoring)
                    "filer_id": row.get("filer_id"),
                    "party": row.get("party"),
                    "chamber": row.get("chamber") or row.get("branch"),
                    "transaction_date": row.get("transaction_date"),
                    "filing_date": row.get("filing_date"),
                    "amount_range": row.get("amount_range_label"),
                    "days_to_file": row.get("days_to_file"),
                },
            )
        )
    return events, counters


def fetch_filer_history(
    filer_id: str, http_get: Callable[[str], str] | None = None
) -> dict | None:
    """One filer's full history payload from the mirror, or None (counted upstream) —
    a missing/renamed filer file must never break the scoring sweep."""
    get = http_get if http_get is not None else _http_get_default
    try:
        payload = json.loads(get(FILER_URL_TEMPLATE.format(filer_id=filer_id)))
    except Exception:  # noqa: BLE001 — transport/JSON failures degrade to None
        return None
    return payload if isinstance(payload, dict) else None


def fetch_congress_trades(
    *,
    now: str,
    http_get: Callable[[str], str] | None = None,
    max_filing_age_days: int = DEFAULT_MAX_FILING_AGE_DAYS,
) -> CollectorResult:
    """Fetch + parse behind one seam; any failure degrades to an explicit status."""
    get = http_get if http_get is not None else _http_get_default
    try:
        payload = get(TRADES_URL)
    except Exception as err:  # noqa: BLE001 — every transport failure becomes a status
        return CollectorResult(SOURCE_CONGRESS, STATUS_FETCH_FAILED, detail=str(err))
    try:
        events, counters = parse_congress_trades(
            payload, now=now, max_filing_age_days=max_filing_age_days
        )
    except (ValueError, KeyError, TypeError) as err:
        return CollectorResult(SOURCE_CONGRESS, STATUS_PARSE_FAILED, detail=str(err))
    detail = (
        f"{counters['rows']} rows -> {counters['kept']} purchases kept "
        f"({counters['no_ticker']} without ticker, {counters['stale']} outside "
        f"{max_filing_age_days}d filing window)"
    )
    return CollectorResult(SOURCE_CONGRESS, STATUS_OK, events=events, detail=detail)
