"""Catalyst-calendar CLI (layer 3 of the radar): write the KNOWN upcoming dates to the signal book.

Two sources, one table: ClinicalTrials.gov phase-2/3 primary completions of industry sponsors
(fetched live, keyless) and the earnings dates scripts/run_earnings.py already collected
(read-only from equity_scout.db). Both land in `catalyst_signals` as source `calendar` with a
`due_date`, so the alarm and cockpit layers can say "MRNA has a phase-3 readout due in 47
days" before anything moves.

Daily cadence is enough — a trial date moves by weeks, not by minutes. Every signal carries a
dedup key built from (NCT id / ticker + date), so running it twice on the same day writes
nothing the second time and a rescheduled readout gets its own row.

Usage:
    uv run python scripts/run_catalyst_calendar.py [--db equity_scout.db]
        [--catalyst-db catalysts.db] [--days 90] [--dry-run]
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from equity_scout.catalyst_calendar import (
    DEFAULT_HORIZON_DAYS,
    build_sponsor_index,
    earnings_signals,
    fetch_trials,
    trial_signals,
)
from equity_scout.catalyst_storage import (
    DEFAULT_CATALYST_DB_PATH,
    init_catalyst_db,
    record_rejections,
    record_signals,
)
from equity_scout.constants import DEFAULT_DB_PATH, DEFAULT_UNIVERSE_PATH
from equity_scout.earnings_storage import earnings_within
from equity_scout.universe import load_universe


def run_catalyst_calendar(
    *,
    db_path: str,
    catalyst_db_path: str,
    universe_path: str,
    today: str,
    seen_at: str,
    days: int = DEFAULT_HORIZON_DAYS,
    apply: bool = True,
    fetch=None,
) -> dict:
    """Fetch both calendars, map sponsors, persist. Returns the run's counts.

    `trials` is None when ClinicalTrials.gov could not be reached — reported as its own state
    so an unreachable source never reads as "no readouts are coming". The earnings half is
    processed either way; the two sources fail independently.
    """
    index = build_sponsor_index([(i.ticker, i.name) for i in load_universe(universe_path)])
    trials = (fetch or fetch_trials)(today=today, days=days)

    signals: list[dict] = []
    rejections: list[dict] = []
    unmapped = 0
    if trials:
        signals, rejections, unmapped = trial_signals(
            trials, index, today=today, days=days, seen_at=seen_at
        )
    earnings = earnings_signals(
        earnings_within(db_path, today=today, days=days), seen_at=seen_at
    )

    written = 0
    rejections_written = 0
    if apply:
        init_catalyst_db(catalyst_db_path)
        written = record_signals(catalyst_db_path, signals + earnings)
        rejections_written = record_rejections(catalyst_db_path, rejections)

    return {
        "source_reachable": trials is not None,
        "trials_fetched": len(trials) if trials is not None else 0,
        "trial_signals": len(signals),
        "ambiguous_sponsors": len(rejections),
        "unmapped_sponsors": unmapped,
        "earnings_signals": len(earnings),
        "written": written,
        "rejections_written": rejections_written,
        "signals": signals + earnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--catalyst-db", default=DEFAULT_CATALYST_DB_PATH)
    parser.add_argument("--days", type=int, default=DEFAULT_HORIZON_DAYS)
    parser.add_argument(
        "--dry-run", action="store_true", help="fetch and report, write nothing"
    )
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    result = run_catalyst_calendar(
        db_path=args.db,
        catalyst_db_path=args.catalyst_db,
        universe_path=DEFAULT_UNIVERSE_PATH,
        today=now.date().isoformat(),
        seen_at=now.isoformat(timespec="seconds"),
        days=args.days,
        apply=not args.dry_run,
    )

    mode = " [dry-run]" if args.dry_run else ""
    if not result["source_reachable"]:
        print("ClinicalTrials.gov nicht erreichbar — keine Aussage über Studientermine.")
    else:
        print(
            f"Studien{mode}: {result['trials_fetched']} Phase-2/3-Studien in den nächsten "
            f"{args.days} Tagen -> {result['trial_signals']} Signal(e); "
            f"{result['unmapped_sponsors']} Sponsor(en) ohne Ticker im Universum, "
            f"{result['ambiguous_sponsors']} mehrdeutig (abgelehnt)."
        )
    print(f"Earnings{mode}: {result['earnings_signals']} bekannte Termine im Fenster.")
    if args.dry_run:
        for sig in sorted(result["signals"], key=lambda s: (s["due_date"], s["ticker"])):
            print(f"  {sig['due_date']}  {sig['ticker']:12} {sig['score']:.2f}  {sig['detail']}")
    else:
        print(
            f"Signalbuch: {result['written']} neu geschrieben "
            f"(Dopplungen übersprungen), {result['rejections_written']} Ablehnung(en)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
