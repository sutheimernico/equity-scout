"""One-off repair (2026-08-11): drop stored voice events whose ticker the headline never names.

The 2026-08-11 audit found 79% of the 296 stored `voice` events carrying a ticker produced by the
capitalization-based name channels rather than by the text — "Aussies Take Over The City" filed
under Take-Two, "Who Foots the Bill" under BILL Holdings, "- Yahoo Finance Singapore" under
Finance of America. `evidence/voices.py` was fixed the same day (`_COMMON_WORDS` +
`strip_outlet_suffix`), but that only stops NEW rows; the stored ones keep polluting the
signal radar and, for the directional ones, the prediction ledger.

Method: re-run the CURRENT resolver over each stored event's own headline. A row is dropped only
when today's resolver refuses the ticker outright or resolves a DIFFERENT one — i.e. when the
stored attribution cannot be reproduced from its own source text. Nothing is re-attributed: a
row whose ticker changed is deleted too, not rewritten, because the surrounding fields (kind,
direction, event_key) were derived under the old attribution and would otherwise disagree with
the ticker.

It also removes some GENUINE but ambiguous mentions, and that is intended rather than a flaw:
"Why Michael Burry Thinks Alibaba, JD.Com, Baidu Needs Re-Evaluation?" names three companies, so
today's resolver returns None by the project's ambiguity-is-a-non-match rule. Such a row only
exists because the older, leakier resolver picked one of the three. Keeping it would preserve an
attribution the current rules would never make — the repair is deliberately biased toward less
evidence over wrong evidence.

Deletes, so the safety rails are deliberate:
  * dry-run by default, `--apply` writes;
  * `--backup PATH` (required with --apply) copies the DB first;
  * matching ledger rows in `evidence_predictions` go with them — an open prediction about a
    company the headline never mentioned must not resolve into the learning loop;
  * RESOLVED predictions are never touched. That ledger is append-only by contract, and a
    resolved row is a historical record of what the system believed, not a live claim.

Run from the repo root:
    uv run python scripts/fix_voice_misattributions_2026_08_11.py            # report only
    uv run python scripts/fix_voice_misattributions_2026_08_11.py --apply --backup pre_fix.db
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3

from equity_scout.data.universe_storage import load_universe_snapshot
from equity_scout.evidence.voices import resolve_ticker

# The universe the collector itself resolves against (the "screen everything" snapshot).
UNIVERSE_AS_OF = "2026-07-14"


def _universe(db: str) -> list[tuple[str, str]]:
    instruments = load_universe_snapshot(db, UNIVERSE_AS_OF)
    if not instruments:
        raise SystemExit(
            f"Kein Universums-Snapshot für {UNIVERSE_AS_OF} in {db} — ohne ihn ist keine "
            "Nachprüfung möglich (und ein Löschen ohne Nachprüfung wäre Raten)."
        )
    return [(i.ticker, i.name) for i in instruments]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="equity_scout.db")
    parser.add_argument("--apply", action="store_true", help="delete the unreproducible rows")
    parser.add_argument("--backup", default=None, help="copy the DB here before writing")
    args = parser.parse_args()

    if args.apply and not args.backup:
        raise SystemExit("--apply verlangt --backup PATH (dieses Skript löscht Zeilen).")

    universe = _universe(args.db)
    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, ticker, event_key, details_json FROM evidence_events WHERE source='voice'"
    ).fetchall()

    doomed: list[tuple[int, str, str, str | None]] = []  # (id, ticker, headline, now_resolves_to)
    unchecked = 0
    for row in rows:
        headline = json.loads(row["details_json"]).get("headline")
        if not headline:
            unchecked += 1  # nothing to re-check against → left alone, never guessed away
            continue
        now = resolve_ticker(headline, universe)
        if now != row["ticker"]:
            doomed.append((row["id"], row["ticker"], headline, now))

    print(f"Gespeicherte voice-Events: {len(rows)}")
    print(f"  ohne Schlagzeile (unangetastet):     {unchecked}")
    print(f"  heute nicht reproduzierbar:          {len(doomed)}")
    print(f"  bleiben:                             {len(rows) - unchecked - len(doomed)}")

    # Ledger rows are keyed by (source, ticker, event_key) rather than by event id.
    doomed_ids = {d[0] for d in doomed}
    doomed_keys = {(row["ticker"], row["event_key"]) for row in rows if row["id"] in doomed_ids}
    open_preds = [
        r["id"]
        for r in con.execute(
            "SELECT id, ticker, event_key FROM evidence_predictions"
            " WHERE source='voice' AND resolved_at IS NULL"
        )
        if (r["ticker"], r["event_key"]) in doomed_keys
    ]
    resolved_kept = con.execute(
        "SELECT COUNT(*) FROM evidence_predictions WHERE source='voice' AND resolved_at IS NOT NULL"
    ).fetchone()[0]
    print(f"  offene Ledger-Vorhersagen dazu:      {len(open_preds)}")
    print(f"  aufgelöste Vorhersagen (unberührt):  {resolved_kept}")

    print("\nBeispiele (max. 12):")
    for _, was, headline, now in doomed[:12]:
        print(f"  {was:10s} -> {str(now):10s} | {headline[:70]}")

    if not args.apply:
        print("\nTrockenlauf — nichts geändert. Mit --apply --backup PATH ausführen zum Löschen.")
        con.close()
        return

    shutil.copy2(args.db, args.backup)
    print(f"\nBackup: {args.backup}")
    con.executemany("DELETE FROM evidence_events WHERE id = ?", [(d[0],) for d in doomed])
    con.executemany("DELETE FROM evidence_predictions WHERE id = ?", [(i,) for i in open_preds])
    con.commit()
    print(f"Gelöscht: {len(doomed)} Events, {len(open_preds)} offene Vorhersagen.")
    con.close()


if __name__ == "__main__":
    main()
