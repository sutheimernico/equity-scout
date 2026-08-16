"""Nightly no-trade-book resolution — settles what the rejected opportunities would have done.

Runs in nightly_train.sh directly before lane_review, so the review can compare traded
against rejected the same night. Read-only with respect to trading: it changes no rule and
routes no order; it only stamps simulation results onto st_rejections rows.

Usage:
    python scripts/run_rejection_review.py [--db shortterm.db]
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone

from equity_scout.data.etf_panel import load_price_history
from equity_scout.exits import ExitRules
from equity_scout.lane_params import load_params
from equity_scout.rejection_review import resolve_swing_rejections
from equity_scout.shortterm_storage import (
    load_open_rejections,
    resolve_rejections,
)
from equity_scout.st_swing import MAX_HOLDING_CALENDAR_DAYS, PROFIT_TARGET, STOP_LOSS

REJECTIONS_SNAPSHOT = "data/prices/st_rejections_panel.csv"


def run_rejection_review(db_path: str, *, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    open_rows = load_open_rejections(db_path, "swing")
    if not open_rows:
        return "Nicht-Trade-Buch: nichts offen."
    shipped = ExitRules(profit_target=PROFIT_TARGET, stop_loss=STOP_LOSS,
                        max_holding_days=MAX_HOLDING_CALENDAR_DAYS)
    rules = load_params(db_path, "swing", default=shipped)
    tickers = sorted({r["ticker"] for r in open_rows})
    start = (
        min(date.fromisoformat(r["seen_at"][:10]) for r in open_rows) - timedelta(days=5)
    ).isoformat()
    panel = load_price_history(tickers, start=start, snapshot=REJECTIONS_SNAPSHOT, refresh=True)
    closes = {
        t: panel.closes[t].dropna()
        for t in panel.tickers
        if len(panel.closes[t].dropna())
    }
    resolutions = resolve_swing_rejections(open_rows, closes, rules, now=now)
    resolve_rejections(db_path, resolutions)
    settled = [r for r in resolutions if r["sim_return"] is not None]
    positive = sum(1 for r in settled if r["sim_return"] > 0)
    mean = (sum(r["sim_return"] for r in settled) / len(settled)) if settled else 0.0
    lines = [
        f"Nicht-Trade-Buch (swing): {len(resolutions)} von {len(open_rows)} offenen aufgelöst.",
    ]
    if settled:
        lines.append(
            f"  Davon wären {positive}/{len(settled)} im Plus gelandet, "
            f"mittlerer simulierter Return {mean:+.2%} (BRUTTO — beantwortet 'war die "
            f"Ablehnung richtig?', nicht 'hätten wir verdient?')."
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="shortterm.db")
    args = parser.parse_args()
    print(run_rejection_review(args.db))


if __name__ == "__main__":
    main()
