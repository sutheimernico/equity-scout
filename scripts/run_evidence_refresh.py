"""Re-evaluate the evidence-featured entry_tb challengers once the resolve loop has produced
enough NEW real resolutions — the v15 P3 learning trigger.

This is a TRIGGER, not a gate and not a model. It only decides WHEN to spend a trial; the work
goes to the existing training path (`run_train_entry_all`, families=("entry_tb",)) whose registry
gate (`ml/model_registry.promote_if_better`) remains the sole promotion path. Every candidate still
has to clear MIN_OOS_N out-of-sample rows and the no-edge band around AUC 0.5; entry_tb has zero
champions today, so its FIRST promotion only needs that absolute floor — the extra AUC delta
scaled by sqrt(number of candidates tested tonight) only applies once entry_tb has an incumbent
champion to beat.

Why a trigger at all: nightly retrains are nightly trials against the same OOS metric, and the
training set only moves when new market history arrives. Re-running on every chain execution buys
nothing but extra draws from the same noise — the same reason `_min_auc_delta` scales with the
candidate count. `resolved_stats(db)["n_resolved"]` is a PROXY for elapsed market information, NOT
the clock of the entry_tb OOS metric: the ledger's predictions are scored by the `entry` family's
champion (`run_score_watchlist.py` -> `entry_champion(db_path)`, default family), and
`walk_forward_evaluate` reads the price panel directly — it never touches the ledger. Measured
cadence: the daily chain logs ~30 predictions per business day (one per watchlist ticker; see
`equity_scout.db`), so once the Wave-1 resolve loop (first real resolutions from 2026-08-11) has
warmed up, almost every day clears `DEFAULT_MIN_NEW_RESOLUTIONS` on its own — this threshold mainly
throttles ad-hoc manual runs, not the nightly chain. It is a proxy, not a designed clock; a
panel-based as_of count would be the more honest v2 — a documented follow-up, not built here.

Dry-run default; `--apply` is what registers challengers and advances the watermark. Network only
in main() (the price panel), `now` injected, so the tests run offline.

Usage:
    python scripts/run_evidence_refresh.py [--db equity_scout.db]
        [--min-new-resolutions 30] [--apply]
"""
from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.ml.evidence_features import EvidenceIndex, load_evidence_index
from equity_scout.ml.prediction_ledger import resolved_stats
from equity_scout.state_storage import get_state, set_state

WATERMARK_KEY = "evidence_refresh_resolved_watermark"

# The repo's standing minimum-evidence unit before it will rule on anything:
# `historical_study.DEFAULT_MIN_CELL_N` is 30 measurements per split side, and the arena's
# promotion gate wants >= 30 trades. This is a TRIGGER threshold, not a statistical test — the
# statistical bar stays MIN_OOS_N / the AUC delta inside `promote_if_better`.
DEFAULT_MIN_NEW_RESOLUTIONS = 30

MULTIPLICITY_NOTE = (
    "Multiples Testen: Für den ersten Champion einer Familie gilt allein die absolute Hürde "
    "des Registry-Gates (Mindestzahl an Out-of-Sample-Zeilen, AUC klar über 0,5 — noch kein "
    "Vergleichswert vorhanden). "
    "Gegen einen bestehenden Champion stellt jeder Lauf zusätzlich mehrere Presets demselben "
    "Champion gegenüber, und die AUC-Hürde steigt mit sqrt(Kandidatenzahl) — bei reinem Zufall "
    "wäre der beste von N Versuchen ohnehin der beste. Ein Champion-Wechsel heißt: Gate "
    "genommen. Er ist kein Nachweis eines Vorteils und keine Kauf-/Verkaufsempfehlung."
)


def _watermark(db_path: str) -> int:
    """The `n_resolved` reading at the last applied refresh. A corrupted value reads as 0 so the
    loop re-triggers — an unparsable watermark must never silently block learning forever."""
    raw = get_state(db_path, key=WATERMARK_KEY)
    if raw is None:
        return 0
    try:
        return int(raw)
    except ValueError:
        return 0


def run_evidence_refresh(
    db_path: str,
    *,
    min_new_resolutions: int = DEFAULT_MIN_NEW_RESOLUTIONS,
    apply: bool = False,
    train: Callable[[EvidenceIndex], list[dict]],
    load_index: Callable[[str], EvidenceIndex] = load_evidence_index,
) -> dict:
    """Trigger check, then (only with `apply`) one evidence-featured entry_tb training round.

    `train` and `load_index` are injected seams so the tests never touch the network or fit a
    model. Nothing is written below the threshold and nothing is written on a dry run — in
    particular the watermark advances ONLY after `train` returned AND produced at least one
    evaluated (non-crashed) row, so a crashed run re-triggers instead of silently consuming its
    own trigger. `run_train_entry_all` reports a broken preset as a row with `version=None`
    rather than raising (one bad preset must not kill the night's others) — this function must
    not count those rows as "evaluated", or a night of pure crashes would print "N Herausforderer
    bewertet, keiner hat die Hürde genommen" and burn the trigger on work that never happened.

    Crash-window trade-off: if the process dies between `train()` returning and `set_state`
    writing the watermark, the next run re-triggers — a LIBERAL choice on trial-counting (any
    challengers `train()` already registered before the crash are invisible to that next run's
    `n_candidates`), chosen deliberately in favor of the learning loop over exact trial-accounting.

    No `now` parameter on purpose: this function reads a COUNT, not a clock. `now` is threaded
    where it is actually used — main() computes it and the `train` closure hands it to
    `run_train_entry_all`, which stamps the registry rows.
    """
    n_resolved = int(resolved_stats(db_path)["n_resolved"])
    watermark = _watermark(db_path)
    new_resolutions = max(n_resolved - watermark, 0)
    result = {
        "n_resolved": n_resolved,
        "watermark": watermark,
        "new_resolutions": new_resolutions,
        "min_new_resolutions": min_new_resolutions,
        "triggered": new_resolutions >= min_new_resolutions,
        "applied": False,
        "apply_requested": bool(apply),
        "n_candidates": 0,
        "n_failed": 0,
        "promoted": [],
    }
    if not result["triggered"] or not apply:
        return result
    results = train(load_index(db_path))
    evaluated = [r for r in results if r.get("version") is not None]
    result["n_candidates"] = len(evaluated)
    result["n_failed"] = len(results) - len(evaluated)
    result["promoted"] = [r["version"] for r in evaluated if r.get("promoted")]
    if not evaluated:
        return result  # every preset crashed — nothing to report, watermark stays put
    set_state(db_path, key=WATERMARK_KEY, value=str(n_resolved))
    result["applied"] = True
    return result


def _summary(result: dict) -> str:
    """German one-paragraph verdict. Never claims an edge: a promotion is a passed gate."""
    if not result["triggered"]:
        return (
            f"Kein Refresh: {result['new_resolutions']} neue aufgelöste Vorhersage(n) seit dem "
            f"letzten Lauf (Wasserstand {result['watermark']}, aktuell {result['n_resolved']}) — "
            f"Minimum ist {result['min_new_resolutions']}. Nichts neu bewertet, Champion "
            "unverändert."
        )
    if not result["applied"]:
        # Branch on the requested mode, not on n_failed truthiness: a train() that returns an
        # empty list on an --apply run is also "nothing evaluated", not a dry run.
        if result.get("apply_requested"):
            return (
                f"Refresh ausgelöst, aber kein Preset wurde bewertet "
                f"({result['n_failed']} fehlgeschlagen) — Wasserstand unverändert "
                f"(weiterhin {result['watermark']}). Der nächste Lauf triggert erneut."
            )
        return (
            f"Trockenlauf: {result['new_resolutions']} neue aufgelöste Vorhersage(n) "
            f"(Minimum {result['min_new_resolutions']}). Mit --apply würden die "
            "entry_tb-Herausforderer mit und ohne Evidence-Features neu bewertet. Nichts "
            "geschrieben, Wasserstand unverändert."
        )
    total = result["n_candidates"] + result["n_failed"]
    if result["n_failed"]:
        lead = (
            f"{result['n_candidates']} von {total} Presets bewertet "
            f"({result['n_failed']} fehlgeschlagen); Wasserstand auf {result['n_resolved']} "
            "gesetzt."
        )
    else:
        lead = (
            f"{result['n_candidates']} entry_tb-Herausforderer gegen denselben Champion "
            f"bewertet; Wasserstand auf {result['n_resolved']} gesetzt."
        )
    if not result["promoted"]:
        return lead + " Kein Champion-Wechsel — keiner hat die Hürde des Registry-Gates genommen."
    versions = ", ".join(f"v{v}" for v in result["promoted"])
    return lead + f" Champion-Wechsel: {versions} hat die Hürde des Registry-Gates genommen."


def _train_entry_tb(db_path: str, *, now: str, evidence_index: EvidenceIndex) -> list[dict]:
    """Network path: reuse run_train_entry's OWN universe/panel helpers, so this runner can never
    train on a different panel than the nightly chain does. Lazy import keeps sklearn/catboost and
    the network out of import time and out of the tests."""
    from scripts.run_train_entry import (
        BENCHMARK,
        _load_panel,
        _resolve_tickers,
        run_train_entry_all,
    )

    tickers = _resolve_tickers(db_path, None)
    panel = _load_panel(list(dict.fromkeys(tickers + [BENCHMARK])), "2007-01-01")
    return run_train_entry_all(
        db_path, panel=panel, tickers=tickers, now=now,
        families=("entry_tb",), evidence_index=evidence_index,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--min-new-resolutions", type=int, default=DEFAULT_MIN_NEW_RESOLUTIONS,
        help="how many newly RESOLVED predictions must have arrived since the last refresh",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="write: register/promote the challengers and advance the watermark",
    )
    args = parser.parse_args()
    if args.min_new_resolutions < 1:
        parser.error(
            "--min-new-resolutions muss >= 1 sein — ein Minimum von 0 macht den Runner zum "
            "Noise-Generator (jede vorbeiziehende Resolution würde erneut triggern)."
        )
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = run_evidence_refresh(
        args.db, min_new_resolutions=args.min_new_resolutions, apply=args.apply,
        train=lambda index: _train_entry_tb(args.db, now=now, evidence_index=index),
    )
    print(_summary(result))
    print(MULTIPLICITY_NOTE)
    # A triggered --apply run in which nothing was evaluated is a failure, not a refusal —
    # a chain wrapper reading the exit code must not log it as OK.
    if result["apply_requested"] and result["triggered"] and not result["applied"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
