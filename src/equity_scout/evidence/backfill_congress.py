"""Congress purchase backfill from kadoa's per-filer JSONs (House Clerk since ~2012,
Senate eFD/OGE similar) into `historical_events` (P2a).

Same mirror as evidence/congress.py's live feed (kadoa-org/congress-trading-monitor)
but the per-filer endpoint (`FILER_URL_TEMPLATE`), not the capped ~2-month `trades.json`
(`TRADES_URL`) — one filer's file holds their FULL disclosed history. Keep-rules mirror
`person_track.calls_from_filer_payload` (purchases only, stock-like assets, resolvable
ticker) but WITHOUT its filing-age bound: backfill wants the history, not just what is
recent. Event identity mirrors congress.py's live collapse rule (`congress.py:104`) so a
politician's same-day, same-ticker purchase collapses into one fact here too — except
the surviving T0 is the EARLIEST filing date across the collapsed rows, never whichever
row happened to land first in mirror-refresh order (a later-filed duplicate must not
push a fact's public date later than it really was).

Seeding: the correct filer list for a 2012-> backfill is the mirror's FULL filer index
(`FILERS_URL`, 440 filers as of 2026-08-06), not the capped `trades.json` (only ~95
filers active in the last ~2 months) — seeding from trades.json alone would
survivorship-bias the study toward currently-active traders. `backfill_congress` seeds
from the index and only falls back to trades.json if the index itself is unreachable
(counted via `index_fallback`, never silent).

Rows/payloads can be malformed (non-dict rows, non-string type fields from a dirty
mirror refresh) — every row is defensively coerced/guarded so one bad row is counted
and skipped rather than raising out of a multi-hundred-filer run (a crash mid-run would
otherwise re-hit the exact same poisoned row on every retry). A filer's history file may
also be missing or briefly broken; `fetch_filer_history` already degrades any such
failure to `None`, counted here as `filers_failed`.
"""
from __future__ import annotations

import json
from collections.abc import Callable

from equity_scout.evidence.base import SOURCE_CONGRESS
from equity_scout.evidence.congress import TRADES_URL, _http_get_default, fetch_filer_history
from equity_scout.evidence.historical_storage import HistoricalEvent, record_historical_events

FILERS_URL = (
    "https://raw.githubusercontent.com/kadoa-org/congress-trading-monitor"
    "/main/public/data/filers.json"
)

# Skip counters aggregated into backfill_congress's return value -- every one of these
# indicates something worth watching across a multi-hundred-filer run, unlike the far
# more common (and harmless) "not_purchase" (sales, the majority of any filer's history).
_AGGREGATE_SKIP_KEYS = ("no_ticker", "not_stock", "no_date", "malformed", "duplicate")


def _distinct_ids(rows: list, id_key: str) -> list[str]:
    """First-seen-order distinct ids, tolerating non-dict rows in a dirty payload."""
    ids: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = row.get(id_key)
        if value and value not in seen:
            seen.add(value)
            ids.append(value)
    return ids


def filer_ids_from_trades(trades_json_text: str) -> list[str]:
    """Distinct filer ids from a trades.json payload, in first-seen order.

    Fallback seed list only (see FILERS_URL/filer_ids_from_index for the primary,
    survivorship-free seed): every filer_id in trades.json is a real, active filer, but
    trades.json itself is capped at ~2 months of recent activity.
    """
    rows = json.loads(trades_json_text)
    if not isinstance(rows, list):
        raise ValueError("expected a JSON list of trades")
    return _distinct_ids(rows, "filer_id")


def filer_ids_from_index(filers_json_text: str) -> list[str]:
    """Distinct filer ids from the mirror's full filer index (`FILERS_URL`).

    The correct seed for a 2012-> backfill: 440 filers as of 2026-08-06, vs. only the
    ~95 active in the capped trades.json.
    """
    rows = json.loads(filers_json_text)
    if not isinstance(rows, list):
        raise ValueError("expected a JSON list of filers")
    return _distinct_ids(rows, "id")


def events_from_filer_payload(
    payload: dict, *, person: str, filer_id: str | None = None
) -> tuple[list[HistoricalEvent], dict]:
    """kadoa per-filer JSON -> full purchase history as HistoricalEvents + skip counters.

    Same keep-rules as `person_track.calls_from_filer_payload` (purchases only,
    stock-like assets, resolvable ticker) minus its filing-age bound. T0 is the filing
    date (falling back to the notification date, same as person_track) -- the day the
    trade became publicly knowable, never the trade day itself. Rows collapsing onto the
    same (ticker, event_key) keep the EARLIEST t0 among them, regardless of payload
    order. `filer_id` should be the caller's authoritative id (from the URL that fetched
    this very payload) whenever known -- the per-row `filer_id` fallback exists only for
    standalone calls, and must never be trusted to disambiguate BETWEEN filers (two
    different filers' rows missing filer_id would otherwise collide on the same
    "unknown-..." event_key).
    """
    filer_obj = payload.get("filer") or {}
    # Executive-branch filers (e.g. the President) have chamber=null but branch set --
    # live-verified 2026-08-06 on oge_donald_trump.
    chamber = filer_obj.get("chamber") or filer_obj.get("branch")
    party = filer_obj.get("party")
    state = filer_obj.get("state")

    counters = {"rows": 0, "kept": 0, "not_purchase": 0, "not_stock": 0, "no_ticker": 0,
                "no_date": 0, "malformed": 0, "duplicate": 0}
    groups: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []
    for row in payload.get("trades") or []:
        counters["rows"] += 1
        if not isinstance(row, dict):
            counters["malformed"] += 1
            continue
        transaction_type = str(row.get("transaction_type") or "").lower()
        if "purchase" not in transaction_type:
            counters["not_purchase"] += 1
            continue
        asset_type = str(row.get("asset_type") or "").lower()
        # kadoa filer files use the raw House/Senate codes ("ST") next to prose labels.
        if asset_type and asset_type != "st" and ("stock" not in asset_type or "option" in asset_type):
            counters["not_stock"] += 1
            continue
        ticker = row.get("ticker")
        if not ticker:
            counters["no_ticker"] += 1
            continue
        ticker = str(ticker).upper()
        t0 = row.get("filing_date") or row.get("notification_date")
        if not t0:
            counters["no_date"] += 1
            continue
        t0 = str(t0)
        row_filer_id = filer_id if filer_id is not None else str(row.get("filer_id") or "unknown")
        transaction_date = str(row.get("transaction_date") or "")
        event_key = f"{row_filer_id}-{transaction_date}-purchase"
        key = (ticker, event_key)
        if key in groups:
            counters["duplicate"] += 1
            if t0 < groups[key]["t0"]:
                groups[key]["t0"] = t0
            continue
        counters["kept"] += 1
        order.append(key)
        groups[key] = {
            "t0": t0,
            "ticker": ticker,
            "event_key": event_key,
            "details": {
                "filer_id": row_filer_id,
                "chamber": chamber,
                "committee": row.get("committee"),  # never seen populated; kept for shape
                "amount_range": row.get("amount_range_label"),
                "transaction_date": transaction_date,
                "party": party,
                "state": state,
            },
        }
    events = [
        HistoricalEvent(
            source=SOURCE_CONGRESS,
            person=person,
            ticker=groups[key]["ticker"],
            event_key=groups[key]["event_key"],
            t0=groups[key]["t0"],
            details=groups[key]["details"],
        )
        for key in order
    ]
    return events, counters


def backfill_congress(
    db_path: str,
    *,
    now: str,
    http_get: Callable[[str], str] | None = None,
    filer_ids: list[str] | None = None,
) -> dict:
    """Full purchase history per filer -> `historical_events`.

    `filer_ids` defaults to the mirror's FULL filer index (`FILERS_URL`) -- the
    survivorship-free seed for a 2012-> backfill; if the index itself can't be fetched,
    falls back to trades.json's ~95 currently-active filers (counted via
    `index_fallback`, never silent). Pass an explicit list to backfill or re-run a
    subset without refetching either seed list. A filer whose history file fails to
    fetch/parse (`fetch_filer_history` degrades any such failure to None) is still
    counted in `filers`/`filers_failed` but contributes no events -- the run continues
    with the next filer.
    """
    counts = {
        "filers": 0, "filers_failed": 0, "events_new": 0, "events_seen": 0,
        "index_fallback": 0,
        **{key: 0 for key in _AGGREGATE_SKIP_KEYS},
    }
    ids = filer_ids
    if ids is None:
        get = http_get if http_get is not None else _http_get_default
        try:
            ids = filer_ids_from_index(get(FILERS_URL))
        except Exception:  # noqa: BLE001 -- a dead/renamed index degrades to the fallback seed
            counts["index_fallback"] = 1
            ids = filer_ids_from_trades(get(TRADES_URL))
    for filer_id in ids:
        counts["filers"] += 1
        payload = fetch_filer_history(filer_id, http_get)
        if payload is None:
            counts["filers_failed"] += 1
            continue
        filer_obj = payload.get("filer") or {}
        person = filer_obj.get("full_name") or filer_id
        events, skip_counters = events_from_filer_payload(payload, person=person, filer_id=filer_id)
        counts["events_seen"] += len(events)
        counts["events_new"] += len(record_historical_events(db_path, events, now=now))
        for key in _AGGREGATE_SKIP_KEYS:
            counts[key] += skip_counters[key]
    return counts
