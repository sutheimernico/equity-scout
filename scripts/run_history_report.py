"""Print the historical catalyst base-rate study and write it to docs/research (P2a Task 6).

Reads `historical_events` (no event data is written — the read path does call
`init_historical_db`, so an empty database file/table is created if none exists yet, but
no row is ever inserted, updated or resolved here), aggregates it via
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
    "Time split: fit = t0 <= split_date, validate = t0 > split_date. A cell passes the "
    "gate only with min_cell_n measurements on BOTH sides and an agreeing direction; "
    "everything else is reported as {measurable: false, reason}. The pooled `all` block "
    "mixes both periods (dated rows only, so all.n == fit.n + validate.n) and is "
    "reporting only — it can never justify a claim.",
    "A row marked unresolvable can still carry measured horizons (delisted after a "
    "month). Those measurements stay in the base rates and the row is ALSO counted in the "
    "coverage gap — the two do not partition the total, by design.",
)

def _multiplicity_note(study: dict) -> str:
    return (
        "MULTIPLE TESTING — read this before any claim below. The gate is direction "
        "agreement across the time split, NOT a significance test: with no effect at all, "
        "agreeing signs are a coin flip, so the gate passes about 50% of the cells it "
        "rules on REGARDLESS of n. This run ruled on "
        f"{study['n_gated_cells']} cell-horizons (class overall, each split value and each "
        "person, times five horizons) and "
        f"{study['n_direction_agreement_cells']} of them showed agreeing direction; at a "
        f"50% pass rate about {study['expected_spurious_at_50pct']} agreements are "
        "expected from chance alone. An agreement count near that number is the noise "
        "floor. The decision-grade outputs of this report are the coverage block and the "
        "effect sizes against their stderr — never the agreement count on its own."
    )


def methodology(study: dict) -> list[str]:
    """The static notes plus the run's own multiplicity numbers — the spurious-agreement
    expectation has to be a number in the artifact, not a caveat someone remembers."""
    return [*METHODOLOGY, _multiplicity_note(study)]


def build_report(
    db_path: str,
    *,
    now: str,
    split_date: str = DEFAULT_SPLIT_DATE,
    min_cell_n: int = DEFAULT_MIN_CELL_N,
) -> dict:
    """Header (disclaimer + methodology) around the aggregate. `now` is injected, so the
    report body stays a pure function of the database."""
    study = aggregate_history(db_path, split_date=split_date, min_cell_n=min_cell_n)
    return {
        "generated_at": now,
        "survivorship_disclaimer": SURVIVORSHIP_DISCLAIMER,
        "methodology": methodology(study),
        "study": study,
    }


def write_report(report: dict, out_path: str | Path) -> Path:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def _hit(stats: dict) -> str:
    return "—" if stats["hit_rate"] is None else f"{stats['hit_rate']:.1%}"


def _horizon_line(cell: dict, horizon: str) -> str:
    """One horizon of one cell. Both per-side hit rates are printed on purpose: a pooled
    56% can be 56.7% in fit against 3.3% in validate riding on one outlier, and a summary
    that only shows the pooled number hides exactly the divergence a reader needs."""
    pooled = cell["all"][horizon]
    fit = cell["fit"][horizon]
    validate = cell["validate"][horizon]
    verdict = cell["edge"][horizon]
    if pooled["n"] == 0:
        return f"  {horizon}: keine Messung"
    spread = f" ±{pooled['stderr'] * 100:.2f}pp stderr" if pooled["stderr"] is not None else ""
    # The verdict states the TEST performed, never a conclusion — the gate is a sign
    # comparison, and about half of all no-effect cells pass it whatever n is.
    claim = (
        f"Richtung in fit und validate gleich ({verdict['direction']}) — kein Signifikanztest"
        if verdict["measurable"]
        else f"kein Richtungsbefund ({verdict['reason']})"
    )
    return (
        f"  {horizon}: {pooled['n']} gemessen (fit {fit['n']} / validate {validate['n']}),"
        f" Treffer {_hit(pooled)} (fit {_hit(fit)} / validate {_hit(validate)}),"
        f" Ø rel. Rendite {pooled['mean_relative_return']:+.2%}{spread} — {claim}"
    )


def _agreeing_cells(cells: dict) -> int:
    return sum(
        1
        for cell in cells.values()
        if any(verdict["measurable"] for verdict in cell["edge"].values())
    )


def _n_cells(count: int) -> str:
    return f"{count} Zelle" if count == 1 else f"{count} Zellen"


def format_summary(report: dict) -> str:
    """Run summary in German (repo convention); the JSON keys stay English."""
    study = report["study"]
    lines = [
        f"Historien-Studie ({report['generated_at']}) — Zeitschnitt {study['split_date']},"
        f" min. Zellen-N {study['min_cell_n']}, {study['n_events']} Events insgesamt.",
        f"Survivorship: {report['survivorship_disclaimer']}",
        f"Multiples Testen: {study['n_gated_cells']} Zell-Horizonte durch das Gate,"
        f" davon {study['n_direction_agreement_cells']} mit übereinstimmender Richtung —"
        f" bei reinem Zufall wären rund {study['expected_spurious_at_50pct']} zu erwarten."
        " Das Gate ist ein Vorzeichenvergleich, kein Signifikanztest.",
    ]
    for source, section in study["classes"].items():
        if source == CLASS_STATEMENT:
            continue
        coverage = section["coverage"]
        reasons = ", ".join(
            f"{reason}: {count}" for reason, count in coverage["unresolvable_by_reason"].items()
        )
        # "Events fit/validate" here vs "gemessen fit/validate" per horizon below: two
        # different denominators, so they never share a bare "fit" label.
        lines.append(
            f"\n{section['label']}: {section['n']} Events"
            f" (fit {coverage['fit']} / validate {coverage['validate']} Events,"
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
                f"  Split {name}: {_n_cells(len(cells))},"
                f" {_agreeing_cells(cells)} mit übereinstimmender Richtung"
            )
        lines.append(
            f"  Personen: {len(section['persons'])},"
            f" {_agreeing_cells(section['persons'])} mit übereinstimmender Richtung"
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
