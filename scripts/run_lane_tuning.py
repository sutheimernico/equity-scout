"""Nightly parameter search for the swing lane, with automatic adoption behind a hurdle (T12).

Chain step: search the grid over the lane's own event history, compare the winner against the
rules currently in force, and adopt only if the paired comparison clears the trial-count
hurdle AND nothing was changed this calendar month.

Nico approved automatic adoption on 2026-08-16 — this script is the only place that acts on it,
and it prints its verdict either way. A refusal has to be as readable as an adoption, or a
working brake looks exactly like a broken search.

Usage:
    python scripts/run_lane_tuning.py [--db shortterm.db] [--main-db equity_scout.db]
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import pandas as pd

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.data.etf_panel import load_price_history
from equity_scout.evidence.event_storage import load_classified_events
from equity_scout.exits import ExitRules
from equity_scout.lane_adoption import evaluate_adoption
from equity_scout.lane_params import changed_this_month, load_params, set_params
from equity_scout.lane_tuning import grid, search
from equity_scout.st_swing import (
    BULLISH_EVENTS,
    MAX_HOLDING_CALENDAR_DAYS,
    PROFIT_TARGET,
    STOP_LOSS,
)

SNAPSHOT = "data/prices/swing_history.csv"
MIN_EVENTS = 60


def collect_events(main_db: str) -> list[tuple[str, pd.Timestamp]]:
    """Bullish classified events — filtered through `st_swing.BULLISH_EVENTS`, the SAME set the
    live lane enters on. Anything else would tune a lane that does not exist."""
    out: list[tuple[str, pd.Timestamp]] = []
    for event in load_classified_events(main_db):
        if event.get("event_type") not in BULLISH_EVENTS:
            continue
        stamp = event.get("published_at") or event.get("seen_at")
        if not event.get("ticker") or not stamp:
            continue
        out.append((event["ticker"].upper(), pd.Timestamp(str(stamp)[:10])))
    return out


def run(db: str, main_db: str, *, now: datetime) -> str:
    events = collect_events(main_db)
    if len(events) < MIN_EVENTS:
        return (f"Parametersuche übersprungen: nur {len(events)} auswertbare Ereignisse "
                f"(mindestens {MIN_EVENTS} nötig, sonst misst die Suche Rauschen).")

    tickers = sorted({t for t, _ in events})
    start = (min(d for _, d in events) - pd.Timedelta(days=30)).date().isoformat()
    panel = load_price_history(tickers, start=start, snapshot=SNAPSHOT, refresh=True)
    closes = {t: panel.closes[t].dropna() for t in panel.tickers if t in panel.closes}
    if not closes:
        return "Parametersuche übersprungen: keine Kurshistorie verfügbar."

    trials = search(closes, events)
    best = max(trials, key=lambda t: t.mean_pnl_pct)
    shipped = ExitRules(PROFIT_TARGET, STOP_LOSS, MAX_HOLDING_CALENDAR_DAYS)
    current = load_params(db, "swing", default=shipped)
    challenger = ExitRules(best.profit_target, best.stop_loss, best.max_days)

    verdict = evaluate_adoption(
        closes, events, challenger=challenger, incumbent=current, n_trials=len(grid()),
        already_changed_this_month=changed_this_month(db, "swing", month=now.strftime("%Y-%m")),
    )
    head = (f"Parametersuche Swing-Lane: {len(events)} Ereignisse, {len(trials)} Kombinationen. "
            f"Bester Kandidat Ziel {challenger.profit_target:.0%} / Stop "
            f"{challenger.stop_loss:.0%} / {challenger.max_holding_days} Tage "
            f"(aktuell {current.profit_target:.0%} / {current.stop_loss:.0%} / "
            f"{current.max_holding_days}).")
    if not verdict.adopt:
        return f"{head}\n  Keine Änderung — {verdict.reason}"

    set_params(
        db, "swing", challenger,
        reason=verdict.reason,
        evidence={"paired_t": verdict.paired_t, "mean_diff": verdict.mean_diff,
                  "n_pairs": verdict.n_pairs, "hurdle_t": verdict.hurdle_t,
                  "n_trials": len(grid()), "previous": [current.profit_target,
                                                        current.stop_loss,
                                                        current.max_holding_days]},
        now=now.isoformat(timespec="seconds"),
    )
    return f"{head}\n  ANGEPASST — {verdict.reason}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="shortterm.db")
    parser.add_argument("--main-db", default=DEFAULT_DB_PATH)
    args = parser.parse_args()
    print(run(args.db, args.main_db, now=datetime.now(timezone.utc)))


if __name__ == "__main__":
    main()
