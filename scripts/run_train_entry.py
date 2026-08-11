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
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.market import PricePanel
from equity_scout.ml.entry_dataset import build_backfill_dataset
from equity_scout.ml.entry_eval import HORIZON_DAYS, SHORT_HORIZON_DAYS
from equity_scout.ml.entry_model import (
    ENTRY_PRESETS,
    evaluate_fitted_model,
    train_entry_model,
    walk_forward_evaluate,
)
from equity_scout.ml.evidence_features import (
    EVIDENCE_ACTIVE_COLUMN,
    EVIDENCE_FEATURE_COLUMNS,
    SHORT_WINDOW_DAYS,
    EvidenceIndex,
    load_evidence_index,
)
from equity_scout.ml.labeling import BarrierConfig
from equity_scout.ml.model_registry import (
    MIN_OOS_N,
    NO_EDGE_BAND,
    RegistryError,
    _no_edge,
    entry_champion,
    promote_if_better,
    register_challenger,
)
from equity_scout.radar_storage import load_latest_watchlist

BENCHMARK = "SPY"
# Distinct from the ETF/backtest snapshot: the stock backfill panel is its own basket.
ENTRY_SNAPSHOT = "data/prices/entry_panel.csv"
# v13 Q1: a ticker whose history starts so late that the common-range trim would cost the
# panel more than this share of its span is excluded from training (and logged).
MAX_PANEL_SPAN_LOSS = 0.30
# Fallback universe when neither --tickers nor a stored watchlist supplies one.
FALLBACK_TICKERS = ("AAPL", "MSFT", "JPM", "XOM", "JNJ", "PG")
# v15 P3: the evidence block trains as EXTRA challengers of THIS family only. entry_tb is the
# safe host: its champion is read for `barrier_config` alone (api.py, run_notify.py) and never
# scores anything, so a champion flip has no live scoring surface. entry/entry_short DO score
# live (strategies/ml_bot.py) and stay price-only until a live evidence feed exists.
EVIDENCE_FAMILY = "entry_tb"


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


def _incumbent_on_this_sample(
    db_path: str,
    X: pd.DataFrame,
    y: pd.Series,
    meta: pd.DataFrame,
    *,
    family: str,
    horizon_days: int,
    trading_days: pd.DatetimeIndex | None,
) -> tuple[float | None, str]:
    """The incumbent champion's AUC re-measured on THIS run's OOS folds, plus a line to print.

    The gate used to compare a fresh challenger AUC against the incumbent's stored one — two
    samples, two universes, two sizes (found 2026-08-11: the live entry champion claimed 0.6195
    on 220 rows, delivered 0.5152 on 3281, and blocked a 0.5348 challenger for five weeks).

    Returns (None, note) whenever the incumbent cannot be scored HERE — no champion yet, a
    different feature block (an evidence-featured champion vs a price-only sample), or an
    unloadable artifact. The gate then falls back to the stored value, because comparing against
    nothing would promote on no evidence at all. Never raises: a failure to re-measure must not
    take down a training run.
    """
    try:
        incumbent = entry_champion(db_path, family=family)
    except RegistryError as err:
        return None, f"Amtsinhaber nicht ladbar ({err}) — Vergleich gegen den gespeicherten Wert."
    if incumbent is None:
        return None, ""  # empty arena: nothing to defend, baseline quality alone decides
    version, model, stored = incumbent
    try:
        fresh = evaluate_fitted_model(
            model, X, y, meta, horizon_days=horizon_days, trading_days=trading_days
        )
    except KeyError:
        return None, (
            f"Amtsinhaber v{version} trägt einen anderen Feature-Block als dieses Sample — "
            "Vergleich gegen den gespeicherten Wert."
        )
    if fresh["auc"] is None:
        return None, (
            f"Amtsinhaber v{version} auf diesem Sample nicht bewertbar — "
            "Vergleich gegen den gespeicherten Wert."
        )
    note = (
        f"Amtsinhaber v{version} auf DIESEM Sample: AUC {_fmt(fresh['auc'])} "
        f"(n_oos={fresh['n_oos']}) — gespeichert war {_fmt(_stored_auc(stored))} "
        f"(n_oos={stored.get('n_oos')}). Der frische Wert ist die Vergleichsbasis."
    )
    if _no_edge(fresh["auc"]):
        # The loudest line the nightly can print: the model that scores live has, on today's
        # sample, no demonstrated edge — it would not clear its own promotion gate as a newcomer.
        # Deliberately a REPORT, not an automatic demotion: dethroning empties the arena and stops
        # the ML-Bot sleeve from trading, which is Nico's call, not the loop's.
        threshold = f"{0.5 + NO_EDGE_BAND:.2f}".replace(".", ",")
        note += (
            f"\n  ⚠ Der Amtsinhaber liegt damit in der No-Edge-Bande (Promotion verlangt "
            f"AUC ≥ {threshold}) — er würde heute NICHT promoten und regiert auf "
            "einer Zahl, die sein eigenes Gate nicht mehr besteht."
        )
    return fresh["auc"], note


def _stored_auc(metrics: dict) -> float | None:
    """The incumbent's persisted AUC, for the honest side-by-side in the log."""
    value = metrics.get("auc")
    return None if value is None else float(value)


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
    n_candidates: int = 1,
    evidence_index: EvidenceIndex | None = None,
) -> dict:
    """Build the backfill, evaluate OUT-OF-SAMPLE, fit on the full set (with OOS isotonic
    calibration when the sample supports it), register the challenger and promote it iff it clears
    the registry's promotion gate (`promote_if_better`: baseline quality + minimum AUC delta over
    the champion, see model_registry.py). `n_candidates` is forwarded to `promote_if_better`'s
    multiple-testing guard (C2) — the caller's job to say how many presets are competing against
    this same family's champion tonight (see `run_train_entry_all`); defaults to 1 (a single,
    standalone training run). Returns {version, metrics, promoted, n_train}. Prints an
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
    is not comparable).

    `evidence_index` (additive, default None = the pre-P3 behaviour): when given, the backfill
    dataset carries `EVIDENCE_FEATURE_COLUMNS` on top of the price block. The promotion path is
    unchanged — the variant is just another challenger that must beat the same champion through
    `promote_if_better`; the caller is responsible for counting it in `n_candidates`."""
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
        evidence_index=evidence_index,
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
    # v15 P3: recorded on EVERY run (empty/None when off) so a registry row always states which
    # feature set it was fitted on — an absent key would leave later readers guessing.
    metrics["evidence_features"] = (
        list(EVIDENCE_FEATURE_COLUMNS) if evidence_index is not None else []
    )
    # Coverage reality check: the share of training rows with an active cluster in the SHORT
    # (91d) window specifically — named so a registry reader isn't left guessing which window a
    # generic "coverage" key meant; rows with ANY ev_* signal (the 365d count included) run ~4x
    # higher, and a feature set that is ~0 everywhere in its OWN window cannot beat the champion.
    metrics["evidence_coverage_91d"] = (
        round(float((X[EVIDENCE_ACTIVE_COLUMN] > 0).mean()), 4)
        if evidence_index is not None
        else None
    )
    if family == "entry_tb":  # MUST be retrievable so a follow-up task can derive target/stop
        metrics["barrier_config"] = tb_config.as_dict()
    fitted = train_entry_model(X, y, model=model, calibrator=calibrator)
    version = register_challenger(
        db_path, fitted, metrics=metrics, n_train=n_train, now=now, family=family
    )
    incumbent_auc, incumbent_note = _incumbent_on_this_sample(
        db_path, X, y, meta, family=family, horizon_days=horizon_days, trading_days=panel.dates
    )
    if incumbent_note:
        print(incumbent_note)
    promoted = promote_if_better(
        db_path, version, now=now, n_candidates=n_candidates, incumbent_metric=incumbent_auc
    )

    label = FAMILY_PRINT_LABEL.get(family, f"{family}-Modell")
    print(f"{label} v{version} ({model}) auf {n_train} Zeilen trainiert.")
    if evidence_index is not None:
        coverage_91d = metrics["evidence_coverage_91d"]
        share = "n/a" if coverage_91d is None else f"{coverage_91d:.1%}".replace(".", ",")
        print(
            f"Evidence-Features aktiv ({len(EVIDENCE_FEATURE_COLUMNS)} Spalten): Anteil "
            f"Trainingszeilen mit Insider-Cluster in den letzten {SHORT_WINDOW_DAYS} Tagen: "
            f"{share}."
        )
        active_tickers = int(meta.loc[X[EVIDENCE_ACTIVE_COLUMN] > 0, "ticker"].nunique())
        print(f"Evidence-Abdeckung: {active_tickers} von {meta['ticker'].nunique()} "
              f"Trainings-Tickern mit aktivem Cluster-Fenster.")
    print(
        f"Out-of-Sample: AUC {_fmt(metrics['auc'])}, Brier {_fmt(metrics['brier'])}, "
        f"Rank-IC {_fmt(metrics['rank_ic'])}, WFE {_fmt(metrics.get('wfe'))} "
        f"(n_oos={metrics['n_oos']}, Splits={metrics['n_splits_used']})."
    )
    wfe = metrics.get("wfe")
    if wfe is not None and wfe < 0.5:
        # v13 Q3: SOFT signal only — no gate reads it, the line just says what it suggests
        print(
            f"Walk-Forward-Effizienz {_fmt(wfe)} < 0,5: wahrscheinlich überangepasst "
            "(Heuristik — nur Diagnose, kein Gate)."
        )
    if metrics["n_splits_used"] == 0:
        # v9 Q5: the split unit is unique monthly as_of dates, not rows — a young panel
        # (MIN_HISTORY warm-up eats the first ~12 months, the label horizon crops the end)
        # cannot fill purged_walk_forward's min_train + n_splits date minimum. Say so
        # instead of a bare Splits=0; the split parameters stay strict on purpose.
        unique_dates = int(pd.to_datetime(meta["as_of"]).nunique())
        print(
            f"Hinweis: nur {unique_dates} monatliche Sample-Stichtage im Panel — zu wenig für"
            " einen einzigen purged Walk-Forward-Split. Kein Fehler: das Modell bleibt"
            " registriert, wird aber ohne OOS-Beleg nie Champion. Abhilfe ist mehr"
            " Panel-Historie, nicht lockerere Split-Parameter."
        )
    print(f"Als Champion übernommen: {'ja' if promoted else 'nein'}.")
    if _no_edge(metrics["auc"]):
        print(
            "Kein belastbarer Vorteil nachgewiesen (AUC nicht klar über 0,5 oder nicht "
            "bestimmbar). "
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
    evidence_index: EvidenceIndex | None = None,
) -> list[dict]:
    """Train every preset in `models` for every family in `families`; the registry gate alone
    decides which (if any) ends up champion per family. The short family trains on its own shorter
    horizon (SHORT_HORIZON_DAYS) — the bots' trading cadence. The triple-barrier family needs no
    entry here: `run_train_entry` derives its horizon from `barrier_config.horizon_days` itself
    (single source of truth — the persisted config must never disagree with the training horizon).
    One preset crashing must not kill the night's other presets — log and continue, mirroring the
    cron chains' contract.

    C2 multiple-testing guard: `len(models)` presets compete against the SAME champion within each
    family (families never compare against each other — each has its own champion track), so
    `len(models)` — not `len(models) * len(families)` — is the candidate count passed to every
    `promote_if_better` call via `run_train_entry`'s `n_candidates`.

    `evidence_index` (v15 P3): when given, `EVIDENCE_FAMILY` (entry_tb) trains each preset TWICE
    — once price-only, once with the evidence block — and that family's `n_candidates` doubles
    accordingly. Twice as many presets competing for the same champion slot without a higher bar
    is exactly the noise-promotion hole `_min_auc_delta`'s sqrt(N) scaling exists to close. Other
    families are untouched: they score live, and no live evidence feed exists yet.

    Caveat: the sqrt(N) correction counts candidates PER RUN of this function against the SAME
    champion — it has no memory across calls. Running the bare nightly (N=len(models)) and then a
    manual --with-evidence run (N=2*len(models)) on the same day is really 3*len(models) trials
    against that one champion, of which each call only ever sees and corrects for its own share;
    an extra same-day run therefore systematically understates the true trial count."""
    tb_config = barrier_config if barrier_config is not None else BarrierConfig()
    family_horizon = {"entry": horizon_days, "entry_short": SHORT_HORIZON_DAYS}
    results = []
    for family in families:
        variants: tuple[EvidenceIndex | None, ...] = (None,)
        if evidence_index is not None and family == EVIDENCE_FAMILY:
            variants = (None, evidence_index)
        n_candidates = len(models) * len(variants)
        for variant in variants:
            for model in models:
                try:
                    results.append(
                        run_train_entry(
                            db_path, panel=panel, tickers=tickers, now=now, model=model,
                            benchmark=benchmark,
                            horizon_days=family_horizon.get(family, horizon_days),
                            family=family, barrier_config=tb_config,
                            n_candidates=n_candidates, evidence_index=variant,
                        )
                    )
                except Exception as err:  # noqa: BLE001 — a broken preset is a report, not a crash
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


def _filter_short_history(closes: pd.DataFrame) -> PricePanel:
    """v13 Q1: drop young tickers BEFORE the common-range trim, so one fresh IPO on the
    watchlist cannot cut the training panel from ~2007 down to its own listing date (the
    walk-forward trainer then starves on monthly split dates). Each exclusion is logged with
    the explicit rule; a filter that leaves no stock next to the benchmark is an error, not
    an empty panel."""
    from equity_scout.data.etf_panel import clean_panel, drop_short_history

    survivors, excluded = drop_short_history(closes, max_span_loss=MAX_PANEL_SPAN_LOSS)
    for entry in excluded:
        print(
            f"Ausgeschlossen {entry['ticker']}: Historie beginnt {entry['first_valid']}, "
            f"Panel beginnt {entry['panel_start']} — das Panel verlöre "
            f"{entry['span_loss']:.0%} seiner Spanne (Grenze {MAX_PANEL_SPAN_LOSS:.0%})."
        )
    panel = clean_panel(survivors)
    if not any(col != BENCHMARK for col in panel.closes.columns):
        raise RuntimeError(
            "Entry-Panel nach Mindest-Historie-Filter ohne Aktien-Ticker "
            f"({len(excluded)} ausgeschlossen) — Training abgebrochen statt auf einem "
            "leeren Panel zu schweigen."
        )
    return panel


def _load_panel(tickers: list[str], start: str) -> PricePanel:
    """Network default: fresh daily closes for the stock universe + SPY from `start`. A distinct
    snapshot keeps this panel separate from the ETF/backtest one; refresh=True so a changed ticker
    set is honoured. Lazy import keeps the network out of import time and tests. The snapshot
    keeps every ticker's full history (column-wise clean); the min-history filter + common-range
    trim happen after, in `_filter_short_history` (v13 Q1)."""
    from equity_scout.data.etf_panel import load_price_history

    raw = load_price_history(tickers, start=start, snapshot=ENTRY_SNAPSHOT, refresh=True)
    return _filter_short_history(raw.closes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--tickers", default=None, help="comma-separated stock tickers")
    parser.add_argument("--model", default="all", help=f"all or one of {ENTRY_PRESETS}")
    parser.add_argument("--family", default="all", help="all, entry, entry_short or entry_tb")
    parser.add_argument("--start", default="2007-01-01")
    parser.add_argument("--horizon", type=int, default=HORIZON_DAYS)
    parser.add_argument(
        "--with-evidence",
        action="store_true",
        help=(
            "additionally train entry_tb challengers carrying the historical insider-cluster"
            " features (raises that family's multiple-testing candidate count accordingly)."
            " Requires a populated historical_events store in --db (raises otherwise)."
        ),
    )
    args = parser.parse_args()

    stock_tickers = _resolve_tickers(args.db, args.tickers)
    # SPY is the relative-return benchmark; dedup so a SPY already in the universe isn't doubled.
    panel_tickers = list(dict.fromkeys(stock_tickers + [BENCHMARK]))
    # Loaded before the network fetch below so a wrong/empty --db fails fast on a cheap DB read
    # instead of after the expensive panel download.
    evidence_index = load_evidence_index(args.db) if args.with_evidence else None
    panel = _load_panel(panel_tickers, args.start)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    models = ENTRY_PRESETS if args.model == "all" else (args.model,)
    families = ("entry", "entry_short", "entry_tb") if args.family == "all" else (args.family,)
    run_train_entry_all(
        args.db, panel=panel, tickers=stock_tickers, now=now, models=models,
        families=families, horizon_days=args.horizon, evidence_index=evidence_index,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
