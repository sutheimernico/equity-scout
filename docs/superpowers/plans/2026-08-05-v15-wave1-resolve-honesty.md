# Vision v15 — Wave 1: Resolve Honesty Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the predict-then-resolve loop measure honestly: due-gate in trading days, a column-wise price panel that cannot shift measurement windows, and a resolver that reports *why* nothing resolved instead of a mute "0".

**Architecture:** Three surgical fixes in the existing resolution path (`ml/prediction_ledger.py` stamps, `scripts/run_resolve_predictions.py` measures) plus a one-off re-stamp of the 299 open ledger rows. No schema changes, no new tables. The ledger stays append-only; resolved rows are never touched.

**Tech Stack:** Python 3 (uv), pandas, SQLite, pytest. Gate: `uv run pytest -q` green + `uv run ruff check .` clean before every commit.

**Deadline:** Must land before the nightly chain of **Mon 2026-08-10** — that run produces the first physically observable resolutions, and without Task 2 they would be measured on a common-range-trimmed panel (silently wrong for global tickers).

**Coordination:** A parallel autopilot session owns `st_session.py`, `alpaca_*.py`, `scripts/run_shortterm.py`, `PLAN.md`, `frontend/`. This plan touches none of those files. Before starting, confirm the other session is idle (`git log -1 --format=%cd` older than ~15 min) or at least commit only the files listed per task (`git add <explicit paths>`, never `-A`). Do NOT edit `PLAN.md` while the other strand is active — the v15 section in `PLAN.md` is added later.

**Background (root cause, diagnosed 2026-08-05):**
1. `log_predictions` stamps `resolve_after = created_at + horizon_days` **calendar** days, but `forward_return` (ml/entry_eval.py:31) counts **trading** days (index positions). 20 trading days ≈ 28 calendar days → every prediction turns "due" ~8 days before its window is observable. 299 rows sat "due but unmeasurable"; the resolver printed "Aufgelöst: 0" for 26 days.
2. `_fetch_price_panel` is the only resolver sibling using `load_etf_panel` → `clean_panel` (common-range trim + `dropna(how="any")`). Prediction tickers are global (`5101.T`, `CQR.AX`, `PETR4.SA`, …) — one young ticker truncates ALL histories. Siblings (`run_resolve_evidence.py`, `run_resolve_events.py`, `run_person_scores.py`) all use `load_price_history` (column-wise).
3. `_realized_relative_return` takes the first panel date ≥ `created_at` without checking the panel actually reaches back that far — a late-starting panel silently measures a **shifted window** (replicated: 2.3pp difference on a random walk).
4. The no-op path (`if rel is None: continue`) has no counter — "0 resolved" cannot be told apart from "0 due".

---

### Task 1: Due-gate in trading-day terms

**Files:**
- Modify: `src/equity_scout/ml/prediction_ledger.py` (function `log_predictions`, ~line 55)
- Test: `tests/test_prediction_ledger.py`

- [x] **Step 1: Write the failing regression test**

In `tests/test_prediction_ledger.py`, first adjust the constants block (~lines 16-19): the old `AFTER` encodes the buggy semantics. Change:

```python
AFTER = "2026-02-01T00:00:00+00:00"   # old: > NOW + 20 calendar days (2026-01-21)
```

to:

```python
# 20 trading days after 2026-01-01 is 2026-01-29; resolve_after over-estimates that as
# NOW + ceil(20*7/5)+4 = 32 calendar days = 2026-02-02. AFTER must lie beyond it.
AFTER = "2026-02-10T00:00:00+00:00"
```

Then append the regression test (reusing the file's existing `_scored()` helper and `NOW`/`HORIZON` constants):

```python
def test_due_gate_waits_for_the_trading_day_horizon_not_calendar_days(tmp_path):
    """Regression 2026-08-05: resolve_after was created_at + horizon CALENDAR days, but
    resolution measures horizon TRADING days (~1.4x longer). 299 rows were 'due' and
    physically unmeasurable for 26 days while the resolver mutely printed 'Aufgelöst: 0'."""
    db = str(tmp_path / "led.db")
    log_predictions(db, model_version=1, scored=_scored(), now=NOW, horizon_days=HORIZON)
    # Old semantics made these due at NOW + 20 calendar days (2026-01-21).
    assert due_predictions(db, "2026-01-22T00:00:00+00:00") == []
    assert len(due_predictions(db, "2026-02-10T00:00:00+00:00")) == len(_scored())
```

- [x] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_prediction_ledger.py -q`
Expected: the new test FAILS on the first assert (rows are already due on 2026-01-22 under the old stamping). Some pre-existing tests referencing `AFTER` may fail too until Step 3 — that is expected and part of the same semantic change.

- [x] **Step 3: Implement the trading-day stamp**

In `src/equity_scout/ml/prediction_ledger.py` (module already imports `math` — if not, add `import math` to the stdlib import block), add above `log_predictions`:

```python
# `horizon_days` counts TRADING days (forward_return counts index positions). 20 trading
# days span ~28 calendar days; the buffer covers holidays and the one-session lag of
# trim_to_completed_sessions (the running session is never in the panel).
RESOLVE_BUFFER_DAYS = 4


def _resolve_after(now: str, horizon_days: int) -> str:
    """The TRADING-day horizon as a calendar date — deliberately late, never early."""
    calendar_days = math.ceil(horizon_days * 7 / 5) + RESOLVE_BUFFER_DAYS
    return (datetime.fromisoformat(now) + timedelta(days=calendar_days)).isoformat()
```

In `log_predictions`, replace:

```python
    """Append one open prediction per scored entry. `resolve_after = now + horizon_days` CALENDAR
    days — a deliberate over-estimate of the trading-day horizon, so a prediction is never resolved
    before its full forward window has actually elapsed. `now` is injected (no wall clock here)."""
    init_ledger_db(db_path)
    resolve_after = (datetime.fromisoformat(now) + timedelta(days=horizon_days)).isoformat()
```

with:

```python
    """Append one open prediction per scored entry. `resolve_after` converts the TRADING-day
    horizon to calendar days (~1.4x) plus a buffer, so `due` can never fire before the forward
    window is observable. `now` is injected (no wall clock here)."""
    init_ledger_db(db_path)
    resolve_after = _resolve_after(now, horizon_days)
```

- [x] **Step 4: Run the module tests, fix remaining date constants**

Run: `uv run pytest tests/test_prediction_ledger.py -q`
Expected: PASS. If any other test in this file still fails, its hardcoded date encodes the old 20-calendar-day semantics — shift that date past `NOW + 32 days` with a one-line comment, same as `AFTER`. Do not weaken asserts.

- [x] **Step 5: Run the full gate and commit**

Run: `uv run pytest -q && uv run ruff check .`
Expected: green/clean. (`tests/test_run_resolve_predictions.py` uses its own `now` far past creation — unaffected.)

```bash
git add src/equity_scout/ml/prediction_ledger.py tests/test_prediction_ledger.py
git commit -m "fix(ml): stamp resolve_after in trading-day calendar terms"
```

---

### Task 2: Column-wise panel, lead-in, and no shifted windows

**Files:**
- Modify: `scripts/run_resolve_predictions.py` (`_realized_relative_return`, `run_resolve_predictions`, `_fetch_price_panel`)
- Test: `tests/test_run_resolve_predictions.py`

- [x] **Step 1: Write the two failing tests**

Append to `tests/test_run_resolve_predictions.py` (module already imports `pd`, `PricePanel`, the resolver module — match the file's existing import alias, called `resolve_mod` below; add `import pytest` if absent):

```python
def test_panel_that_starts_after_created_at_resolves_to_none():
    """A panel whose first row lies AFTER the prediction date must not silently measure a
    shifted window (regression 2026-08-05: clean_panel/young tickers moved the panel start)."""
    truncated = PricePanel(_panel().closes.loc[pd.Timestamp("2026-01-20"):])
    assert resolve_mod._realized_relative_return(
        truncated, "AAA", "2026-01-05T00:00:00+00:00", 20
    ) is None


def test_price_panel_loader_is_column_wise(monkeypatch):
    """Prediction tickers are global (5101.T, CQR.AX, PETR4.SA) — the common-range trim of
    load_etf_panel/clean_panel would cut every history at the youngest ticker's first bar."""
    import equity_scout.data.etf_panel as panel_mod
    seen = {}
    monkeypatch.setattr(
        panel_mod, "load_price_history",
        lambda tickers, **kw: seen.update(kw) or PricePanel(pd.DataFrame()),
    )
    monkeypatch.setattr(
        panel_mod, "load_etf_panel",
        lambda *a, **k: pytest.fail("resolver must not use the common-range loader"),
    )
    resolve_mod._fetch_price_panel(["AAA", "SPY"], "2026-01-01")
    assert seen["snapshot"] == resolve_mod.RESOLVE_SNAPSHOT
    assert seen["refresh"] is True
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_run_resolve_predictions.py -q`
Expected: FAIL — the first returns a number (shifted window measured), the second dies with the `pytest.fail` (wrong loader).

- [x] **Step 3: Implement loader swap, lead-in, and guard**

In `scripts/run_resolve_predictions.py`, add near the other module constants:

```python
# Lead-in so the fetched panel always reaches back to the prediction day itself
# (created_at on a weekend/holiday, plus provider quirks at range starts).
PANEL_LEAD_IN_DAYS = 10
```

In `_realized_relative_return`, replace:

```python
    pair = closes[[ticker, BENCHMARK]].dropna()
    on_or_after = pair.index[pair.index >= _as_of_timestamp(created_at)]
    if len(on_or_after) == 0:
        return None
```

with:

```python
    pair = closes[[ticker, BENCHMARK]].dropna()
    as_of = _as_of_timestamp(created_at)
    if len(pair) == 0 or pair.index[0] > as_of:
        # Panel does not reach back to the prediction day: stay open rather than
        # silently measuring a shifted window.
        return None
    on_or_after = pair.index[pair.index >= as_of]
    if len(on_or_after) == 0:
        return None
```

In `run_resolve_predictions`, replace:

```python
        start = min(_as_of_timestamp(d["created_at"]) for d in due).date().isoformat()
```

with:

```python
        oldest = min(_as_of_timestamp(d["created_at"]) for d in due)
        start = (oldest - pd.Timedelta(days=PANEL_LEAD_IN_DAYS)).date().isoformat()
```

(ensure the script imports `pandas as pd`; add it to the import block if missing). In `_fetch_price_panel`, replace:

```python
    from equity_scout.data.etf_panel import load_etf_panel

    return load_etf_panel(tickers, start=start, snapshot=RESOLVE_SNAPSHOT, refresh=True)
```

with:

```python
    # Column-wise like every sibling resolver: prediction tickers are global, and one
    # young or gappy ticker must not truncate everyone else's history.
    from equity_scout.data.etf_panel import load_price_history

    return load_price_history(tickers, start=start, snapshot=RESOLVE_SNAPSHOT, refresh=True)
```

Keep the import lazy (inside the function) — tests monkeypatch the `etf_panel` module attributes and the lazy import keeps the network out of import time.

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_run_resolve_predictions.py -q`
Expected: PASS (existing tests too — their `_fetch` fake bypasses `_fetch_price_panel`, and their panels start well before the prediction dates).

- [x] **Step 5: Run the full gate and commit**

Run: `uv run pytest -q && uv run ruff check .`

```bash
git add scripts/run_resolve_predictions.py tests/test_run_resolve_predictions.py
git commit -m "fix(resolve): column-wise panel and refuse shifted measurement windows"
```

---

### Task 3: The no-op stops being mute

**Files:**
- Modify: `scripts/run_resolve_predictions.py` (`run_resolve_predictions`, `main`)
- Test: `tests/test_run_resolve_predictions.py`

- [x] **Step 1: Write the failing test**

Append to `tests/test_run_resolve_predictions.py`:

```python
def _windowed_fetch(panel: PricePanel, *, last_session: str):
    """Production-faithful seam: the real loader returns [start … last completed session].
    The original `_fetch` fake ignored both bounds and hid the 2026-08-05 bug."""
    def fetch(tickers: list[str], start: str) -> PricePanel:
        return PricePanel(panel.closes.loc[pd.Timestamp(start):pd.Timestamp(last_session)])
    return fetch


def test_due_prediction_without_full_forward_window_is_counted_not_swallowed(tmp_path):
    db = str(tmp_path / "led.db")
    log_predictions(
        db, model_version=1, scored=[("AAA", 80, {"mkt_vol": 0.1})],
        now="2026-01-05T00:00:00+00:00", horizon_days=20,
    )
    # resolve_after (trading-day stamp) = 2026-02-06; due at 2026-02-09, but the panel
    # ends 2026-01-30 — only 20 rows from Jan 5, forward_return needs pos+20 < len.
    result = run_resolve_predictions(
        db, now="2026-02-09T00:00:00+00:00",
        fetch_prices=_windowed_fetch(_panel(), last_session="2026-01-30"),
    )
    assert result["resolved"] == 0
    assert result["due"] == 1
    assert result["not_observable"] == 1
```

- [x] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_run_resolve_predictions.py -q`
Expected: FAIL with `KeyError: 'due'` (the result dict has no such key yet).

- [x] **Step 3: Implement counters and verbose output**

Replace `run_resolve_predictions` with this complete version (it includes Task 2's
lead-in lines — Task 3 builds on Task 2):

```python
def run_resolve_predictions(
    db_path: str,
    *,
    now: str,
    fetch_prices: Callable[[list[str], str], PricePanel],
) -> dict:
    """Resolve every due prediction against its realized forward relative return. Returns
    {resolved, due, not_observable, still_open}. still_open counts all predictions left
    open after this run — those not yet due, plus any due one whose forward window is not
    yet fully observable."""
    due = due_predictions(db_path, now)
    resolved = 0
    not_observable = 0
    if due:
        tickers = sorted({d["ticker"] for d in due} | {BENCHMARK})
        oldest = min(_as_of_timestamp(d["created_at"]) for d in due)
        start = (oldest - pd.Timedelta(days=PANEL_LEAD_IN_DAYS)).date().isoformat()
        panel = fetch_prices(tickers, start)
        for pred in due:
            rel = _realized_relative_return(
                panel, pred["ticker"], pred["created_at"], pred["horizon_days"]
            )
            if rel is None:
                not_observable += 1
                continue  # forward window not yet fully observable — resolve honestly later
            if resolve_prediction(
                db_path, pred["id"], realized_relative_return=rel, resolved_at=now
            ):
                resolved += 1
    return {
        "resolved": resolved,
        "due": len(due),
        "not_observable": not_observable,
        "still_open": resolved_stats(db_path)["n_open"],
    }
```

In `main()`, replace the print:

```python
    print(f"Aufgelöst: {result['resolved']} Vorhersage(n); noch offen: {result['still_open']}.")
```

with:

```python
    print(
        f"Aufgelöst: {result['resolved']} von {result['due']} fälligen Vorhersage(n)"
        f" ({result['not_observable']} ohne volles Vorwärtsfenster);"
        f" noch offen: {result['still_open']}."
    )
```

- [x] **Step 4: Run tests, update the output assertion**

Run: `uv run pytest tests/test_run_resolve_predictions.py -q`
Expected: the new test PASSES; the existing `capsys` test fails on the old output string. Update its expected string to the new format (keep its scenario values — with a fully observable panel it reads `Aufgelöst: N von N fälligen Vorhersage(n) (0 ohne volles Vorwärtsfenster); noch offen: M.`), then re-run until PASS.

- [x] **Step 5: Run the full gate and commit**

Run: `uv run pytest -q && uv run ruff check .`

```bash
git add scripts/run_resolve_predictions.py tests/test_run_resolve_predictions.py
git commit -m "feat(resolve): count and report unobservable forward windows"
```

---

### Task 4: Re-stamp the 299 open rows + live verification

**Files:**
- Create: `scripts/fix_resolve_after_2026_08_05.py`

- [x] **Step 1: Write the one-off repair script**

```python
"""One-off repair (2026-08-05): re-stamp resolve_after on OPEN entry_predictions with the
trading-day formula. Rows were stamped created_at + horizon CALENDAR days and became "due"
~8 days before their forward window was observable. Resolved rows are never touched
(append-only ledger). Dry-run by default; --apply writes.

Run from the repo root: uv run python scripts/fix_resolve_after_2026_08_05.py [--apply]
"""

from __future__ import annotations

import argparse
import sqlite3

from equity_scout.ml.prediction_ledger import _resolve_after


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="equity_scout.db")
    parser.add_argument("--apply", action="store_true", help="write the new stamps")
    args = parser.parse_args()

    con = sqlite3.connect(args.db)
    rows = con.execute(
        "SELECT id, created_at, horizon_days, resolve_after FROM entry_predictions"
        " WHERE resolved_at IS NULL"
    ).fetchall()
    changes = [
        (_resolve_after(created, horizon), row_id)
        for row_id, created, horizon, old in rows
        if _resolve_after(created, horizon) != old
    ]
    print(f"Offene Predictions: {len(rows)}, neu zu stempeln: {len(changes)}")
    if args.apply and changes:
        con.executemany(
            "UPDATE entry_predictions SET resolve_after = ? WHERE id = ?", changes
        )
        con.commit()
        print(f"Aktualisiert: {len(changes)}")
    con.close()


if __name__ == "__main__":
    main()
```

(No dedicated test: the stamped logic `_resolve_after` is unit-tested in Task 1; this is
glue over it, follows the `scripts/fix_future_asof_2026_07_24.py` precedent, and is
dry-run-first.)

- [x] **Step 2: Dry-run against the live DB**

Run (repo root): `uv run python scripts/fix_resolve_after_2026_08_05.py`
Expected: `Offene Predictions: 299, neu zu stempeln: 299` (299 as of 2026-08-05 23:00; the count grows by ~30/day with each daily chain — any value ≥299 with both numbers equal is right).

- [x] **Step 3: Apply**

Run: `uv run python scripts/fix_resolve_after_2026_08_05.py --apply`
Expected: `Aktualisiert: <same count>`.

- [x] **Step 4: Verify the ledger state end to end**

```bash
sqlite3 equity_scout.db "SELECT COUNT(*) AS total, SUM(resolved_at IS NOT NULL) AS resolved FROM entry_predictions;"
# expected: total unchanged, resolved 0 (nothing is observable before 2026-08-07's close)
uv run python scripts/run_resolve_predictions.py --db equity_scout.db
# expected output: "Aufgelöst: 0 von 0 fälligen Vorhersage(n) (0 ohne volles Vorwärtsfenster); noch offen: <total>."
# (all open rows now carry honest resolve_after stamps in the future)
```

Only run the resolver manually if the intraday/nightly chain is not mid-run (`pgrep -f run_resolve_predictions` empty).

- [x] **Step 5: Run the full gate, commit, log**

Run: `uv run pytest -q && uv run ruff check .`

```bash
git add scripts/fix_resolve_after_2026_08_05.py
git commit -m "chore(ml): re-stamp open predictions with trading-day resolve_after"
```

Append one line to `AUTOPILOT_LOG.md` (only if the parallel session is idle; otherwise leave it for the outcome pass): `- 2026-08-05 v15-W1: resolve loop honest (trading-day due-gate, column-wise panel, observable no-op, 299 rows re-stamped)`.

---

## Expected timeline of first real resolutions (proof the fix worked)

With the re-stamp, batches resolve on the first nightly run after `created_at + 32 days`
whose panel covers the 20th trading session: 2026-07-10 batch (30 rows) around
**2026-08-11**, then ~30 rows/day of backlog through early September. Check with:

```bash
sqlite3 equity_scout.db "SELECT substr(created_at,1,10) d, COUNT(*), SUM(resolved_at IS NOT NULL) FROM entry_predictions GROUP BY d ORDER BY d;"
```

`learning_curve` rows from the following nights must show `n_resolved > 0` and a real
`hit_rate`/`rank_ic` for the first time. If 2026-08-12 passes with `resolved` still 0,
reopen this plan — the diagnosis missed something.

## Outcome

**Executed 2026-08-06 (interactive session, Nico's go), all 4 tasks, gate green per task
(`uv run pytest -q` exit 0 + `ruff` clean). Commits: df6ff29 (Task 1), 908d707 (Task 2),
bba5150 (Task 3), 33dda3c + 4ec0165 (Task 4 + log).**

Live verification (Task 4): dry-run reported exactly 299/299, apply updated 299; ledger
after: total=299, resolved=0, open `resolve_after` range 2026-08-11T18:52Z …
2026-09-06T20:29Z — the 2026-07-10 batch lands on the predicted 2026-08-11. Resolver live
run printed the new observable no-op: "Aufgelöst: 0 von 0 fälligen Vorhersage(n) (0 ohne
volles Vorwärtsfenster); noch offen: 299."

Deviations from plan:
- `sqlite3` CLI is not installed on this box — all DB verifications ran via
  `uv run python` + stdlib sqlite3 (read-only URIs) instead.
- Task 1 also required a date shift in `tests/test_run_learning_snapshot.py`
  (`test_snapshot_reflects_champion_n_train_and_resolved_window` queried due at
  created+9d with horizon 5 → new stamp is +11d); same one-line-comment convention.
- Task 3's existing capsys test needed NO output-string update — it only asserts
  "Aufgelöst" is present, laxer than the plan expected.
- Executed directly on `autopilot/work` (repo loop convention, parallel session idle
  ~11h) instead of a worktree; every commit used explicit paths, PLAN.md untouched.
- `pgrep -f run_resolve_predictions` false-positively matches the invoking shell's own
  command line — verify with `ps -p <pid>` before concluding a resolver is mid-run.

Proof-of-fix checkpoint (from the plan's timeline): if the 2026-08-12 nightly still shows
`resolved` = 0, reopen this plan — the diagnosis missed something.
