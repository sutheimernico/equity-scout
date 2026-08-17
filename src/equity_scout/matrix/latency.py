"""Latency-decay curve: how much of a news reaction survives an entry delay.

The question this answers (Nico, 2026-08-17): "should we scrape many sources so we are faster
than everyone else?" The honest answer depends on ONE measurement — the shape of the decay.

For every news item with a second-level timestamp, the move is measured in two parts:

- **before(d)** — what already happened between the wire and an entry `d` minutes later. That is
  the part a slower trader MISSES. It is the price of latency, in basis points.
- **after(d)** — what happens from that delayed entry over the holding window. That is what a
  trader at delay `d` can actually still earn.

Read the resulting table like this: if after(5min) is still positive and significant, latency is
not the binding constraint and no scraping network is needed. If after(1min) is already zero
while before(1min) is large, the whole move happens instantly — and then nothing we can build
catches it, because our signal-to-fill path is ~5 seconds against microsecond competition.

Anchor choice, and why it is OPENs and not closes: a bar's close is only known ~60 s after the
bar begins. Anchoring the pre-news price at the close of the first bar AFTER the wire (the old
construction) put the anchor ~90 s past the news — before(0) was identically zero and the whole
reaction invisible. Now the pre-news anchor is the OPEN of the bar that CONTAINS the wire stamp
(printed at most ~60 s before it), and entries/exits are the OPEN of the first bar starting at
or after their target time — the earliest price a delayed trader could realistically touch.

Events are dropped, not repaired, when their bars do not exist where they should (session
edges, overnight): a wire item published at 20:00 ET "entering" at the next morning's open
would turn an overnight gap into a fake news reaction. Every drop is COUNTED per reason, so
the measurement reports which slice of the news flow it actually covers.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

DELAY_MINUTES = (0, 1, 2, 5, 15, 30)  # entry delay after the wire timestamp
HOLD_MINUTES = (5, 15, 30, 60)  # holding window measured from the delayed entry
MIN_EVENTS = 100  # below this an event bucket reports its count and nothing else
DROP_REASONS = (
    "no_pre_bar", "pre_too_far", "no_entry_bar", "entry_gap",
    "no_exit_bar", "exit_gap", "bad_price",
)


def _position_at_or_after(index: pd.DatetimeIndex, stamp: pd.Timestamp) -> int | None:
    """Index of the first bar STARTING at or after `stamp`, or None when the series ends."""
    position = int(index.searchsorted(stamp, side="left"))
    return position if position < len(index) else None


def _position_containing(index: pd.DatetimeIndex, stamp: pd.Timestamp) -> int | None:
    """Index of the last bar STARTING at or before `stamp` — the bar the stamp falls into."""
    position = int(index.searchsorted(stamp, side="right")) - 1
    return position if position >= 0 else None


def event_moves(
    bars: pd.DataFrame,
    stamps: pd.Series,
    *,
    delay_minutes: int,
    hold_minutes: int,
    max_gap_minutes: int = 5,
) -> dict:
    """Per-event (before, after) moves in bp for one (delay, hold) combination.

    `max_gap_minutes` guards every anchor: pre-news bar, delayed entry and exit must each sit
    within this distance of their intended time, otherwise the event lands across a session
    break and is dropped — and counted under its reason in `dropped`.
    """
    index = bars.index
    opens = bars["open"].to_numpy(dtype=float)
    before: list[float] = []
    after: list[float] = []
    dropped = dict.fromkeys(DROP_REASONS, 0)
    gap = pd.Timedelta(minutes=max_gap_minutes)
    for stamp in stamps:
        pre = _position_containing(index, stamp)
        if pre is None:
            dropped["no_pre_bar"] += 1
            continue
        if (stamp - index[pre]) > gap:
            dropped["pre_too_far"] += 1  # wire landed outside the session (evening, weekend)
            continue
        entry_time = stamp + pd.Timedelta(minutes=delay_minutes)
        entry = _position_at_or_after(index, entry_time)
        if entry is None:
            dropped["no_entry_bar"] += 1
            continue
        if (index[entry] - entry_time) > gap:
            dropped["entry_gap"] += 1  # entry would land after a session break
            continue
        exit_time = index[entry] + pd.Timedelta(minutes=hold_minutes)
        exit_position = _position_at_or_after(index, exit_time)
        if exit_position is None:
            dropped["no_exit_bar"] += 1
            continue
        if (index[exit_position] - exit_time) > gap:
            dropped["exit_gap"] += 1
            continue
        if opens[pre] <= 0 or opens[entry] <= 0:
            dropped["bad_price"] += 1
            continue
        before.append((opens[entry] / opens[pre] - 1.0) * 10_000.0)
        after.append((opens[exit_position] / opens[entry] - 1.0) * 10_000.0)
    return {
        "before_bp": np.asarray(before),
        "after_bp": np.asarray(after),
        "dropped": dropped,
    }


def summarise(moves: dict, *, cost_bps: float) -> dict:
    """Event-bucket statistics. Below MIN_EVENTS everything but the count comes back None."""
    after = moves["after_bp"]
    n = len(after)
    if n < MIN_EVENTS:
        return {"n": n, "missed_bp": None, "after_bp": None, "net_bp": None, "t": None,
                "hit_rate": None}
    net = after - cost_bps
    std = float(net.std(ddof=1))
    return {
        "n": n,
        "missed_bp": float(moves["before_bp"].mean()),
        "after_bp": float(after.mean()),
        "net_bp": float(net.mean()),
        "t": float(net.mean()) / (std / math.sqrt(n)) if std > 0 else None,
        "hit_rate": float((net > 0).mean()),
    }


def decay_verdict(rows: list[dict]) -> str:
    """One sentence on what the curve implies for the scraping question.

    Deliberately blunt in all three directions — the point of the measurement is to settle the
    question, and a hedged sentence would leave it open.
    """
    usable = [r for r in rows if r.get("net_bp") is not None and r.get("t") is not None]
    if not usable:
        return ("Kein Urteil möglich: keine Ereignis-Gruppe erreicht die Mindestzahl. "
                "Die Frage nach Latenz ist an diesen Daten nicht entscheidbar.")
    significant = [r for r in usable if r["net_bp"] > 0 and r["t"] >= 2.0]
    if not significant:
        return ("Latenz ist NICHT der Engpass, weil es keinen Effekt gibt, den man verpassen "
                "könnte: keine Verzögerungsstufe ist nach Kosten positiv und signifikant. "
                "Schneller zu werden würde nichts kaufen.")
    slowest = max(r["delay_minutes"] for r in significant)
    fastest = min(r["delay_minutes"] for r in significant)
    if slowest >= 5:
        return (f"Der Effekt hält mindestens {slowest} Minuten nach der Meldung. Latenz ist "
                f"damit nicht der Engpass — ein Scraping-Netz wäre Aufwand ohne Gegenwert, "
                f"unsere ~5 Sekunden reichen.")
    return (f"Der Effekt existiert nur bis {slowest} Minute(n) Verzögerung (ab {fastest}). "
            f"Das ist ein Latenzrennen gegen Gegner im Mikrosekundenbereich — mit ~5 Sekunden "
            f"Signal-zu-Fill ist es nicht gewinnbar, auch nicht mit mehr Quellen.")
