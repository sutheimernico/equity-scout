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
import contextlib
import io
import json
import os
import sys
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from equity_scout.alpaca_broker import (
    AlpacaBrokerError,
    await_fill,
    close_position,
    fetch_account,
    fetch_fills,
)
from equity_scout.alpaca_broker import fetch_positions as fetch_broker_positions
from equity_scout.alpaca_broker import (
    fetch_order,
    place_auction_order,
    place_bracket,
    settle_or_cancel,
)
from equity_scout.alpaca_data import (
    RANGE_BAR_MINUTES,
    TRIGGER_BAR_MINUTES,
    complete_bars,
    regular_session_bars,
)
from equity_scout.alpaca_data import fetch_bars as alpaca_fetch_bars
from equity_scout.alpaca_data import AlpacaDataError, fetch_latest_trades
from equity_scout.tracked_tickers import tracked_tickers
from equity_scout.constants import DEFAULT_DB_PATH, DISCLAIMER
from equity_scout.data.etf_panel import load_price_history
from equity_scout.evidence.event_storage import load_classified_events
from equity_scout.intraday_bars import SESSION_UNIVERSE, fetch_bars, settled_bars
from equity_scout.kraken_data import (
    CRYPTO_PAIRS,
    DAILY_INTERVAL_MINUTES,
    completed_bars,
    fetch_ohlc,
)
from equity_scout.market_hours import within_market_window
from equity_scout.shortterm_book import (
    LaneBook,
    buy,
    capture_benchmark,
    sell,
    valuation,
)
from equity_scout.session_reconcile import reconcile, resolve_book_only
from equity_scout.shortterm_storage import (
    DEFAULT_SHORTTERM_DB_PATH,
    clear_lane_state,
    get_lane_state,
    load_book,
    persist_lane_step,
    record_execution,
    record_rejections,
    set_lane_state,
)
from equity_scout.state_storage import record_heartbeat
from equity_scout.st_crypto import ENTRY_FRACTION as CRYPTO_FRACTION
from equity_scout.st_crypto import decide_pair
from equity_scout.st_session import ENTRY_FRACTION as SESSION_FRACTION
from equity_scout.st_session import (
    STOP_RANGE_MULT,
    TARGET_RANGE_MULT,
    SessionAction,
    decide,
    opening_range,
)
from equity_scout.exits import ExitRules
from equity_scout.lane_params import load_params
from equity_scout.st_gapfade import ENTRY_FRACTION as GAPFADE_FRACTION
from equity_scout.st_gapfade import pick_gap_entries
from equity_scout.st_swing import ENTRY_FRACTION as SWING_FRACTION
from equity_scout.st_swing import (
    MAX_HOLDING_CALENDAR_DAYS,
    MAX_POSITIONS,
    PROFIT_TARGET,
    STOP_LOSS,
    check_exits,
    pick_entries,
    pick_entries_explained,
)

SWING_SNAPSHOT = "data/prices/st_swing_panel.csv"
CRYPTO_SLIPPAGE_BPS = 10.0
# Kraken Pro spot taker, lowest tier (<$5M 30-day volume), per side — checked 2026-08-09
# (kraken.com/features/fee-schedule). Donchian breakouts fill as market orders, so the taker
# rate is the honest floor; DEFAULT_FEE_BPS=0 is a stock-broker fact that never applied here.
CRYPTO_FEE_BPS = 80.0
EVENTS_SEEN_KEY = "events_seen_until"
SESSION_STATE_KEY = "session_state"
# Set when a lane's STRATEGY changed under it (crypto: 15-minute -> daily bars, 2026-08-10).
# Sibling of EXECUTION_REGIME_KEY, which marks a change in how fills were obtained.
STRATEGY_REGIME_KEY = "strategy_regime"


def _hour_stamp(now: datetime) -> str:
    return now.replace(minute=0, second=0, microsecond=0).isoformat(timespec="minutes")


def _print_fills(fills: list) -> None:
    for fill in fills:
        pnl = f"  P&L {fill.realized_pnl:+,.2f}" if fill.realized_pnl is not None else ""
        print(f"  {fill.side.upper():<5} {fill.ticker:<8} @ {fill.price:,.2f}  ({fill.reason}){pnl}")


def run_swing(db: str, main_db: str, *, now: datetime) -> None:
    book = load_book(db, "swing") or LaneBook.fresh("swing", benchmark_ticker="SPY")
    # Exit rules come from the database when something has tuned them, from the module
    # constants otherwise (T11, 2026-08-16). Printed whenever they differ from the shipped
    # values: a lane running on rules nobody sees is a track record nobody can read.
    shipped = ExitRules(
        profit_target=PROFIT_TARGET, stop_loss=STOP_LOSS,
        max_holding_days=MAX_HOLDING_CALENDAR_DAYS,
    )
    rules = load_params(db, "swing", default=shipped)
    if rules != shipped:
        print(
            f"Angepasste Regeln aktiv: Ziel {rules.profit_target:.0%}, "
            f"Stop {rules.stop_loss:.0%}, Haltefrist {rules.max_holding_days} Tage "
            f"(Standard: {shipped.profit_target:.0%}/{shipped.stop_loss:.0%}/"
            f"{shipped.max_holding_days})."
        )
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
    for exit_order in check_exits(
        book, prices, today,
        profit_target=rules.profit_target,
        stop_loss=rules.stop_loss,
        max_days=rules.max_holding_days,
    ):
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
    entries, rejections = pick_entries_explained(fresh_events, book, now=now)
    for candidate in entries:
        price = prices.get(candidate["ticker"])
        if not price:
            # event ticker without a quote — honest skip, and a row in the no-trade book
            rejections.append({
                "ticker": candidate["ticker"], "reason": "no_quote",
                "seen_at": candidate["seen_at"], "detail": candidate["reason"],
            })
            continue
        book, fill = buy(book, candidate["ticker"], price, today,
                         fraction=SWING_FRACTION, reason=candidate["reason"])
        if fill:
            fills.append(fill)

    book = capture_benchmark(book, prices.get("SPY"))
    snap = valuation(book, prices, prices.get("SPY"), today)
    marker_state = [(EVENTS_SEEN_KEY, max(e["seen_at"] for e in events))] if events else []
    persist_lane_step(db, book, updated_at=today, trades=fills, valuation=snap,
                      state=marker_state)
    # after the book commit: rejection rows are observability, never worth aborting a
    # persisted step over — and the UNIQUE key keeps a crash-rerun from double-counting
    record_rejections(db, [{**r, "lane": "swing"} for r in rejections])
    print(f"Swing {today}: Equity {snap.equity:,.2f} ({snap.total_return:+.2%}), "
          f"{len(book.positions)} offen, {len(fills)} Fills, "
          f"{len(rejections)} verworfen (Nicht-Trade-Buch)")
    _print_fills(fills)


# --- Gap-fade lane (2026-08-17): pre-market signal -> MOO entry -> MOC exit -------------
GAPFADE_DAY_KEY = "gapfade_signal_day"
GAPFADE_ENTRY_ORDERS_KEY = "gapfade_entry_orders"
GAPFADE_EXIT_ORDERS_KEY = "gapfade_exit_orders"
GAPFADE_SNAPSHOT = "data/prices/st_gapfade_panel.csv"
_NY_TZ = ZoneInfo("America/New_York")
# Alpaca accepts opg orders until ~09:28 ET; signalling earlier than 09:00 would judge
# yesterday's pre-market prints.
GAPFADE_SIGNAL_START = time(9, 0)
GAPFADE_SIGNAL_END = time(9, 28)
_TERMINAL_ORDER_STATES = ("canceled", "expired", "rejected", "done_for_day")


def _gapfade_load_orders(db: str, key: str) -> list[dict]:
    raw = get_lane_state(db, "gapfade", key)
    return json.loads(raw) if raw else []


def _gapfade_signals(db: str, main_db: str, book: LaneBook, *, now: datetime) -> None:
    """Phase 1, once per day inside the window: signal, size, submit MOO, log rejections.

    The day marker is set BEFORE the first submission (fail-closed): a crash between
    order and marker must cost the day, never place the same auction order twice."""
    et = now.astimezone(_NY_TZ)
    tickers = sorted(tracked_tickers(main_db))
    if not tickers:
        set_lane_state(db, "gapfade", GAPFADE_DAY_KEY, et.date().isoformat())
        print("Gap-Fade: keine getrackten Ticker — heute nichts zu prüfen.")
        return
    start = (now - timedelta(days=10)).date().isoformat()
    panel = load_price_history(sorted({*tickers, "SPY"}), start=start,
                               snapshot=GAPFADE_SNAPSHOT, refresh=True)
    prev_closes: dict[str, float] = {}
    for ticker in panel.tickers:
        closes = panel.closes[ticker].dropna()
        # rows stamped today (a half-written daily bar) must not serve as "yesterday"
        closes = closes[closes.index.date < et.date()]
        if len(closes):
            prev_closes[ticker] = float(closes.iloc[-1])
    try:
        premarket = fetch_latest_trades(tickers)
    except (AlpacaDataError, AlpacaBrokerError, OSError) as error:
        # no day marker: the 5-minute cron retries inside the window
        print(f"Gap-Fade: Pre-Market-Kurse nicht lesbar ({error}) — nächster Versuch in 5 Min.",
              file=sys.stderr)
        return
    picks, rejections = pick_gap_entries(premarket, prev_closes, book, now=now, traded=set())
    set_lane_state(db, "gapfade", GAPFADE_DAY_KEY, et.date().isoformat())
    record_rejections(db, [{**r, "lane": "gapfade"} for r in rejections])
    entry_orders = _gapfade_load_orders(db, GAPFADE_ENTRY_ORDERS_KEY)
    for pick in picks:
        qty = int(GAPFADE_FRACTION * book.cash / pick["signal_price"])
        if qty < 1:
            print(f"Gap-Fade: {pick['ticker']} unter einer ganzen Aktie — übersprungen.")
            continue
        try:
            order = place_auction_order(pick["ticker"], qty=qty, side="buy", auction="opg")
        except AlpacaBrokerError as error:
            print(f"Gap-Fade: Order abgelehnt ({pick['ticker']}): {error}", file=sys.stderr)
            continue
        entry_orders.append({
            "order_id": order.order_id, "ticker": pick["ticker"],
            "signal_price": pick["signal_price"], "reason": pick["reason"],
            "signalled_at": now.isoformat(timespec="seconds"),
        })
    set_lane_state(db, "gapfade", GAPFADE_ENTRY_ORDERS_KEY, json.dumps(entry_orders))
    print(f"Gap-Fade {et.date().isoformat()}: {len(entry_orders)} MOO platziert, "
          f"{len(rejections)} verworfen (Nicht-Trade-Buch).")


def _gapfade_absorb_entries(db: str, book: LaneBook, *, now: datetime) -> LaneBook:
    """Phase 2: read the auction fills back. The signal-vs-fill drift in st_executions is
    the lane's core measurement; the exit is handed to a market-on-close order at once,
    so no later run has to be awake at 16:00 ET to get out."""
    orders = _gapfade_load_orders(db, GAPFADE_ENTRY_ORDERS_KEY)
    if not orders:
        return book
    remaining: list[dict] = []
    fills = []
    exit_orders = _gapfade_load_orders(db, GAPFADE_EXIT_ORDERS_KEY)
    for entry in orders:
        try:
            order = fetch_order(entry["order_id"])
        except (AlpacaBrokerError, OSError) as error:
            print(f"Gap-Fade: Order {entry['order_id']} nicht lesbar ({error}).", file=sys.stderr)
            remaining.append(entry)
            continue
        if order.filled_qty and order.filled_avg_price is not None:
            book, fill = buy(book, entry["ticker"], order.filled_avg_price,
                             now.isoformat(timespec="seconds"), fraction=GAPFADE_FRACTION,
                             reason=entry["reason"], slippage_bps=0.0, qty=order.filled_qty)
            record_execution(db, lane="gapfade", ticker=entry["ticker"], side="buy",
                             signalled_at=entry["signalled_at"],
                             expected_price=entry["signal_price"],
                             actual_price=order.filled_avg_price, qty=order.filled_qty,
                             order_id=order.order_id)
            if fill:
                fills.append(fill)
            try:
                close = place_auction_order(entry["ticker"], qty=order.filled_qty,
                                            side="sell", auction="cls")
                exit_orders.append({
                    "order_id": close.order_id, "ticker": entry["ticker"],
                    "signalled_at": now.isoformat(timespec="seconds"),
                })
            except AlpacaBrokerError as error:
                print(f"Gap-Fade: MOC-Order fehlgeschlagen ({entry['ticker']}): {error} — "
                      f"nächster Lauf versucht es erneut.", file=sys.stderr)
                exit_orders.append({"order_id": None, "ticker": entry["ticker"],
                                    "signalled_at": now.isoformat(timespec="seconds")})
        elif order.status in _TERMINAL_ORDER_STATES:
            print(f"Gap-Fade: {entry['ticker']} in der Auktion nicht gefüllt "
                  f"(status={order.status}).")
        else:
            remaining.append(entry)
    persist_lane_step(
        db, book, updated_at=now.isoformat(timespec="seconds"), trades=fills,
        state=[(GAPFADE_ENTRY_ORDERS_KEY, json.dumps(remaining)),
               (GAPFADE_EXIT_ORDERS_KEY, json.dumps(exit_orders))],
    )
    _print_fills(fills)
    return book


def _gapfade_settle_exits(db: str, book: LaneBook, *, now: datetime) -> LaneBook:
    """Phase 3 (typically the nightly): the closing-auction fill flattens the book. An
    exit order that died without filling gets a fresh MOC for the next session — a
    position must never linger because its order went terminal."""
    orders = _gapfade_load_orders(db, GAPFADE_EXIT_ORDERS_KEY)
    if not orders:
        return book
    remaining: list[dict] = []
    fills = []
    for exit_entry in orders:
        position = book.positions.get(exit_entry["ticker"])
        if position is None:
            continue  # already settled by an earlier run
        order = None
        if exit_entry.get("order_id"):
            try:
                order = fetch_order(exit_entry["order_id"])
            except (AlpacaBrokerError, OSError) as error:
                print(f"Gap-Fade: Exit-Order {exit_entry['order_id']} nicht lesbar "
                      f"({error}).", file=sys.stderr)
                remaining.append(exit_entry)
                continue
        if order is not None and order.filled_qty and order.filled_avg_price is not None:
            book, fill = sell(book, exit_entry["ticker"], order.filled_avg_price,
                              now.isoformat(timespec="seconds"),
                              reason="Schlussauktion (Market-on-Close)", slippage_bps=0.0)
            record_execution(db, lane="gapfade", ticker=exit_entry["ticker"], side="sell",
                             signalled_at=exit_entry["signalled_at"],
                             # a market-on-close carries no expectation to measure against
                             expected_price=order.filled_avg_price,
                             actual_price=order.filled_avg_price, qty=order.filled_qty,
                             order_id=order.order_id)
            if fill:
                fills.append(fill)
        elif order is None or order.status in _TERMINAL_ORDER_STATES:
            try:
                fresh = place_auction_order(exit_entry["ticker"], qty=position.qty,
                                            side="sell", auction="cls")
                remaining.append({"order_id": fresh.order_id, "ticker": exit_entry["ticker"],
                                  "signalled_at": now.isoformat(timespec="seconds")})
                print(f"Gap-Fade: Exit {exit_entry['ticker']} neu platziert "
                      f"(alte Order terminal).", file=sys.stderr)
            except AlpacaBrokerError as error:
                print(f"Gap-Fade: Exit-Neuplatzierung fehlgeschlagen "
                      f"({exit_entry['ticker']}): {error}.", file=sys.stderr)
                remaining.append(exit_entry)
        else:
            remaining.append(exit_entry)
    today = now.isoformat(timespec="seconds")
    book = capture_benchmark(book, None)
    snap = valuation(book, {}, None, today) if fills else None
    persist_lane_step(
        db, book, updated_at=today, trades=fills, valuation=snap,
        state=[(GAPFADE_EXIT_ORDERS_KEY, json.dumps(remaining))],
    )
    _print_fills(fills)
    return book


def run_gapfade(db: str, main_db: str, *, now: datetime) -> None:
    """The gap-fade measurement lane, phase-dispatched by wall clock (see st_gapfade's
    module docstring for the evidence trail and the honesty boundary)."""
    et = now.astimezone(_NY_TZ)
    book = load_book(db, "gapfade") or LaneBook.fresh("gapfade", benchmark_ticker="SPY")
    # Old business first, and strictly before new: an order placed in THIS run is only
    # ever read back by the NEXT run — polling it seconds after submission would burn a
    # request on an answer that cannot exist yet.
    book = _gapfade_settle_exits(db, book, now=now)
    book = _gapfade_absorb_entries(db, book, now=now)
    in_window = et.weekday() < 5 and GAPFADE_SIGNAL_START <= et.time() <= GAPFADE_SIGNAL_END
    already_signalled = get_lane_state(db, "gapfade", GAPFADE_DAY_KEY) == et.date().isoformat()
    if in_window and not already_signalled:
        _gapfade_signals(db, main_db, book, now=now)


MAX_RUN_GAP = timedelta(minutes=5)
LAST_RUN_KEY = "last_session_run"
# Stamped once, on the first fill that came from the broker rather than from a simulation.
# Everything before it was priced off delayed bars and is therefore too favourable — the
# dashboard says so rather than splicing the two track records together silently.
EXECUTION_REGIME_KEY = "execution_regime"


def _broker_equity(feed: str) -> float | None:
    """The venue's own account equity, or None when it cannot be had.

    Recorded alongside the book's equity because the two answer different questions on
    different denominators: the book runs a 10k strategy ledger, the paper account holds
    100k, so the same trades read as -2.41% and -0.10% (measured 2026-08-10). A broker
    hiccup must never cost the lane its valuation row, hence None over raising.
    """
    if feed != "alpaca":
        return None
    try:
        return fetch_account().equity
    except (AlpacaBrokerError, OSError) as error:
        print(f"Warnung: Konto-Equity nicht abrufbar ({error}) — Buchwert bleibt allein.")
        return None


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


def _session_bars(tickers: list[str], *, now: datetime, feed: str) -> tuple[dict, dict, object]:
    """(trigger bars, range bars, gate) for the requested feed.

    Alpaca answers two resolutions — 1-minute bars carry the breakout trigger, 15-minute bars
    build the opening range (design decision 5) — and BOTH are cut down to the current regular
    session first: `opening_range` reads the first two bars it is handed, so an unfiltered
    Alpaca frame would hand it a thin pre-market range and every stop and target would follow
    from that. yfinance gets this for free (period="1d", prepost off) and keeps one resolution.
    """
    if feed != "alpaca":
        bars = fetch_bars(tickers)
        return bars, bars, lambda frame: settled_bars(frame, now)
    trigger = {
        ticker: regular_session_bars(frame)
        for ticker, frame in alpaca_fetch_bars(
            tickers, now=now, bar_minutes=TRIGGER_BAR_MINUTES
        ).items()
    }
    ranges = {
        ticker: regular_session_bars(frame)
        for ticker, frame in alpaca_fetch_bars(
            tickers, now=now, bar_minutes=RANGE_BAR_MINUTES
        ).items()
    }
    return (
        {ticker: frame for ticker, frame in trigger.items() if not frame.empty},
        ranges,
        lambda frame: complete_bars(frame, now, bar_minutes=TRIGGER_BAR_MINUTES),
    )


def _opening_range_of(bars, *, now: datetime, feed: str) -> tuple[float, float] | None:
    """The opening range from the resolution that owns it, gated by that resolution's own
    completeness rule (a 15-minute bar is complete 15 minutes after it started, not 1)."""
    if bars is None or bars.empty:
        return None
    gated = (
        complete_bars(bars, now, bar_minutes=RANGE_BAR_MINUTES)
        if feed == "alpaca"
        else settled_bars(bars, now)
    )
    return opening_range(gated)


def _open_position(db: str, book: LaneBook, action, *, or_range: tuple[float, float],
                   feed: str) -> tuple[LaneBook, object]:
    """Size locally, then either route the order to the broker or book it simulated.

    On the Alpaca path the fill price comes from the BROKER and no slippage is modelled on
    top of it — the broker price already contains the real thing, and booking the estimate as
    well would charge the lane twice for the same cost.
    """
    if feed != "alpaca":
        return buy(book, action.ticker, action.price, action.at,
                   fraction=SESSION_FRACTION, reason=action.reason)

    or_high, or_low = or_range
    range_size = or_high - or_low
    # Size against a probe book, so a rejected order leaves the real book untouched.
    probe, _ = buy(book, action.ticker, action.price, action.at,
                   fraction=SESSION_FRACTION, reason=action.reason)
    intended = probe.positions.get(action.ticker)
    if intended is None:
        return book, None
    try:
        order = place_bracket(
            action.ticker,
            qty=intended.qty,
            stop_price=action.price - STOP_RANGE_MULT * range_size,
            target_price=action.price + TARGET_RANGE_MULT * range_size,
        )
    except AlpacaBrokerError as error:
        print(f"Order abgelehnt ({action.ticker}): {error}", file=sys.stderr)
        return book, None
    # The POST answers `pending_new` even when the fill is milliseconds away, so the fill is
    # read back; an order that still has not filled is cancelled rather than left resting.
    order = settle_or_cancel(order)
    if not order.filled_qty or order.filled_avg_price is None:
        print(f"Order {order.order_id} ({action.ticker}) nicht ausgefuehrt "
              f"(status={order.status}) — storniert, Buch bleibt flat.", file=sys.stderr)
        return book, None
    record_execution(db, lane="session", ticker=action.ticker, side="buy",
                     signalled_at=action.at, expected_price=action.price,
                     actual_price=order.filled_avg_price, qty=order.filled_qty,
                     order_id=order.order_id)
    if get_lane_state(db, "session", EXECUTION_REGIME_KEY) is None:
        set_lane_state(db, "session", EXECUTION_REGIME_KEY, action.at)
    # The broker's quantity, not the ratio's: Alpaca rounds a bracket down to whole shares,
    # and a book holding more than the broker does is the divergence this design prevents.
    return buy(book, action.ticker, order.filled_avg_price, action.at,
               fraction=SESSION_FRACTION, reason=action.reason, slippage_bps=0.0,
               qty=order.filled_qty)


def _close_position(db: str, book: LaneBook, action, *, feed: str) -> tuple[LaneBook, object]:
    """Exits on the Alpaca path may already have happened in the market — the bracket legs
    fire without us. Closing is therefore best-effort: a 'position not found' is the normal
    case after a stop or target triggered, not an error."""
    if feed != "alpaca":
        return sell(book, action.ticker, action.price, action.at, reason=action.reason)
    price = action.price
    try:
        # The flatten answers `pending_new` too — read the real exit price back rather than
        # booking the signal price (which is how the 2026-08-06 cleanup recorded five exits at
        # their own entry price). No cancel on this path: an exit has to go through.
        order = await_fill(close_position(action.ticker))
        price = order.filled_avg_price or action.price
        record_execution(db, lane="session", ticker=action.ticker, side="sell",
                         signalled_at=action.at, expected_price=action.price,
                         actual_price=order.filled_avg_price, qty=order.filled_qty,
                         order_id=order.order_id)
    except AlpacaBrokerError as error:
        print(f"Schliessen ueber Broker fehlgeschlagen ({action.ticker}): {error} — "
              f"Buch wird zum Signalpreis geschlossen, Abweichung im naechsten Abgleich.",
              file=sys.stderr)
    return sell(book, action.ticker, price, action.at, reason=action.reason, slippage_bps=0.0)


def _absorb_broker_exits(db: str, book: LaneBook, *, now: datetime) -> LaneBook:
    """Report every divergence, and book back the ones the broker can explain.

    The bracket legs fire in the market without us — that is why they are there (2026-07-21:
    the machine was down for two days). The consequence stayed unhandled until 2026-08-07:
    when a stop leg filled, the book went on holding a position the broker no longer had, and
    when our own bars finally produced the exit signal, `_close_position` got a 404 and booked
    the SIGNAL price. All six stop exits of that day were booked that way, every one of them
    better than the market gave.

    So the fill is read back from the order history and booked as what it is. This does not
    weaken the broker-is-truth rule, it applies it: an unexplained divergence still only gets
    reported, and nothing here ever moves the broker's side.
    """
    fills = []
    for divergence in reconcile(book, fetch_broker_positions()):
        print(f"ABWEICHUNG {divergence.describe()} — Buch und Broker laufen auseinander.",
              file=sys.stderr)
        position = book.positions.get(divergence.ticker)
        if position is None:
            continue
        try:
            history = fetch_fills(divergence.ticker, after=position.opened_at)
        except AlpacaBrokerError as error:
            # Loud: a failed lookup is not "no fill found", and the difference decides
            # whether the position below is a ghost or real.
            print(f"Fill-Historie ({divergence.ticker}) nicht lesbar: {error} — "
                  f"Abweichung bleibt offen.", file=sys.stderr)
            continue
        exit_ = resolve_book_only(divergence, history, opened_at=position.opened_at)
        if exit_ is None:
            continue
        book, fill = sell(book, exit_.ticker, exit_.price, exit_.at,
                          reason="Broker-Bracket (nachgebucht)", slippage_bps=0.0)
        if fill is None:
            continue
        record_execution(db, lane="session", ticker=exit_.ticker, side="sell",
                         signalled_at=exit_.at,
                         # The leg's own price is the expectation; without one there is
                         # nothing to measure against and the fill stands for itself.
                         # Absence, not falsiness — as in `parse_order`.
                         expected_price=(exit_.price if exit_.requested_price is None
                                         else exit_.requested_price),
                         actual_price=exit_.price, qty=exit_.qty,
                         order_id=exit_.order_ids[-1])
        fills.append(fill)
        print(f"Nachgebucht: {exit_.ticker} {exit_.qty:g} @ {exit_.price:.4f} "
              f"(Broker-Bracket, {exit_.at}).", file=sys.stderr)
    if fills:
        # Persisted here rather than handed to the caller's step: a run that finds no bars
        # returns before that step, and a booked exit must not depend on the feed being up.
        persist_lane_step(db, book, updated_at=now.isoformat(timespec="seconds"), trades=fills)
    return book


def _session_overnight_sweep(db: str, book: LaneBook, *, now: datetime,
                             feed: str = "yfinance") -> None:
    """Flatten anything still open once the session is over. The last session bar (15:45 ET)
    is not yet 'settled' when the final intraday run fires, so a position entered late can
    slip past the in-session force-flat — this sweep (called by the nightly chain) closes it
    at the last settled close. The lane must NEVER hold overnight.

    Goes through the broker on the Alpaca path: flattening the book while the broker keeps the
    position is exactly the divergence this design exists to prevent."""
    all_bars, _, gate = _session_bars(list(book.positions), now=now, feed=feed)
    fills = []
    prices: dict[str, float] = {}
    for ticker in list(book.positions):
        bars = all_bars.get(ticker)
        settled = gate(bars) if bars is not None else None
        if settled is None or settled.empty:
            continue  # no price, no trade — retried on the next sweep
        price = float(settled["close"].iloc[-1])
        prices[ticker] = price
        book, fill = _close_position(
            db, book,
            SessionAction("sell", ticker, price, settled.index[-1].isoformat(),
                          "Session-Ende (Nachlauf)"),
            feed=feed,
        )
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
    book: LaneBook, all_bars: dict, session_date: str, now: datetime, gate=None,
) -> tuple[LaneBook, list]:
    """Close any position carried over from a previous day BEFORE decide() runs (P0,
    review 2026-07-20): after an outage the overnight sweep may never have fired, and
    decide() would otherwise manage the stale position with TODAY's opening range —
    stop/target become arbitrary. Fill = open of today's first settled bar (the first
    knowable price of the session); no bars yet -> left for a later run / the sweep."""
    gate = gate or (lambda frame: settled_bars(frame, now))
    fills = []
    for ticker, position in list(book.positions.items()):
        if position.opened_at[:10] == session_date:
            continue
        bars = all_bars.get(ticker)
        settled = gate(bars) if bars is not None else None
        if settled is None or settled.empty:
            continue
        book, fill = sell(book, ticker, float(settled["open"].iloc[0]),
                          settled.index[0].isoformat(), reason="Altbestand (zwangsflat)")
        if fill:
            fills.append(fill)
    return book, fills


def run_session(db: str, *, now: datetime, feed: str = "alpaca") -> None:
    """One session-lane step. `feed="alpaca"` routes real bracket orders on the paper account
    and books the BROKER's fill price; `feed="yfinance"` is the old, delayed, simulated path,
    kept reachable so a broken key degrades the lane loudly instead of stopping it."""
    if feed == "alpaca" and not os.getenv("ALPACA_API_KEY_ID"):
        print("WARN Alpaca-Keys fehlen — Session-Lane faellt auf yfinance zurueck "
              "(verzoegerte Bars, Executability-Bias).", file=sys.stderr)
        feed = "yfinance"

    if not within_market_window(now):
        book = load_book(db, "session")
        if book is not None and book.positions:
            if feed == "alpaca":
                # Before the sweep, for the same reason as in-session: a position the broker
                # already stopped out would otherwise be "flattened" at the last bar's close,
                # against a broker that answers 404 (measured 2026-08-07).
                book = _absorb_broker_exits(db, book, now=now)
            if book.positions:
                _session_overnight_sweep(db, book, now=now, feed=feed)
        # Silent otherwise: outside the window with a flat book is the normal state for
        # most of the day, and on a one-minute cron it would be ~1,380 lines of it.
        return
    book = load_book(db, "session") or LaneBook.fresh("session", benchmark_ticker="SPY")
    state = json.loads(get_lane_state(db, "session", SESSION_STATE_KEY) or "{}")
    # include held tickers: a stale position must be flattenable even if it left the universe
    tickers = sorted({*SESSION_UNIVERSE, *book.positions})
    all_bars, range_bars, gate = _session_bars(tickers, now=now, feed=feed)
    if feed == "alpaca":
        # The broker is the truth. Runs BEFORE the stale-position flatten and before decide():
        # a position the broker already closed must not be managed, force-flattened at today's
        # open, or exited a second time on our own bars.
        book = _absorb_broker_exits(db, book, now=now)
    if not all_bars:
        print("Keine Intraday-Bars verfügbar — Lauf übersprungen.")
        return

    may_open = may_open_new_position(
        last_run=get_lane_state(db, "session", LAST_RUN_KEY), now=now
    )
    if not may_open:
        print("Lücke seit dem letzten Lauf — nur Bestandsführung, keine neuen Einstiege.",
              file=sys.stderr)

    session_date = next(iter(all_bars.values())).index[0].date().isoformat()
    first_run_of_day = state.get("date") != session_date
    if first_run_of_day:
        state = {"date": session_date, "last_bar": {}, "ranges": {}, "traded": []}

    book, fills = _flatten_stale_positions(book, all_bars, session_date, now, gate=gate)
    prices: dict[str, float] = {}
    for ticker, bars in all_bars.items():
        settled = gate(bars)
        if settled.empty:
            continue
        prices[ticker] = float(settled["close"].iloc[-1])
        # The range comes from the 15-minute bars on the Alpaca path, the trigger from the
        # 1-minute bars above — mixing them up would build the range from one minute of trade.
        or_range = state["ranges"].get(ticker) or _opening_range_of(
            range_bars.get(ticker), now=now, feed=feed
        )
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
                if not may_open:
                    continue
                book, fill = _open_position(db, book, action, or_range=tuple(or_range),
                                            feed=feed)
                if fill:
                    state["traded"].append(ticker)
            elif action.ticker in book.positions:
                book, fill = _close_position(db, book, action, feed=feed)
            else:
                # `decide` emits buy AND sell for an entry bar that trades through its own
                # stop. If the entry was dropped (run gap, rejected order), its exit must be
                # dropped too — routing it asked the broker to close a position that was never
                # opened (live run 2026-08-06: 404 position not found: SPY).
                continue
            if fill:
                fills.append(fill)
        if new_marker:
            state["last_bar"][ticker] = new_marker

    book = capture_benchmark(book, prices.get("SPY"))
    snap = valuation(book, prices, prices.get("SPY"), _hour_stamp(now),
                     broker_equity=_broker_equity(feed))
    persist_lane_step(db, book, updated_at=now.isoformat(timespec="seconds"),
                      trades=fills, valuation=snap,
                      state=[(SESSION_STATE_KEY, json.dumps(state)),
                             (LAST_RUN_KEY, now.isoformat())])
    if session_report_due(fills=fills, first_run_of_day=first_run_of_day):
        print(f"Session {session_date}: Equity {snap.equity:,.2f} ({snap.total_return:+.2%}), "
              f"{len(book.positions)} offen, {len(fills)} Fills")
        if snap.broker_equity is not None:
            # Both numbers or neither: quoting only the book's percentage next to a live
            # broker account overstates the account's return by the capital-usage factor.
            print(f"  Konto (Alpaca): {snap.broker_equity:,.2f} USD — das Buch rechnet auf "
                  f"{book.initial_capital:,.0f}, das Konto ist der volle Rahmen.")
        _print_fills(fills)


def run_crypto(db: str, *, now: datetime, fetch=fetch_ohlc) -> bool:
    book = load_book(db, "crypto") or LaneBook.fresh("crypto", benchmark_ticker="BTC")
    fills = []
    markers: list[tuple[str, str]] = []
    prices: dict[str, float] = {}
    # Stamped once, when the lane first runs on the daily timescale. The 15-minute track
    # before it lost ~460 USD in fees on 32 trades and is NOT the same series — the cockpit
    # says so rather than splicing two strategies into one curve.
    if get_lane_state(db, "crypto", STRATEGY_REGIME_KEY) is None:
        markers.append((STRATEGY_REGIME_KEY, now.isoformat(timespec="seconds")))
        # The old markers belong to the old timescale: a 15-minute watermark is NEWER than
        # the newest completed daily bar, so leaving them would block every decision until
        # the wall clock passed them (measured on the first daily run, 2026-08-10).
        dropped = clear_lane_state(db, "crypto", "last_bar_")
        if dropped:
            print(f"Zeitskala gewechselt: {dropped} Bar-Marker der 15-Minuten-Ära verworfen.")
    for symbol, pair in CRYPTO_PAIRS.items():
        raw = fetch(pair, interval=DAILY_INTERVAL_MINUTES)
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
                                 fee_bps=CRYPTO_FEE_BPS, slippage_bps=CRYPTO_SLIPPAGE_BPS)
            else:
                book, fill = sell(book, symbol, action.price, action.at,
                                  reason=action.reason, fee_bps=CRYPTO_FEE_BPS,
                                  slippage_bps=CRYPTO_SLIPPAGE_BPS)
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
    print(f"Crypto (Tagesbars): Equity {snap.equity:,.2f} ({snap.total_return:+.2%}) vs BTC "
          f"{snap.benchmark_return:+.2%} — {len(book.positions)} offen, {len(fills)} Fills"
          if snap.benchmark_return is not None else
          f"Crypto (Tagesbars): Equity {snap.equity:,.2f} ({snap.total_return:+.2%}), "
          f"{len(book.positions)} offen, {len(fills)} Fills")
    _print_fills(fills)
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lane", required=True, choices=("swing", "session", "crypto", "gapfade"))
    ap.add_argument("--db", default=DEFAULT_SHORTTERM_DB_PATH, help="Shortterm DB path.")
    ap.add_argument("--main-db", default=DEFAULT_DB_PATH, help="Main DB (events).")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    header = f"\nKurzfrist-Arena — Lane '{args.lane}' ({now.isoformat(timespec='seconds')})\n"
    if args.lane == "session":
        # The session lane runs every minute, and most of those minutes decide nothing. The
        # header and the disclaimer are framing, not content: printed unconditionally they add
        # ~3,000 lines a day to session.log, which is how two production bugs stayed invisible
        # in intraday.log. Warnings go to stderr and are therefore never swallowed here.
        body = io.StringIO()
        with contextlib.redirect_stdout(body):
            run_session(args.db, now=now)
        if body.getvalue().strip():
            print(header)
            print(body.getvalue(), end="")
            print(f"\n{DISCLAIMER}\n")
        return

    if args.lane == "gapfade":
        # Same silence discipline as the session lane: the 5-minute cron produces mostly
        # no-op runs, and only a run that actually said something earns a log block.
        body = io.StringIO()
        with contextlib.redirect_stdout(body):
            run_gapfade(args.db, args.main_db, now=now)
        if body.getvalue().strip():
            print(header)
            print(body.getvalue(), end="")
            print(f"\n{DISCLAIMER}\n")
        return

    print(header)
    if args.lane == "swing":
        run_swing(args.db, args.main_db, now=now)
    elif run_crypto(args.db, now=now):
        # heartbeat only on a live advance: a dead feed must LOOK dead (v12 W1)
        record_heartbeat(args.main_db, "crypto", now=now.isoformat())
    print(f"\n{DISCLAIMER}\n")


if __name__ == "__main__":
    main()
