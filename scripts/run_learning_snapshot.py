"""Write today's daily learning-curve snapshot (Strang C, task C1).

Glue over already-tested building blocks — no new computation: `n_train` comes from the current
`entry` champion's registry row (`registry_summary`), `n_resolved`/`hit_rate`/`rank_ic` come from
the trailing prediction-ledger window (`resolved_stats_windowed`). `now` is injected so the core
function runs offline in tests; only `main()` reads the wall clock. Meant to run nightly right
after `run_train_entry.py` (same chain, `nightly_train.sh`), so the snapshot reflects that night's
freshest champion — but it is read-only w.r.t. training/resolving, so it is also safe to run any
time (e.g. by hand) without side effects on the registry or the ledger.

Usage:
    python scripts/run_learning_snapshot.py [--db equity_scout.db] [--window-days 30]
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.ml.learning_curve import save_snapshot
from equity_scout.ml.model_registry import registry_summary
from equity_scout.ml.prediction_ledger import resolved_stats_windowed

# The rolling window backing hit_rate/rank_ic — matches the shorter of the two windows already
# shown on /api/model ("is it getting better LATELY?"), so the daily snapshot and the live
# dashboard numbers agree at a glance.
DEFAULT_WINDOW_DAYS = 30


def run_learning_snapshot(
    db_path: str, *, now: str, window_days: int = DEFAULT_WINDOW_DAYS, family: str = "entry"
) -> dict:
    """Compute + persist today's snapshot for `family`'s champion. `n_train` is None (never
    faked) when `family` has no champion yet; `hit_rate`/`rank_ic` are None when the window has
    no resolved predictions (`resolved_stats_windowed` already reports that honestly). Returns
    the persisted row."""
    summary = registry_summary(db_path)
    champion_version = summary["champions"].get(family)
    n_train = None
    if champion_version is not None:
        row = next(v for v in summary["versions"] if v["version"] == champion_version)
        n_train = row["n_train"]

    stats = resolved_stats_windowed(db_path, window_days=window_days, now=now)
    snapshot = {
        "snapshot_date": now[:10],
        "created_at": now,
        "n_train": n_train,
        "n_resolved": stats["n_resolved"],
        "hit_rate": stats["hit_rate"],
        "rank_ic": stats["rank_ic"],
    }
    save_snapshot(db_path, **snapshot)
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    args = parser.parse_args()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    snapshot = run_learning_snapshot(args.db, now=now, window_days=args.window_days)
    n_train = snapshot["n_train"] if snapshot["n_train"] is not None else "n/a"
    hit_rate = (
        f"{snapshot['hit_rate'] * 100:.0f} %" if snapshot["hit_rate"] is not None else "n/a"
    )
    print(
        f"Lernkurven-Snapshot {snapshot['snapshot_date']}: n_train={n_train}, "
        f"n_resolved={snapshot['n_resolved']} ({args.window_days}d), Trefferquote={hit_rate}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
