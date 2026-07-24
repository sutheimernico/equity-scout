"""One-off state repair for the 2026-07-24 future-as_of incident (see the companion
commit "fix(data): trim price panels to the last completed US session").

What happened: the 02:34 nightly ran against a stock panel carrying a Tokyo-stamped
2026-07-24 row (US columns = ffill copies of Thursday's closes). The depot and the
ML Long Bot advanced to a day whose US session had not happened: last_as_of and the
depot's pending_orders.decided_as_of landed on 2026-07-24, three depot marks were
stamped 2026-07-24 at Thursday's prices, and both books wrote a pseudo valuation for
2026-07-24. Left alone, the Saturday run (real Friday close, panel now trimmed to
completed sessions) would see last_as_of >= today and idempotently skip -> Friday's
close never books and the pending orders only fill Tuesday at the close fallback.

This repair re-anchors the state to the last completed session (2026-07-23):
  - autotrader.db account blob: last_as_of + pending_orders.decided_as_of -> 2026-07-23;
    marks dated 2026-07-24 -> 2026-07-23 (prices untouched - the ffill values ARE
    Thursday's closes); DELETE the 2026-07-24 pseudo valuation.
  - forward_paper.db "ML Long Bot" blob: last_as_of -> 2026-07-23; DELETE its
    2026-07-24 pseudo valuation.

Known, accepted residue (not repairable): the 2026-07-23 15:57 manual run booked
intraday prices as that day's close; the depot's mark path silently absorbed the
intraday-to-close difference. One-time valuation blur, documented in AUTOPILOT_LOG.md.

Idempotent: rows/fields already clean are reported and skipped. Dry-run by default;
pass --apply to write. Take DB copies first.
"""
from __future__ import annotations

import argparse
import json
import sqlite3

BAD_DAY = "2026-07-24"
GOOD_DAY = "2026-07-23"


def fix_autotrader(db: str, apply: bool) -> None:
    con = sqlite3.connect(db)
    try:
        row = con.execute(
            "SELECT id, data FROM autotrader_account ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        if row is None:
            print("autotrader: no account row - nothing to do")
            return
        acc_id, blob = row[0], json.loads(row[1])
        changed = False
        if blob.get("last_as_of") == BAD_DAY:
            blob["last_as_of"] = GOOD_DAY
            changed = True
            print(f"autotrader: last_as_of {BAD_DAY} -> {GOOD_DAY}")
        pending = blob.get("pending_orders") or {}
        if pending.get("decided_as_of") == BAD_DAY:
            pending["decided_as_of"] = GOOD_DAY
            changed = True
            print(f"autotrader: pending_orders.decided_as_of {BAD_DAY} -> {GOOD_DAY}")
        for ticker, mark in (blob.get("last_marks") or {}).items():
            if mark[0] == BAD_DAY:
                mark[0] = GOOD_DAY
                changed = True
                print(f"autotrader: mark {ticker} dated {BAD_DAY} -> {GOOD_DAY} "
                      f"(price {mark[1]} kept - it IS Thursday's close)")
        if not changed:
            print("autotrader: account blob already clean")
        elif apply:
            con.execute(
                "UPDATE autotrader_account SET data = ? WHERE id = ?",
                (json.dumps(blob), acc_id),
            )
        doomed = con.execute(
            "SELECT id FROM autotrader_valuations WHERE created_at = ?", (BAD_DAY,)
        ).fetchall()
        print(f"autotrader: pseudo valuations for {BAD_DAY}: {[r[0] for r in doomed] or 'none'}")
        if doomed and apply:
            con.execute("DELETE FROM autotrader_valuations WHERE created_at = ?", (BAD_DAY,))
        if apply:
            con.commit()
    finally:
        con.close()


def fix_forward(db: str, apply: bool) -> None:
    con = sqlite3.connect(db)
    try:
        for name, data in con.execute("SELECT strategy_name, data FROM forward_accounts"):
            blob = json.loads(data)
            if blob.get("last_as_of") != BAD_DAY:
                continue
            blob["last_as_of"] = GOOD_DAY
            print(f"forward: {name} last_as_of {BAD_DAY} -> {GOOD_DAY}")
            if apply:
                con.execute(
                    "UPDATE forward_accounts SET data = ? WHERE strategy_name = ?",
                    (json.dumps(blob), name),
                )
            doomed = con.execute(
                "SELECT id FROM forward_valuations WHERE strategy_name = ? AND created_at = ?",
                (name, BAD_DAY),
            ).fetchall()
            print(f"forward: {name} pseudo valuations for {BAD_DAY}: "
                  f"{[r[0] for r in doomed] or 'none'}")
            if doomed and apply:
                con.execute(
                    "DELETE FROM forward_valuations WHERE strategy_name = ? AND created_at = ?",
                    (name, BAD_DAY),
                )
        if apply:
            con.commit()
    finally:
        con.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--autotrader-db", default="autotrader.db")
    ap.add_argument("--forward-db", default="forward_paper.db")
    ap.add_argument("--apply", action="store_true", help="Write the repair (default: dry-run).")
    args = ap.parse_args()
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] re-anchoring future as_of {BAD_DAY} -> {GOOD_DAY}\n")
    fix_autotrader(args.autotrader_db, args.apply)
    print()
    fix_forward(args.forward_db, args.apply)


if __name__ == "__main__":
    main()
