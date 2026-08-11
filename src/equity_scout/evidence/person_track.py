"""Person-level track record over disclosed stock purchases (congress, 13F funds,
Form 4 corporate insiders).

Pure computation: payload/event parsing in, scores out — prices arrive as an aligned
close panel (pandas), the network stays in the CLI. Methodology (documented in
docs/superpowers/plans/2026-07-10-person-track-record-v4.md):

- T0 of every call is the FILING date — the day a reader could have known, not the
  trade day; a disclosed trade is a trade, not a recommendation (confound honesty).
- Abnormal return per call = ticker forward return minus SPY forward return over the
  same trading-day window (1M/3M = 21/63 days), via ml.entry_eval — signed BY THE CALL'S
  DIRECTION since 2026-08-11, so a bearish call that was followed by underperformance
  counts as a hit. Filings only ever express buying, so congress/13F/insider scores are
  bit-identical to before; the change unlocks the bearish voice calls, which had been
  collected and then dropped from every statistic (20 of 35 stored directional calls).
- No score below `min_calls` resolvable calls: "zu wenig Daten" beats a lucky number.
- The headline score is the recency-weighted (half-life 540d) mean abnormal return
  @63d; hit-rates, both horizons and n ride along on every surface — never a bare
  opaque number, always history, never a forecast.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from equity_scout.ml.entry_eval import relative_forward_return

HORIZON_SHORT_DAYS = 21  # ~1 month of trading days
HORIZON_LONG_DAYS = 63  # ~3 months — the headline horizon
DEFAULT_MIN_CALLS = 5
DEFAULT_HALF_LIFE_DAYS = 540.0

# Voice event kinds that carry a direction, mapped to it. Kept as a literal map rather than
# importing evidence.voices: person_track is the measurement layer and must not depend on a
# collector. `KIND_CONTEXT` is deliberately absent — a mention without a direction cannot be
# right or wrong, and scoring it either way would fabricate a verdict.
_VOICE_CALL_DIRECTION = {"call": "bullish", "call_bearish": "bearish"}
# Multiplier applied to every measured relative return, so "hit" means "the direction held".
_DIRECTION_SIGN = {"bullish": 1.0, "bearish": -1.0}


def yf_symbol(ticker: str) -> str:
    """Disclosure tickers use dots for share classes (BRK.B), Yahoo uses dashes (BRK-B)."""
    return ticker.upper().replace(".", "-")


@dataclass(frozen=True)
class Call:
    person: str
    source: str  # evidence.base SOURCE_* of the originating feed
    ticker: str
    t0: str  # ISO date the fact became PUBLIC (filing date)
    transaction_date: str | None = None  # display only, never the measurement anchor
    # Which way the call pointed. "bearish" flips the sign of every measured return, so a hit
    # rate means "was the direction right" for both kinds instead of "did the stock rise".
    # Defaults to bullish: buying is the only direction congress/13F/insider filings express,
    # so those three sources — and every existing call site — are unaffected.
    direction: str = "bullish"


@dataclass(frozen=True)
class PersonScore:
    person: str
    source: str
    n_calls: int  # calls with at least the SHORT horizon resolvable
    n_unresolvable: int  # counted, never guessed (ticker missing / window not elapsed)
    hit_rate_short: float | None
    hit_rate_long: float | None
    mean_abnormal_short: float | None
    mean_abnormal_long: float | None
    weighted_score: float | None  # recency-weighted mean abnormal @long — None if gated
    # The HEADLINE score is the LONG-horizon measurement, so the gate counts calls whose
    # full 3M window has elapsed: scoreable implies weighted_score is not None. A person
    # whose buys are all 21-62 trading days old is "noch nicht 3M-reif" — never a
    # fabricated 0 %. False -> surfaces say "zu wenig Daten", never a number.
    scoreable: bool


def calls_from_filer_payload(payload: dict) -> tuple[list[Call], dict]:
    """kadoa per-filer JSON -> purchase calls + honest skip counters.

    Same keep-rules as the live congress collector (purchases only, stock-like assets,
    resolvable ticker) minus the filing-window bound — backfill WANTS the history.
    One person's same-day purchases in one ticker collapse into one call.
    """
    filer = (payload.get("filer") or {}).get("full_name") or "unbekannt"
    counters = {"rows": 0, "kept": 0, "not_purchase": 0, "not_stock": 0, "no_ticker": 0,
                "no_date": 0}
    calls: list[Call] = []
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
        key = (str(ticker).upper(), t0)
        if key in seen:
            continue
        seen.add(key)
        counters["kept"] += 1
        calls.append(
            Call(
                person=filer,
                source="congress",
                ticker=str(ticker).upper(),
                t0=t0,
                transaction_date=row.get("transaction_date"),
            )
        )
    return calls, counters


def calls_from_events(events: list[dict]) -> list[Call]:
    """Own evidence_events rows -> calls, source-agnostic.

    Congress rows carry `politician`, 13F rows carry `fund`, insider (Form 4) rows
    carry `insider` — whichever is present names the person; the event's own `source`
    (congress/thirteen_f/insider) rides along on the Call and keeps the three kinds of
    buyer scored separately (score_persons keys by (person, source), so a name that
    appears in two sources never blends into one fake sample). Rows without a person
    (news themes) are silently skipped: themes have no author to track.
    """
    calls: list[Call] = []
    for event in events:
        details = event.get("details") or {}
        person = details.get("politician") or details.get("fund") or details.get("insider")
        direction = "bullish"
        if not person and details.get("kind") in _VOICE_CALL_DIRECTION:
            # Voice rows: BOTH directional kinds are track-record material since 2026-08-11.
            # Bearish ones used to be skipped because they "would resolve with inverted
            # meaning" — which is now handled by carrying the direction and flipping the sign
            # in `score_persons` instead of throwing the sample away. Context mentions still
            # have no direction at all and stay out.
            person = details.get("speaker")
            direction = _VOICE_CALL_DIRECTION[details["kind"]]
        if not person:
            continue
        calls.append(
            Call(
                person=person,
                source=event["source"],
                ticker=event["ticker"],
                t0=details.get("filing_date") or details.get("filed_at") or event["event_date"],
                transaction_date=details.get("transaction_date"),
                direction=direction,
            )
        )
    return calls


def _as_panel_timestamp(iso_date: str) -> pd.Timestamp:
    ts = pd.Timestamp(iso_date)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts.normalize()


def _recency_weight(t0: str, now: str, half_life_days: float) -> float:
    age_days = max(
        0.0,
        (datetime.fromisoformat(now).replace(tzinfo=None)
         - datetime.fromisoformat(t0).replace(tzinfo=None)).days,
    )
    return math.pow(0.5, age_days / half_life_days)


def score_persons(
    calls: list[Call],
    closes: pd.DataFrame,
    *,
    now: str,
    benchmark: str = "SPY",
    min_calls: int = DEFAULT_MIN_CALLS,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
) -> dict[str, PersonScore]:
    """Measure every person's calls against the close panel. Keyed by person name.

    A call resolves on a horizon only when the FULL forward window is observable in
    the panel (no peeking); calls whose ticker the panel lacks are counted as
    unresolvable — missing free data is stated, never interpolated. Persons from
    multiple sources are scored per (person, source) pair; the dict key is
    "person" for single-source persons (the common case) and "person·source" on a
    collision, so two sources never blend into one fake sample.
    """
    if benchmark not in closes.columns:
        raise ValueError(f"benchmark {benchmark} missing from the close panel")
    grouped: dict[tuple[str, str], list[Call]] = {}
    for call in calls:
        grouped.setdefault((call.person, call.source), []).append(call)

    persons_seen: dict[str, int] = {}
    for person, _source in grouped:
        persons_seen[person] = persons_seen.get(person, 0) + 1

    scores: dict[str, PersonScore] = {}
    for (person, source), person_calls in grouped.items():
        short_results: list[float] = []
        long_results: list[float] = []
        weighted_sum = 0.0
        weight_total = 0.0
        unresolvable = 0
        for call in person_calls:
            symbol = yf_symbol(call.ticker)
            # Buying the benchmark itself is not a stock call — "SPY vs SPY" has no
            # measurable edge (and closes[[SPY, SPY]] would blow up downstream).
            if symbol == benchmark or symbol not in closes.columns:
                unresolvable += 1
                continue
            pair = closes[[symbol, benchmark]].dropna()
            on_or_after = pair.index[pair.index >= _as_panel_timestamp(call.t0)]
            if len(on_or_after) == 0:
                unresolvable += 1
                continue
            at = on_or_after[0]
            # A bearish call is right when the stock LAGS, so its returns are measured with the
            # sign flipped. Every stored number therefore means "return in the direction the
            # person called", which is the only reading under which one hit rate can cover both.
            sign = _DIRECTION_SIGN.get(call.direction, 1.0)
            rel_short = relative_forward_return(
                pair[symbol], pair[benchmark], at, HORIZON_SHORT_DAYS
            )
            if rel_short is None:
                unresolvable += 1
                continue
            short_results.append(sign * rel_short)
            rel_long = relative_forward_return(
                pair[symbol], pair[benchmark], at, HORIZON_LONG_DAYS
            )
            if rel_long is not None:
                rel_long *= sign
                long_results.append(rel_long)
                weight = _recency_weight(call.t0, now, half_life_days)
                weighted_sum += weight * rel_long
                weight_total += weight
        n = len(short_results)
        scoreable = len(long_results) >= min_calls
        key = person if persons_seen[person] == 1 else f"{person}·{source}"
        scores[key] = PersonScore(
            person=person,
            source=source,
            n_calls=n,
            n_unresolvable=unresolvable,
            hit_rate_short=round(sum(r > 0 for r in short_results) / n, 4) if n else None,
            hit_rate_long=(
                round(sum(r > 0 for r in long_results) / len(long_results), 4)
                if long_results
                else None
            ),
            mean_abnormal_short=round(sum(short_results) / n, 4) if n else None,
            mean_abnormal_long=(
                round(sum(long_results) / len(long_results), 4) if long_results else None
            ),
            weighted_score=(
                round(weighted_sum / weight_total, 4)
                if scoreable and weight_total > 0
                else None
            ),
            scoreable=scoreable,
        )
    return scores
