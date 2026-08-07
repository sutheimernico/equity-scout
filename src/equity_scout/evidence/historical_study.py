"""Base-rate study over `historical_events` (P2a Task 6): what the 10–20 years of
backfilled catalysts actually measured, per class, per person, per deterministic split —
with every cell that cannot honestly claim an edge saying so instead of showing a number.

Aggregation contract (plan Decision 4, the load-bearing one):
  * every horizon is aggregated over `r_X IS NOT NULL`, NOT over `resolved_at` and NOT
    over `unresolvable = 0`. Resolution is per-column, so an `unresolvable = 1` row can
    carry real measured horizons (delisted after a month: real r_1w/r_1m, then
    `no_price_history` for the rest). Dropping those rows would discard exactly the
    delisted names the survivorship disclaimer exists for — the measured hit rate would
    then be an upper bound on an upper bound.
  * `unresolvable` feeds ONLY the coverage/survivorship counters. `resolved_at` feeds NO
    published number at all — it is a terminal timestamp written by BOTH transitions
    (`mark_resolved` when all five horizons are in, `mark_unresolvable` immediately), so
    reading it alone as "has usable data" is always wrong (Decision 3).

Honesty rules for a cell (class, or class x one deterministic split value, or person):
  * a cell claims an edge for a horizon ONLY with >= `min_cell_n` measurements on BOTH
    sides of the time split AND an agreeing direction. Anything else is
    `{"measurable": False, "reason": ...}` — the same refusal shape as
    `event_reactions.aggregate_reactions`'s 1h window, never a bare number nor a NULL.
  * a cell with zero coverage on either side can never claim an edge, whatever
    `min_cell_n` is set to: in-sample-only is not evidence.
  * splits run on DETERMINISTIC details fields only (amount band, chamber, cluster size,
    value band) — no derived, fitted or judgement-based conditioning.

Class wording (Decisions 6/7): `source = 'congress'` includes OGE executive-branch filers
(`details.chamber` carries chamber OR branch), hence the label "congress & executive
filers"; `source = 'insider'` is reported as "insider clusters". The statement class is a
MEASURED zero, not an unrun one — see `STATEMENT_MEASURED`.

No wall clock and no file IO here: the aggregate is a pure function of the database, the
report header/formatting/writing lives in `scripts/run_history_report.py`.
"""
from __future__ import annotations

import json
import statistics
from collections import Counter
from datetime import date

from equity_scout import db as db_module
from equity_scout.evidence.historical_storage import (
    RETURN_HORIZONS,
    init_historical_db,
)

DEFAULT_SPLIT_DATE = "2021-12-31"
DEFAULT_MIN_CELL_N = 30

# Stored `source` values (Decision 7: the insider class is stored as "insider"; the
# "insider clusters" wording is report-only).
CLASS_CONGRESS = "congress"
CLASS_INSIDER = "insider"
CLASS_STATEMENT = "statement"

CLASS_LABELS = {
    # Decision 6: OGE executive-branch filers ride in the congress source.
    CLASS_CONGRESS: "congress & executive filers",
    CLASS_INSIDER: "insider clusters",
    CLASS_STATEMENT: "statements",
}

UNKNOWN = "unknown"

REASON_NO_BOTH_SIDES = (
    "no coverage on both sides of the time split — an in-sample-only cell is not evidence"
)
REASON_DIRECTION_DISAGREES = "fit and validate disagree on the direction"
REASON_NO_DIRECTION = "mean relative return is exactly zero — no direction to validate"

# Verbatim from docs/superpowers/specs/2026-08-05-vision-v15-two-depots-evidence-learning.md,
# section "Proposed P2a" (markdown emphasis markers dropped, wording untouched). Every
# published study surface carries this; tests/test_historical_study.py asserts it still
# matches the spec so the two can never drift apart silently.
SURVIVORSHIP_DISCLAIMER = (
    "Hard honesty limit (stated up front): survivorship bias. No free source covers "
    "delisted US equities (verified — Stooq undocumented, real coverage is paid-only: "
    "Norgate/Finaeon/EODHD). Events whose ticker later delisted cannot be resolved with "
    "yfinance; they are counted and reported as a coverage gap on every study surface, "
    "never silently dropped — measured hit rates are an upper bound."
)

# Plan Decision 9: the statement class was MEASURED and buried, not skipped. These are the
# constants of the 2026-08-07 full-corpus run — the per-event audit triples (ticker,
# post_id, matched_phrase) and the blind-spot defense live in `backfill_statements.py`'s
# module docstring, so the finding is auditable without rerunning the corpus. Hardcoded on
# purpose: nothing was written to `historical_events`, so no query could reproduce them.
STATEMENT_MEASURED = {
    "corpus_rows": 78728,
    "candidates": 132,
    "raw_events": 10,
    "genuine": 0,
    "published": False,
    "reason": (
        "Measured 2026-08-07 over the full corpus (both Trump Twitter archive files plus "
        "the Truth Social archive, 7,499-name universe) with strict full-name-only ticker "
        "resolution, retweets filtered and exact-text repeats deduped: 132 candidate rows "
        "survived to ticker resolution and produced 10 raw events, all 10 manually "
        "verified as false attributions (9 are Trump-branded merchandise sold AT Macy's, "
        "1 is a reposted CNN headline) — zero genuine investment calls. None of the 10 "
        "was written to historical_events: the store is irreversible and min_cell_n is a "
        "statistical control, not a known-false-data control. Known blind spot: strict "
        "matching cannot see single-token company names (2,440 of 7,499); the 4 candidate "
        "rows naming such a company were checked by hand and none is a call. This is a "
        "measured zero for this corpus, not an unrun class."
    ),
}

INSIDER_COVERAGE_NOTES = (
    "Clusters are built per quarterly SEC file, so a cluster whose filings straddle a "
    "quarter boundary is structurally invisible — neither file sees all of it and no "
    "stitching pass exists. `boundary_candidates` in the backfill run counts the tickers "
    "sitting at exactly that edge; the number here is therefore a floor, never a ceiling.",
    "`mixed_issuer` counts clusters spanning more than one issuer CIK (one ticker string, "
    "two companies). They stay in the base rates and are surfaced here rather than "
    "silently dropped.",
)

_ROW_COLUMNS = (
    "id", "source", "person", "ticker", "t0", "details_json",
    *RETURN_HORIZONS, "unresolvable", "unresolvable_reason",
)


def _load_events(db_path: str) -> list[dict]:
    """Every row of `historical_events`, decoded for aggregation.

    The read side of the study lives here rather than in `historical_storage`, whose
    `unresolved_events` deliberately serves the RESOLVER's queue (open rows only). The
    study needs the full table — including buried rows, which carry measured horizons.
    A malformed `details_json` is decoded as `{}` and flagged, never raised: one bad row
    must not take down the report.
    """
    init_historical_db(db_path)
    with db_module.connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT {', '.join(_ROW_COLUMNS)} FROM historical_events ORDER BY id"
        ).fetchall()

    events: list[dict] = []
    for row in rows:
        event = dict(zip(_ROW_COLUMNS, row, strict=True))
        raw = event.pop("details_json")
        try:
            details = json.loads(raw)
        except (TypeError, ValueError):
            details = None
        # A JSON array/scalar is as unusable as broken JSON — both mean "no split keys".
        event["details_ok"] = isinstance(details, dict)
        event["details"] = details if isinstance(details, dict) else {}
        event["period"] = _period(event["t0"])
        events.append(event)
    return events


def _period(t0: str | None) -> str | None:
    """The event's date as a NORMALIZED ISO string, or None when `t0` is unusable
    (counted, never guessed). Normalizing matters: `fromisoformat` also accepts the basic
    format ("20200601"), which would then string-compare wrongly against the split date."""
    try:
        parsed = date.fromisoformat(str(t0 or "")[:10])
    except ValueError:
        return None
    return parsed.isoformat()


def _stats(values: list[float]) -> dict:
    """Per-horizon base rate. `hit_rate` = share of events with a POSITIVE relative
    return (the return is already relative to SPY, so >0 means it beat the benchmark)."""
    if not values:
        return {"n": 0, "hit_rate": None, "mean_relative_return": None}
    return {
        "n": len(values),
        "hit_rate": round(sum(1 for value in values if value > 0) / len(values), 4),
        "mean_relative_return": round(statistics.mean(values), 6),
    }


def _horizon_stats(rows: list[dict]) -> dict:
    return {
        horizon: _stats([row[horizon] for row in rows if row[horizon] is not None])
        for horizon in RETURN_HORIZONS
    }


def _edge(fit: dict, validate: dict, min_cell_n: int) -> dict:
    """Whether this horizon may claim an edge at all — the study's only verdict.

    Direction is the SIGN of the mean relative return; the hit rate is reported next to it
    but does not gate the claim (two ways of asking the same question would just make the
    gate's meaning fuzzy). Zero coverage on either side is refused independently of
    `min_cell_n` so a permissive threshold can never turn in-sample-only into a claim.
    """
    if fit["n"] == 0 or validate["n"] == 0:
        return {"measurable": False, "reason": REASON_NO_BOTH_SIDES}
    if fit["n"] < min_cell_n or validate["n"] < min_cell_n:
        return {"measurable": False, "reason": f"n<{min_cell_n}"}
    fit_mean = fit["mean_relative_return"]
    validate_mean = validate["mean_relative_return"]
    if fit_mean == 0 or validate_mean == 0:
        return {"measurable": False, "reason": REASON_NO_DIRECTION}
    if (fit_mean > 0) != (validate_mean > 0):
        return {"measurable": False, "reason": REASON_DIRECTION_DISAGREES}
    return {"measurable": True, "direction": "positive" if fit_mean > 0 else "negative"}


def _cell(rows: list[dict], *, min_cell_n: int, split_date: str) -> dict:
    """One aggregation unit: the whole class, one split value, or one person.

    `all` is the pooled base rate (reporting only — it mixes fit and validate and can
    therefore never justify a claim); `edge` is the verdict, and it reads fit/validate.
    """
    dated = [row for row in rows if row["period"] is not None]
    fit_rows = [row for row in dated if row["period"] <= split_date]
    validate_rows = [row for row in dated if row["period"] > split_date]
    fit = _horizon_stats(fit_rows)
    validate = _horizon_stats(validate_rows)
    return {
        "n": len(rows),
        "n_fit": len(fit_rows),
        "n_validate": len(validate_rows),
        "all": _horizon_stats(rows),
        "fit": fit,
        "validate": validate,
        "edge": {
            horizon: _edge(fit[horizon], validate[horizon], min_cell_n)
            for horizon in RETURN_HORIZONS
        },
    }


def _split_value(value: object) -> str:
    """A details field as a split key. Missing/empty/non-scalar -> `unknown`, so a cell is
    never quietly merged into a neighbouring one."""
    if value is None or isinstance(value, (dict, list)):
        return UNKNOWN
    text = str(value).strip()
    return text or UNKNOWN


def _cluster_size_band(value: object) -> str:
    """Insider cluster size bands (3 / 4-5 / 6+ insiders); MIN_INSIDERS is 3, so anything
    below it is data we do not understand rather than a smaller cluster."""
    try:
        size = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return UNKNOWN
    if size == 3:
        return "3"
    if 4 <= size <= 5:
        return "4-5"
    if size >= 6:
        return "6+"
    return UNKNOWN


# Deterministic split features per class (Decisions 6/7). Statements have none — the class
# is dead, and a split of zero events is noise, not a finding.
SPLIT_FEATURES = {
    CLASS_CONGRESS: {
        "amount_band": lambda details: _split_value(details.get("amount_range")),
        "chamber": lambda details: _split_value(details.get("chamber")),
    },
    CLASS_INSIDER: {
        "cluster_size_band": lambda details: _cluster_size_band(details.get("n_insiders")),
        "value_band": lambda details: _split_value(details.get("value_band")),
    },
}


def _coverage(rows: list[dict], *, source: str, split_date: str) -> dict:
    """Survivorship/coverage accounting — the numbers the disclaimer refers to.

    `unresolvable_with_measured_horizons` is Decision 4's case made visible: a row that
    IS both a real measurement and a survivorship gap. It is therefore counted in the base
    rates AND in `unresolvable`, which is why those two do not partition the total.
    """
    total = len(rows)
    measured = {
        horizon: sum(1 for row in rows if row[horizon] is not None)
        for horizon in RETURN_HORIZONS
    }
    horizon_counts = [
        sum(1 for horizon in RETURN_HORIZONS if row[horizon] is not None) for row in rows
    ]
    unresolvable_rows = [row for row in rows if row["unresolvable"]]
    reasons = Counter(row["unresolvable_reason"] or UNKNOWN for row in unresolvable_rows)
    full = len(RETURN_HORIZONS)
    coverage = {
        "total": total,
        "measured_per_horizon": measured,
        "coverage_per_horizon": {
            horizon: (round(count / total, 4) if total else None)
            for horizon, count in measured.items()
        },
        "fully_measured": sum(1 for count in horizon_counts if count == full),
        "partially_measured": sum(1 for count in horizon_counts if 0 < count < full),
        "unmeasured": sum(1 for count in horizon_counts if count == 0),
        "unresolvable": len(unresolvable_rows),
        "unresolvable_by_reason": dict(sorted(reasons.items())),
        "unresolvable_with_measured_horizons": sum(
            1
            for row in unresolvable_rows
            if any(row[horizon] is not None for horizon in RETURN_HORIZONS)
        ),
        "open": sum(
            1
            for row, count in zip(rows, horizon_counts, strict=True)
            if not row["unresolvable"] and count < full
        ),
        "t0_unparsable": sum(1 for row in rows if row["period"] is None),
        "details_unparsable": sum(1 for row in rows if not row["details_ok"]),
        "fit": sum(
            1 for row in rows if row["period"] is not None and row["period"] <= split_date
        ),
        "validate": sum(
            1 for row in rows if row["period"] is not None and row["period"] > split_date
        ),
    }
    if source == CLASS_INSIDER:
        # One ticker string, two issuer CIKs = two COMPANIES fused into one "cluster".
        # They stay in the base rates (Decision 7) and are counted here instead.
        coverage["mixed_issuer"] = sum(
            1
            for row in rows
            if isinstance(row["details"].get("issuer_ciks"), list)
            and len(row["details"]["issuer_ciks"]) > 1
        )
        coverage["notes"] = list(INSIDER_COVERAGE_NOTES)
    return coverage


def _class_section(rows: list[dict], *, source: str, split_date: str, min_cell_n: int) -> dict:
    splits: dict[str, dict] = {}
    for name, extract in SPLIT_FEATURES.get(source, {}).items():
        buckets: dict[str, list[dict]] = {}
        for row in rows:
            buckets.setdefault(extract(row["details"]), []).append(row)
        splits[name] = {
            value: _cell(bucket, min_cell_n=min_cell_n, split_date=split_date)
            for value, bucket in sorted(buckets.items())
        }

    persons: dict[str, list[dict]] = {}
    for row in rows:
        person = str(row["person"] or "").strip()
        if person:  # Decision 2: form-4 clusters have no single person (person = "")
            persons.setdefault(person, []).append(row)

    return {
        "label": CLASS_LABELS.get(source, source),
        "n": len(rows),
        "coverage": _coverage(rows, source=source, split_date=split_date),
        "overall": _cell(rows, min_cell_n=min_cell_n, split_date=split_date),
        "splits": splits,
        "persons": {
            person: _cell(bucket, min_cell_n=min_cell_n, split_date=split_date)
            for person, bucket in sorted(persons.items())
        },
    }


def _statement_section(rows: list[dict]) -> dict:
    """The measured negative result (Decision 9) — "measured, found nothing" must stay
    distinguishable from "never ran", so the class is reported even with zero rows."""
    section = {
        **STATEMENT_MEASURED,
        "label": CLASS_LABELS[CLASS_STATEMENT],
        "n": len(rows),  # 0 in a healthy database — see the warning below if it is not
    }
    if rows:
        # Contract violation: the burial says nothing may be written. Say so instead of
        # publishing base rates over data that was verified false.
        section["warning"] = (
            f"unexpected: {len(rows)} statement row(s) in historical_events — Decision 9 "
            "buried this class as measured-false and nothing may be written. No base rate "
            "is published for them; investigate the writer before using any number here."
        )
    return section


def aggregate_history(
    db_path: str,
    *,
    split_date: str = DEFAULT_SPLIT_DATE,
    min_cell_n: int = DEFAULT_MIN_CELL_N,
) -> dict:
    """Base rates per class / split / person, time-split into fit (t0 <= `split_date`) and
    validate (t0 > `split_date`), with every un-claimable cell refusing explicitly.

    An empty (or not-yet-created) database is a valid input: every class comes back with
    n = 0 and refused edges — a report that says "nothing measured yet" loudly beats an
    exception, because the same script runs before and after the first backfill. A
    malformed `split_date` is NOT: it would silently push every event into `validate` and
    produce a study with no in-sample side at all.
    """
    if _period(split_date) != split_date:
        raise ValueError(f"split_date must be a plain ISO date (YYYY-MM-DD): {split_date!r}")
    events = _load_events(db_path)
    by_source: dict[str, list[dict]] = {}
    for event in events:
        by_source.setdefault(str(event["source"]), []).append(event)

    classes = {
        source: _class_section(
            by_source.get(source, []),
            source=source,
            split_date=split_date,
            min_cell_n=min_cell_n,
        )
        for source in (CLASS_CONGRESS, CLASS_INSIDER)
    }
    classes[CLASS_STATEMENT] = _statement_section(by_source.get(CLASS_STATEMENT, []))

    return {
        "split_date": split_date,
        "min_cell_n": min_cell_n,
        "n_events": len(events),
        "classes": classes,
        # Anything the study does not know how to read is counted, never invisible.
        "other_sources": {
            source: len(rows)
            for source, rows in sorted(by_source.items())
            if source not in classes
        },
    }
