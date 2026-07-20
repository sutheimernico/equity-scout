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
import os
import sys

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
    persist_advance,
    record_events,
    save_sleeve_weights,
)
from equity_scout.constants import (
    DEFAULT_DB_PATH,
    DEFAULT_FORWARD_DB_PATH,
    DISCLAIMER,
    ML_SLEEVE_NAMES,
)
from equity_scout.forward_storage import load_account
from equity_scout.data.etf_panel import load_etf_panel
from equity_scout.etf_universe import ETF_TICKERS
from equity_scout.fx import eur_rate
from equity_scout.state_storage import record_heartbeat
from equity_scout.telegram_client import TelegramError, load_telegram_config, send_message
from equity_scout.market import PricePanel
from equity_scout.autotrader_protections import RiskEvent
from equity_scout.promotion import lane_promotion_status, trailing_net_pnl
from equity_scout.radar_storage import load_latest_watchlist
from equity_scout.shortterm_storage import DEFAULT_SHORTTERM_DB_PATH
from equity_scout.shortterm_storage import LANES as ARENA_LANES
from equity_scout.shortterm_storage import load_trades as load_lane_trades
from equity_scout.shortterm_storage import load_valuations as load_lane_valuations
from equity_scout.strategies.base import TargetWeight
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


def ml_sleeve_holdings(forward_db: str, sleeve_names: list[str]) -> dict[str, set[str]]:
    """Currently-held tickers per ML sleeve from its POST-exit forward book (v12 R5): the
    forward chain runs BEFORE the autotrader in nightly_train.sh, so its book already
    reflects tonight's exits. A bot without a forward account yet is left unfiltered —
    the exit information honestly does not exist. Rule sleeves are never mirrored."""
    holdings: dict[str, set[str]] = {}
    for name in sleeve_names:
        if name not in ML_SLEEVE_NAMES:
            continue
        account = load_account(forward_db, name)
        if account is None:
            continue
        holdings[name] = {t for t, w in account.weights.items() if abs(w) > 1e-9}
    return holdings


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
    return PricePanel(
        pd.concat([etf.closes, stocks.closes[extra]], axis=1, sort=False).sort_index()
    )


class LaneSleeve:
    """A promoted arena lane as a depot sleeve (v12 I3): the depot buys the lane's
    EQUITY CURVE like a fund share — a synthetic `ARENA_<lane>` panel column built from
    the lane's own valuations. Positions are never re-simulated (Kraken tickers do not
    exist in the depot panel), and the lane keeps trading its own book."""

    def __init__(self, lane: str) -> None:
        self.lane = lane
        self.name = f"Arena {lane}"
        self.ticker = f"ARENA_{lane.upper()}"

    def decide(self, as_of, market):  # noqa: ANN001, ANN201 - Strategy protocol
        return [TargetWeight(self.ticker, 1.0)]


def lane_equity_series(shortterm_db: str, lane: str) -> pd.Series | None:
    """Last equity per calendar day from the lane's valuations (fund-share price)."""
    vals = load_lane_valuations(shortterm_db, lane)
    if len(vals) < 2:
        return None
    series = pd.Series(
        {pd.Timestamp(v["created_at"][:10]): float(v["equity"]) for v in vals}
    ).sort_index()
    return series if len(series) >= 2 else None


def resolve_promotions(
    account: AutoDepotAccount, shortterm_db: str, *, today: str
) -> tuple[list[str], list[RiskEvent]]:
    """Evidence in, capital out (v12 I3): a lane enters on the strict I2 gate and leaves
    when its trailing-60d realised net P&L stops being positive — a deliberately laxer
    exit (hysteresis) so borderline lanes do not flap monthly."""
    promoted = list(account.promoted_lanes)
    events: list[RiskEvent] = []
    for lane in ARENA_LANES:
        vals = load_lane_valuations(shortterm_db, lane)
        if not vals:
            continue
        trades = load_lane_trades(shortterm_db, lane, limit=5000)
        if lane in promoted:
            trailing = trailing_net_pnl(trades, today=today)
            if trailing <= 0:
                promoted.remove(lane)
                events.append(RiskEvent(
                    protection=f"promotion:{lane}", action="demote",
                    detail=(f"Arena-Lane '{lane}' degradiert: 60-Tage-Netto-P&L "
                            f"{trailing:+,.2f} $ — zurück auf den Prüfstand"),
                ))
        else:
            status = lane_promotion_status(trades, vals, today=today)
            if status["eligible"]:
                promoted.append(lane)
                pf = status["profit_factor"]
                pf_str = "∞" if pf is not None and pf == float("inf") else f"{pf:.2f}"
                events.append(RiskEvent(
                    protection=f"promotion:{lane}", action="promote",
                    detail=(f"Arena-Lane '{lane}' befördert: "
                            f"{status['realized_trades']} realisierte Trades, "
                            f"Netto {status['net_pnl']:+,.2f} $, Profit-Faktor {pf_str}"),
                ))
    return promoted, events


def resolve_allocation(
    autotrader_db: str, forward_db: str, sleeve_names: list[str], as_of: pd.Timestamp,
    extra_returns: pd.DataFrame | None = None,
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
    if extra_returns is not None and not extra_returns.empty:
        frame = pd.concat([frame, returns_before(extra_returns, as_of)], axis=1)
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
    shortterm_db: str | None = None,
    regime_level: str | None = None,
    fx_rate: float | None = None,
    costs_bps: float = 10.0,
    persist: bool = True,
) -> tuple[AutoDepotAccount, AutoDepotValuation | None]:
    """One testable advance: promotions -> allocation -> engine -> persistence."""
    from dataclasses import replace as _replace

    as_of = panel.dates[-1]
    account = load_depot(autotrader_db) or AutoDepotAccount.fresh()
    lane_returns: pd.DataFrame | None = None
    if shortterm_db is not None:
        today_iso = as_of.date().isoformat()
        promoted, promo_events = resolve_promotions(account, shortterm_db, today=today_iso)
        if tuple(promoted) != account.promoted_lanes:
            account = _replace(account, promoted_lanes=tuple(promoted))
        lane_cols: dict[str, pd.Series] = {}
        for lane in promoted:
            series = lane_equity_series(shortterm_db, lane)
            if series is None:
                continue  # not enough curve to price the fund share — skip honestly
            sleeve = LaneSleeve(lane)
            strategies = [*strategies, sleeve]
            panel = PricePanel(
                panel.closes.join(series.rename(sleeve.ticker), how="left").sort_index()
            )
            lane_cols[sleeve.name] = series.pct_change().iloc[1:]
        if lane_cols:
            lane_returns = pd.DataFrame(lane_cols)
        if promo_events and persist:
            record_events(autotrader_db, today_iso, promo_events)
    allocation = resolve_allocation(
        autotrader_db, forward_db, [s.name for s in strategies], as_of,
        extra_returns=lane_returns,
    )
    account, valuation = advance_depot(
        account, strategies, allocation, panel,
        regime_level=regime_level,
        depot_returns=depot_return_series(autotrader_db),
        fx_rate=fx_rate,
        costs_bps=costs_bps,
        sleeve_holdings=ml_sleeve_holdings(forward_db, [s.name for s in strategies]),
    )
    if persist:
        persist_advance(
            autotrader_db, account, valuation, updated_at=as_of.date().isoformat()
        )
    return account, valuation


EVENT_TRADE_CAP = 10


def build_event_message(valuation: AutoDepotValuation | None) -> str | None:
    """One bundled nightly push (v12 W2): trades + risk events, or None when the advance
    was a quiet no-op — no activity, no message."""
    if valuation is None or (not valuation.trades and not valuation.risk_events):
        return None
    lines = [f"🤖 Auto-Depot {valuation.created_at}: {len(valuation.trades)} Trade(s)"]
    for t in valuation.trades[:EVENT_TRADE_CAP]:
        side = "KAUF" if t.delta_weight > 0 else "VERKAUF"
        lines.append(f"• {side} {t.ticker} Δ{t.delta_weight:+.1%} (~{t.notional:,.0f} $)")
    rest = len(valuation.trades) - EVENT_TRADE_CAP
    if rest > 0:
        lines.append(f"… +{rest} weitere")
    for event in valuation.risk_events:
        lines.append(f"⚠ {event.detail}")
    lines.append("(Paper-Depot · nächtlicher Lauf · Details im 18:00-Digest)")
    return "\n".join(lines)


def push_events(valuation: AutoDepotValuation | None, env: dict) -> bool:
    """Send the bundled event message SILENT (disable_notification — the nightly chain
    runs ~02:35; the 18:00 digest stays the loud surface). Env-gated: set
    COPILOT_TG_AUTOTRADER_EVENTS=0 to turn the push off entirely."""
    if env.get("COPILOT_TG_AUTOTRADER_EVENTS", "1") == "0":
        return False
    text = build_event_message(valuation)
    if text is None:
        return False
    config = load_telegram_config(env)
    if config is None:
        return False
    try:
        send_message(
            config["token"], config.get("daily_chat_id", config["chat_id"]),
            text, silent=True,
        )
    except TelegramError as err:
        print(f"Warnung: Auto-Depot-Event-Push fehlgeschlagen: {err}", file=sys.stderr)
        return False
    return True


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
    ap.add_argument("--shortterm-db", default=DEFAULT_SHORTTERM_DB_PATH,
                    help="Arena DB (promotion gate reads lane evidence from here).")
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
        shortterm_db=args.shortterm_db,
        regime_level=_collect_regime_level(panel),
        fx_rate=eur_rate("USD"),
        costs_bps=args.cost_bps,
        persist=not args.dry_run,
    )
    if not args.dry_run:
        from datetime import datetime, timezone

        record_heartbeat(args.main_db, "nightly", now=datetime.now(timezone.utc).isoformat())
        push_events(valuation, dict(os.environ))

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
