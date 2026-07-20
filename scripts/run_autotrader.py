"""CLI: advance the Auto-Depot (vision v10) one step on the latest prices.

The one meta book over all strategy sleeves: sleeve weights from each sleeve's own forward
track record (equal-weight anchor + Sharpe-softmax tilt, monthly recompute), look-through
aggregation to per-ticker targets, protection chain (concentration cap, regime gate, vol
target, drawdown breaker), then the same look-ahead-safe close-fill execution as forward
paper. Trades, valuations, and risk interventions are persisted to the autotrader DB and
surfaced in digest/API/dashboard. Idempotent per panel date — safe in the daily cron chain.

PAPER / RESEARCH ONLY. No alpha promise, no real-money routing — see the disclaimer and
LOOP.md's iron constraints.
"""
from __future__ import annotations

import argparse

import pandas as pd

from equity_scout.autotrader_allocator import (
    SleeveAllocation,
    blend_weights,
    returns_before,
    sleeve_return_frame,
)
from equity_scout.autotrader_engine import AutoDepotAccount, AutoDepotValuation, advance_depot
from equity_scout.autotrader_storage import (
    DEFAULT_AUTOTRADER_DB_PATH,
    load_depot,
    load_latest_sleeve_weights,
    load_valuations,
    record_advance,
    save_depot,
    save_sleeve_weights,
)
from equity_scout.constants import DEFAULT_DB_PATH, DEFAULT_FORWARD_DB_PATH, DISCLAIMER
from equity_scout.data.etf_panel import load_etf_panel
from equity_scout.etf_universe import ETF_TICKERS
from equity_scout.fx import eur_rate
from equity_scout.market import PricePanel
from equity_scout.radar_storage import load_latest_watchlist
from equity_scout.strategies.ensemble import EnsembleStrategy
from equity_scout.strategies.ml_bot import SHORTABLE_TICKERS, MLLongStrategy, MLShortStrategy
from equity_scout.strategies.registry import default_strategies

ML_BOTS_SNAPSHOT = "data/prices/ml_bots_panel.csv"  # same stock panel the forward bots trade


def active_sleeves(main_db: str) -> list:
    """The depot's sleeves: every default strategy EXCEPT the ensemble blend (it is itself a
    mix of the same strategies — including it would double-count them), plus each ML bot that
    has a promoted champion. A bot without one is not a sleeve at all — no track record, no
    seat at the table (same honesty gate as forward paper)."""
    sleeves = [s for s in default_strategies() if not isinstance(s, EnsembleStrategy)]
    watchlist = load_latest_watchlist(main_db) or {}
    watch_tickers = [e["ticker"] for e in watchlist.get("entries", [])]
    long_universe = watch_tickers or list(SHORTABLE_TICKERS)
    bots = [
        MLLongStrategy.from_registry(main_db, tickers=long_universe),
        MLShortStrategy.from_registry(main_db),
    ]
    sleeves.extend(bot for bot in bots if bot.ready)
    return sleeves


def combined_panel(*, start: str, refresh: bool, need_stocks: bool, main_db: str) -> PricePanel:
    """ETF panel joined column-wise with the ML-bots stock panel (only when a bot is active).
    No common-range trim: a young stock must not truncate the ETFs' long history — consumers
    (MarketView, _asset_return) handle per-ticker NaN gaps themselves."""
    etf = load_etf_panel(ETF_TICKERS, start=start, refresh=refresh)
    if not need_stocks:
        return etf
    watchlist = load_latest_watchlist(main_db) or {}
    watch_tickers = [e["ticker"] for e in watchlist.get("entries", [])]
    bot_tickers = list(dict.fromkeys([*watch_tickers, *SHORTABLE_TICKERS, "SPY"]))
    stocks = load_etf_panel(bot_tickers, start=start, snapshot=ML_BOTS_SNAPSHOT, refresh=refresh)
    extra = [t for t in stocks.tickers if t not in etf.tickers]
    return PricePanel(pd.concat([etf.closes, stocks.closes[extra]], axis=1).sort_index())


def resolve_allocation(
    autotrader_db: str, forward_db: str, sleeve_names: list[str], as_of: pd.Timestamp
) -> SleeveAllocation:
    """Reuse this month's stored sleeve weights; recompute when the month rolled over OR the
    active sleeve set changed (e.g. a short bot just got its first champion — stale weights
    would silently ignore the new lane). Recompute uses only history strictly before as_of."""
    month = as_of.strftime("%Y-%m")
    stored = load_latest_sleeve_weights(autotrader_db)
    if stored and stored[0]["month"] == month and {r["strategy_name"] for r in stored} == set(
        sleeve_names
    ):
        return SleeveAllocation(
            weights={r["strategy_name"]: r["weight"] for r in stored},
            mode=stored[0]["mode"],
            sharpes={
                r["strategy_name"]: r["sharpe"] for r in stored if r["sharpe"] is not None
            },
        )
    frame = returns_before(sleeve_return_frame(forward_db, sleeve_names), as_of)
    allocation = blend_weights(frame, sleeve_names)
    save_sleeve_weights(autotrader_db, month, allocation)
    return allocation


def depot_return_series(autotrader_db: str) -> pd.Series | None:
    """The depot's own daily returns from its valuation history (vol-target input)."""
    valuations = load_valuations(autotrader_db)
    if len(valuations) < 2:
        return None
    equity = pd.Series(
        {pd.Timestamp(v["created_at"]): float(v["equity"]) for v in valuations}
    ).sort_index()
    return equity.pct_change().iloc[1:]


def advance_autotrader(
    panel: PricePanel,
    strategies: list,
    *,
    autotrader_db: str,
    forward_db: str,
    regime_level: str | None = None,
    fx_rate: float | None = None,
    costs_bps: float = 10.0,
    persist: bool = True,
) -> tuple[AutoDepotAccount, AutoDepotValuation | None]:
    """One testable advance: allocation -> engine -> (optionally) persistence."""
    as_of = panel.dates[-1]
    account = load_depot(autotrader_db) or AutoDepotAccount.fresh()
    allocation = resolve_allocation(
        autotrader_db, forward_db, [s.name for s in strategies], as_of
    )
    account, valuation = advance_depot(
        account, strategies, allocation, panel,
        regime_level=regime_level,
        depot_returns=depot_return_series(autotrader_db),
        fx_rate=fx_rate,
        costs_bps=costs_bps,
    )
    if persist:
        save_depot(autotrader_db, account, updated_at=as_of.date().isoformat())
        if valuation is not None:
            record_advance(autotrader_db, valuation)
    return account, valuation


def _collect_regime_level(panel: PricePanel) -> str | None:
    """Regime light via the digest's collector; any fetch failure -> None (the gate treats
    unknown as no-op — a broken feed must never move the book)."""
    try:
        from scripts.run_digest import collect_regime

        regime = collect_regime(panel)
        return regime["level"] if regime else None
    except Exception:  # noqa: BLE001 - network/feed errors degrade to "unknown"
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_AUTOTRADER_DB_PATH, help="Autotrader DB path.")
    ap.add_argument("--forward-db", default=DEFAULT_FORWARD_DB_PATH, help="Forward paper DB (sleeve history).")
    ap.add_argument("--main-db", default=DEFAULT_DB_PATH, help="Main DB (watchlist + model registry).")
    ap.add_argument("--start", default="2007-01-01", help="Panel start date (first fetch only).")
    ap.add_argument("--cost-bps", type=float, default=10.0, help="Round-trip rebalance cost.")
    ap.add_argument("--refresh", action="store_true", help="Re-fetch the latest prices from yfinance.")
    ap.add_argument("--dry-run", action="store_true", help="Compute and print, persist nothing.")
    args = ap.parse_args()

    strategies = active_sleeves(args.main_db)
    has_bots = any(isinstance(s, (MLLongStrategy, MLShortStrategy)) for s in strategies)
    panel = combined_panel(
        start=args.start, refresh=args.refresh, need_stocks=has_bots, main_db=args.main_db
    )
    as_of = panel.dates[-1].date()
    print(f"\nAuto-Depot — advancing to {as_of} ({len(panel.dates)} panel days)\n")

    account, valuation = advance_autotrader(
        panel, strategies,
        autotrader_db=args.db, forward_db=args.forward_db,
        regime_level=_collect_regime_level(panel),
        fx_rate=eur_rate("USD"),
        costs_bps=args.cost_bps,
        persist=not args.dry_run,
    )

    mode_note = (
        "Anker-Phase: zu wenig Forward-Historie für Performance-Tilt — reines Equal-Weight"
        if account.sleeve_mode == "anchor"
        else "Tilt: Sharpe-Softmax auf 63-Tage-Fenster, 50% Equal-Weight-Anker"
    )
    print(f"Sleeves ({len(strategies)}): {mode_note}")
    for name, weight in sorted(account.sleeve_weights.items(), key=lambda kv: -kv[1]):
        print(f"  {name:<22}{weight:>7.1%}")

    if valuation is None:
        print("\nBereits aktuell für dieses Panel-Datum — nichts gebucht (idempotent).")
    else:
        eur = f" ({valuation.equity_eur:,.0f} EUR)" if valuation.equity_eur is not None else ""
        print(
            f"\nEquity {valuation.equity:,.0f} USD{eur}"
            f" · Return {valuation.total_return:+.1%} vs Benchmark {valuation.benchmark_return:+.1%}"
            f" · Brutto-Exposure {valuation.gross_exposure:.0%}"
            f" · Drawdown {valuation.drawdown:.1%}"
        )
        if valuation.trades:
            print(f"Trades heute ({len(valuation.trades)}):")
            for trade in valuation.trades:
                side = "KAUF" if trade.delta_weight > 0 else "VERKAUF"
                print(
                    f"  {side:<8}{trade.ticker:<10}Δ{trade.delta_weight:+.2%}"
                    f"  ~{trade.notional:,.0f} USD  (Kosten {trade.cost:,.2f} USD)"
                )
        for event in valuation.risk_events:
            print(f"  ⚠ Risk-Layer: {event.detail}")
        if args.dry_run:
            print("\nDRY-RUN — nichts persistiert.")

    print(f"\n{DISCLAIMER}\n")


if __name__ == "__main__":
    main()
