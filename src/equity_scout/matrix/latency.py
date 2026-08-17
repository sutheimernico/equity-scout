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

Entries use the first bar whose interval STARTS at or after the delayed timestamp, so a fill is
never booked at a price that existed before the trader could have acted.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

DELAY_MINUTES = (0, 1, 2, 5, 15, 30)  # entry delay after the wire timestamp
HOLD_MINUTES = (5, 15, 30, 60)  # holding window measured from the delayed entry
MIN_EVENTS = 100  # below this an event bucket reports its count and nothing else


def _position_at_or_after(index: pd.DatetimeIndex, stamp: pd.Timestamp) -> int | None:
    """Index of the first bar at or after `stamp`, or None when the series ends first."""
    position = int(index.searchsorted(stamp, side="left"))
    return position if position < len(index) else None


def event_moves(
    bars: pd.DataFrame,
    stamps: pd.Series,
    *,
    delay_minutes: int,
    hold_minutes: int,
    max_gap_minutes: int = 5,
) -> dict:
    """Per-event (before, after) moves in bp for one (delay, hold) combination.

    `max_gap_minutes` guards the session edge: a wire item published at 20:00 ET would otherwise
    "enter" at the next morning's open, turning an overnight gap into a fake news reaction. An
    event whose entry bar sits further than this from the intended entry time is dropped.
    """
    index = bars.index
    closes = bars["close"].to_numpy(dtype=float)
    before: list[float] = []
    after: list[float] = []
    for stamp in stamps:
        base = _position_at_or_after(index, stamp)
        if base is None:
            continue
        entry_time = stamp + pd.Timedelta(minutes=delay_minutes)
        entry = _position_at_or_after(index, entry_time)
        if entry is None:
            continue
        if (index[entry] - entry_time) > pd.Timedelta(minutes=max_gap_minutes):
            continue  # entry would land after a session break — not this event's reaction
        exit_time = index[entry] + pd.Timedelta(minutes=hold_minutes)
        exit_position = _position_at_or_after(index, exit_time)
        if exit_position is None:
            continue
        if (index[exit_position] - exit_time) > pd.Timedelta(minutes=max_gap_minutes):
            continue
        if closes[base] <= 0 or closes[entry] <= 0:
            continue
        before.append((closes[entry] / closes[base] - 1.0) * 10_000.0)
        after.append((closes[exit_position] / closes[entry] - 1.0) * 10_000.0)
    return {"before_bp": np.asarray(before), "after_bp": np.asarray(after)}


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
