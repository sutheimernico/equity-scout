"""Train the entry-quality models: backfill -> walk-forward OOS -> register -> promote if better.

The nightly-retrain entrypoint; the nightly cron line is installed by
`scripts/install_crontab.sh` (see docs/scheduling.md). Default trains EVERY preset
(`--model all`) for EVERY family (`entry`, `entry_short`, `entry_tb`) and lets the hardened
registry gate alone decide champion promotion, per family. The core takes an INJECTED PricePanel
so tests run offline; main() is the only place that loads prices from the network and reads the
wall clock. Every printed number is OUT-OF-SAMPLE (walk_forward_evaluate); an AUC of None or ~0.5
is stated as "no demonstrated edge", never dressed up — a null result is a valid, honest outcome
(invariant #2). The deployed artifact's probabilities are isotonic-calibrated on OOS walk-forward
probabilities only (never in-sample).

Usage:
    python scripts/run_train_entry.py [--db equity_scout.db] [--tickers AAA,BBB,...]
        [--model all|random_forest|elastic_net|catboost|ensemble]
        [--family all|entry|entry_short|entry_tb] [--start 2007-01-01] [--horizon 20]
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import numpy as np
from sklearn.isotonic import IsotonicRegression

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.market import PricePanel
from equity_scout.ml.entry_dataset import build_backfill_dataset
from equity_scout.ml.entry_eval import HORIZON_DAYS, SHORT_HORIZON_DAYS
from equity_scout.ml.entry_model import (
    ENTRY_PRESETS,
    train_entry_model,
    walk_forward_evaluate,
)
from equity_scout.ml.labeling import BarrierConfig
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


def _fit_oos_calibrator(oos: dict) -> IsotonicRegression | None:
    """Isotonic calibrator on the walk-forward OOS probabilities, or None when the OOS sample is
    too small / single-class to support one. OOS-only by construction: the arrays come from
    `walk_forward_evaluate(collect_oos=True)`, never from the deployed in-sample fit."""
    prob = np.asarray(oos.get("prob", []), dtype=float)
    y = np.asarray(oos.get("y", []), dtype=float)
    if len(prob) < 50 or len(np.unique(y)) < 2:
        return None
    return IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(prob, y)


FAMILY_LABEL_DIRECTION = {"entry": "beats", "entry_short": "lags", "entry_tb": "triple_barrier"}
FAMILY_PRINT_LABEL = {
    "entry": "Entry-Modell", "entry_short": "Short-Modell", "entry_tb": "Triple-Barrier-Entry-Modell",
}


def run_train_entry(
    db_path: str,
    *,
    panel: PricePanel,
    tickers: list[str],
    now: str,
    model: str = "random_forest",
    benchmark: str = BENCHMARK,
    horizon_days: int = HORIZON_DAYS,
    family: str = "entry",
    barrier_config: BarrierConfig | None = None,
) -> dict:
    """Build the backfill, evaluate OUT-OF-SAMPLE, fit on the full set (with OOS isotonic
    calibration when the sample supports it), register the challenger and promote it iff it clears
    the registry's promotion gate (`promote_if_better`: baseline quality + minimum AUC delta over
    the champion, see model_registry.py). Returns {version, metrics, promoted, n_train}. Prints an
    honest German summary (a weak/undefined AUC is reported as no demonstrated edge; too few OOS
    rows is reported as such rather than silently not promoting).

    `family="entry_short"` trains the SHORT model: label = underperforms the benchmark
    (`label_direction="lags"`). `family="entry_tb"` trains the triple-barrier model: label = the
    ticker's own vol-scaled profit barrier is touched before its stop (`label_direction=
    "triple_barrier"`, see `entry_dataset.build_backfill_dataset`); its `barrier_config` (defaults
    to `BarrierConfig()` — k_pt, k_sl, horizon_days, vol_window) is persisted verbatim into the
    registered metrics so a follow-up task can derive a price target/stop from the champion's own
    stored config. For entry_tb `barrier_config.horizon_days` is THE horizon — the `horizon_days`
    param is overridden by it (labels, walk-forward purge and `metrics["horizon_days"]` all follow
    the config), so the persisted config can never disagree with the actual training horizon.
    Every family is registered and promoted in its OWN registry partition with the same gate
    constants — families never compare against each other (AUC across different label definitions
    is not comparable)."""
    label_direction = FAMILY_LABEL_DIRECTION.get(family, "beats")
    tb_config = barrier_config if barrier_config is not None else BarrierConfig()
    if family == "entry_tb":
        # Mirrors build_backfill_dataset's derivation: the purge window and the persisted
        # metrics["horizon_days"] must match the label horizon the dataset actually used —
        # otherwise the walk-forward purge would under-purge (labels span the config horizon).
        horizon_days = tb_config.horizon_days
    X, y, meta = build_backfill_dataset(
        panel, tickers, benchmark=benchmark, horizon_days=horizon_days,
        label_direction=label_direction, barrier_config=tb_config,
    )
    n_train = len(X)
    if n_train == 0:
        print("Kein Trainingsdatensatz aufgebaut (zu wenig Historie) — kein Modell registriert.")
        return {"version": None, "metrics": {}, "promoted": False, "n_train": 0}

    metrics = walk_forward_evaluate(
        X, y, meta, model=model, horizon_days=horizon_days, trading_days=panel.dates,
        collect_oos=True,
    )
    calibrator = _fit_oos_calibrator(metrics.pop("oos", {}))
    metrics["horizon_days"] = horizon_days
    metrics["calibrated"] = calibrator is not None
    # Training feature means feed the live drift snapshot (/api/model) — the registry stores the
    # model, not the training matrix, so the means must ride along in the metrics.
    metrics["feature_means"] = {c: round(float(X[c].mean()), 6) for c in X.columns}
    if family == "entry_tb":  # MUST be retrievable so a follow-up task can derive target/stop
        metrics["barrier_config"] = tb_config.as_dict()
    fitted = train_entry_model(X, y, model=model, calibrator=calibrator)
    version = register_challenger(
        db_path, fitted, metrics=metrics, n_train=n_train, now=now, family=family
    )
    promoted = promote_if_better(db_path, version, now=now)

    label = FAMILY_PRINT_LABEL.get(family, f"{family}-Modell")
    print(f"{label} v{version} ({model}) auf {n_train} Zeilen trainiert.")
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


def run_train_entry_all(
    db_path: str,
    *,
    panel: PricePanel,
    tickers: list[str],
    now: str,
    models: tuple[str, ...] = ENTRY_PRESETS,
    families: tuple[str, ...] = ("entry", "entry_short", "entry_tb"),
    benchmark: str = BENCHMARK,
    horizon_days: int = HORIZON_DAYS,
    barrier_config: BarrierConfig | None = None,
) -> list[dict]:
    """Train every preset in `models` for every family in `families`; the registry gate alone
    decides which (if any) ends up champion per family. The short family trains on its own shorter
    horizon (SHORT_HORIZON_DAYS) — the bots' trading cadence. The triple-barrier family needs no
    entry here: `run_train_entry` derives its horizon from `barrier_config.horizon_days` itself
    (single source of truth — the persisted config must never disagree with the training horizon).
    One preset crashing must not kill the night's other presets — log and continue, mirroring the
    cron chains' contract."""
    tb_config = barrier_config if barrier_config is not None else BarrierConfig()
    family_horizon = {"entry": horizon_days, "entry_short": SHORT_HORIZON_DAYS}
    results = []
    for family in families:
        for model in models:
            try:
                results.append(
                    run_train_entry(
                        db_path, panel=panel, tickers=tickers, now=now, model=model,
                        benchmark=benchmark,
                        horizon_days=family_horizon.get(family, horizon_days),
                        family=family, barrier_config=tb_config,
                    )
                )
            except Exception as err:  # noqa: BLE001 — one broken preset is a report, not a crash
                print(f"Preset {family}/{model} fehlgeschlagen: {err}")
                results.append(
                    {"version": None, "metrics": {}, "promoted": False, "model": model,
                     "family": family}
                )
    return results


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
    parser.add_argument("--model", default="all", help=f"all or one of {ENTRY_PRESETS}")
    parser.add_argument("--family", default="all", help="all, entry, entry_short or entry_tb")
    parser.add_argument("--start", default="2007-01-01")
    parser.add_argument("--horizon", type=int, default=HORIZON_DAYS)
    args = parser.parse_args()

    stock_tickers = _resolve_tickers(args.db, args.tickers)
    # SPY is the relative-return benchmark; dedup so a SPY already in the universe isn't doubled.
    panel_tickers = list(dict.fromkeys(stock_tickers + [BENCHMARK]))
    panel = _load_panel(panel_tickers, args.start)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    models = ENTRY_PRESETS if args.model == "all" else (args.model,)
    families = ("entry", "entry_short", "entry_tb") if args.family == "all" else (args.family,)
    run_train_entry_all(
        args.db, panel=panel, tickers=stock_tickers, now=now, models=models,
        families=families, horizon_days=args.horizon,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
