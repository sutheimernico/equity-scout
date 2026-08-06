"""Congress purchase backfill from kadoa's per-filer JSONs (House Clerk since ~2012,
Senate eFD/OGE similar) into `historical_events` (P2a).

Same mirror as evidence/congress.py's live feed (kadoa-org/congress-trading-monitor)
but the per-filer endpoint (`FILER_URL_TEMPLATE`), not the capped ~2-month `trades.json`
(`TRADES_URL`) — one filer's file holds their FULL disclosed history. Keep-rules mirror
`person_track.calls_from_filer_payload` (purchases only, stock-like assets, resolvable
ticker) but WITHOUT its filing-age bound: backfill wants the history, not just what is
recent. Event identity mirrors congress.py's live collapse rule (`congress.py:104`) so a
politician's same-day, same-ticker purchase collapses into one fact here too.

A filer's history file may be missing, renamed or briefly broken; `fetch_filer_history`
already degrades any such failure to `None`, so one dead file is counted and skipped,
never aborts a multi-hundred-filer run.
"""
from __future__ import annotations

import json
from collections.abc import Callable

from equity_scout.evidence.base import SOURCE_CONGRESS
from equity_scout.evidence.congress import TRADES_URL, _http_get_default, fetch_filer_history
from equity_scout.evidence.historical_storage import HistoricalEvent, record_historical_events


def filer_ids_from_trades(trades_json_text: str) -> list[str]:
    """Distinct filer ids from a trades.json payload, in first-seen order.

    Seeds the one-time backfill: trades.json is capped at ~2 months of recent activity,
    but every filer_id in it is a real, active filer worth pulling the full history for.
    """
    rows = json.loads(trades_json_text)
    ids: list[str] = []
    seen: set[str] = set()
    for row in rows:
        filer_id = row.get("filer_id")
        if filer_id and filer_id not in seen:
            seen.add(filer_id)
            ids.append(filer_id)
    return ids


def events_from_filer_payload(payload: dict, *, person: str) -> tuple[list[HistoricalEvent], dict]:
    """kadoa per-filer JSON -> full purchase history as HistoricalEvents + skip counters.

    Same keep-rules as `person_track.calls_from_filer_payload` (purchases only,
    stock-like assets, resolvable ticker) minus its filing-age bound. T0 is the filing
    date (falling back to the notification date, same as person_track) -- the day the
    trade became publicly knowable, never the trade day itself.
    """
    chamber = (payload.get("filer") or {}).get("chamber")
    counters = {"rows": 0, "kept": 0, "not_purchase": 0, "not_stock": 0, "no_ticker": 0,
                "no_date": 0}
    events: list[HistoricalEvent] = []
    seen: set[tuple[str, str]] = set()
    for row in payload.get("trades") or []:
        counters["rows"] += 1
        if "purchase" not in (row.get("transaction_type") or "").lower():
            counters["not_purchase"] += 1
            continue
        asset_type = (row.get("asset_type") or "").lower()
        # kadoa filer files use the raw House/Senate codes ("ST") next to prose labels.
        if asset_type and asset_type != "st" and ("stock" not in asset_type or "option" in asset_type):
            counters["not_stock"] += 1
            continue
        ticker = row.get("ticker")
        if not ticker:
            counters["no_ticker"] += 1
            continue
        t0 = row.get("filing_date") or row.get("notification_date")
        if not t0:
            counters["no_date"] += 1
            continue
        ticker = str(ticker).upper()
        filer_id = row.get("filer_id", "unknown")
        event_key = f"{filer_id}-{row.get('transaction_date', '')}-purchase"
        if (ticker, event_key) in seen:
            continue
        seen.add((ticker, event_key))
        counters["kept"] += 1
        events.append(
            HistoricalEvent(
                source=SOURCE_CONGRESS,
                person=person,
                ticker=ticker,
                event_key=event_key,
                t0=t0,
                details={
                    "filer_id": filer_id,
                    "chamber": chamber,
                    "committee": row.get("committee"),  # never seen populated; kept for shape
                    "amount_range": row.get("amount_range_label"),
                    "transaction_date": row.get("transaction_date"),
                },
            )
        )
    return events, counters


def backfill_congress(
    db_path: str,
    *,
    now: str,
    http_get: Callable[[str], str] | None = None,
    filer_ids: list[str] | None = None,
) -> dict:
    """Full purchase history per filer -> `historical_events`.

    `filer_ids` defaults to every distinct filer currently in trades.json (the seed list
    for the one-time backfill); pass an explicit list to backfill or re-run a subset
    without refetching trades.json. A filer whose history file fails to fetch/parse
    (`fetch_filer_history` degrades any such failure to None) is still counted in
    `filers` but contributes no events -- the run continues with the next filer.
    """
    ids = filer_ids
    if ids is None:
        get = http_get if http_get is not None else _http_get_default
        ids = filer_ids_from_trades(get(TRADES_URL))
    counts = {"filers": 0, "events_new": 0, "events_seen": 0}
    for filer_id in ids:
        counts["filers"] += 1
        payload = fetch_filer_history(filer_id, http_get)
        if payload is None:
            continue
        person = (payload.get("filer") or {}).get("full_name") or "unbekannt"
        events, _skip_counters = events_from_filer_payload(payload, person=person)
        counts["events_seen"] += len(events)
        counts["events_new"] += len(record_historical_events(db_path, events, now=now))
    return counts
