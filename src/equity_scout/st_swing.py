"""Event-swing lane (vision v11, lane `swing`): bullish earnings events → 1–5 day holds.

Pure decision logic over the v7 event engine's output (`classified_events`): buy tickers
with a fresh bullish event (beat / guidance_up) at today's close, exit at +5 % / −3 % /
after ~5 trading days (7 calendar days — the nightly runner has no trading calendar, and
the difference is one weekend). The runner owns all I/O; everything here is testable with
canned events and prices.
"""
from __future__ import annotations

from datetime import date, datetime

import numpy as np

from equity_scout.shortterm_book import LaneBook

BULLISH_EVENTS = ("beat", "guidance_up")
ENTRY_FRACTION = 0.10
MAX_POSITIONS = 8
PROFIT_TARGET = 0.05
STOP_LOSS = 0.03
MAX_HOLDING_CALENDAR_DAYS = 7  # ≈ 5 trading days
MAX_EVENT_AGE_BUSDAYS = 3  # v12 R11: after an outage, week-old news is no longer an entry


def pick_entries(
    events: list[dict],
    book: LaneBook,
    *,
    now: datetime | None = None,
    max_positions: int = MAX_POSITIONS,
) -> list[dict]:
    """Entry candidates from bullish events: newest first, one per ticker, never a ticker
    already held, capped to the free position slots. Each result is {ticker, reason}.
    With `now` set, events older than MAX_EVENT_AGE_BUSDAYS trading days are skipped —
    a multi-day outage must not buy week-old news at today's price (v12 R11); the
    event reaction is long priced in by then."""
    free_slots = max(0, max_positions - len(book.positions))
    if free_slots == 0:
        # without this a full book still yielded one pick (the cap check below fires only
        # AFTER an append), letting the lane creep past max_positions run by run (v13 R7)
        return []
    picks: list[dict] = []
    seen: set[str] = set()
    ordered = sorted(events, key=lambda e: e.get("seen_at") or "", reverse=True)
    for event in ordered:
        ticker = (event.get("ticker") or "").upper()
        if not ticker or ticker in seen or ticker in book.positions:
            continue
        if event.get("event_type") not in BULLISH_EVENTS:
            continue
        if now is not None:
            seen_date = (event.get("seen_at") or "")[:10]
            today = now.date().isoformat()
            if not seen_date or int(np.busday_count(seen_date, today)) > MAX_EVENT_AGE_BUSDAYS:
                continue
        seen.add(ticker)
        picks.append({"ticker": ticker, "reason": f"event: {event['event_type']}"})
        if len(picks) >= free_slots:
            break
    return picks


def check_exits(
    book: LaneBook,
    prices: dict[str, float],
    today: str,
    *,
    profit_target: float = PROFIT_TARGET,
    stop_loss: float = STOP_LOSS,
    max_days: int = MAX_HOLDING_CALENDAR_DAYS,
) -> list[dict]:
    """Exit orders for the current book at today's closes. A position without a price is
    held untouched (cannot judge a rule without a price — same stance as the other books).
    Each result is {ticker, price, reason}."""
    exits: list[dict] = []
    for ticker, position in book.positions.items():
        price = prices.get(ticker)
        if not price or price <= 0 or position.entry_price <= 0:
            continue
        ret = price / position.entry_price - 1.0
        held_days = (date.fromisoformat(today) - date.fromisoformat(position.opened_at[:10])).days
        if ret >= profit_target:
            reason = f"Gewinnziel +{profit_target:.0%} erreicht ({ret:+.1%})"
        elif ret <= -stop_loss:
            reason = f"Stop -{stop_loss:.0%} gerissen ({ret:+.1%})"
        elif held_days >= max_days:
            reason = f"Max-Haltedauer ({held_days} Tage)"
        else:
            continue
        exits.append({"ticker": ticker, "price": price, "reason": reason})
    return exits
