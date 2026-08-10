# v15 P3 — Evidence Learning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the entry-model family learn from the evidence it already collects: feed deterministic, point-in-time insider-cluster features from the P2a `historical_events` store into the EXISTING `entry_tb` training path, and add a runner that re-evaluates only when the Wave-1 resolve loop has produced enough NEW real resolutions — with the existing registry gate as the sole promotion path.

**Requirements doc:** `docs/superpowers/specs/2026-08-05-vision-v15-two-depots-evidence-learning.md`, section "P3 amendment — evidence features into the entry models" (spec line 249-253) plus the P3 scope line 112-118. This plan implements exactly the amendment; the other P3 bullets (champion→sleeve promotion, rank-IC on `run_scores`, cadence rotation) are NOT in this plan — see Non-Goals.

**Architecture (locked):** A new pure module `src/equity_scout/ml/evidence_features.py` loads the `historical_events` insider-cluster rows once into a per-ticker index and answers "what was publicly knowable about this ticker's insider buying strictly BEFORE `as_of`" as a three-column feature block. `entry_dataset.build_backfill_dataset` and `run_train_entry`/`run_train_entry_all` gain one additive `evidence_index` parameter (default `None` = today's exact behaviour and today's `FEATURE_COLUMNS`); with an index, the `entry_tb` family trains a second set of challengers that must beat the same champion through the unchanged `model_registry.promote_if_better` gate, with `n_candidates` raised to the true number of competitors. `scripts/run_evidence_refresh.py` watermarks the prediction ledger's `n_resolved` in `app_state`, refuses to spend a trial below a minimum of new resolutions, and otherwise delegates to that same training path.

**Tech Stack:** Python 3 (uv), pandas, scikit-learn, sqlite3, pytest. Gate before every commit: `uv run python -m pytest -q` green (baseline: **1732 tests**) + `uv run ruff check .` clean. (`uv run pytest -q` is the documented equivalent — `pythonpath = ["."]` is pinned in `pyproject.toml`.)

---

## Non-Goals (explicit, with the numbers that killed them)

- **No congress-derived features.** The P2a post-fix rerun measured the congress & executive class on 16,358–20,792 events per horizon and found no economically meaningful edge in either direction: r_1w **+0.15% ± 0.03pp (directions disagree)**, r_1m **+0.06% ± 0.07pp**, r_3m **−0.22% ± 0.13pp**, r_6m **−0.63% ± 0.19pp**, r_12m **−0.39% ± 0.33pp (directions disagree)**. Validate-side hit rates 51.5 / 47.3 / 44.7 / 43.1 / 39.7%. That is a feature-selection FACT, not a data gap — the class had full coverage. Encoding it would spend model capacity and multiple-testing budget on a measured null.
- **No statement/voice features.** P2a Decision 9: 78,728 corpus rows → 132 candidates → 10 raw events → **0 genuine**, `published: false`. Nothing was ever written to `historical_events`; there is no data to feature-engineer.
- **No new model class, no new training loop, no new registry family.** Evidence variants are extra challengers inside the existing `entry_tb` family (same label definition, same barrier config → AUC is comparable), trained by the existing `run_train_entry`.
- **No new promotion mechanism.** `model_registry.promote_if_better` stays the only path to champion: `MIN_OOS_N = 200`, `NO_EDGE_BAND = 0.05`, `MIN_AUC_DELTA * sqrt(n_candidates)`. This plan raises `n_candidates` honestly; it never lowers a bar.
- **No study-fitted prior as a numeric feature.** See Design ruling 2 — a prior estimated over 2006→2026 is look-ahead for every training row inside that span. The study informs WHICH features exist, not what value they take.
- **No capital, no broker, no frontend, no scheduling.** Nothing is wired into `nightly_train.sh` or `daily_copilot.sh`; the refresh runner is manual (`--apply`) like the P2a backfill runners. No `frontend/` change, no API change, no Telegram surface.
- **No live scoring change.** `entry_tb` champions are never used to score anything (verified: `api.py:1147` and `scripts/run_notify.py:202` read `champ[2]["barrier_config"]` only; the scoring families are `entry`/`entry_short` via `strategies/ml_bot.py` and `scripts/run_score_watchlist.py`).
- **Not in this plan (rest of spec P3):** champion→sleeve promotion for the v14 strategy-parameter search, rank-IC tracking on `run_scores` history, cadence rotation for coin-flip families. Separate waves.

---

## Design rulings (binding for all tasks; Nico can veto at the plan gate)

1. **`entry_tb` is the target family because it has no live consumer and no champion.** 28 nightly versions, best AUC ≤ 0.51, champion slot empty. A promotion there changes exactly one thing in the product: which `barrier_config` the Scout-Ziel display reads — and that config is written identically by both variants. Zero blast radius, which is what makes an honest experiment affordable.
2. **Features are counts and recencies, never fitted priors.** The controller's example list named "insider short-horizon prior from the study". Deviating on purpose: the study was fit over the whole 2006→2026 span, so a per-band prior injected as a column leaks the future into every training row inside that span. The study instead selects the FEATURE SET (insider clusters in, congress out) and the WINDOW (see ruling 3). A point-in-time expanding prior is a real v2 candidate; it is not v1.
3. **Windows are calendar days, not panel rows.** `historical_events.t0` is a plain ISO DATE (P2a Decision 10) with no session semantics, and P2a Decision 11 warns that the study's horizons count panel rows rather than exchange sessions. A calendar window keeps the feature identical no matter which panel it is computed against. `SHORT_WINDOW_DAYS = 91` (≈63 trading days = the study's r_3m, the nearest measured horizon to `BarrierConfig.horizon_days = 40` trading days, and the horizon where insider clusters showed **+2.55% ± 0.67pp** on 13,694 measurements); `LONG_WINDOW_DAYS = 365` (the r_12m horizon: repeat-buying intensity).
4. **`t0 < as_of`, strictly.** A Form 4 stamped on the decision date may have hit EDGAR after the close, and the price features are computed on that close. Same-day events are excluded — the conservative side of the PIT line.
5. **The loader never SELECTs an `r_*` column.** Forward returns are measured after `t0`; they must not be reachable from a feature. Enforced by a regression test, not only by review.
6. **`unresolvable = 1` rows stay in the index.** A delisted name still had a real cluster at its t0 — that is a fact knowable at decision time. Dropping them would rebuild the survivorship bias P2a exists to count (P2a Decision 4's spirit).
7. **"Reuse ml/ledger mechanics" = reuse `model_registry.promote_if_better`.** `ml/ledger.py`'s DSR hurdle rules `MetaConfig` strategy trials, a different object with a different metric (deflated Sharpe over backtest returns, not OOS AUC over classification labels). Bending entry models into it would BE the fork. The entry family's champion mechanic is `promote_if_better`, and its multiple-testing correction (`_min_auc_delta(n) = MIN_AUC_DELTA * sqrt(n)`) is the same idea as `expected_max_sharpe` — best-of-N noise gets a numeric hurdle. This plan reuses it untouched.
8. **The refresh runner is a trigger, not a gate.** It decides WHEN to spend a trial; `promote_if_better` decides whether anything changes. `--min-new-resolutions` defaults to 30, the repo's standing minimum-evidence unit (`historical_study.DEFAULT_MIN_CELL_N = 30`, arena promotion ≥30 trades). Dry-run default; `--apply` is what writes.
9. **Multiplicity wording is inherited verbatim in spirit from `historical_study`.** Every printed claim states how many candidates competed and that best-of-N is expected to win by chance. The word "belegbar" never appears; a champion flip is reported as "Gate genommen", never as a demonstrated edge.

---

## Coordination

A parallel autopilot session owns `src/equity_scout/st_session.py`, `src/equity_scout/alpaca_*.py`, `scripts/run_shortterm.py`, `PLAN.md`, `frontend/`. **Verified: none of this plan's files appear on that list.** Commit only explicit paths (`git add <paths>`, never `-A`). Do NOT edit `PLAN.md`.

**Second plan in flight:** `docs/superpowers/plans/2026-08-07-v15-p2-insider-shadow-lane.md` (written the same day) edits `src/equity_scout/ml/prediction_ledger.py` to rename the private `_resolve_after` into a public `resolve_after_stamp`. This plan does not edit that file — it only *imports* its public functions (`resolved_stats`, `log_predictions`, `due_predictions`, `resolve_prediction`), none of which that rename touches. No collision; no ordering constraint between the two plans.

---

## File-structure map

```
src/equity_scout/ml/
  evidence_features.py        NEW  — PIT insider-cluster index + the 3-column feature block
  entry_dataset.py            MOD  — additive `evidence_index` param (default None = today)
  entry_model.py              MOD  — score_row raises on missing feature columns
  entry_features.py           —    (untouched: the price block stays the price block)
  model_registry.py           —    (untouched: the promotion gate is reused, not changed)
scripts/
  run_train_entry.py          MOD  — thread `evidence_index`, `--with-evidence`, n_candidates
  run_evidence_refresh.py     NEW  — resolution-watermarked refresh runner
tests/
  test_evidence_features.py   NEW
  test_run_evidence_refresh.py NEW
  test_entry_dataset.py       MOD  — additive-param regression + evidence columns
  test_entry_model.py         MOD  — missing-column guard
  test_run_train_entry.py     MOD  — metrics keyset, n_candidates accounting, CLI flag
docs/superpowers/plans/
  2026-08-07-v15-p3-evidence-learning.md   (this file; Outcome filled in Task 6)
```

Untouched by design: `frontend/`, `PLAN.md`, `scripts/nightly_train.sh`, `scripts/daily_copilot.sh`, every `alpaca_*`/`st_*`/`shortterm*` file, `src/equity_scout/api.py`.

---

### Task 1: `ml/evidence_features.py` — the point-in-time insider index

**Files:** Create `src/equity_scout/ml/evidence_features.py`, `tests/test_evidence_features.py`.

- [x] **Step 1: Write the failing tests**

Create `tests/test_evidence_features.py`:

```python
"""PIT evidence-feature tests: what was knowable about insider clusters before `as_of`."""
from __future__ import annotations

import sqlite3
from datetime import date

import pandas as pd

from equity_scout.evidence.base import SOURCE_CONGRESS, SOURCE_INSIDER
from equity_scout.evidence.historical_storage import (
    HistoricalEvent,
    mark_resolved,
    mark_unresolvable,
    record_historical_events,
)
from equity_scout.ml.evidence_features import (
    EVIDENCE_FEATURE_COLUMNS,
    LONG_WINDOW_DAYS,
    SHORT_WINDOW_DAYS,
    EvidenceIndex,
    load_evidence_index,
)

NOW = "2026-08-07T12:00:00+00:00"


def _cluster(ticker: str, t0: str, n_insiders: int, *, source: str = SOURCE_INSIDER):
    return HistoricalEvent(
        source=source,
        person="",
        ticker=ticker,
        event_key=f"{ticker}-{t0}-cluster{n_insiders}",
        t0=t0,
        details={"n_insiders": n_insiders},
    )


def _index(*events) -> EvidenceIndex:
    """Index built straight from the dataclass, no DB — keeps the pure logic tests fast."""
    clusters: dict = {}
    for event in events:
        clusters.setdefault(event.ticker, []).append(
            (date.fromisoformat(event.t0), int(event.details["n_insiders"]))
        )
    for entries in clusters.values():
        entries.sort()
    return EvidenceIndex(clusters)


def _only_event_id(db: str) -> int:
    with sqlite3.connect(db) as conn:
        return int(conn.execute("SELECT id FROM historical_events").fetchone()[0])


def test_unknown_ticker_is_all_zeros_never_none():
    """Absence of insider buying is a FACT, not a gap — the block never returns None (unlike
    `entry_features.build_feature_row`, whose None means 'cannot be computed honestly')."""
    features = _index().features("AAA", pd.Timestamp("2026-01-15"))
    assert list(features) == list(EVIDENCE_FEATURE_COLUMNS)
    assert set(features.values()) == {0.0}


def test_cluster_inside_the_short_window_sets_flag_size_and_count():
    index = _index(_cluster("AAA", "2026-01-02", 5))
    features = index.features("AAA", pd.Timestamp("2026-02-02"))
    assert features["ev_insider_cluster_91d"] == 1.0
    assert features["ev_insider_max_size_91d"] == 5.0
    assert features["ev_insider_count_365d"] == 1.0


def test_future_and_same_day_clusters_are_invisible():
    """Ruling 4: a filing stamped ON the decision date may have hit EDGAR after the close."""
    index = _index(_cluster("AAA", "2026-02-02", 4), _cluster("AAA", "2026-03-01", 9))
    assert index.features("AAA", pd.Timestamp("2026-02-02")) == {
        "ev_insider_cluster_91d": 0.0,
        "ev_insider_max_size_91d": 0.0,
        "ev_insider_count_365d": 0.0,
    }


def test_window_boundaries_are_half_open():
    """(as_of - window, as_of): a cluster exactly `window` days back is already out."""
    as_of = pd.Timestamp("2026-06-01")
    short_edge = (as_of - pd.Timedelta(days=SHORT_WINDOW_DAYS)).date().isoformat()
    long_edge = (as_of - pd.Timedelta(days=LONG_WINDOW_DAYS)).date().isoformat()
    index = _index(_cluster("AAA", short_edge, 6), _cluster("BBB", long_edge, 6))
    assert index.features("AAA", as_of)["ev_insider_cluster_91d"] == 0.0
    assert index.features("AAA", as_of)["ev_insider_count_365d"] == 1.0  # still inside the year
    assert index.features("BBB", as_of)["ev_insider_count_365d"] == 0.0


def test_max_size_is_the_max_inside_the_window_not_the_latest():
    index = _index(_cluster("AAA", "2026-01-05", 8), _cluster("AAA", "2026-02-05", 3))
    features = index.features("AAA", pd.Timestamp("2026-03-01"))
    assert features["ev_insider_max_size_91d"] == 8.0
    assert features["ev_insider_count_365d"] == 2.0


def test_loader_reads_only_insider_clusters_from_the_store(tmp_path):
    db = str(tmp_path / "hist.db")
    record_historical_events(
        db,
        [
            _cluster("AAA", "2026-01-02", 4),
            _cluster("BBB", "2026-01-02", 7, source=SOURCE_CONGRESS),  # Non-Goal: never indexed
        ],
        now=NOW,
    )
    index = load_evidence_index(db)
    assert index.features("AAA", pd.Timestamp("2026-02-01"))["ev_insider_cluster_91d"] == 1.0
    assert index.features("BBB", pd.Timestamp("2026-02-01"))["ev_insider_cluster_91d"] == 0.0


def test_forward_returns_can_never_reach_a_feature(tmp_path):
    """Ruling 5 (leakage regression): r_* columns are measured AFTER t0. Writing an absurd
    forward return must not move a single feature value."""
    db = str(tmp_path / "hist.db")
    record_historical_events(db, [_cluster("AAA", "2026-01-02", 4)], now=NOW)
    as_of = pd.Timestamp("2026-02-01")
    before = load_evidence_index(db).features("AAA", as_of)
    assert mark_resolved(db, _only_event_id(db), {"r_1w": 999.0, "r_3m": -999.0}, now=NOW)
    assert load_evidence_index(db).features("AAA", as_of) == before


def test_unresolvable_rows_stay_in_the_index(tmp_path):
    """Ruling 6: a delisted name still had a real cluster at t0 — dropping it would rebuild
    the survivorship bias P2a exists to count."""
    db = str(tmp_path / "hist.db")
    record_historical_events(db, [_cluster("AAA", "2026-01-02", 4)], now=NOW)
    assert mark_unresolvable(db, _only_event_id(db), "no_price_history", now=NOW)
    features = load_evidence_index(db).features("AAA", pd.Timestamp("2026-02-01"))
    assert features["ev_insider_cluster_91d"] == 1.0


def test_malformed_rows_are_skipped_never_guessed(tmp_path):
    db = str(tmp_path / "hist.db")
    record_historical_events(
        db,
        [
            HistoricalEvent(SOURCE_INSIDER, "", "AAA", "k1", "not-a-date", {"n_insiders": 4}),
            HistoricalEvent(SOURCE_INSIDER, "", "BBB", "k2", "2026-01-02", {"insiders": ["x"]}),
        ],
        now=NOW,
    )
    index = load_evidence_index(db)
    assert index.clusters == {}
```

- [x] **Step 2: Run the tests to verify they fail**

```bash
uv run python -m pytest tests/test_evidence_features.py -q
```
Expected: collection error — `ModuleNotFoundError: No module named 'equity_scout.ml.evidence_features'`.

- [x] **Step 3: Implement**

Create `src/equity_scout/ml/evidence_features.py`:

```python
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
```

- [x] **Step 4: Run the module tests**

```bash
uv run python -m pytest tests/test_evidence_features.py -q
```
Expected: `9 passed`.

- [x] **Step 5: Full gate + commit**

```bash
uv run python -m pytest -q && uv run ruff check .
```
Expected: `1741 passed` (1732 + 9), `All checks passed!`.

```bash
git add src/equity_scout/ml/evidence_features.py tests/test_evidence_features.py
git commit -m "feat(ml): point-in-time insider-cluster evidence features"
```

---

### Task 2: `EntryModel.score_row` must fail loudly on a missing feature column

**Files:** Modify `src/equity_scout/ml/entry_model.py`, `tests/test_entry_model.py`.

**Why now, not later:** this plan is the first time the registry holds models with DIFFERENT feature sets side by side. `score_row` currently builds `pd.DataFrame([features], columns=self.feature_columns)`, which fills any column the caller did not supply with **NaN and scores it silently**. That is the one way an evidence-featured champion could ever produce a fabricated number, so it is closed here before the champion can exist.

- [x] **Step 1: Write the failing test**

Append to `tests/test_entry_model.py`:

```python
def test_score_row_refuses_a_row_missing_a_fitted_feature_column():
    """v15 P3: models with different feature sets now coexist in one registry.
    `pd.DataFrame([features], columns=...)` would NaN-fill a missing column and score it
    silently — the one path that could fabricate a number. Extra keys stay fine."""
    import pytest  # only test in this module that needs it

    X = pd.DataFrame({"a": np.linspace(0.0, 1.0, 40), "b": np.linspace(1.0, 0.0, 40)})
    y = pd.Series([0, 1] * 20)
    model = train_entry_model(X, y, model="elastic_net")

    with pytest.raises(ValueError, match="missing"):
        model.score_row({"a": 0.5})

    assert 0 <= model.score_row({"a": 0.5, "b": 0.5, "unused": 9.9}) <= 100
```

- [x] **Step 2: Run the test to verify it fails**

```bash
uv run python -m pytest tests/test_entry_model.py -q -k score_row_refuses
```
Expected: `DID NOT RAISE <class 'ValueError'>` (the NaN row scores silently today).

- [x] **Step 3: Implement**

In `src/equity_scout/ml/entry_model.py`, replace `score_row` (lines 92-95):

```python
    def score_row(self, features: dict) -> int:
        """Score a single feature dict. Every column the model was FITTED on must be present:
        `pd.DataFrame([features], columns=...)` would otherwise fill a missing one with NaN and
        score it silently. Since v15 P3 the registry holds models with different feature sets
        (evidence-featured challengers next to price-only ones), so handing the wrong block to
        the wrong model must fail loudly. Extra keys are ignored, exactly as before."""
        missing = [column for column in self.feature_columns if column not in features]
        if missing:
            raise ValueError(
                f"feature row is missing {len(missing)} column(s) the model was fitted on: "
                f"{missing}"
            )
        row = pd.DataFrame([features], columns=list(self.feature_columns))
        return int(self.score_many(row)[0])
```

- [x] **Step 4: Full gate + commit**

```bash
uv run python -m pytest -q && uv run ruff check .
```
Expected: `1742 passed`, `All checks passed!`. (Every existing caller — `ml_bot.score_universe`, `run_score_watchlist` — passes a full `build_feature_row` dict, so the guard is a no-op for them. If any existing test fails here, that test was relying on NaN-filling and the failure is the finding, not a regression to paper over.)

```bash
git add src/equity_scout/ml/entry_model.py tests/test_entry_model.py
git commit -m "fix(ml): score_row raises on missing fitted feature columns instead of NaN-filling"
```

---

### Task 3: `build_backfill_dataset` takes an additive `evidence_index`

**Files:** Modify `src/equity_scout/ml/entry_dataset.py`, `tests/test_entry_dataset.py`.

- [x] **Step 1: Write the failing tests**

Append to `tests/test_entry_dataset.py`:

```python
def test_default_call_is_unchanged_by_the_additive_evidence_param():
    """Regression: `evidence_index=None` must reproduce today's exact layout — the nightly
    chain calls this without the parameter and must not move an inch."""
    panel = _panel()
    X, y, meta = build_backfill_dataset(panel, ["AAA", "BBB"], horizon_days=HORIZON_DAYS)
    X2, y2, meta2 = build_backfill_dataset(
        panel, ["AAA", "BBB"], horizon_days=HORIZON_DAYS, evidence_index=None
    )
    assert list(X.columns) == list(FEATURE_COLUMNS)
    pd.testing.assert_frame_equal(X, X2)
    pd.testing.assert_series_equal(y, y2)
    pd.testing.assert_frame_equal(meta, meta2)


def test_evidence_index_appends_its_block_point_in_time():
    """With an index, X carries FEATURE_COLUMNS + EVIDENCE_FEATURE_COLUMNS, and the flag is 0
    for every as_of at or before the cluster's t0 and 1 inside the window after it."""
    from datetime import date

    from equity_scout.ml.evidence_features import EVIDENCE_FEATURE_COLUMNS, EvidenceIndex

    panel = _panel()
    cluster_day = date(2020, 6, 1)
    index = EvidenceIndex({"AAA": [(cluster_day, 7)]})
    X, _, meta = build_backfill_dataset(
        panel, ["AAA", "BBB"], horizon_days=HORIZON_DAYS, evidence_index=index
    )
    assert list(X.columns) == list(FEATURE_COLUMNS) + list(EVIDENCE_FEATURE_COLUMNS)

    as_of = pd.to_datetime(meta["as_of"])
    is_aaa = meta["ticker"] == "AAA"
    flag = X["ev_insider_cluster_91d"]
    # BBB has no clusters at all -> the whole block is zero for it.
    assert (X.loc[~is_aaa.to_numpy(), list(EVIDENCE_FEATURE_COLUMNS)] == 0.0).all().all()
    # AAA before the filing day: invisible. Inside the 91-day window after it: visible.
    before = is_aaa.to_numpy() & (as_of.dt.date <= cluster_day).to_numpy()
    inside = (
        is_aaa.to_numpy()
        & (as_of.dt.date > cluster_day).to_numpy()
        & (as_of.dt.date <= date(2020, 8, 1)).to_numpy()
    )
    assert (flag[before] == 0.0).all()
    assert inside.any() and (flag[inside] == 1.0).all()
    assert (X.loc[inside, "ev_insider_max_size_91d"] == 7.0).all()
```

- [x] **Step 2: Run the tests to verify they fail**

```bash
uv run python -m pytest tests/test_entry_dataset.py -q -k "additive or evidence_index"
```
Expected: `TypeError: build_backfill_dataset() got an unexpected keyword argument 'evidence_index'` (both tests).

- [x] **Step 3: Implement**

In `src/equity_scout/ml/entry_dataset.py`:

Add the import next to the existing `entry_features` import block:

```python
from equity_scout.ml.evidence_features import EVIDENCE_FEATURE_COLUMNS, EvidenceIndex
```

Add the parameter to the signature (after `barrier_config`):

```python
    barrier_config: BarrierConfig | None = None,
    evidence_index: EvidenceIndex | None = None,
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
```

Add to the docstring, right before the closing paragraph:

```
    `evidence_index` (v15 P3, additive — default None reproduces the pre-P3 layout exactly):
    when given, every row's feature dict is extended by `EVIDENCE_FEATURE_COLUMNS`, appended
    after the price block, so X's columns become FEATURE_COLUMNS + EVIDENCE_FEATURE_COLUMNS. The
    block is point-in-time by construction (`EvidenceIndex.features` only sees events strictly
    before `as_of`) and never returns None, so it can add columns but can never drop a row —
    which keeps the with/without comparison an apples-to-apples one on the SAME sample.
```

Inside the per-`as_of` loop, right after the `if features is None: continue` guard:

```python
            if evidence_index is not None:
                features = {**features, **evidence_index.features(ticker, as_of)}
```

And replace the `X = ...` construction:

```python
    columns = list(FEATURE_COLUMNS)
    if evidence_index is not None:
        columns += list(EVIDENCE_FEATURE_COLUMNS)
    X = pd.DataFrame([r[2] for r in rows], columns=columns)
```

- [x] **Step 4: Full gate + commit**

```bash
uv run python -m pytest -q && uv run ruff check .
```
Expected: `1744 passed`, `All checks passed!`.

```bash
git add src/equity_scout/ml/entry_dataset.py tests/test_entry_dataset.py
git commit -m "feat(ml): additive evidence_index in the entry backfill dataset"
```

---

### Task 4: train the evidence variant as extra `entry_tb` challengers, with honest `n_candidates`

**Files:** Modify `scripts/run_train_entry.py`, `tests/test_run_train_entry.py`.

- [x] **Step 1: Write the failing tests**

First fix the existing metrics-keyset assertion in `tests/test_run_train_entry.py` (line 62-65) — two keys are added so a registry row can always say whether the model used evidence:

```python
    assert set(result["metrics"]) == {
        "auc", "brier", "rank_ic", "n_oos", "n_splits_used", "feature_importance",
        "horizon_days", "calibrated", "feature_means", "is_auc", "wfe",
        # v15 P3: always present, so "trained without evidence" is a recorded fact, not an
        # absent key that a later reader has to guess about.
        "evidence_features", "evidence_coverage",
    }
```

Then append:

```python
def test_plain_run_records_that_no_evidence_features_were_used(tmp_path):
    db = str(tmp_path / "train.db")
    result = run_train_entry(db, panel=_panel(), tickers=["AAA", "BBB"], now=NOW)
    assert result["metrics"]["evidence_features"] == []
    assert result["metrics"]["evidence_coverage"] is None


def test_evidence_run_records_columns_and_coverage(tmp_path, capsys):
    """The coverage share is a first-class output: a feature set that is zero on ~every
    training row cannot possibly beat the champion, and must say so before anyone believes a
    promotion."""
    from datetime import date

    from equity_scout.ml.evidence_features import EVIDENCE_FEATURE_COLUMNS, EvidenceIndex

    db = str(tmp_path / "train.db")
    index = EvidenceIndex({"AAA": [(date(2020, 6, 1), 7)]})
    result = run_train_entry(
        db, panel=_panel_with_vol(), tickers=["AAA", "BBB"], now=NOW,
        family="entry_tb", barrier_config=BarrierConfig(), evidence_index=index,
    )
    assert result["metrics"]["evidence_features"] == list(EVIDENCE_FEATURE_COLUMNS)
    assert 0.0 < result["metrics"]["evidence_coverage"] < 1.0
    assert "Evidence-Features aktiv" in capsys.readouterr().out


def test_evidence_variant_only_doubles_entry_tb_and_its_candidate_count(tmp_path, monkeypatch):
    """Ruling 1: the evidence block competes inside entry_tb only. Ruling 7: the extra
    challengers must raise that family's multiple-testing count — testing twice as many
    presets against the same champion without raising the bar is exactly the noise-promotion
    hole `_min_auc_delta` exists to close."""
    from datetime import date

    from equity_scout.ml.evidence_features import EvidenceIndex
    from scripts.run_train_entry import run_train_entry_all

    calls: list[tuple] = []

    def _fake(db_path, **kwargs):
        calls.append(
            (kwargs["family"], kwargs["model"], kwargs["evidence_index"] is not None,
             kwargs["n_candidates"])
        )
        return {"version": len(calls), "metrics": {}, "promoted": False, "n_train": 1}

    monkeypatch.setattr(train_mod, "run_train_entry", _fake)
    run_train_entry_all(
        str(tmp_path / "train.db"), panel=_panel(), tickers=["AAA"], now=NOW,
        models=("random_forest", "elastic_net"),
        evidence_index=EvidenceIndex({"AAA": [(date(2020, 6, 1), 7)]}),
    )

    by_family: dict[str, list[tuple]] = {}
    for family, model, with_evidence, n_candidates in calls:
        by_family.setdefault(family, []).append((model, with_evidence, n_candidates))

    assert [c[1] for c in by_family["entry"]] == [False, False]
    assert {c[2] for c in by_family["entry"]} == {2}  # unchanged: 2 presets, 1 variant
    assert [c[1] for c in by_family["entry_short"]] == [False, False]
    assert sorted(c[1] for c in by_family["entry_tb"]) == [False, False, True, True]
    assert {c[2] for c in by_family["entry_tb"]} == {4}  # 2 presets x 2 variants


def test_cli_without_the_flag_loads_no_evidence_index(tmp_path, monkeypatch):
    """The nightly chain calls `run_train_entry.py` bare — it must stay evidence-free."""
    seen: dict = {}

    monkeypatch.setattr(train_mod, "_load_panel", lambda tickers, start: _panel())
    monkeypatch.setattr(
        train_mod, "run_train_entry_all",
        lambda db, **kwargs: seen.update(kwargs) or [],
    )
    monkeypatch.setattr(sys, "argv", ["run_train_entry.py", "--db", str(tmp_path / "x.db")])
    assert main() == 0
    assert seen["evidence_index"] is None
```

- [x] **Step 2: Run the tests to verify they fail**

```bash
uv run python -m pytest tests/test_run_train_entry.py -q
```
Expected: the keyset assertion fails on the two new keys, and the new tests fail with `TypeError: run_train_entry() got an unexpected keyword argument 'evidence_index'`.

- [x] **Step 3: Implement**

In `scripts/run_train_entry.py`:

Add the import next to the other `equity_scout.ml` imports:

```python
from equity_scout.ml.evidence_features import (
    EVIDENCE_ACTIVE_COLUMN,
    EVIDENCE_FEATURE_COLUMNS,
    SHORT_WINDOW_DAYS,
    EvidenceIndex,
    load_evidence_index,
)
```

Add the constant below `FALLBACK_TICKERS`:

```python
# v15 P3: the evidence block trains as EXTRA challengers of THIS family only. entry_tb is the
# safe host: its champion is read for `barrier_config` alone (api.py, run_notify.py) and never
# scores anything, so a champion flip has no live scoring surface. entry/entry_short DO score
# live (strategies/ml_bot.py) and stay price-only until a live evidence feed exists.
EVIDENCE_FAMILY = "entry_tb"
```

Add the parameter to `run_train_entry`'s signature (after `n_candidates`):

```python
    n_candidates: int = 1,
    evidence_index: EvidenceIndex | None = None,
) -> dict:
```

Append to its docstring:

```
    `evidence_index` (additive, default None = the pre-P3 behaviour): when given, the backfill
    dataset carries `EVIDENCE_FEATURE_COLUMNS` on top of the price block. The promotion path is
    unchanged — the variant is just another challenger that must beat the same champion through
    `promote_if_better`; the caller is responsible for counting it in `n_candidates`.
```

Thread it into the dataset call:

```python
    X, y, meta = build_backfill_dataset(
        panel, tickers, benchmark=benchmark, horizon_days=horizon_days,
        label_direction=label_direction, barrier_config=tb_config,
        evidence_index=evidence_index,
    )
```

After `metrics["feature_means"] = ...`, add:

```python
    # v15 P3: recorded on EVERY run (empty/None when off) so a registry row always states which
    # feature set it was fitted on — an absent key would leave later readers guessing.
    metrics["evidence_features"] = (
        list(EVIDENCE_FEATURE_COLUMNS) if evidence_index is not None else []
    )
    # Coverage reality check: the share of training rows that actually carry an active cluster.
    # A feature set that is ~0 everywhere cannot beat the champion, and saying so up front is
    # cheaper than reading an AUC that never moved.
    metrics["evidence_coverage"] = (
        round(float((X[EVIDENCE_ACTIVE_COLUMN] > 0).mean()), 4)
        if evidence_index is not None
        else None
    )
```

After the existing `print(f"{label} v{version} ({model}) auf {n_train} Zeilen trainiert.")`:

```python
    if evidence_index is not None:
        coverage = metrics["evidence_coverage"]
        share = "n/a" if coverage is None else f"{coverage:.1%}".replace(".", ",")
        print(
            f"Evidence-Features aktiv ({len(EVIDENCE_FEATURE_COLUMNS)} Spalten): Anteil "
            f"Trainingszeilen mit Insider-Cluster in den letzten {SHORT_WINDOW_DAYS} Tagen: "
            f"{share}."
        )
```

In `run_train_entry_all`, add the parameter (after `barrier_config`):

```python
    barrier_config: BarrierConfig | None = None,
    evidence_index: EvidenceIndex | None = None,
) -> list[dict]:
```

Append to its docstring:

```
    `evidence_index` (v15 P3): when given, `EVIDENCE_FAMILY` (entry_tb) trains each preset TWICE
    — once price-only, once with the evidence block — and that family's `n_candidates` doubles
    accordingly. Twice as many presets competing for the same champion slot without a higher bar
    is exactly the noise-promotion hole `_min_auc_delta`'s sqrt(N) scaling exists to close. Other
    families are untouched: they score live, and no live evidence feed exists yet.
```

Replace the loop body:

```python
    tb_config = barrier_config if barrier_config is not None else BarrierConfig()
    family_horizon = {"entry": horizon_days, "entry_short": SHORT_HORIZON_DAYS}
    results = []
    for family in families:
        variants: tuple[EvidenceIndex | None, ...] = (None,)
        if evidence_index is not None and family == EVIDENCE_FAMILY:
            variants = (None, evidence_index)
        n_candidates = len(models) * len(variants)
        for variant in variants:
            for model in models:
                try:
                    results.append(
                        run_train_entry(
                            db_path, panel=panel, tickers=tickers, now=now, model=model,
                            benchmark=benchmark,
                            horizon_days=family_horizon.get(family, horizon_days),
                            family=family, barrier_config=tb_config,
                            n_candidates=n_candidates, evidence_index=variant,
                        )
                    )
                except Exception as err:  # noqa: BLE001 — a broken preset is a report, not a crash
                    print(f"Preset {family}/{model} fehlgeschlagen: {err}")
                    results.append(
                        {"version": None, "metrics": {}, "promoted": False, "model": model,
                         "family": family}
                    )
    return results
```

In `main()`, add the flag and thread it:

```python
    parser.add_argument(
        "--with-evidence",
        action="store_true",
        help=(
            "additionally train entry_tb challengers carrying the historical insider-cluster"
            " features (raises that family's multiple-testing candidate count accordingly)"
        ),
    )
```

```python
    evidence_index = load_evidence_index(args.db) if args.with_evidence else None
    run_train_entry_all(
        args.db, panel=panel, tickers=stock_tickers, now=now, models=models,
        families=families, horizon_days=args.horizon, evidence_index=evidence_index,
    )
```

- [x] **Step 4: Full gate + commit**

```bash
uv run python -m pytest -q && uv run ruff check .
```
Expected: `1748 passed`, `All checks passed!`.

```bash
git add scripts/run_train_entry.py tests/test_run_train_entry.py
git commit -m "feat(ml): train evidence-featured entry_tb challengers with honest candidate count"
```

---

### Task 5: `scripts/run_evidence_refresh.py` — resolution-gated refresh

**Files:** Create `scripts/run_evidence_refresh.py`, `tests/test_run_evidence_refresh.py`.

- [x] **Step 1: Write the failing tests**

Create `tests/test_run_evidence_refresh.py`:

```python
"""Refresh-runner tests: the resolve loop is the clock, the registry gate is the judge."""
from __future__ import annotations

import sys
from collections.abc import Callable

from equity_scout.ml.evidence_features import EvidenceIndex
from equity_scout.ml.prediction_ledger import (
    due_predictions,
    log_predictions,
    resolve_prediction,
)
from equity_scout.state_storage import get_state, set_state
from scripts.run_evidence_refresh import (
    DEFAULT_MIN_NEW_RESOLUTIONS,
    MULTIPLICITY_NOTE,
    WATERMARK_KEY,
    main,
    run_evidence_refresh,
)

NOW = "2026-01-01T00:00:00+00:00"
LATER = "2026-03-01T00:00:00+00:00"
EMPTY = EvidenceIndex({})


def _seed_resolved(db: str, n: int) -> None:
    """`n` RESOLVED predictions — the only clock the runner reads."""
    scored = [(f"T{i:04d}", 60, {}) for i in range(n)]
    log_predictions(db, model_version=1, scored=scored, now=NOW, horizon_days=20)
    for pred in due_predictions(db, LATER):
        resolve_prediction(db, pred["id"], realized_relative_return=0.01, resolved_at=LATER)


def _train_spy(calls: list) -> Callable[[EvidenceIndex], list[dict]]:
    def _train(index: EvidenceIndex) -> list[dict]:
        calls.append(index)
        return [
            {"version": 7, "metrics": {}, "promoted": False},
            {"version": 8, "metrics": {}, "promoted": True},
        ]

    return _train


def test_below_the_minimum_nothing_is_re_evaluated(tmp_path):
    db = str(tmp_path / "es.db")
    _seed_resolved(db, DEFAULT_MIN_NEW_RESOLUTIONS - 1)
    calls: list = []
    result = run_evidence_refresh(
        db, apply=True, train=_train_spy(calls), load_index=lambda _: EMPTY
    )
    assert result["triggered"] is False
    assert result["new_resolutions"] == DEFAULT_MIN_NEW_RESOLUTIONS - 1
    assert calls == []  # no trial spent
    assert get_state(db, key=WATERMARK_KEY) is None  # watermark untouched


def test_dry_run_triggers_but_writes_nothing(tmp_path):
    db = str(tmp_path / "es.db")
    _seed_resolved(db, DEFAULT_MIN_NEW_RESOLUTIONS)
    calls: list = []
    result = run_evidence_refresh(
        db, apply=False, train=_train_spy(calls), load_index=lambda _: EMPTY
    )
    assert result["triggered"] is True
    assert result["applied"] is False
    assert calls == []
    assert get_state(db, key=WATERMARK_KEY) is None


def test_apply_trains_reports_the_gate_verdict_and_advances_the_watermark(tmp_path):
    db = str(tmp_path / "es.db")
    _seed_resolved(db, DEFAULT_MIN_NEW_RESOLUTIONS + 5)
    calls: list = []
    result = run_evidence_refresh(
        db, apply=True, train=_train_spy(calls), load_index=lambda _: EMPTY
    )
    assert result["applied"] is True
    assert len(calls) == 1
    assert result["n_candidates"] == 2
    assert result["promoted"] == [8]
    assert get_state(db, key=WATERMARK_KEY) == str(DEFAULT_MIN_NEW_RESOLUTIONS + 5)


def test_a_second_run_without_new_resolutions_refuses(tmp_path):
    """The watermark is what makes this a trigger and not a nightly noise generator."""
    db = str(tmp_path / "es.db")
    _seed_resolved(db, DEFAULT_MIN_NEW_RESOLUTIONS)
    calls: list = []
    run_evidence_refresh(db, apply=True, train=_train_spy(calls), load_index=lambda _: EMPTY)
    second = run_evidence_refresh(
        db, apply=True, train=_train_spy(calls), load_index=lambda _: EMPTY
    )
    assert second["new_resolutions"] == 0
    assert second["triggered"] is False
    assert len(calls) == 1


def test_corrupt_watermark_re_triggers_instead_of_blocking(tmp_path):
    db = str(tmp_path / "es.db")
    _seed_resolved(db, DEFAULT_MIN_NEW_RESOLUTIONS)
    set_state(db, key=WATERMARK_KEY, value="not-a-number")
    result = run_evidence_refresh(
        db, apply=False, train=_train_spy([]), load_index=lambda _: EMPTY
    )
    assert result["watermark"] == 0
    assert result["triggered"] is True


def test_cli_prints_the_refusal_and_the_multiplicity_note(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "es.db")
    _seed_resolved(db, 1)
    monkeypatch.setattr(sys, "argv", ["run_evidence_refresh.py", "--db", db])
    assert main() == 0
    out = capsys.readouterr().out
    assert "Kein Refresh" in out
    assert MULTIPLICITY_NOTE in out
    assert "belegbar" not in out  # honesty guardrail: a gate is never a proof
```

- [x] **Step 2: Run the tests to verify they fail**

```bash
uv run python -m pytest tests/test_run_evidence_refresh.py -q
```
Expected: collection error — `ModuleNotFoundError: No module named 'scripts.run_evidence_refresh'`.

- [x] **Step 3: Implement**

Create `scripts/run_evidence_refresh.py`:

```python
"""Re-evaluate the evidence-featured entry_tb challengers once the resolve loop has produced
enough NEW real resolutions — the v15 P3 learning trigger.

This is a TRIGGER, not a gate and not a model. It only decides WHEN to spend a trial; the work
goes to the existing training path (`run_train_entry_all`, families=("entry_tb",)) whose registry
gate (`ml/model_registry.promote_if_better`) remains the sole promotion path. A champion still has
to clear MIN_OOS_N out-of-sample rows, the no-edge band around AUC 0.5, and an AUC delta scaled by
sqrt(number of candidates tested against it tonight).

Why a trigger at all: nightly retrains are nightly trials against the same OOS metric, and the
training set only moves when new market history arrives. Re-running on every chain execution buys
nothing but extra draws from the same noise — the same reason `_min_auc_delta` scales with the
candidate count. The Wave-1 resolve loop (first real resolutions from 2026-08-11) is the honest
clock: `resolved_stats(db)["n_resolved"]` counts the predictions the world has actually judged.

Dry-run default; `--apply` is what registers challengers and advances the watermark. Network only
in main() (the price panel), `now` injected, so the tests run offline.

Usage:
    python scripts/run_evidence_refresh.py [--db equity_scout.db]
        [--min-new-resolutions 30] [--apply]
"""
from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.ml.evidence_features import EvidenceIndex, load_evidence_index
from equity_scout.ml.prediction_ledger import resolved_stats
from equity_scout.state_storage import get_state, set_state

WATERMARK_KEY = "evidence_refresh_resolved_watermark"

# The repo's standing minimum-evidence unit before it will rule on anything:
# `historical_study.DEFAULT_MIN_CELL_N` is 30 measurements per split side, and the arena's
# promotion gate wants >= 30 trades. This is a TRIGGER threshold, not a statistical test — the
# statistical bar stays MIN_OOS_N / the AUC delta inside `promote_if_better`.
DEFAULT_MIN_NEW_RESOLUTIONS = 30

MULTIPLICITY_NOTE = (
    "Multiples Testen: jeder Lauf stellt mehrere Presets demselben Champion gegenüber. Die "
    "AUC-Hürde steigt deshalb mit sqrt(Kandidatenzahl) — bei reinem Zufall wäre der beste von "
    "N Versuchen ohnehin der beste. Ein Champion-Wechsel heißt: Gate genommen. Er ist kein "
    "Nachweis eines Vorteils und keine Kauf-/Verkaufsempfehlung."
)


def _watermark(db_path: str) -> int:
    """The `n_resolved` reading at the last applied refresh. A corrupted value reads as 0 so the
    loop re-triggers — an unparsable watermark must never silently block learning forever."""
    raw = get_state(db_path, key=WATERMARK_KEY)
    if raw is None:
        return 0
    try:
        return int(raw)
    except ValueError:
        return 0


def run_evidence_refresh(
    db_path: str,
    *,
    min_new_resolutions: int = DEFAULT_MIN_NEW_RESOLUTIONS,
    apply: bool = False,
    train: Callable[[EvidenceIndex], list[dict]],
    load_index: Callable[[str], EvidenceIndex] = load_evidence_index,
) -> dict:
    """Trigger check, then (only with `apply`) one evidence-featured entry_tb training round.

    `train` and `load_index` are injected seams so the tests never touch the network or fit a
    model. Nothing is written below the threshold and nothing is written on a dry run — in
    particular the watermark advances ONLY after `train` returned, so a crashed run re-triggers
    instead of silently consuming its own trigger.

    No `now` parameter on purpose: this function reads a COUNT, not a clock. `now` is threaded
    where it is actually used — main() computes it and the `train` closure hands it to
    `run_train_entry_all`, which stamps the registry rows.
    """
    n_resolved = int(resolved_stats(db_path)["n_resolved"])
    watermark = _watermark(db_path)
    new_resolutions = max(n_resolved - watermark, 0)
    result = {
        "n_resolved": n_resolved,
        "watermark": watermark,
        "new_resolutions": new_resolutions,
        "min_new_resolutions": min_new_resolutions,
        "triggered": new_resolutions >= min_new_resolutions,
        "applied": False,
        "n_candidates": 0,
        "promoted": [],
    }
    if not result["triggered"] or not apply:
        return result
    results = train(load_index(db_path))
    result["n_candidates"] = len(results)
    result["promoted"] = [r["version"] for r in results if r.get("promoted")]
    set_state(db_path, key=WATERMARK_KEY, value=str(n_resolved))
    result["applied"] = True
    return result


def _summary(result: dict) -> str:
    """German one-paragraph verdict. Never claims an edge: a promotion is a passed gate."""
    if not result["triggered"]:
        return (
            f"Kein Refresh: {result['new_resolutions']} neue aufgelöste Vorhersage(n) seit dem "
            f"letzten Lauf (Wasserstand {result['watermark']}, aktuell {result['n_resolved']}) — "
            f"Minimum ist {result['min_new_resolutions']}. Nichts neu bewertet, Champion "
            "unverändert."
        )
    if not result["applied"]:
        return (
            f"Trockenlauf: {result['new_resolutions']} neue aufgelöste Vorhersage(n) "
            f"(Minimum {result['min_new_resolutions']}). Mit --apply würden die "
            "entry_tb-Herausforderer mit und ohne Evidence-Features neu bewertet. Nichts "
            "geschrieben, Wasserstand unverändert."
        )
    lead = (
        f"{result['n_candidates']} entry_tb-Herausforderer gegen denselben Champion bewertet; "
        f"Wasserstand auf {result['n_resolved']} gesetzt."
    )
    if not result["promoted"]:
        return lead + " Kein Champion-Wechsel — keiner hat die Hürde des Registry-Gates genommen."
    versions = ", ".join(f"v{v}" for v in result["promoted"])
    return lead + f" Champion-Wechsel: {versions} hat die Hürde des Registry-Gates genommen."


def _train_entry_tb(db_path: str, *, now: str, evidence_index: EvidenceIndex) -> list[dict]:
    """Network path: reuse run_train_entry's OWN universe/panel helpers, so this runner can never
    train on a different panel than the nightly chain does. Lazy import keeps sklearn/catboost and
    the network out of import time and out of the tests."""
    from scripts.run_train_entry import (
        BENCHMARK,
        _load_panel,
        _resolve_tickers,
        run_train_entry_all,
    )

    tickers = _resolve_tickers(db_path, None)
    panel = _load_panel(list(dict.fromkeys(tickers + [BENCHMARK])), "2007-01-01")
    return run_train_entry_all(
        db_path, panel=panel, tickers=tickers, now=now,
        families=("entry_tb",), evidence_index=evidence_index,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--min-new-resolutions", type=int, default=DEFAULT_MIN_NEW_RESOLUTIONS,
        help="how many newly RESOLVED predictions must have arrived since the last refresh",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="write: register/promote the challengers and advance the watermark",
    )
    args = parser.parse_args()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = run_evidence_refresh(
        args.db, min_new_resolutions=args.min_new_resolutions, apply=args.apply,
        train=lambda index: _train_entry_tb(args.db, now=now, evidence_index=index),
    )
    print(_summary(result))
    print(MULTIPLICITY_NOTE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 4: Run the module tests**

```bash
uv run python -m pytest tests/test_run_evidence_refresh.py -q
```
Expected: `6 passed`.

- [x] **Step 5: Full gate + commit**

```bash
uv run python -m pytest -q && uv run ruff check .
```
Expected: `1754 passed`, `All checks passed!`.

```bash
git add scripts/run_evidence_refresh.py tests/test_run_evidence_refresh.py
git commit -m "feat(ml): resolution-gated evidence refresh runner"
```

---

### Task 6: Live coverage check + Outcome

**Files:** Modify `docs/superpowers/plans/2026-08-07-v15-p3-evidence-learning.md` (this file's Outcome).

**Purpose:** measure before believing. The 27,681 backfilled insider clusters span the whole US market; the entry panel's universe is the current watchlist. If almost no training row carries an active cluster, the feature set is dead on arrival and the honest move is to say so — not to read an unchanged AUC as a subtle result.

- [x] **Step 1: Confirm the store is populated and see the raw overlap**

```bash
uv run python -c "
import sqlite3
c = sqlite3.connect('file:equity_scout.db?mode=ro', uri=True)
print('insider clusters:', c.execute(
    \"SELECT COUNT(*), COUNT(DISTINCT ticker) FROM historical_events WHERE source='insider'\"
).fetchone())
print('t0 range:', c.execute(
    \"SELECT MIN(t0), MAX(t0) FROM historical_events WHERE source='insider'\"
).fetchone())
"
```
Expected: ~27,681 clusters over several thousand distinct tickers, t0 range ~2006-01 → 2026-06.

- [x] **Step 2: One evidence training run on the real panel (single preset, entry_tb only)**

```bash
uv run python scripts/run_train_entry.py --family entry_tb --model random_forest --with-evidence
```
Expected: two blocks (plain + evidence variant), each printing `Triple-Barrier-Entry-Modell vN (random_forest) auf …`, the evidence block additionally printing `Evidence-Features aktiv (3 Spalten): Anteil Trainingszeilen mit Insider-Cluster in den letzten 91 Tagen: X,X%`, and `Als Champion übernommen: …` for both. Record X,X% — that number is the finding.

**Interpretation rule (binding, write it into the Outcome as measured):**
- coverage < 2% → the feature set cannot move an AUC; report it as a measured dead end and stop. Do NOT tune windows to chase coverage (that is the multiple-testing hole in another costume).
- coverage ≥ 2% and no promotion → the honest, expected default. Report the AUC delta and the hurdle it failed against.
- promotion → report the version, the AUC, `n_oos`, and the hurdle it cleared (`0.01 * sqrt(n_candidates)`), with the multiplicity note. Never as a demonstrated edge.

- [x] **Step 3: Refresh-runner dry run against the live ledger**

```bash
uv run python scripts/run_evidence_refresh.py
```
Expected today (first resolutions land 2026-08-11): `Kein Refresh: 0 neue aufgelöste Vorhersage(n) … Minimum ist 30.` plus the multiplicity note. That refusal IS the correct current behaviour — record it.

- [x] **Step 4: Full gate, fill the Outcome, commit**

```bash
uv run python -m pytest -q && uv run ruff check .
```
Expected: `1754 passed`, `All checks passed!`.

Fill this plan's `## Outcome` with: the cluster count/ticker overlap, the measured `evidence_coverage`, the two AUCs and whether the gate flipped, the refresh runner's live refusal line, and any deviation from the plan.

```bash
git add docs/superpowers/plans/2026-08-07-v15-p3-evidence-learning.md
git commit -m "docs(ml): v15 P3 outcome — evidence-feature coverage and first gated run"
```

---

## Expected proof

After Task 6 the repo can answer, from tests and one command each:
1. Do the evidence features exist and are they point-in-time? — `tests/test_evidence_features.py`, including the r_*-leakage regression.
2. Can a model with a different feature set silently score a NaN row? — no, `EntryModel.score_row` raises.
3. Did the nightly chain change? — no: `run_train_entry.py` without `--with-evidence` is byte-for-byte the old behaviour (`test_default_call_is_unchanged_by_the_additive_evidence_param`, `test_cli_without_the_flag_loads_no_evidence_index`).
4. Can extra challengers swap the champion more easily? — no: `n_candidates` doubles for entry_tb, so the AUC hurdle rises with it.
5. What is the measured overlap between the insider store and the training universe? — the `evidence_coverage` number in the Outcome.

**A null result is the expected default and a valid outcome.** entry_tb has been champion-less for 28 nightly versions; three features on a small coverage share are unlikely to change that. Reporting "the features are live, measured, and did not clear the hurdle" is the deliverable — the plan fails only if it reports something it did not measure.

---

## Self-Review against the spec and the controller rulings

Checked before hand-off; issues found were fixed inline in the tasks above.

| Requirement | Where | Verdict |
|---|---|---|
| (a) Evidence features from `historical_events` into the EXISTING entry_tb path, behind existing seams | Tasks 1/3/4 — additive params only, `build_backfill_dataset` + `run_train_entry` unchanged by default | ✅ |
| No new model class, no new training loop | Task 4 reuses `run_train_entry`/`run_train_entry_all` verbatim; no new family | ✅ |
| Existing time-split + honesty gate | `walk_forward_evaluate` and `promote_if_better` untouched; only `n_candidates` rises | ✅ |
| (b) Resolution-driven refresh, ledger-gated | Task 5; watermark on `resolved_stats["n_resolved"]`, promotion delegated to `promote_if_better` | ✅ (see clarification below) |
| Champion changes only if the hurdle clears; do not fork ledger mechanics | Ruling 7 | ⚠️ **Clarified, flag for Nico:** the controller said "reuse ml/ledger mechanics". `ml/ledger.py` is the DSR ledger for `MetaConfig` strategy trials (deflated Sharpe over backtest returns) — a different object with a different metric. The entry family's champion mechanic is `model_registry.promote_if_better` with `_min_auc_delta(n) = 0.01 * sqrt(n)`, the same best-of-N logic. Forcing entry models into `ml/ledger` would have been the fork. Reused `promote_if_better` untouched. |
| Congress = feature-selection kill with the numbers | Non-Goals, first bullet, all five horizons with stderr and validate hit rates | ✅ |
| No capital / broker / frontend surface | Non-Goals; file map lists only ml/, scripts/, tests/, this doc | ✅ |
| No file overlap with the parallel session | Coordination section; cross-checked `st_session.py`, `alpaca_*.py`, `run_shortterm.py`, `PLAN.md`, `frontend/` against the file map | ✅ |
| Deterministic tests, no network, LLM never scores | Every test uses in-memory panels / tmp DBs / injected seams; no LLM anywhere in this plan | ✅ |
| Leakage discipline; features knowable at t0 | Rulings 4/5, enforced by `test_future_and_same_day_clusters_are_invisible` and `test_forward_returns_can_never_reach_a_feature` | ✅ |
| PIT lesson from P2a (filing dates, not transaction dates) | `t0` is the cluster's LAST FILING date by construction (`backfill_form4.py:460`); the plan never touches `first_transaction_date` | ✅ |
| Decision 11 caveat (panel rows ≠ sessions) | Ruling 3 — calendar windows, documented in the module docstring | ✅ |
| Multiplicity wording reuses direction-agreement / expected-spurious framing; never "belegbar" | `MULTIPLICITY_NOTE` + Task 6 interpretation rule; `test_cli_prints_the_refusal_and_the_multiplicity_note` asserts "belegbar" is absent | ✅ |
| 5–7 tasks, YAGNI | 6 tasks: 3 features + 1 guard + 1 threading + 1 runner + 1 verification | ✅ |
| Every task: complete code, exact paths, exact commands, expected output, explicit-path commit, gate first | All six | ✅ |

**Deliberate deviations from the controller's brief, for Nico's veto:**

1. **No study-fitted prior feature** (controller example list said "insider short-horizon prior from the study"). Reason: the study was fit over the full 2006→2026 span, so a per-band prior injected as a column is look-ahead for every training row inside that span — it would violate the leakage guardrail the same brief imposes. The study's role here is feature SELECTION (insider in, congress out) and window CHOICE (r_3m → 91 days). A point-in-time expanding prior is a genuine v2 candidate; it is not v1. **If Nico wants the prior in v1 anyway, the honest version is a separate task computing an expanding mean over events fully resolved before each `as_of` — roughly one extra task, and it should be planned as such, not smuggled in.**
2. **Task 2 (`score_row` guard) is not literally "features + gated refresh".** It is 6 lines plus a test, and it closes the single path by which this plan's own output (a model with a different feature set) could fabricate a score. Cut it and the plan ships a silent-NaN hazard; keeping it is cheaper than the incident.

**Known limitation, stated up front:** the evidence features are training-side only. Live scoring (`entry`/`entry_short` via `ml_bot.py`) has no evidence feed, because the `historical_events` form4 walk is a manual quarterly batch job (cursor at `2026q2`), not a nightly collector. `entry_tb` is chosen precisely because its champion never scores anything, so no train/serve skew can arise. Wiring evidence into a live-scoring family requires a nightly cluster feed first — that is P2's job, not this plan's.

---

## Outcome

**Executed 2026-08-09/10 (Fable-Session, subagent-driven, two-stage review per task). All 6 tasks done, gate green throughout (final: 1856 passed, ruff clean).**

### Live measurement (Task 6, 2026-08-10 early morning)

- Store probe: **27,681 insider clusters over 7,053 distinct tickers**, t0 range 2006-01-03 → 2026-06-30. entry_tb registry before the run: 40 versions, **0 champions**.
- Real training run (`--family entry_tb --model random_forest --with-evidence`, panel of 27 usable tickers after the 30%-span exclusions INSW/LPG/BBSE3.SA):
  - plain v122: OOS AUC **0.4713**, Brier 0.2538, Rank-IC 0.0305, WFE -0.1486 (n_oos=3834, 4 splits) → not promoted.
  - evidence v123: OOS AUC **0.4743**, Brier 0.2522, Rank-IC 0.0446, WFE -0.1319 (same n_oos) → not promoted.
  - **evidence_coverage_91d = 2.5%** (printed: "Anteil Trainingszeilen mit Insider-Cluster in den letzten 91 Tagen: 2,5%"), **7 von 27 Trainings-Tickern** with an active cluster window.
- Interpretation per the binding rule: coverage ≥ 2% and no promotion → **the honest, expected default**. AUC delta of the evidence variant over plain: **+0.0030**; the hurdle it failed is the ABSOLUTE bootstrap bar (empty champion slot: n_oos ≥ 200 and AUC ≥ 0.55) — the sqrt(N) delta never came into play because no champion exists. The features are live, measured, and did not clear the hurdle. That is the deliverable.
- Refresh runner dry run against the live ledger: `Kein Refresh: 0 neue aufgelöste Vorhersage(n) … Minimum ist 30.` + multiplicity note, exit 0 — the correct refusal (first real resolutions expected from 2026-08-11/12).

### Deviations from the plan text (all review-driven, each its own commit)

- Task 1 hardening after Opus review (`6dd40e7`): tz-aware/None `as_of` raises; loader no longer creates schema (missing table → ValueError, empty insider partition → loud warning); malformed rows counted + reported; `features()` keys single-sourced from `EVIDENCE_FEATURE_COLUMNS`; strict `isinstance(n_insiders, int)`; 13 module tests (plan: 9).
- Task 2 addition (`dee2873`): the guard test's `match` pinned to "fitted on" — sklearn's own NaN ValueError contains "missing", so the plan's match would stay green with the guard deleted.
- Task 3 addition (`48374db`): module docstring de-contradicted, `FEATURE_COLUMNS`∩`EVIDENCE_FEATURE_COLUMNS`=∅ test, NaN-raise after X construction (training-side mirror of the Task-2 guard).
- Task 4 (`24332ad`): metrics key renamed **`evidence_coverage` → `evidence_coverage_91d`** (the number counts only the 91d flag; rows with ANY ev_* signal are ~4x higher — plan lines 1250/1266 still say the old name, this Outcome uses the new one). `--with-evidence` fails fast before the panel fetch; per-run sqrt(N) caveat documented. Plus one report-only print line (active tickers vs. total).
- **Registry gate tightened outside the plan's file map** (`88fe531`, wording `d0a4df3`): `_no_edge` is now one-sided — an anti-predictive model (AUC ≤ 0.45) can no longer bootstrap an empty champion slot. Rationale: symmetric band + empty entry_tb slot + doubled draws made a fake first champion the single most likely bad outcome of this plan; call-site survey confirmed auc-only, higher-is-better everywhere. The bar was raised, never lowered.
- Task 5 (`6d37a6d`, `f426416`): crash honesty (all-crashed presets no longer reported as "evaluated", watermark not burned, exit 1 on a triggered --apply run that evaluated nothing); module docstring de-overclaimed (the resolution count is a PROXY for elapsed market information — the daily chain logs ~30 predictions per weekday, so after the resolve loop warms up nearly every day clears the minimum; a panel-`as_of` clock is the honest v2); MULTIPLICITY_NOTE states both promotion regimes (bootstrap = absolute bar only); `--min-new-resolutions` floor ≥ 1; 9 module tests (plan: 6).

### Findings for Nico (plan-level, not fixed in code)

1. **Non-US structural zeros:** 13 of 31 panel tickers trade outside the Form-4 regime (NSE/Tokio/ASX/B3/LSE/Euronext) — for them `ev_* = 0` encodes "no disclosure regime", not "no insider buying". A tree splitting on the evidence block partly learns a jurisdiction dummy. Mitigations in place: the absolute 0.55 bootstrap bar (a confound would have to be strongly predictive OOS), `feature_importance` recorded per registry row, and this documentation. The clean v2 fix is a US-regime-only training universe or an explicit regime column — Nico's call.
2. **Low discriminating power:** at 2.5% coverage (172-ish active rows of ~6.3-7k), any AUC delta rides on very few rows; this experiment can realistically only produce a null on this universe. A US-heavy universe (the store spans 7,053 tickers!) would give the same features real support — v2 decision.
3. **Trigger clock:** see Task-5 deviation — consider a panel-`as_of`-based clock in v2.
4. **Surfaces (M2):** evidence variants are indistinguishable in `/api/model/history` and ModelPanel (fixed field list; `api.py` currently owned by the parallel cockpit session). Follow-up wiring wanted.
5. **Cosmetics (M3):** `run_train_entry_all` returns three result-dict shapes (success/empty/crash); consumers today are tests only.
