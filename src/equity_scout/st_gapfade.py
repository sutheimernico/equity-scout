"""Gap-fade lane (lane `gapfade`, 2026-08-17): buy deep pre-market DOWN gaps at the opening
auction, sell at the closing auction — a MEASUREMENT lane, not a proven edge.

Evidence trail (docs/research/2026-08-16-*): the day-session recovery after a down gap is
monotone and robust in backtest (T7, t up to 15.7), but only reachable at the opening print
(T8: +65 bp at the open, -0.09 bp 15 minutes later), and the tradable pre-market selection
kept two thirds of the effect at t = 1.00 on 42 days (T9). What a paper book can still
measure where the backtest cannot: how well the pre-market price predicts the gap LIVE, and
how far the auction fill drifts from the signal price. Stop criterion: after 60 closed
trades `significance.assess_trades` decides — verdict "negativ" ends the lane.

Honesty boundary (also shown in the frontend): paper MOO fills measure the drift between
signal and opening print, NOT the market impact of a real order in the auction.

Pure decision logic; the runner owns all I/O and the auction order plumbing.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from equity_scout.shortterm_book import LaneBook

GAP_THRESHOLD = -0.02  # T9: this threshold hits the realised gap in 61 % of cases
LOG_THRESHOLD = -0.01  # gaps in (GAP_THRESHOLD, LOG_THRESHOLD] are rejected AND logged
ENTRY_FRACTION = 0.15
MAX_POSITIONS = 3
MAX_QUOTE_AGE_MINUTES = 20  # IEX pre-market is thin; an old quote is not a signal

_NY = ZoneInfo("America/New_York")


def pick_gap_entries(
    premarket: dict[str, tuple[float, datetime]],
    prev_closes: dict[str, float],
    book: LaneBook,
    *,
    now: datetime,
    traded: set[str],
    max_positions: int = MAX_POSITIONS,
) -> tuple[list[dict], list[dict]]:
    """(picks, rejections) — pure, no I/O.

    premarket: {ticker: (last pre-market price, quote timestamp)}. Deepest gaps win the
    slots (T7: the effect grows with gap depth). Rejections carry the NY trading DAY as
    seen_at — deterministic per day, so a crash-rerun cannot double-log; the actual quote
    time lives in the detail text. below_threshold rows are the calibration data Nico
    asked for: they answer nightly whether -2 % is the right threshold.
    """
    day_key = now.astimezone(_NY).date().isoformat()
    picks: list[dict] = []
    rejections: list[dict] = []

    candidates: list[tuple[float, str, float, datetime]] = []
    for ticker, (price, quoted_at) in premarket.items():
        prev = prev_closes.get(ticker)
        if not prev or prev <= 0 or not price or price <= 0:
            continue
        candidates.append((price / prev - 1.0, ticker, price, quoted_at))

    free_slots = max(0, max_positions - len(book.positions))
    for gap, ticker, price, quoted_at in sorted(candidates):
        if gap > LOG_THRESHOLD:
            continue  # not an opportunity under any reading — no row, no noise

        def _reject(reason: str) -> None:
            rejections.append({
                "ticker": ticker, "reason": reason, "seen_at": day_key,
                "ref_price": price,
                "detail": f"gap {gap:+.1%}, quote {quoted_at.isoformat(timespec='minutes')}",
            })

        if now - quoted_at > timedelta(minutes=MAX_QUOTE_AGE_MINUTES):
            _reject("stale_premarket")
            continue
        if gap > GAP_THRESHOLD:
            _reject("below_threshold")
            continue
        if ticker in book.positions or ticker in traded:
            if ticker in book.positions:
                _reject("already_held")
            continue  # traded today: the day marker already tells this story
        if len(picks) >= free_slots:
            _reject("cap_full")
            continue
        picks.append({
            "ticker": ticker,
            "signal_price": price,
            "gap": gap,
            "reason": f"Gap {gap:+.1%} zur Eröffnung gekauft (Fade)",
        })
    return picks, rejections


def coverage_summary(
    tickers: list[str],
    premarket: dict[str, tuple[float, datetime]],
    prev_closes: dict[str, float],
    *,
    now: datetime,
) -> dict:
    """How much of the watchlist the lane could actually judge this run.

    Why this is not cosmetic: "0 MOO platziert, 1 verworfen" reads the same whether 24
    tickers were priced and none gapped, or 23 tickers had no pre-market print at all. The
    first is the lane working; the second is the lane measuring nothing. IEX is a small
    slice of US volume (order of a few percent — general knowledge, NOT measured here),
    so for the small caps this watchlist produces the second is the likely case. The
    numbers this function returns are what settles it either way; the share is only the
    reason to look. On 2026-08-21, the lane's only healthy day so far, its single logged
    row carried a quote that was TWO DAYS old.

    `judgeable` is the honest denominator: a ticker needs a fresh print AND a previous
    close before a gap can be computed at all.
    """
    fresh = 0
    judgeable = 0
    for ticker in tickers:
        quote = premarket.get(ticker)
        if quote is None:
            continue
        _price, quoted_at = quote
        if now - quoted_at > timedelta(minutes=MAX_QUOTE_AGE_MINUTES):
            continue
        fresh += 1
        if prev_closes.get(ticker, 0) > 0:
            judgeable += 1
    return {
        "asked": len(tickers),
        "quoted": sum(1 for t in tickers if t in premarket),
        "fresh": fresh,
        "judgeable": judgeable,
    }


def format_coverage(summary: dict) -> str:
    """One line, and it leads with the number that decides whether the run meant anything."""
    return (
        f"Gap-Fade-Abdeckung: {summary['judgeable']} von {summary['asked']} Tickern "
        f"bewertbar ({summary['quoted']} mit Pre-Market-Print, davon "
        f"{summary['fresh']} frisch ≤ {MAX_QUOTE_AGE_MINUTES} Min)."
    )
