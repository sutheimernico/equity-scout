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


# 8-K types never carry a direction by design (event_classifier), so they are not a
# rejected opportunity — only these two are worth a row in the no-trade book.
_REJECTABLE_NON_BULLISH = ("unknown", "miss")


def pick_entries_explained(
    events: list[dict],
    book: LaneBook,
    *,
    now: datetime | None = None,
    max_positions: int = MAX_POSITIONS,
) -> tuple[list[dict], list[dict]]:
    """Entry candidates plus WHY the others fell out (the no-trade book, 2026-08-17).

    Picks: bullish events, newest first, one per ticker, never a ticker already held,
    capped to the free position slots — identical to the historical pick_entries.
    Rejections are pure data ({ticker, reason, seen_at, detail}); each keeps the EVENT's
    timestamp as its idempotency key and as the honest start of any later simulation.
    Not logged: empty tickers, same-run duplicates of a picked ticker, 8-K types.
    With `now` set, events older than MAX_EVENT_AGE_BUSDAYS trading days are rejected —
    a multi-day outage must not buy week-old news at today's price (v12 R11)."""
    free_slots = max(0, max_positions - len(book.positions))
    picks: list[dict] = []
    rejections: list[dict] = []
    seen: set[str] = set()
    ordered = sorted(events, key=lambda e: e.get("seen_at") or "", reverse=True)
    for event in ordered:
        ticker = (event.get("ticker") or "").upper()
        seen_at = event.get("seen_at") or ""
        event_type = event.get("event_type")
        if not ticker or ticker in seen:
            continue

        def _reject(reason: str, detail: str) -> None:
            rejections.append(
                {"ticker": ticker, "reason": reason, "seen_at": seen_at, "detail": detail}
            )

        if event_type not in BULLISH_EVENTS:
            if event_type in _REJECTABLE_NON_BULLISH:
                raw = str(event.get("detail") or "")[:120]
                _reject("not_bullish", f"{event_type} — {raw}" if raw else str(event_type))
            continue
        if now is not None:
            seen_date = seen_at[:10]
            if not seen_date:
                continue  # no timestamp, no stable key and no simulation start
            age = int(np.busday_count(seen_date, now.date().isoformat()))
            if age > MAX_EVENT_AGE_BUSDAYS:
                _reject("too_old", f"{event_type}, {age} busdays old")
                continue
        if ticker in book.positions:
            _reject("already_held", str(event_type))
            continue
        if len(picks) >= free_slots:
            _reject("cap_full", f"{event_type}, book full at {max_positions}")
            continue
        seen.add(ticker)
        # seen_at rides along so the runner can log a later price-less skip (no_quote)
        # under the event's own timestamp instead of inventing one
        picks.append(
            {"ticker": ticker, "reason": f"event: {event['event_type']}", "seen_at": seen_at}
        )
    return picks, rejections


def pick_entries(
    events: list[dict],
    book: LaneBook,
    *,
    now: datetime | None = None,
    max_positions: int = MAX_POSITIONS,
) -> list[dict]:
    return pick_entries_explained(events, book, now=now, max_positions=max_positions)[0]


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
