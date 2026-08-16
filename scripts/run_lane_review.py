"""Nightly lane review — the "was it working, and where did the result come from" step.

Runs after the lanes have advanced (`nightly_train.sh`), reads each lane's closed trades,
and writes one review per lane. The previous review is kept in `st_state` so the text can say
what MOVED since last night instead of restating the same totals every day.

Read-only with respect to trading: it changes no rule, promotes nothing, and routes no order.

Usage:
    python scripts/run_lane_review.py [--db shortterm.db]
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone

from equity_scout.lane_review import render, review_lane
from equity_scout.shortterm_storage import (
    LANES,
    get_lane_state,
    load_resolved_rejections,
    load_trades,
    set_lane_state,
)

STATE_KEY = "last_review"
# The review window for the no-trade book: one lane holding period, so "what would the
# rejected have done" and "what did the traded do" cover comparable nights.
REJECTION_WINDOW_DAYS = 7


def run_lane_review(db_path: str) -> str:
    reviews = []
    since = (
        datetime.now(timezone.utc) - timedelta(days=REJECTION_WINDOW_DAYS)
    ).isoformat(timespec="seconds")
    for lane in LANES:
        trades = load_trades(db_path, lane, limit=None)
        rejections = load_resolved_rejections(db_path, lane, since=since)
        if not trades and not rejections:
            continue
        raw = get_lane_state(db_path, lane, STATE_KEY)
        previous = json.loads(raw) if raw else None
        review = review_lane(lane, trades, previous=previous, rejections=rejections)
        reviews.append(review)
        set_lane_state(db_path, lane, STATE_KEY, json.dumps(review.as_dict()))
    return render(reviews)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="shortterm.db")
    args = parser.parse_args()
    print(run_lane_review(args.db))


if __name__ == "__main__":
    main()
