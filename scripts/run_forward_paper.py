"""CLI: advance the forward paper accounts one step on the latest prices.

Each v1 strategy runs forward as its own persistent account; since v6 the two ML bots (long +
short) trade here too, but ONLY when their registry family has a promoted champion — the
promotion gate is the single authority, a bot without a demonstrated edge is skipped and says
so. Run this (e.g. daily, or via cron) to roll every account to the newest price and append a
valuation snapshot — the forward, out-of-sample track record that accumulates over real time.
Idempotent: running twice on the same day books nothing new (the valuation is unique per
strategy + date).

PAPER / RESEARCH ONLY. No alpha promise — see the disclaimer. The short account charges a
borrow-cost PROXY and fills at close prices with no borrow-availability model (labelled
simplification); a simulated margin floor force-liquidates at equity <= 0.
"""
from __future__ import annotations

import argparse

from equity_scout.constants import DEFAULT_DB_PATH, DEFAULT_FORWARD_DB_PATH, DISCLAIMER
from equity_scout.data.etf_panel import load_etf_panel, load_price_history
from equity_scout.etf_universe import ETF_TICKERS
from equity_scout.forward_paper import ForwardAccount, advance_account
from equity_scout.forward_storage import (
    append_exit,
    append_valuation,
    init_forward_db,
    load_account,
    save_account,
)
from equity_scout.market import PricePanel
from equity_scout.radar_storage import load_latest_watchlist
from equity_scout.strategies.ml_bot import SHORTABLE_TICKERS, MLLongStrategy, MLShortStrategy
from equity_scout.strategies.registry import default_strategies

# The bots trade a STOCK panel (watchlist + shortable whitelist + SPY) — its own snapshot,
# separate from the ETF/backtest one.
ML_BOTS_SNAPSHOT = "data/prices/ml_bots_panel.csv"


def stock_panel_for_bots(bot_tickers: list[str], *, start: str, refresh: bool) -> PricePanel:
    """The ML bots' stock panel — gap-tolerant (clean_columns via load_price_history, same as
    combined_panel's stock subpanel in run_autotrader.py post-R3): a young watchlist ticker
    must not truncate an established ticker's history in the SAVED snapshot. This runner runs
    nightly WITH --refresh and therefore WRITES data/prices/ml_bots_panel.csv; run_autotrader
    runs right after it WITHOUT --refresh and just reads that file back, so a common-range trim
    here would silently poison the depot's stock subpanel too (R3's own gap-tolerant loader
    notwithstanding). Self-heals on the next nightly --refresh run — load_price_history always
    re-derives + re-saves from a fresh download when refresh=True, no manual cache deletion
    needed."""
    return load_price_history(bot_tickers, start=start, snapshot=ML_BOTS_SNAPSHOT, refresh=refresh)


def _advance_and_report(strategy, panel, args, as_of) -> None:
    account = load_account(args.db, strategy.name) or ForwardAccount.fresh(strategy.name)
    advanced, valuation = advance_account(account, strategy, panel, costs_bps=args.cost_bps)
    save_account(args.db, advanced, updated_at=as_of.isoformat())
    status = "current"
    if valuation is not None:
        append_valuation(args.db, strategy.name, valuation)
        for exit_event in valuation.exits:
            append_exit(args.db, strategy.name, exit_event)
        # A booked zero-equity valuation is the simulated margin call — say it, loudly.
        status = "LIQUIDIERT" if valuation.equity <= 0.0 else "advanced"
    print(
        f"{strategy.name:<22}{advanced.equity:>12,.0f}"
        f"{advanced.equity / advanced.initial_capital - 1:>8.1%}"
        f"{advanced.benchmark_equity / advanced.initial_capital - 1:>8.1%}{status:>10}"
    )
    for exit_event in (valuation.exits if valuation is not None else ()):
        print(f"  → Exit {exit_event.ticker}: {exit_event.reason}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_FORWARD_DB_PATH, help="Forward paper DB path.")
    ap.add_argument("--main-db", default=DEFAULT_DB_PATH, help="Main DB (watchlist + model registry).")
    ap.add_argument("--start", default="2007-01-01", help="Panel start date (first fetch only).")
    ap.add_argument("--cost-bps", type=float, default=10.0, help="Round-trip rebalance cost.")
    ap.add_argument("--refresh", action="store_true", help="Re-fetch the latest prices from yfinance.")
    args = ap.parse_args()

    panel = load_etf_panel(ETF_TICKERS, start=args.start, refresh=args.refresh)
    as_of = panel.dates[-1].date()
    print(f"\nForward paper — advancing to {as_of} ({len(panel.dates)} panel days)\n")

    init_forward_db(args.db)
    header = f"{'Strategy':<22}{'Equity':>12}{'Return':>9}{'Bench':>9}{'Status':>10}"
    print(f"{header}\n{'-' * len(header)}")
    for strategy in default_strategies():
        try:
            _advance_and_report(strategy, panel, args, as_of)
        except Exception as err:  # noqa: BLE001 - one strategy's crash must not skip the rest
            print(f"{strategy.name} fehlgeschlagen: {err}")

    watchlist = load_latest_watchlist(args.main_db) or {}
    watch_tickers = [e["ticker"] for e in watchlist.get("entries", [])]
    long_universe = watch_tickers or list(SHORTABLE_TICKERS)
    bots = [
        MLLongStrategy.from_registry(args.main_db, tickers=long_universe),
        MLShortStrategy.from_registry(args.main_db),
    ]
    stock_panel = None
    if any(bot.ready for bot in bots):
        bot_tickers = list(dict.fromkeys([*long_universe, *SHORTABLE_TICKERS, "SPY"]))
        stock_panel = stock_panel_for_bots(bot_tickers, start=args.start, refresh=args.refresh)
    for bot in bots:
        if not bot.ready or stock_panel is None:
            print(f"{bot.name:<22} kein promoteter Champion — Bot übersprungen (ehrlich: kein Edge, kein Trade)")
            continue
        try:
            _advance_and_report(bot, stock_panel, args, as_of)
        except Exception as err:  # noqa: BLE001 - one bot's crash must not skip the other
            print(f"{bot.name} fehlgeschlagen: {err}")
    print(
        "\nML-Bots: Paper-only. Das Short-Konto rechnet einen Borrow-Kosten-PROXY, Fills zum"
        " Schlusskurs ohne Borrow-Verfügbarkeit — gelabelte Vereinfachung, keine realen"
        " Handelsbedingungen. Simulierter Margin-Floor: Equity <= 0 wird zwangsglattgestellt."
    )

    print(f"\n{DISCLAIMER}\n")


if __name__ == "__main__":
    main()
