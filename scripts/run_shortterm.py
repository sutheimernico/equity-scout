"""CLI: advance one short-term arena lane (vision v11) — `--lane swing|session|crypto`.

Three independent paper lanes, one runner:
- swing   nightly, after the auto-depot: bullish earnings events -> 1-5 day holds.
- session every 15 min inside the market window: Opening-Range-Breakout on DELAYED
          15-min bars (settled-bar honesty gate), always flat by the close.
- crypto  every 15 min around the clock: Donchian breakout on Kraken's free REAL-TIME
          bars, benchmarked against BTC buy-and-hold (the honest bar, not cash).

PAPER / RESEARCH ONLY. The arena exists to MEASURE whether any of this survives its
costs — the research-backed expectation for retail short-term trading is that it does
not, and the arena will say so either way. See the disclaimer and LOOP.md.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone

from equity_scout.constants import DEFAULT_DB_PATH, DISCLAIMER
from equity_scout.data.etf_panel import load_price_history
from equity_scout.evidence.event_storage import load_classified_events
from equity_scout.intraday_bars import SESSION_UNIVERSE, fetch_bars, settled_bars
from equity_scout.kraken_data import CRYPTO_PAIRS, completed_bars, fetch_ohlc
from equity_scout.market_hours import within_market_window
from equity_scout.shortterm_book import (
    LaneBook,
    buy,
    capture_benchmark,
    sell,
    valuation,
)
from equity_scout.shortterm_storage import (
    DEFAULT_SHORTTERM_DB_PATH,
    get_lane_state,
    load_book,
    persist_lane_step,
)
from equity_scout.state_storage import record_heartbeat
from equity_scout.st_crypto import ENTRY_FRACTION as CRYPTO_FRACTION
from equity_scout.st_crypto import decide_pair
from equity_scout.st_session import ENTRY_FRACTION as SESSION_FRACTION
from equity_scout.st_session import decide, opening_range
from equity_scout.st_swing import ENTRY_FRACTION as SWING_FRACTION
from equity_scout.st_swing import MAX_POSITIONS, check_exits, pick_entries

SWING_SNAPSHOT = "data/prices/st_swing_panel.csv"
CRYPTO_SLIPPAGE_BPS = 10.0
EVENTS_SEEN_KEY = "events_seen_until"
SESSION_STATE_KEY = "session_state"


def _hour_stamp(now: datetime) -> str:
    return now.replace(minute=0, second=0, microsecond=0).isoformat(timespec="minutes")


def _print_fills(fills: list) -> None:
    for fill in fills:
        pnl = f"  P&L {fill.realized_pnl:+,.2f}" if fill.realized_pnl is not None else ""
        print(f"  {fill.side.upper():<5} {fill.ticker:<8} @ {fill.price:,.2f}  ({fill.reason}){pnl}")


def run_swing(db: str, main_db: str, *, now: datetime) -> None:
    book = load_book(db, "swing") or LaneBook.fresh("swing", benchmark_ticker="SPY")
    marker = get_lane_state(db, "swing", EVENTS_SEEN_KEY)
    if marker is None:
        # first run: only the last 24h of events — never buy the whole stored history
        marker = (now - timedelta(hours=24)).isoformat(timespec="seconds")
    events = [e for e in load_classified_events(main_db) if (e["seen_at"] or "") > marker]
    # pool sized as if every held position could exit today: the price panel must already
    # cover entries that only become possible once today's exits free their slots (v13 R7)
    candidate_pool = pick_entries(events, book, now=now,
                                  max_positions=MAX_POSITIONS + len(book.positions))

    tickers = sorted({*book.positions, *(c["ticker"] for c in candidate_pool), "SPY"})
    start = (now - timedelta(days=40)).date().isoformat()
    panel = load_price_history(tickers, start=start, snapshot=SWING_SNAPSHOT, refresh=True)
    if len(panel.dates) == 0:
        print("Keine Preise verfügbar — Lauf übersprungen (ehrlich: kein Preis, kein Trade).")
        return
    today = panel.dates[-1].date().isoformat()
    prices = {
        t: float(panel.closes[t].dropna().iloc[-1])
        for t in panel.tickers
        if len(panel.closes[t].dropna())
    }

    fills = []
    exited_today: set[str] = set()
    for exit_order in check_exits(book, prices, today):
        book, fill = sell(book, exit_order["ticker"], exit_order["price"], today,
                          reason=exit_order["reason"])
        if fill:
            fills.append(fill)
            exited_today.add(exit_order["ticker"])
    # re-pick against the post-exit book so capital freed today is investable today (v13
    # R7). Tickers exited today are dropped from the event pool BEFORE the slot cap —
    # otherwise a stopped-out name with the freshest event would claim its old slot back
    # at the same close it just exited on (churn, not a new decision).
    fresh_events = [e for e in events if (e.get("ticker") or "").upper() not in exited_today]
    for candidate in pick_entries(fresh_events, book, now=now):
        price = prices.get(candidate["ticker"])
        if not price:
            continue  # event ticker without a quote — honest skip
        book, fill = buy(book, candidate["ticker"], price, today,
                         fraction=SWING_FRACTION, reason=candidate["reason"])
        if fill:
            fills.append(fill)

    book = capture_benchmark(book, prices.get("SPY"))
    snap = valuation(book, prices, prices.get("SPY"), today)
    marker_state = [(EVENTS_SEEN_KEY, max(e["seen_at"] for e in events))] if events else []
    persist_lane_step(db, book, updated_at=today, trades=fills, valuation=snap,
                      state=marker_state)
    print(f"Swing {today}: Equity {snap.equity:,.2f} ({snap.total_return:+.2%}), "
          f"{len(book.positions)} offen, {len(fills)} Fills")
    _print_fills(fills)


MAX_RUN_GAP = timedelta(minutes=5)
LAST_RUN_KEY = "last_session_run"


def session_report_due(*, fills: list, first_run_of_day: bool) -> bool:
    """Whether this session run has anything worth a log block.

    Task 9 Step 1, and a prerequisite for the one-minute cadence rather than polish: at
    `*/15` the lane writes ~26 report blocks a day and every one carries information, but at
    `* * * * *` it writes ~390 near-identical ones and the log stops being read. Both
    production defects this project has hit (the v12 cron `cd` bug, the Tokyo-stamped panel
    row) survived by hiding in output nobody scanned.

    A run reports when it FILLED something, plus once per session so that "the lane found no
    setup" stays distinguishable from "the lane never ran". Errors and missing data print
    on their own paths regardless — silence is only for the genuinely uneventful run.
    """
    return bool(fills) or first_run_of_day


def may_open_new_position(
    *, last_run: str | None, now: datetime, max_gap: timedelta = MAX_RUN_GAP
) -> bool:
    """False when the previous run is further back than `max_gap`. A gap means the machine
    cannot promise to be here for the exit either, and an entry without a reliable exit is
    the exact shape of the 2026-07-21 loss. The very first run is allowed: no history is
    not the same as a gap. Exits and sweeps ignore this gate entirely.

    The tolerance is an argument, not a constant folded into the body, because it measures
    MISSED SLOTS and therefore belongs to the cron cadence — which is 15 minutes today and
    one minute after Task 9. The default is sized for the target cadence; a caller running
    on the old schedule must pass its own. A future `last_run` also fails the gate: clock
    skew or a repaired state file is not evidence that we were just here (cf. the
    2026-07-24 Tokyo-timestamp incident).
    """
    if last_run is None:
        return True
    return timedelta(0) <= now - datetime.fromisoformat(last_run) <= max_gap


def _session_overnight_sweep(db: str, book: LaneBook, *, now: datetime) -> None:
    """Flatten anything still open once the session is over. The last session bar (15:45 ET)
    is not yet 'settled' when the final intraday run fires, so a position entered late can
    slip past the in-session force-flat — this sweep (called by the nightly chain) closes it
    at the last settled close. The lane must NEVER hold overnight."""
    all_bars = fetch_bars(list(book.positions))
    fills = []
    prices: dict[str, float] = {}
    for ticker in list(book.positions):
        bars = all_bars.get(ticker)
        settled = settled_bars(bars, now) if bars is not None else None
        if settled is None or settled.empty:
            continue  # no price, no trade — retried on the next sweep
        price = float(settled["close"].iloc[-1])
        prices[ticker] = price
        book, fill = sell(book, ticker, price, settled.index[-1].isoformat(),
                          reason="Session-Ende (Nachlauf)")
        if fill:
            fills.append(fill)
    if not fills:
        print("Nachlauf: nichts zu flatten.")
        return
    snap = valuation(book, prices, prices.get("SPY"), _hour_stamp(now))
    persist_lane_step(db, book, updated_at=now.isoformat(timespec="seconds"),
                      trades=fills, valuation=snap)
    print(f"Nachlauf-Sweep: {len(fills)} Position(en) geflattet — Lane ist über Nacht flat.")
    _print_fills(fills)


def _flatten_stale_positions(
    book: LaneBook, all_bars: dict, session_date: str, now: datetime,
) -> tuple[LaneBook, list]:
    """Close any position carried over from a previous day BEFORE decide() runs (P0,
    review 2026-07-20): after an outage the overnight sweep may never have fired, and
    decide() would otherwise manage the stale position with TODAY's opening range —
    stop/target become arbitrary. Fill = open of today's first settled bar (the first
    knowable price of the session); no bars yet -> left for a later run / the sweep."""
    fills = []
    for ticker, position in list(book.positions.items()):
        if position.opened_at[:10] == session_date:
            continue
        bars = all_bars.get(ticker)
        settled = settled_bars(bars, now) if bars is not None else None
        if settled is None or settled.empty:
            continue
        book, fill = sell(book, ticker, float(settled["open"].iloc[0]),
                          settled.index[0].isoformat(), reason="Altbestand (zwangsflat)")
        if fill:
            fills.append(fill)
    return book, fills


def run_session(db: str, *, now: datetime) -> None:
    if not within_market_window(now):
        book = load_book(db, "session")
        if book is not None and book.positions:
            _session_overnight_sweep(db, book, now=now)
        # Silent otherwise: outside the window with a flat book is the normal state for
        # most of the day, and on a one-minute cron it would be ~1,380 lines of it.
        return
    book = load_book(db, "session") or LaneBook.fresh("session", benchmark_ticker="SPY")
    state = json.loads(get_lane_state(db, "session", SESSION_STATE_KEY) or "{}")
    # include held tickers: a stale position must be flattenable even if it left the universe
    all_bars = fetch_bars(sorted({*SESSION_UNIVERSE, *book.positions}))
    if not all_bars:
        print("Keine Intraday-Bars verfügbar — Lauf übersprungen.")
        return

    session_date = next(iter(all_bars.values())).index[0].date().isoformat()
    first_run_of_day = state.get("date") != session_date
    if first_run_of_day:
        state = {"date": session_date, "last_bar": {}, "ranges": {}, "traded": []}

    book, fills = _flatten_stale_positions(book, all_bars, session_date, now)
    prices: dict[str, float] = {}
    for ticker, bars in all_bars.items():
        settled = settled_bars(bars, now)
        if settled.empty:
            continue
        prices[ticker] = float(settled["close"].iloc[-1])
        or_range = state["ranges"].get(ticker) or opening_range(settled)
        if or_range is None:
            continue
        state["ranges"][ticker] = list(or_range)
        actions, new_marker = decide(
            ticker, settled, book.positions.get(ticker),
            or_range=tuple(or_range),
            last_processed=state["last_bar"].get(ticker),
            traded_today=ticker in state["traded"],
        )
        for action in actions:
            if action.kind == "buy":
                book, fill = buy(book, ticker, action.price, action.at,
                                 fraction=SESSION_FRACTION, reason=action.reason)
                if fill:
                    state["traded"].append(ticker)
            else:
                book, fill = sell(book, ticker, action.price, action.at, reason=action.reason)
            if fill:
                fills.append(fill)
        if new_marker:
            state["last_bar"][ticker] = new_marker

    book = capture_benchmark(book, prices.get("SPY"))
    snap = valuation(book, prices, prices.get("SPY"), _hour_stamp(now))
    persist_lane_step(db, book, updated_at=now.isoformat(timespec="seconds"),
                      trades=fills, valuation=snap,
                      state=[(SESSION_STATE_KEY, json.dumps(state))])
    if session_report_due(fills=fills, first_run_of_day=first_run_of_day):
        print(f"Session {session_date}: Equity {snap.equity:,.2f} ({snap.total_return:+.2%}), "
              f"{len(book.positions)} offen, {len(fills)} Fills")
        _print_fills(fills)


def run_crypto(db: str, *, now: datetime, fetch=fetch_ohlc) -> bool:
    book = load_book(db, "crypto") or LaneBook.fresh("crypto", benchmark_ticker="BTC")
    fills = []
    markers: list[tuple[str, str]] = []
    prices: dict[str, float] = {}
    for symbol, pair in CRYPTO_PAIRS.items():
        raw = fetch(pair)
        if raw is None:
            continue  # feed down for this pair — no price, no trade
        bars = completed_bars(raw)
        if bars.empty:
            continue
        prices[symbol] = float(bars["close"].iloc[-1])
        action, marker = decide_pair(
            symbol, bars, book.positions.get(symbol),
            last_processed=get_lane_state(db, "crypto", f"last_bar_{symbol}"),
        )
        if action is not None:
            if action.kind == "buy":
                book, fill = buy(book, symbol, action.price, action.at,
                                 fraction=CRYPTO_FRACTION, reason=action.reason,
                                 slippage_bps=CRYPTO_SLIPPAGE_BPS)
            else:
                book, fill = sell(book, symbol, action.price, action.at,
                                  reason=action.reason, slippage_bps=CRYPTO_SLIPPAGE_BPS)
            if fill:
                fills.append(fill)
        if marker:
            markers.append((f"last_bar_{symbol}", marker))

    if not prices:
        print("Kraken nicht erreichbar — Lauf übersprungen (kein Preis, kein Trade).")
        return False
    book = capture_benchmark(book, prices.get("BTC"))
    snap = valuation(book, prices, prices.get("BTC"), _hour_stamp(now))
    persist_lane_step(db, book, updated_at=now.isoformat(timespec="seconds"),
                      trades=fills, valuation=snap, state=markers)
    print(f"Crypto: Equity {snap.equity:,.2f} ({snap.total_return:+.2%}) vs BTC "
          f"{snap.benchmark_return:+.2%} — {len(book.positions)} offen, {len(fills)} Fills"
          if snap.benchmark_return is not None else
          f"Crypto: Equity {snap.equity:,.2f} ({snap.total_return:+.2%}), "
          f"{len(book.positions)} offen, {len(fills)} Fills")
    _print_fills(fills)
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lane", required=True, choices=("swing", "session", "crypto"))
    ap.add_argument("--db", default=DEFAULT_SHORTTERM_DB_PATH, help="Shortterm DB path.")
    ap.add_argument("--main-db", default=DEFAULT_DB_PATH, help="Main DB (events).")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    print(f"\nKurzfrist-Arena — Lane '{args.lane}' ({now.isoformat(timespec='seconds')})\n")
    if args.lane == "swing":
        run_swing(args.db, args.main_db, now=now)
    elif args.lane == "session":
        run_session(args.db, now=now)
    elif run_crypto(args.db, now=now):
        # heartbeat only on a live advance: a dead feed must LOOK dead (v12 W1)
        record_heartbeat(args.main_db, "crypto", now=now.isoformat())
    print(f"\n{DISCLAIMER}\n")


if __name__ == "__main__":
    main()
