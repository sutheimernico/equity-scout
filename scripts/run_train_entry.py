"""Train the entry-quality model: backfill -> walk-forward OOS -> register -> promote if better.

The nightly-retrain entrypoint (Phase 5 crons it). The core takes an INJECTED PricePanel so tests
run offline; main() is the only place that loads prices from the network and reads the wall clock.
Every printed number is OUT-OF-SAMPLE (walk_forward_evaluate); an AUC of None or ~0.5 is stated as
"no demonstrated edge", never dressed up — a null result is a valid, honest outcome (invariant #2).

Usage:
    python scripts/run_train_entry.py [--db equity_scout.db] [--tickers AAA,BBB,...]
        [--model random_forest|elastic_net] [--start 2007-01-01]
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.market import PricePanel
from equity_scout.ml.entry_dataset import build_backfill_dataset
from equity_scout.ml.entry_eval import HORIZON_DAYS
from equity_scout.ml.entry_model import train_entry_model, walk_forward_evaluate
from equity_scout.ml.model_registry import (
    MIN_OOS_N,
    _no_edge,
    promote_if_better,
    register_challenger,
)
from equity_scout.radar_storage import load_latest_watchlist

BENCHMARK = "SPY"
# Distinct from the ETF/backtest snapshot: the stock backfill panel is its own basket.
ENTRY_SNAPSHOT = "data/prices/entry_panel.csv"
# Fallback universe when neither --tickers nor a stored watchlist supplies one.
FALLBACK_TICKERS = ("AAPL", "MSFT", "JPM", "XOM", "JNJ", "PG")


def _fmt(value: float | None) -> str:
    """German decimal (comma) for a metric, or 'n/a' when the metric is undefined (honest)."""
    return "n/a" if value is None else f"{value:.4f}".replace(".", ",")


def run_train_entry(
    db_path: str,
    *,
    panel: PricePanel,
    tickers: list[str],
    now: str,
    model: str = "random_forest",
    benchmark: str = BENCHMARK,
    horizon_days: int = HORIZON_DAYS,
) -> dict:
    """Build the backfill, evaluate OUT-OF-SAMPLE, fit on the full set, register the challenger and
    promote it iff it clears the registry's promotion gate (`promote_if_better`: baseline quality +
    minimum AUC delta over the champion, see model_registry.py). Returns {version, metrics,
    promoted, n_train}. Prints an honest German summary (a weak/undefined AUC is reported as no
    demonstrated edge; too few OOS rows is reported as such rather than silently not promoting)."""
    X, y, meta = build_backfill_dataset(
        panel, tickers, benchmark=benchmark, horizon_days=horizon_days
    )
    n_train = len(X)
    if n_train == 0:
        print("Kein Trainingsdatensatz aufgebaut (zu wenig Historie) — kein Modell registriert.")
        return {"version": None, "metrics": {}, "promoted": False, "n_train": 0}

    metrics = walk_forward_evaluate(
        X, y, meta, model=model, horizon_days=horizon_days, trading_days=panel.dates
    )
    fitted = train_entry_model(X, y, model=model)
    version = register_challenger(db_path, fitted, metrics=metrics, n_train=n_train, now=now)
    promoted = promote_if_better(db_path, version)

    print(f"Entry-Modell v{version} ({model}) auf {n_train} Zeilen trainiert.")
    print(
        f"Out-of-Sample: AUC {_fmt(metrics['auc'])}, Brier {_fmt(metrics['brier'])}, "
        f"Rank-IC {_fmt(metrics['rank_ic'])} "
        f"(n_oos={metrics['n_oos']}, Splits={metrics['n_splits_used']})."
    )
    print(f"Als Champion übernommen: {'ja' if promoted else 'nein'}.")
    if _no_edge(metrics["auc"]):
        print(
            "Kein belastbarer Vorteil nachgewiesen (AUC ~ 0,5 oder nicht bestimmbar). "
            "Das ist ein valides, ehrliches Ergebnis — keine Kauf-/Verkaufsempfehlung."
        )
    elif metrics["n_oos"] < MIN_OOS_N:
        print(
            f"Zu wenige Out-of-Sample-Zeilen ({metrics['n_oos']} < {MIN_OOS_N}) für eine "
            "belastbare Promotion-Entscheidung — Modell bleibt Herausforderer."
        )
    return {"version": version, "metrics": metrics, "promoted": promoted, "n_train": n_train}


def _resolve_tickers(db_path: str, tickers_arg: str | None) -> list[str]:
    """CLI --tickers list, else the latest watchlist's tickers, else the fixed fallback universe."""
    if tickers_arg:
        return [t.strip().upper() for t in tickers_arg.split(",") if t.strip()]
    watchlist = load_latest_watchlist(db_path)
    if watchlist and watchlist.get("entries"):
        return [e["ticker"] for e in watchlist["entries"]]
    return list(FALLBACK_TICKERS)


def _load_panel(tickers: list[str], start: str) -> PricePanel:
    """Network default: fresh daily closes for the stock universe + SPY from `start`. A distinct
    snapshot keeps this panel separate from the ETF/backtest one; refresh=True so a changed ticker
    set is honoured. Lazy import keeps the network out of import time and tests."""
    from equity_scout.data.etf_panel import load_etf_panel

    return load_etf_panel(tickers, start=start, snapshot=ENTRY_SNAPSHOT, refresh=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--tickers", default=None, help="comma-separated stock tickers")
    parser.add_argument("--model", default="random_forest")
    parser.add_argument("--start", default="2007-01-01")
    args = parser.parse_args()

    stock_tickers = _resolve_tickers(args.db, args.tickers)
    # SPY is the relative-return benchmark; dedup so a SPY already in the universe isn't doubled.
    panel_tickers = list(dict.fromkeys(stock_tickers + [BENCHMARK]))
    panel = _load_panel(panel_tickers, args.start)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    run_train_entry(args.db, panel=panel, tickers=stock_tickers, now=now, model=args.model)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
