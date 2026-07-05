"""Score the latest watchlist with the champion entry-model and log live predictions.

The 'predict' half of the honest online-learning loop (invariant #3): the champion scores each
watchlist entry 0-100 = P(it beats SPY over the horizon) as-of the latest trading day, and every
score is appended to the immutable prediction ledger BEFORE its outcome is known.
`scripts/run_resolve_predictions.py` fills the realized outcome once the horizon has elapsed.

Scoring and training are DIFFERENT cadences (score daily against the current watchlist; retrain the
backfill less often), so this is a dedicated CLI, not folded into run_train_entry. The score RANKS
entry attractiveness — it is not a price forecast and not advice.

The core takes an INJECTED PricePanel so tests run offline; main() is the only place that loads
prices from the network and reads the wall clock (datetime.now only in main()).

Usage:
    python scripts/run_score_watchlist.py [--db equity_scout.db] [--tickers AAA,BBB,...]
        [--start 2007-01-01]
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import pandas as pd

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.market import PricePanel
from equity_scout.ml.entry_eval import HORIZON_DAYS
from equity_scout.ml.entry_features import MIN_HISTORY, build_feature_row, market_context
from equity_scout.ml.model_registry import entry_champion
from equity_scout.ml.prediction_ledger import log_predictions
from equity_scout.radar_storage import load_latest_watchlist

BENCHMARK = "SPY"
# Distinct snapshot so scoring never clobbers the training/backtest panels.
SCORE_SNAPSHOT = "data/prices/score_panel.csv"


def _as_of_timestamp(now: str) -> pd.Timestamp:
    """`now` (tz-aware ISO) as a tz-naive date, to match the tz-naive panel index."""
    ts = pd.Timestamp(now)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts.normalize()


def _latest_as_of(panel: PricePanel, now: str) -> pd.Timestamp | None:
    """The most recent panel trading day at or before `now` — the decision date for the score row."""
    prior = panel.dates[panel.dates <= _as_of_timestamp(now)]
    return prior[-1] if len(prior) else None


def _feature_row(
    closes: pd.DataFrame, context_df: pd.DataFrame, ticker: str, as_of: pd.Timestamp
) -> dict | None:
    """Price-derived feature row for `ticker` as-of `as_of`, or None if the ticker lacks the market
    context on that day or a full `MIN_HISTORY` of its own closes (mirrors the backfill builder)."""
    if ticker not in closes.columns:
        return None
    stock_hist = closes[ticker].dropna()
    if as_of not in context_df.index or as_of not in stock_hist.index:
        return None
    if len(stock_hist.loc[:as_of]) < MIN_HISTORY:
        return None
    return build_feature_row(stock_hist, context_df.loc[as_of].to_dict(), as_of)


def run_score_watchlist(
    db_path: str,
    *,
    panel: PricePanel,
    now: str,
    benchmark: str = BENCHMARK,
    horizon_days: int = HORIZON_DAYS,
) -> dict:
    """Score every watchlist entry with the champion model and log the predictions to the ledger.
    Returns {logged, model_version, skipped} on success, or {logged: 0} when there is no champion
    or no watchlist (honest no-ops, not errors)."""
    champ = entry_champion(db_path)
    if champ is None:
        print("Kein Champion-Modell vorhanden — bitte zuerst scripts/run_train_entry.py ausführen.")
        return {"logged": 0}
    version, model, _metrics = champ

    watchlist = load_latest_watchlist(db_path)
    entries = (watchlist or {}).get("entries") or []
    if not entries:
        print("Keine Watchlist vorhanden — bitte zuerst scripts/run_radar.py ausführen.")
        return {"logged": 0}

    as_of = _latest_as_of(panel, now)
    context_df = market_context(panel, benchmark=benchmark)
    closes = panel.closes

    scored: list[tuple[str, int, dict]] = []
    skipped: list[str] = []
    for ticker in [e["ticker"] for e in entries]:
        features = None if as_of is None else _feature_row(closes, context_df, ticker, as_of)
        if features is None:
            skipped.append(ticker)
            continue
        scored.append((ticker, model.score_row(features), features))

    if scored:
        log_predictions(
            db_path, model_version=version, scored=scored, now=now, horizon_days=horizon_days
        )
    print(
        f"{len(scored)} Watchlist-Ticker mit Champion v{version} bewertet und protokolliert; "
        f"{len(skipped)} ohne ausreichende Historie übersprungen."
    )
    return {"logged": len(scored), "model_version": version, "skipped": skipped}


def _resolve_tickers(db_path: str, tickers_arg: str | None) -> list[str]:
    """Panel-fetch universe: CLI --tickers override, else the latest watchlist's tickers, else just
    the benchmark (core then no-ops honestly on the empty watchlist)."""
    if tickers_arg:
        return [t.strip().upper() for t in tickers_arg.split(",") if t.strip()]
    watchlist = load_latest_watchlist(db_path)
    entries = (watchlist or {}).get("entries") or []
    return [e["ticker"] for e in entries]


def _load_panel(tickers: list[str], start: str) -> PricePanel:
    """Network default: fresh daily closes for the watchlist tickers + SPY from `start`. A distinct
    snapshot keeps this panel separate from the training/backtest ones. Lazy import keeps the
    network out of import time and tests."""
    from equity_scout.data.etf_panel import load_etf_panel

    return load_etf_panel(tickers, start=start, snapshot=SCORE_SNAPSHOT, refresh=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--tickers", default=None, help="comma-separated override of the panel set")
    parser.add_argument("--start", default="2007-01-01")
    args = parser.parse_args()

    # SPY is the relative-return benchmark; dedup so a SPY already present isn't doubled.
    panel_tickers = list(dict.fromkeys(_resolve_tickers(args.db, args.tickers) + [BENCHMARK]))
    panel = _load_panel(panel_tickers, args.start)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    run_score_watchlist(args.db, panel=panel, now=now)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
