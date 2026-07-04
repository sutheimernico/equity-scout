"""Radar CLI: latest funnel run -> entry-signal watchlist.

Usage:
    python scripts/run_radar.py [--db equity_scout.db] [--json-out watchlist.json]

Reads the newest screener run from the DB (run scripts/run_scout.py first),
fetches 1y of history per finalist, computes sub-signals + entry zones, stores
the watchlist snapshot and writes an optional JSON artifact (the file the
GitHub Actions tier will commit back in Phase 5).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timezone

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.entry import fetch_entry_history
from equity_scout.radar import History, build_watchlist
from equity_scout.radar_storage import save_watchlist
from equity_scout.storage import load_latest_run


def _finalists_from_run(run: dict) -> list[dict]:
    """Flatten a stored run's buckets into the finalist dicts radar.build_watchlist eats."""
    finalists: list[dict] = []
    for bucket, picks in run.get("buckets", {}).items():
        for pick in picks:
            instrument = pick.get("instrument", {})
            finalists.append(
                {
                    "ticker": instrument.get("ticker", ""),
                    "name": instrument.get("name", ""),
                    "bucket": bucket,
                    "breakdown": pick.get("breakdown", {}),
                }
            )
    return finalists


def run_radar(
    run: dict,
    db_path: str,
    json_out: str | None,
    created_at: str,
    fetch_history: Callable[[str], History] = fetch_entry_history,
) -> int:
    """Build, persist and (optionally) export the watchlist. Returns entry count."""
    finalists = _finalists_from_run(run)
    histories = {f["ticker"]: fetch_history(f["ticker"]) for f in finalists}
    watchlist = build_watchlist(finalists, histories, created_at=created_at)
    save_watchlist(db_path, watchlist)
    if json_out:
        with open(json_out, "w", encoding="utf-8") as fh:
            json.dump(asdict(watchlist), fh, ensure_ascii=False, indent=2)
    for ticker, reason in watchlist.skipped.items():
        print(f"skipped {ticker}: {reason}")
    return len(watchlist.entries)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()
    run = load_latest_run(args.db)
    if run is None:
        print("No screener run found — run scripts/run_scout.py first.", file=sys.stderr)
        return 1
    # load_latest_run returns a RunResult dataclass, not a plain dict (deviation from the
    # plan's assumption); run_radar()/_finalists_from_run() stay dict-based so both this CLI
    # and tests (which build the dict by hand) share one code path — round-trip it here.
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    count = run_radar(asdict(run), db_path=args.db, json_out=args.json_out, created_at=created_at)
    print(f"Watchlist saved: {count} entries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
