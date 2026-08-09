"""Point-in-time evidence features for the entry-quality model (v15 P3).

Turns the P2a `historical_events` insider-cluster store into a small deterministic feature block
per (ticker, as_of). ONLY insider clusters are encoded: the P2a post-fix rerun measured the
congress & executive class over 16,358-20,792 events per horizon and found no economically
meaningful edge in either direction (r_1w +0.15% +/- 0.03pp with disagreeing directions, r_6m
-0.63% +/- 0.19pp), and the statement class is a measured zero (0 of 10 raw events genuine,
never written). Those are feature-selection FACTS, not data gaps — see the plan's Non-Goals.

Honesty invariant (the `entry_features` rule plus one more):
  * every value is a pure function of clusters whose `t0` — the LAST filing date of the cluster,
    i.e. the day the whole cluster became publicly knowable — lies STRICTLY BEFORE `as_of`. A
    Form 4 stamped on the decision date may have hit EDGAR after that day's close, and the price
    features are computed on exactly that close, so same-day events are excluded.
  * nothing here reads a `historical_events.r_*` column. Those are forward returns measured after
    `t0` and would be pure look-ahead — the loader does not even SELECT them.

Windows are CALENDAR days, not panel rows. `t0` is a plain ISO DATE (P2a Decision 10) with no
session semantics, and P2a Decision 11 warns that the study's horizons count panel rows rather
than exchange sessions. A calendar window therefore keeps the feature identical no matter which
panel it is computed against.

Rows marked `unresolvable` stay in the index on purpose: a name that later delisted still had a
real cluster at its `t0`, which is exactly what was knowable at decision time. Dropping them
would rebuild the survivorship bias P2a exists to count (P2a Decision 4's spirit).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd

from equity_scout import db as db_module
from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.evidence.base import SOURCE_INSIDER
from equity_scout.evidence.historical_storage import init_historical_db

# Ordered evidence block, appended AFTER `entry_features.FEATURE_COLUMNS` when a caller opts in.
# Ordered and single-sourced for the same reason FEATURE_COLUMNS is: the dataset builder and the
# fitted model must never disagree about the layout.
EVIDENCE_FEATURE_COLUMNS: tuple[str, ...] = (
    "ev_insider_cluster_91d",
    "ev_insider_max_size_91d",
    "ev_insider_count_365d",
)
# The 0/1 flag column. Named so the training CLI's coverage number reads one source of truth
# instead of repeating a magic string that would silently rot if a window ever changes.
EVIDENCE_ACTIVE_COLUMN = EVIDENCE_FEATURE_COLUMNS[0]

# ~63 trading days: the study's r_3m horizon — the nearest MEASURED window to the entry_tb label's
# 40-trading-day barrier horizon (`BarrierConfig.horizon_days`), and the horizon where insider
# clusters showed +2.55% +/- 0.67pp mean relative return on 13,694 measurements.
SHORT_WINDOW_DAYS = 91
# ~252 trading days: the study's r_12m horizon — repeat-buying intensity over a year.
LONG_WINDOW_DAYS = 365


def _as_date(value: object) -> date:
    """A pandas Timestamp / datetime / date / ISO string as a plain date — the store's `t0` is a
    plain date, so the comparison unit is a date on BOTH sides (no tz, no time-of-day)."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


@dataclass(frozen=True)
class EvidenceIndex:
    """Per-ticker sorted `(t0, n_insiders)` pairs — the whole state the feature block needs.

    Built once per training run and queried ~100k times, so it is a plain in-memory dict rather
    than a per-row query. Lists are tiny (tens of clusters per ticker over 20 years), which is why
    `features` scans linearly instead of carrying a bisect index nobody can read.
    """

    clusters: dict[str, list[tuple[date, int]]]

    def features(self, ticker: str, as_of: object) -> dict[str, float]:
        """The evidence block for one (ticker, as_of), keys == `EVIDENCE_FEATURE_COLUMNS`.

        All zeros for a ticker with no cluster history: absence of insider buying is a FACT that
        was knowable, not a missing measurement, so this never returns None (unlike
        `entry_features.build_feature_row`, whose None means "cannot be computed honestly" and
        drops the row). Windows are half-open `(as_of - window, as_of)` — see the module docstring
        for why the upper bound is strict.
        """
        as_of_date = _as_date(as_of)
        short_start = as_of_date - timedelta(days=SHORT_WINDOW_DAYS)
        long_start = as_of_date - timedelta(days=LONG_WINDOW_DAYS)
        short_sizes: list[int] = []
        long_count = 0
        for t0, n_insiders in self.clusters.get(ticker, ()):
            if t0 >= as_of_date:
                continue  # not knowable at this day's close
            if t0 > long_start:
                long_count += 1
            if t0 > short_start:
                short_sizes.append(n_insiders)
        return {
            "ev_insider_cluster_91d": 1.0 if short_sizes else 0.0,
            "ev_insider_max_size_91d": float(max(short_sizes)) if short_sizes else 0.0,
            "ev_insider_count_365d": float(long_count),
        }


def load_evidence_index(db_path: str = DEFAULT_DB_PATH) -> EvidenceIndex:
    """Build the index from the `historical_events` insider clusters.

    Selects `ticker, t0, details_json` ONLY — the `r_*` forward-return columns are measured after
    `t0` and must never be reachable from a feature (leakage; `tests/test_evidence_features.py`
    guards this). A row whose `t0` is unparsable or whose details carry no integer `n_insiders` is
    skipped and never guessed: a cluster we cannot describe is not a feature.
    """
    init_historical_db(db_path)
    with db_module.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT ticker, t0, details_json FROM historical_events WHERE source = ?",
            (SOURCE_INSIDER,),
        ).fetchall()
    clusters: dict[str, list[tuple[date, int]]] = {}
    for ticker, t0, details_json in rows:
        try:
            parsed = date.fromisoformat(str(t0)[:10])
            n_insiders = int(json.loads(details_json)["n_insiders"])
        except (KeyError, TypeError, ValueError):
            continue
        clusters.setdefault(ticker, []).append((parsed, n_insiders))
    for entries in clusters.values():
        entries.sort()
    return EvidenceIndex(clusters)
