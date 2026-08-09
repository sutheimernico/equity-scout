"""One-off repair (2026-08-05): re-stamp resolve_after on OPEN entry_predictions with the
trading-day formula. Rows were stamped created_at + horizon CALENDAR days and became "due"
~8 days before their forward window was observable. Resolved rows are never touched
(append-only ledger). Dry-run by default; --apply writes.

Run from the repo root: uv run python scripts/fix_resolve_after_2026_08_05.py [--apply]
"""

from __future__ import annotations

import argparse
import sqlite3

from equity_scout.ml.prediction_ledger import resolve_after_stamp


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="equity_scout.db")
    parser.add_argument("--apply", action="store_true", help="write the new stamps")
    args = parser.parse_args()

    con = sqlite3.connect(args.db)
    rows = con.execute(
        "SELECT id, created_at, horizon_days, resolve_after FROM entry_predictions"
        " WHERE resolved_at IS NULL"
    ).fetchall()
    changes = [
        (resolve_after_stamp(created, horizon), row_id)
        for row_id, created, horizon, old in rows
        if resolve_after_stamp(created, horizon) != old
    ]
    print(f"Offene Predictions: {len(rows)}, neu zu stempeln: {len(changes)}")
    if args.apply and changes:
        con.executemany(
            "UPDATE entry_predictions SET resolve_after = ? WHERE id = ?", changes
        )
        con.commit()
        print(f"Aktualisiert: {len(changes)}")
    con.close()


if __name__ == "__main__":
    main()
