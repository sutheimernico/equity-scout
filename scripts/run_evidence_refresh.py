"""Re-evaluate the evidence-featured entry_tb challengers once the resolve loop has produced
enough NEW real resolutions — the v15 P3 learning trigger.

This is a TRIGGER, not a gate and not a model. It only decides WHEN to spend a trial; the work
goes to the existing training path (`run_train_entry_all`, families=("entry_tb",)) whose registry
gate (`ml/model_registry.promote_if_better`) remains the sole promotion path. A champion still has
to clear MIN_OOS_N out-of-sample rows, the no-edge band around AUC 0.5, and an AUC delta scaled by
sqrt(number of candidates tested against it tonight).

Why a trigger at all: nightly retrains are nightly trials against the same OOS metric, and the
training set only moves when new market history arrives. Re-running on every chain execution buys
nothing but extra draws from the same noise — the same reason `_min_auc_delta` scales with the
candidate count. The Wave-1 resolve loop (first real resolutions from 2026-08-11) is the honest
clock: `resolved_stats(db)["n_resolved"]` counts the predictions the world has actually judged.

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
    "Multiples Testen: jeder Lauf stellt mehrere Presets demselben Champion gegenüber. Die "
    "AUC-Hürde steigt deshalb mit sqrt(Kandidatenzahl) — bei reinem Zufall wäre der beste von "
    "N Versuchen ohnehin der beste. Ein Champion-Wechsel heißt: Gate genommen. Er ist kein "
    "Nachweis eines Vorteils und keine Kauf-/Verkaufsempfehlung."
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
    particular the watermark advances ONLY after `train` returned, so a crashed run re-triggers
    instead of silently consuming its own trigger.

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
        "n_candidates": 0,
        "promoted": [],
    }
    if not result["triggered"] or not apply:
        return result
    results = train(load_index(db_path))
    result["n_candidates"] = len(results)
    result["promoted"] = [r["version"] for r in results if r.get("promoted")]
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
        return (
            f"Trockenlauf: {result['new_resolutions']} neue aufgelöste Vorhersage(n) "
            f"(Minimum {result['min_new_resolutions']}). Mit --apply würden die "
            "entry_tb-Herausforderer mit und ohne Evidence-Features neu bewertet. Nichts "
            "geschrieben, Wasserstand unverändert."
        )
    lead = (
        f"{result['n_candidates']} entry_tb-Herausforderer gegen denselben Champion bewertet; "
        f"Wasserstand auf {result['n_resolved']} gesetzt."
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
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = run_evidence_refresh(
        args.db, min_new_resolutions=args.min_new_resolutions, apply=args.apply,
        train=lambda index: _train_entry_tb(args.db, now=now, evidence_index=index),
    )
    print(_summary(result))
    print(MULTIPLICITY_NOTE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
