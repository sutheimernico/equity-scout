"""Print the historical catalyst base-rate study and write it to docs/research (P2a Task 6).

Reads `historical_events` (nothing is written to the database), aggregates it via
`evidence.historical_study.aggregate_history` and emits
`docs/research/history-study-report.json`: header with the spec's survivorship disclaimer
verbatim, methodology, per-class base rates + coverage + honest cells, and the statement
class's measured negative result.

The JSON is DERIVED state — every run recomputes it from the database, so overwriting is
the contract (same as the person scores). There is deliberately no `--apply`: this script
cannot change a measurement, only re-report it.

The numbers here are EVIDENCE for the P2 lane design, not an automatic go: a class whose
cells all refuse to claim an edge has killed a lane cheaply, which is a result.

Usage:
    uv run python scripts/run_history_report.py [--db equity_scout.db]
        [--split-date 2021-12-31] [--min-cell-n 30] [--out docs/research/...json]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.evidence.historical_storage import RETURN_HORIZONS
from equity_scout.evidence.historical_study import (
    CLASS_STATEMENT,
    DEFAULT_MIN_CELL_N,
    DEFAULT_SPLIT_DATE,
    SURVIVORSHIP_DISCLAIMER,
    aggregate_history,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "docs/research/history-study-report.json"

# Plan Decision 11 plus the entry convention the live lanes already use. These belong in
# the report because every hit rate below is only as meaningful as the window it counted.
METHODOLOGY = (
    "Horizons count PANEL ROWS, not exchange sessions: r_1w/r_1m/r_3m/r_6m/r_12m are "
    "5/21/63/126/252 rows of the daily close panel after entry. A provider gap or a "
    "holiday the panel does not carry therefore shifts the calendar length of a window "
    "slightly — the count is exact, the elapsed wall-clock time is approximate.",
    "Entry = the CLOSE of the first panel date on or after t0 (same-day-close entry, the "
    "convention inherited from the live lanes). t0 is the day the fact became publicly "
    "knowable — the filing date, never the transaction date.",
    "Returns are relative to SPY over the identical window "
    "(ml.entry_eval.relative_forward_return, the same function the live person track and "
    "the prediction ledger measure with). hit_rate = share of events with a positive "
    "relative return, i.e. share that beat the benchmark.",
    "Time split: fit = t0 <= split_date, validate = t0 > split_date. A cell may claim an "
    "edge only with min_cell_n measurements on BOTH sides and an agreeing direction; "
    "everything else is reported as {measurable: false, reason}. The pooled `all` block "
    "mixes both periods and is reporting only — it can never justify a claim.",
    "A row marked unresolvable can still carry measured horizons (delisted after a "
    "month). Those measurements stay in the base rates and the row is ALSO counted in the "
    "coverage gap — the two do not partition the total, by design.",
)


def build_report(
    db_path: str,
    *,
    now: str,
    split_date: str = DEFAULT_SPLIT_DATE,
    min_cell_n: int = DEFAULT_MIN_CELL_N,
) -> dict:
    """Header (disclaimer + methodology) around the aggregate. `now` is injected, so the
    report body stays a pure function of the database."""
    return {
        "generated_at": now,
        "survivorship_disclaimer": SURVIVORSHIP_DISCLAIMER,
        "methodology": list(METHODOLOGY),
        "study": aggregate_history(db_path, split_date=split_date, min_cell_n=min_cell_n),
    }


def write_report(report: dict, out_path: str | Path) -> Path:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def _horizon_line(cell: dict, horizon: str) -> str:
    stats = cell["all"][horizon]
    verdict = cell["edge"][horizon]
    if stats["n"] == 0:
        return f"  {horizon}: keine Messung"
    # Naming the basis matters: direction is the sign of the MEAN, so a claimable edge can
    # sit next to a sub-50% hit rate (few large winners) without either number being wrong.
    claim = (
        f"Edge {verdict['direction']} (Ø-Richtung, fit+validate)"
        if verdict["measurable"]
        else f"kein Edge ({verdict['reason']})"
    )
    return (
        f"  {horizon}: n={stats['n']} (fit {cell['fit'][horizon]['n']},"
        f" validate {cell['validate'][horizon]['n']}),"
        f" Trefferquote {stats['hit_rate']:.1%},"
        f" Ø rel. Rendite {stats['mean_relative_return']:+.2%} — {claim}"
    )


def _claimable_cells(cells: dict) -> int:
    return sum(
        1
        for cell in cells.values()
        if any(verdict["measurable"] for verdict in cell["edge"].values())
    )


def format_summary(report: dict) -> str:
    """Run summary in German (repo convention); the JSON keys stay English."""
    study = report["study"]
    lines = [
        f"Historien-Studie ({report['generated_at']}) — Zeitschnitt {study['split_date']},"
        f" min. Zellen-N {study['min_cell_n']}, {study['n_events']} Events insgesamt.",
        f"Survivorship: {report['survivorship_disclaimer']}",
    ]
    for source, section in study["classes"].items():
        if source == CLASS_STATEMENT:
            continue
        coverage = section["coverage"]
        reasons = ", ".join(
            f"{reason}: {count}" for reason, count in coverage["unresolvable_by_reason"].items()
        )
        lines.append(
            f"\n{section['label']}: {section['n']} Events"
            f" (fit {coverage['fit']}, validate {coverage['validate']},"
            f" ohne brauchbares t0 {coverage['t0_unparsable']});"
            f" unresolvable {coverage['unresolvable']}"
            f"{f' ({reasons})' if reasons else ''},"
            f" davon mit gemessenen Horizonten"
            f" {coverage['unresolvable_with_measured_horizons']};"
            f" offen {coverage['open']}, defekte details {coverage['details_unparsable']}."
        )
        if "mixed_issuer" in coverage:
            lines.append(f"  mixed_issuer-Cluster: {coverage['mixed_issuer']}")
        for horizon in RETURN_HORIZONS:
            lines.append(_horizon_line(section["overall"], horizon))
        for name, cells in section["splits"].items():
            lines.append(
                f"  Split {name}: {len(cells)} Zellen,"
                f" {_claimable_cells(cells)} mit belegbarem Edge"
            )
        lines.append(
            f"  Personen: {len(section['persons'])},"
            f" {_claimable_cells(section['persons'])} mit belegbarem Edge"
        )

    statement = study["classes"][CLASS_STATEMENT]
    lines.append(
        f"\n{statement['label']}: gemessene Null, nicht ungelaufen —"
        f" {statement['corpus_rows']} Corpus-Zeilen -> {statement['candidates']} Kandidaten"
        f" -> {statement['raw_events']} Roh-Events -> {statement['genuine']} echte Calls;"
        f" publiziert: {'ja' if statement['published'] else 'nein'}."
    )
    if "warning" in statement:
        lines.append(f"  WARNUNG: {statement['warning']}")
    if study["other_sources"]:
        others = ", ".join(f"{source}: {count}" for source, count in study["other_sources"].items())
        lines.append(f"\nNicht ausgewertete Quellen (gezählt, nicht ignoriert): {others}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--split-date", default=DEFAULT_SPLIT_DATE,
                        help="fit = t0 <= this date, validate = t0 after it")
    parser.add_argument("--min-cell-n", type=int, default=DEFAULT_MIN_CELL_N,
                        help="minimum measurements per side before a cell may claim an edge")
    parser.add_argument("--out", default=str(DEFAULT_OUT),
                        help="report JSON (derived state — overwritten every run)")
    args = parser.parse_args()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report = build_report(
        args.db, now=now, split_date=args.split_date, min_cell_n=args.min_cell_n
    )
    print(format_summary(report))
    path = write_report(report, args.out)
    print(f"\nReport geschrieben: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
