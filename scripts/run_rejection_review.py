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
from equity_scout.data.ohlc_panel import load_ohlc_panel
from equity_scout.exits import ExitRules
from equity_scout.lane_params import load_params
from equity_scout.rejection_review import (
    resolve_gapfade_rejections,
    resolve_swing_rejections,
)
from equity_scout.shortterm_storage import (
    load_open_rejections,
    resolve_rejections,
)
from equity_scout.st_swing import MAX_HOLDING_CALENDAR_DAYS, PROFIT_TARGET, STOP_LOSS

REJECTIONS_SNAPSHOT = "data/prices/st_rejections_panel.csv"
REJECTIONS_OHLC_SNAPSHOT = "data/prices/st_rejections_ohlc.csv"


def _earliest_start(rows: list[dict], *, margin_days: int = 5) -> str:
    return (
        min(date.fromisoformat(r["seen_at"][:10]) for r in rows) - timedelta(days=margin_days)
    ).isoformat()


def _resolve_swing(db_path: str, rows: list[dict], *, now: datetime) -> list[dict]:
    shipped = ExitRules(profit_target=PROFIT_TARGET, stop_loss=STOP_LOSS,
                        max_holding_days=MAX_HOLDING_CALENDAR_DAYS)
    rules = load_params(db_path, "swing", default=shipped)
    panel = load_price_history(sorted({r["ticker"] for r in rows}),
                               start=_earliest_start(rows),
                               snapshot=REJECTIONS_SNAPSHOT, refresh=True)
    closes = {
        t: panel.closes[t].dropna()
        for t in panel.tickers
        if len(panel.closes[t].dropna())
    }
    return resolve_swing_rejections(rows, closes, rules, now=now)


def _resolve_gapfade(rows: list[dict], *, now: datetime) -> list[dict]:
    ohlc = load_ohlc_panel(sorted({r["ticker"] for r in rows}),
                           start=_earliest_start(rows),
                           snapshot=REJECTIONS_OHLC_SNAPSHOT, refresh=True)
    return resolve_gapfade_rejections(rows, ohlc, now=now)


def _summary(lane: str, open_rows: list[dict], resolutions: list[dict]) -> list[str]:
    settled = [r for r in resolutions if r["sim_return"] is not None]
    positive = sum(1 for r in settled if r["sim_return"] > 0)
    mean = (sum(r["sim_return"] for r in settled) / len(settled)) if settled else 0.0
    lines = [
        f"Nicht-Trade-Buch ({lane}): {len(resolutions)} von {len(open_rows)} "
        f"offenen aufgelöst."
    ]
    if settled:
        lines.append(
            f"  Davon wären {positive}/{len(settled)} im Plus gelandet, "
            f"mittlerer simulierter Return {mean:+.2%} (BRUTTO — beantwortet 'war die "
            f"Ablehnung richtig?', nicht 'hätten wir verdient?')."
        )
    return lines


def run_rejection_review(db_path: str, *, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    lines: list[str] = []
    swing_rows = load_open_rejections(db_path, "swing")
    if swing_rows:
        resolutions = _resolve_swing(db_path, swing_rows, now=now)
        resolve_rejections(db_path, resolutions)
        lines += _summary("swing", swing_rows, resolutions)
    gapfade_rows = load_open_rejections(db_path, "gapfade")
    if gapfade_rows:
        resolutions = _resolve_gapfade(gapfade_rows, now=now)
        resolve_rejections(db_path, resolutions)
        lines += _summary("gapfade", gapfade_rows, resolutions)
    return "\n".join(lines) if lines else "Nicht-Trade-Buch: nichts offen."


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="shortterm.db")
    args = parser.parse_args()
    print(run_rejection_review(args.db))


if __name__ == "__main__":
    main()
