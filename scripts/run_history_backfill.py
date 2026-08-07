"""Ingest historical catalyst events point-in-time, one source at a time (P2a Task 7).

Front end for the three backfill collectors. Each source is its own invocation because
they have nothing in common operationally: congress is one pass over ~440 filer JSONs,
form4 is a resumable multi-year walk over quarterly SEC ZIPs (one quarter per fetch,
cursor in `app_state`), statements is a dry-run-only measurement of a class that is
already dead. `now` is read exactly once in `main()` and threaded down — no library code
in this repo reads the wall clock, and a multi-hour form4 run must not drift its
`created_at` mid-walk.

DRY-RUN IS THE DEFAULT (`fix_*`/backfill script convention). "Would insert" is not
guessed: the run happens for real against a THROWAWAY copy of the dedupe state
(`historical_events` keys + the form4 cursor), so the reported count is what an `--apply`
would actually add — already deduped against the rows the production db holds. The
network is hit either way; only the destination differs. For form4 that makes a dry-run
EXPENSIVE, not free: there is no ZIP cache, so every dry-run quarter downloads its data
set again (~13 MB each, ~1.1 GB for a full 82-quarter walk). Sane pattern: a small
`--quarters` dry-run to check the wiring, then `--apply` for the real walk.

EXIT CODES (deliberately sharing argparse's own taxonomy):
  0  ran, and nothing the runner can judge went wrong
  1  ran, and something did go wrong (dead mirror, broken quarter, empty seed)
  2  the INVOCATION was refused and nothing ran (buried source, bad flag combination) —
     argparse uses 2 for a usage error, and a refused invocation is exactly that
Exit 0 is NOT a health signal: a congress run where 439 of 440 filers failed exits 0
because the run did what it could. Anything chaining this script must read the printed
counts and ratios, not the exit code.

CONGRESS HAS NO CURSOR, by design. A re-run refetches all ~440 filer histories and
inserts only what is new (`record_historical_events` is INSERT OR IGNORE on
`(source, ticker, event_key)`). The seed lists are small and the dedupe is exact, so a
cursor would buy nothing and add a way to get stuck half-way.

STATEMENTS ARE BURIED (plan Decision 9, ratified after re-review). The full-corpus run
measured 78,728 rows -> 132 candidates -> 10 surviving events, and all 10 were manually
verified FALSE attributions (0 genuine calls). `historical_events` is an irreversible
store and `min_cell_n` is a statistical control, not a known-false-data control — so this
runner refuses `--apply --source statements` outright and routes it to the shadow db.
Re-running it in dry-run stays useful: it re-measures the negative result on the current
corpus, which is what makes "measured, found nothing" distinguishable from "never ran".

FORM4 PUBLICATION LAG (plan Decision 7): the SEC publishes each quarterly data set weeks
after the quarter ends, so a `fetch_failed` on the NEWEST candidate quarter is normal —
logged, cursor untouched, exit 0. Any other failing status (or a fetch_failed on an older
quarter) stops the loop and exits non-zero: the cursor only advances on `ok`, so
continuing would refetch the same quarter forever. The cursor is strictly sequential —
if one quarter is permanently broken upstream, skip it by hand. The cursor holds the LAST
COMPLETED quarter, so the value to write is THE BROKEN QUARTER ITSELF; the next run then
starts at the one after it:
    # 2011q3 is broken upstream -> pretend it completed, resume at 2011q4
    uv run python -c "from equity_scout.state_storage import set_state; \
set_state('equity_scout.db', key='history_form4_cursor', value='2011q3')"

Usage:
    uv run python scripts/run_history_backfill.py --source congress [--db ...] [--apply]
    uv run python scripts/run_history_backfill.py --source form4 --quarters 82 --apply
    uv run python scripts/run_history_backfill.py --source statements   # dry-run only
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import tempfile
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from equity_scout import db
from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.evidence.backfill_congress import backfill_congress
from equity_scout.evidence.backfill_form4 import (
    HISTORY_FORM4_CURSOR_KEY,
    backfill_form4_quarter,
    latest_published_quarter,
    next_quarter_to_backfill,
)
from equity_scout.evidence.backfill_statements import backfill_statements
from equity_scout.evidence.base import STATUS_FETCH_FAILED, STATUS_OK
from equity_scout.evidence.historical_storage import init_historical_db
from equity_scout.state_storage import init_state_db

SOURCE_CONGRESS = "congress"
SOURCE_FORM4 = "form4"
SOURCE_STATEMENTS = "statements"
SOURCES = (SOURCE_CONGRESS, SOURCE_FORM4, SOURCE_STATEMENTS)

# Sources that may NEVER be written to the production store, with the reason shown in
# --help and in the refusal message. See the module docstring / plan Decision 9.
BURIED_SOURCES = {
    SOURCE_STATEMENTS: (
        "class measured dead: 10/10 surviving events verified false;"
        " see backfill_statements.py docstring"
    ),
}
APPLYABLE_SOURCES = tuple(source for source in SOURCES if source not in BURIED_SOURCES)

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_REFUSED = 2  # a forbidden invocation, distinct from "ran and something broke"

DEFAULT_QUARTERS = 1
# Copied into the shadow db so a dry-run form4 walk starts where the real one left off.
MIRRORED_STATE_KEYS = (HISTORY_FORM4_CURSOR_KEY,)


# --- dry-run plumbing -----------------------------------------------------------------

@contextmanager
def shadow_db(db_path: str) -> Iterator[str]:
    """A throwaway db carrying only what the collectors dedupe/resume against.

    Not a copy of the whole 30 MB production file: the collectors only ever read
    `historical_events`' unique keys (INSERT OR IGNORE) and the form4 cursor, so those
    are all that must be mirrored for the counts to be exact. A missing production db is
    mirrored as empty — ATTACHing a nonexistent path would CREATE it, and a dry-run that
    conjures the production database is not a dry-run.
    """
    tmp_dir = tempfile.mkdtemp(prefix="history-backfill-dryrun-")
    shadow = os.path.join(tmp_dir, "shadow.db")
    try:
        init_historical_db(shadow)
        init_state_db(shadow)
        if os.path.exists(db_path):
            # Explicit connection lifecycle, not `with db.connect(...)`: that context
            # manager commits but never CLOSES, and a still-open connection would hold a
            # read lock on the production db for the whole (multi-hour) run. DETACH also
            # needs the write transaction committed first, or sqlite reports "src is
            # locked".
            conn = db.connect(shadow)
            try:
                conn.execute("ATTACH DATABASE ? AS src", (db_path,))
                _mirror_dedupe_state(conn)
                conn.commit()
                conn.execute("DETACH DATABASE src")
            finally:
                conn.close()
        yield shadow
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _mirror_dedupe_state(conn: sqlite3.Connection) -> None:
    """Copy dedupe keys + cursor out of the ATTACHed `src`, ASKING what exists first.

    A production db that has never run a backfill has neither table; that is the normal
    first-run case, so a missing table mirrors as "nothing known yet". It is checked via
    `sqlite_master` rather than by catching OperationalError, because that except clause
    cannot tell "table not there yet" from "column renamed underneath us" — and swallowing
    the second one is silently catastrophic in both directions: a drifted
    `historical_events` would report the whole corpus as new ("Würde einfügen: 23274"
    against a full store) and a drifted `app_state` would rewind a form4 dry-run to
    2006q1. A real schema drift must raise here.
    """
    tables = {
        row[0] for row in conn.execute("SELECT name FROM src.sqlite_master WHERE type='table'")
    }
    if "historical_events" in tables:
        conn.execute(
            "INSERT INTO historical_events"
            " (source, person, ticker, event_key, t0, details_json, created_at)"
            " SELECT source, person, ticker, event_key, t0, details_json, created_at"
            " FROM src.historical_events"
        )
    if "app_state" in tables:
        for key in MIRRORED_STATE_KEYS:
            conn.execute(
                "INSERT OR REPLACE INTO app_state (key, value)"
                " SELECT key, value FROM src.app_state WHERE key = ?",
                (key,),
            )


@contextmanager
def target_db(db_path: str, *, apply: bool) -> Iterator[str]:
    """The db the collectors are handed: production on `--apply`, else a shadow."""
    if not apply:
        with shadow_db(db_path) as shadow:
            yield shadow
        return
    init_historical_db(db_path)
    init_state_db(db_path)
    yield db_path


# --- per-source runs ------------------------------------------------------------------

def run_congress(db_path: str, *, now: str) -> dict:
    """One full pass over the filer index. No cursor by design (see the module docstring):
    a re-run refetches everything and inserts only what is new."""
    counts = backfill_congress(db_path, now=now)
    every_filer_failed = counts["filers"] > 0 and counts["filers_failed"] == counts["filers"]
    return {
        "source": SOURCE_CONGRESS,
        "ok": not counts["seed_empty"] and not every_filer_failed,
        "counts": counts,
    }


def run_form4(db_path: str, *, now: str, quarters: int) -> dict:
    """Walk up to `quarters` quarterly data sets forward from the cursor.

    Stops early on the first non-`ok` status: the cursor advances only on success, so a
    further iteration would just refetch the same quarter. Whether that stop is a failure
    is decided by the caller-visible `publication_lag` flag (Decision 7).

    Each quarter's result is printed AS IT COMPLETES, not only in the final summary: an
    82-quarter walk runs for many minutes, and a crash at quarter 60 must not take the
    record of the first 59 with it. The cursor in `app_state` remains the state of record
    either way — these lines are for the human watching, the cursor is for the next run.
    """
    newest = latest_published_quarter(now)

    runs: list[dict] = []
    caught_up = False
    publication_lag = False
    for _ in range(max(quarters, 0)):
        quarter = next_quarter_to_backfill(db_path, now=now)
        if quarter is None:
            caught_up = True
            break
        counts = backfill_form4_quarter(db_path, quarter, now=now)
        runs.append(counts)
        print(_quarter_progress(counts), flush=True)
        if counts["status"] != STATUS_OK:
            publication_lag = counts["status"] == STATUS_FETCH_FAILED and quarter == newest
            break
    else:
        caught_up = next_quarter_to_backfill(db_path, now=now) is None

    failed = bool(runs) and runs[-1]["status"] != STATUS_OK
    return {
        "source": SOURCE_FORM4,
        "ok": not failed or publication_lag,
        "quarters": runs,
        "caught_up": caught_up,
        "publication_lag": publication_lag,
        "newest_published": newest,
    }


def run_statements(db_path: str, *, now: str) -> dict:
    """Re-measure the statement class. No `apply` parameter BY DESIGN — Decision 9's
    burial is enforced by this signature plus `main`'s refusal, not by a caller's care."""
    counts = backfill_statements(db_path, now=now)
    # A run that loaded ZERO posts measured nothing — and "0 events" from an empty corpus
    # looks exactly like Decision 9's real negative result. `sources_fetched` is not
    # enough: it is incremented BEFORE parsing, so three schema-drifted mirrors would
    # report three "fetched" sources and an empty corpus. Count the posts, not the URLs.
    return {
        "source": SOURCE_STATEMENTS,
        "ok": counts["twitter_rows"] + counts["truth_social_rows"] > 0,
        "counts": counts,
    }


# --- reporting ------------------------------------------------------------------------

def _insert_line(events_new: int, events_seen: int, *, apply: bool) -> str:
    verb = "Eingefügt" if apply else "Würde einfügen"
    return f"{verb}: {events_new} (von {events_seen} erzeugten Events, Rest bereits bekannt)."


def _quarter_progress(counts: dict) -> str:
    """One line per completed quarter, printed live so a crash keeps the record so far."""
    if counts["status"] != STATUS_OK:
        return f"  {counts['quarter']}: {counts['status']} — {counts['detail']}"
    return (
        f"  {counts['quarter']}: ok, {counts['clusters']} Cluster,"
        f" {counts['events_new']} neu (von {counts['events_seen']})."
    )


def format_summary(result: dict, *, apply: bool) -> str:
    """German run summary in the Wave-1 style: every counted failure visible, always."""
    source = result["source"]
    if source == SOURCE_FORM4:
        lines = _format_form4(result, apply=apply)
    elif source == SOURCE_CONGRESS:
        lines = _format_congress(result, apply=apply)
    else:
        lines = _format_statements(result, apply=apply)
    if not apply:
        lines.append("Dry-Run gegen eine Wegwerf-Kopie — nichts geschrieben. Mit --apply schreiben.")
    return "\n".join(lines)


def _format_congress(result: dict, *, apply: bool) -> list[str]:
    counts = result["counts"]
    lines = [
        f"congress: {counts['filers']} Filer"
        f" ({counts['filers_failed']}/{counts['filers']} fehlgeschlagen),"
        f" {counts['rows']} Transaktionszeilen gelesen.",
        _insert_line(counts["events_new"], counts["events_seen"], apply=apply),
        f"Verworfen — kein Ticker: {counts['no_ticker']}, kein Aktienkauf:"
        f" {counts['not_stock']}, kein Datum: {counts['no_date']},"
        f" defekt: {counts['malformed']}, Dublette: {counts['duplicate']}.",
    ]
    if counts["index_fallback"]:
        lines.append(
            "WARNUNG: Filer-Index nicht erreichbar — nur die ~95 aktiven Filer aus"
            " trades.json geseedet (Survivorship-Bias, Plan-Entscheidung 5)."
        )
    if counts["seed_empty"]:
        lines.append("FEHLER: seed_empty — weder Filer-Index noch trades.json lieferten IDs.")
    return lines


def _format_form4(result: dict, *, apply: bool) -> list[str]:
    runs = result["quarters"]
    events_new = sum(run["events_new"] for run in runs)
    events_seen = sum(run["events_seen"] for run in runs)
    ok_runs = [run for run in runs if run["status"] == STATUS_OK]
    span = f" ({ok_runs[0]['quarter']}..{ok_runs[-1]['quarter']})" if ok_runs else ""
    lines = [
        f"form4: {len(ok_runs)}/{len(runs)} Quartale ok{span}.",
        f"Cluster: {sum(run['clusters'] for run in runs)},"
        f" Schlüsselkollisionen: {sum(run['duplicate_key'] for run in runs)},"
        f" Quartalsgrenzen-Kandidaten: {sum(run['boundary_candidates'] for run in runs)},"
        f" gemischte Emittenten: {sum(run['mixed_issuer'] for run in runs)}.",
        _insert_line(events_new, events_seen, apply=apply),
    ]
    for run in runs:
        if run["status"] != STATUS_OK:
            lines.append(f"{run['quarter']}: {run['status']} — {run['detail']}")
    if result["publication_lag"]:
        lines.append(
            f"Publikationsverzug: {result['newest_published']} ist das neueste mögliche"
            " Quartal und die SEC veröffentlicht Wochen nach Quartalsende — kein Fehler,"
            " Cursor unverändert, nächster Lauf holt es."
        )
    elif runs and runs[-1]["status"] != STATUS_OK:
        lines.append(
            f"FEHLER: Lauf gestoppt bei {runs[-1]['quarter']} — der Cursor rückt nur bei"
            " 'ok' vor, ein weiterer Durchlauf würde dasselbe Quartal erneut holen."
            f" Ist das Quartal dauerhaft kaputt, überspringe es von Hand:"
            f" set_state(db, key='{HISTORY_FORM4_CURSOR_KEY}', value='{runs[-1]['quarter']}')."
        )
    if result["caught_up"]:
        lines.append(
            f"Aufgeholt: bis {result['newest_published']} ist nichts mehr zu holen."
        )
    return lines


def _coverage_bound(platform: str, preposition: str, value: str | None) -> str:
    return f"{platform} {preposition} {value}" if value else f"{platform}: nicht geladen"


def _format_statements(result: dict, *, apply: bool) -> list[str]:
    counts = result["counts"]
    corpus = counts["twitter_rows"] + counts["truth_social_rows"]
    # Denominator from what was actually attempted, not a literal: the collector decides how
    # many mirrors it walks (two Twitter files + one Truth Social today), and a hardcoded /3
    # would quietly lie the day that list changes.
    attempted = counts["sources_fetched"] + counts["sources_failed"]
    lines = [
        f"statements: {counts['sources_fetched']}/{attempted} Quellen geladen"
        f" ({counts['sources_failed']} nicht erreichbar,"
        f" {counts['sources_parse_failed']} Format verändert), {corpus} Beiträge"
        f" (twitter {counts['twitter_rows']}, truth_social {counts['truth_social_rows']}).",
        # A dead mirror leaves its date bounds at None; "Twitter bis None" reads like a
        # parsed value. Say the mirror did not load instead.
        f"Abdeckungslücke: {_coverage_bound('Twitter', 'bis', counts['twitter_date_max'])},"
        f" {_coverage_bound('Truth Social', 'ab', counts['truth_social_date_min'])}"
        " (Plattform-Sperre).",
        _insert_line(counts["events_new"], counts["events_seen"], apply=apply),
        f"BEERDIGT (Plan-Entscheidung 9): {BURIED_SOURCES[SOURCE_STATEMENTS]}."
        " Diese Zahl ist das Studienergebnis, kein Ladefehler.",
    ]
    lines.extend(f"Quellfehler: {error}" for error in counts["source_errors"])
    if not corpus:
        lines.append(
            "FEHLER: kein einziger Beitrag geladen — dieser Lauf misst nichts und die"
            " 0 oben ist KEIN Negativbefund."
        )
    return lines


# --- entry point ----------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--source", required=True, choices=SOURCES,
        help="which collector to run;"
             f" --apply is accepted only for {', '.join(APPLYABLE_SOURCES)}."
             f" statements is dry-run ONLY ({BURIED_SOURCES[SOURCE_STATEMENTS]})",
    )
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument(
        # default None, not DEFAULT_QUARTERS, so "was it passed at all?" stays answerable
        # and the flag can be REFUSED for the sources it means nothing to.
        "--quarters", type=int, default=None,
        help=f"--source {SOURCE_FORM4} ONLY (rejected elsewhere): how many quarterly data"
             f" sets to walk forward from the cursor (default {DEFAULT_QUARTERS}; the full"
             " 2006-> run is 82)",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="write to the real db (default: dry-run against a throwaway copy). NOTE: a"
             " form4 dry-run is not free — there is no ZIP cache, so it re-downloads every"
             " quarter it walks (~13 MB each, ~1.1 GB for the full run). Check the wiring"
             " with a small --quarters dry-run, then --apply for the real walk",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.quarters is not None and args.source != SOURCE_FORM4:
        parser.error(
            f"--quarters gilt nur für --source {SOURCE_FORM4}, nicht für {args.source}"
        )
    quarters = DEFAULT_QUARTERS if args.quarters is None else args.quarters
    if quarters < 1:
        # A silent no-op is the worst outcome for a job whose whole point is progress.
        parser.error("--quarters muss >= 1 sein")
    if args.apply and args.source in BURIED_SOURCES:
        print(
            f"--apply --source {args.source} verweigert: {BURIED_SOURCES[args.source]}."
            " historical_events ist ein irreversibler Store; der Dry-Run misst den"
            " Negativbefund erneut, ohne ihn zu speichern.",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with target_db(args.db, apply=args.apply) as target:
            if args.source == SOURCE_CONGRESS:
                result = run_congress(target, now=now)
            elif args.source == SOURCE_FORM4:
                result = run_form4(target, now=now, quarters=quarters)
            else:
                result = run_statements(target, now=now)
    except Exception as err:  # noqa: BLE001 — an 82-quarter walk must not die reportless
        # Without this, a crash at quarter 60 loses the whole run's account. The per-quarter
        # lines are already on stdout; say plainly that they still hold and where the real
        # resume point lives.
        traceback.print_exc()
        message = (
            f"ABBRUCH ({type(err).__name__}): {err}."
            " Was oben bereits gedruckt wurde, ist passiert und bleibt gültig."
        )
        if args.source == SOURCE_FORM4 and args.apply:
            message += (
                f" Maßgeblich für den Wiederaufsatz ist der Cursor"
                f" `{HISTORY_FORM4_CURSOR_KEY}`, nicht diese Ausgabe — der nächste Lauf"
                " macht dort weiter."
            )
        print(message, file=sys.stderr)
        return EXIT_FAILED

    print(format_summary(result, apply=args.apply))
    return EXIT_OK if result["ok"] else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
