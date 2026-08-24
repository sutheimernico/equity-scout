"""CLI: advance the ignition lane (v16, layer 4) — ride a verified catalyst move.

Reads the signals the catalyst scan wrote (`catalysts.db`), enters with LIMIT bracket orders
on Alpaca paper, manages trailing exits, and books everything in the short-term arena's own
tables so the cockpit and the nightly review see it like any other lane.

Own runner rather than a `--lane ignition` arm of run_shortterm.py: that file is 930 lines
serving four lanes with three different data feeds, and this lane's inputs (the catalyst
signal book) and order type (limit bracket) are shared with none of them. The lane is
registered in shortterm_storage.LANES, so everything downstream still treats it as a
first-class lane.

PAPER ONLY. Whether this survives its costs is what the lane exists to measure — after 60
closed trades `significance.assess_trades` decides, and a "negativ" verdict ends it.

Usage:
    uv run python scripts/run_ignition_lane.py [--dry-run] [--force]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from equity_scout.alpaca_broker import (
    AlpacaBrokerError,
    BrokerOrder,
    close_position,
    place_limit_bracket,
    settle_or_cancel,
)
from equity_scout.alpaca_screener import AlpacaScreenerError, fetch_quotes, fetch_snapshots
from equity_scout.catalyst_storage import (
    DEFAULT_CATALYST_DB_PATH,
    SOURCE_SCAN,
    init_catalyst_db,
    load_signals,
    mark_traded,
)
from equity_scout.constants import DEFAULT_DB_PATH, DISCLAIMER
from equity_scout.market_hours import within_market_window
from equity_scout.shortterm_book import LaneBook, buy, sell, valuation
from equity_scout.shortterm_storage import (
    DEFAULT_SHORTTERM_DB_PATH,
    get_lane_state,
    load_book,
    load_trades,
    persist_lane_step,
    record_execution,
    record_rejections,
)
from equity_scout.significance import assess_trades
from equity_scout.st_ignition import (
    ENTRY_FRACTION,
    LANE,
    MAX_HOLD_DAYS,
    market_closing_soon,
    pick_entries,
    pick_exits,
    stop_criterion_reached,
    update_high_water,
)
from equity_scout.state_storage import record_heartbeat

INITIAL_CAPITAL = 10_000.0
BENCHMARK_TICKER = "SPY"
HIGH_WATER_KEY = "high_water"
ENTRIES_TODAY_KEY = "entries_on"


def _load_high_water(db_path: str) -> dict[str, float]:
    raw = get_lane_state(db_path, LANE, HIGH_WATER_KEY)
    if not raw:
        return {}
    import json
    try:
        return {k: float(v) for k, v in json.loads(raw).items()}
    except (ValueError, AttributeError):
        return {}


def bookable(settled: BrokerOrder) -> tuple[float, float] | None:
    """(qty, price) to book from a SETTLED order, or None when there is nothing to book.

    `settle_or_cancel` has already awaited, cancelled whatever still rested and re-read the
    order, so its quantity is final even for a partial fill — booking it is what keeps the
    book and the venue holding the same number of shares. The live run of 2026-08-19 booked
    `await_fill`'s intermediate state instead (128 of 141 shares) and discarded the settled
    state entirely when the fill arrived after the poll window (two whole entries, 283
    shares, 3x the intended position).
    """
    if not settled.filled_qty or settled.filled_avg_price is None:
        return None
    return settled.filled_qty, settled.filled_avg_price


def _entries_today(db_path: str, ny_day: str) -> int:
    raw = get_lane_state(db_path, LANE, ENTRIES_TODAY_KEY)
    if not raw or not raw.startswith(ny_day):
        return 0
    try:
        return int(raw.split(":", 1)[1])
    except (IndexError, ValueError):
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalyst-db", default=DEFAULT_CATALYST_DB_PATH)
    parser.add_argument("--shortterm-db", default=DEFAULT_SHORTTERM_DB_PATH)
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="main DB — heartbeat only")
    parser.add_argument("--dry-run", action="store_true",
                        help="decide and print, place no orders and write nothing")
    parser.add_argument("--force", action="store_true",
                        help="ignore the market-window guard (smoke tests)")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    if not args.force and not within_market_window(now):
        return 0

    init_catalyst_db(args.catalyst_db)
    book = load_book(args.shortterm_db, LANE) or LaneBook(
        lane=LANE, initial_capital=INITIAL_CAPITAL, cash=INITIAL_CAPITAL,
        benchmark_ticker=BENCHMARK_TICKER,
    )

    from zoneinfo import ZoneInfo
    ny_day = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    high_water = _load_high_water(args.shortterm_db)
    entries_today = _entries_today(args.shortterm_db, ny_day)

    closed = [t for t in load_trades(args.shortterm_db, LANE, limit=None)
              if t.get("side") == "sell"]
    if stop_criterion_reached(len(closed)):
        verdict = assess_trades([t["realized_pnl"] for t in closed
                                 if t.get("realized_pnl") is not None])
        print(f"Stop-Kriterium erreicht ({len(closed)} geschlossene Trades): "
              f"Urteil {verdict.verdict}")
        if verdict.verdict == "negativ":
            print("Lane beendet — die Einstiegsregel ist an unseren Daten widerlegt.")
            return 0

    # --- signals to act on --------------------------------------------------------------
    signals = [s for s in load_signals(args.catalyst_db, since=ny_day, source=SOURCE_SCAN,
                                       untraded_only=True, limit=50)]
    held = set(book.positions)
    watch = sorted(held | {s["ticker"] for s in signals})

    try:
        quotes = fetch_quotes(watch) if watch else {}
        # SPY always included: without it the lane has no benchmark to be judged against,
        # and "we made 3 %" means nothing without "the market made 4 %".
        snapshots = fetch_snapshots(sorted(held | {BENCHMARK_TICKER}))
    except (AlpacaScreenerError, AlpacaBrokerError) as exc:
        print(f"Datenfehler in der Ignition-Lane: {exc}", file=sys.stderr)
        return 1

    prices = {t: snap["price"] for t, snap in snapshots.items()}
    high_water = update_high_water(high_water, prices, held)

    # --- exits first: freeing a slot may enable an entry in the same pass ----------------
    trades = []
    for exit_order in pick_exits(book, prices, high_water, now=now):
        ticker = exit_order["ticker"]
        if args.dry_run:
            print(f"  [Ausstieg] {ticker}: {exit_order['reason']}")
            continue
        try:
            close_position(ticker)
        except AlpacaBrokerError as exc:
            print(f"Broker lehnte Verkauf {ticker} ab: {exc}", file=sys.stderr)
            continue
        book, fill = sell(book, ticker, exit_order["price"],
                          now.isoformat(timespec="seconds"), reason=exit_order["reason"])
        if fill:
            trades.append(fill)
            print(f"  VERKAUFT {ticker} @ {exit_order['price']:.2f} — "
                  f"{exit_order['reason']}")

    # --- entries -------------------------------------------------------------------------
    traded_today = {t["ticker"] for t in load_trades(args.shortterm_db, LANE, limit=None)
                    if str(t.get("executed_at", "")).startswith(ny_day)}
    picks, rejections = pick_entries(
        signals, quotes, book, now=now, entries_today=entries_today,
        traded_today=traded_today,
    )
    if market_closing_soon(now) and picks:
        print("Kurz vor Handelsschluss — keine neuen Einstiege mehr.")
        picks = []

    traded_signal_ids: list[int] = []
    for pick in picks:
        ticker = pick["ticker"]
        book_value = book.cash + sum(p.qty * p.entry_price for p in book.positions.values())
        qty = int(book_value * ENTRY_FRACTION / pick["limit_price"])
        if qty < 1:
            print(f"  {ticker}: Positionsgröße unter einer Aktie — übersprungen")
            continue
        print(f"  [Einstieg] {ticker} {qty} Stk Limit {pick['limit_price']:.2f} $ "
              f"Stop {pick['stop_price']:.2f} — {pick['reason']}")
        if args.dry_run:
            continue
        try:
            order = place_limit_bracket(
                ticker, qty=qty, limit_price=pick["limit_price"],
                stop_price=pick["stop_price"], target_price=pick["target_price"],
            )
            booked = bookable(settle_or_cancel(order))
            if booked is None:
                print(f"  {ticker}: Limit nicht erreicht — kein Einstieg (das ist ok)")
                continue
            filled_qty, filled_price = booked
        except AlpacaBrokerError as exc:
            print(f"Broker lehnte Einstieg {ticker} ab: {exc}", file=sys.stderr)
            continue
        # Book the BROKER's quantity and price, never our intended ones (live lesson
        # 2026-08-06: Alpaca rounds bracket quantities, and re-deriving them desynced the book).
        book, fill = buy(book, ticker, filled_price,
                         now.isoformat(timespec="seconds"), fraction=ENTRY_FRACTION,
                         reason=pick["reason"], qty=filled_qty)
        if fill:
            trades.append(fill)
            entries_today += 1
            high_water[ticker] = filled_price
            if pick.get("signal_id"):
                traded_signal_ids.append(pick["signal_id"])
            record_execution(
                args.shortterm_db, lane=LANE, ticker=ticker, side="buy",
                signalled_at=now.isoformat(timespec="seconds"),
                expected_price=pick["limit_price"], actual_price=filled_price,
                qty=filled_qty, order_id=order.order_id,
            )
            print(f"  GEKAUFT {ticker} {filled_qty} Stk @ "
                  f"{filled_price:.2f} $ (Limit war {pick['limit_price']:.2f})")

    if args.dry_run:
        for rej in rejections:
            print(f"  [abgelehnt] {rej['ticker']}: {rej['reason']} — {rej['detail']}")
        print("--dry-run: keine Orders, nichts geschrieben.")
        return 0

    # --- persist --------------------------------------------------------------------------
    import json
    snap = valuation(book, prices, created_at=now.isoformat(timespec="seconds"),
                     benchmark_price=prices.get(BENCHMARK_TICKER))
    persist_lane_step(
        args.shortterm_db, book, updated_at=now.isoformat(timespec="seconds"),
        trades=trades, valuation=snap,
        state=[(HIGH_WATER_KEY, json.dumps(high_water)),
               (ENTRIES_TODAY_KEY, f"{ny_day}:{entries_today}")],
    )
    record_rejections(args.shortterm_db, [
        {**r, "lane": LANE, "ref_price": None} for r in rejections
    ])
    mark_traded(args.catalyst_db, traded_signal_ids, now=now.isoformat(timespec="seconds"))
    record_heartbeat(args.db, "ignition_lane", now=now.isoformat(timespec="seconds"))

    print(f"Buch: {len(book.positions)} Positionen, {book.cash:.0f} $ Kasse, "
          f"{len(closed)} geschlossene Trades (Stop-Kriterium bei 60), "
          f"Haltefrist max {MAX_HOLD_DAYS} Tage")
    print(DISCLAIMER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
