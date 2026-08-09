# v15 P2 — Insider-Cluster Shadow Lane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the one evidence class that survived the P2a study — Form-4 insider clusters — a forward, pre-registered SHADOW track: one prediction per fresh cluster in the existing evidence ledger, resolved by the existing resolver, with no capital, no orders and no promotion mechanism anywhere in the code.

**Requirements doc:** `docs/superpowers/specs/2026-08-05-vision-v15-two-depots-evidence-learning.md`, section "Scope → P2 — Evidence that trades" and plan-document item 3. This plan implements the insider half of that scope and deliberately kills the congress half (numbers below).

**Evidence base:** `docs/superpowers/plans/2026-08-06-v15-p2a-historical-backfill.md`, Outcome → "Post-fix rerun — 2026-08-07 19:36–20:26 CEST (final)", plus `docs/research/history-study-report.json`.

**Architecture (locked):** A new pure-detection module `src/equity_scout/evidence/insider_shadow.py` reads the Form-4 events the LIVE collector already stored (`evidence/form4.py` → `evidence_events`, filled daily by `scripts/run_evidence.py`), applies the live cluster rule (`aggregate.MIN_INSIDERS` = 3 distinct insiders) and turns each fresh cluster into ONE `EvidenceEvent` under its own source string `insider_shadow`. A new standalone runner `scripts/run_insider_shadow.py` registers those events in the EXISTING evidence ledger (`evidence/ledger.py`, `evidence_predictions`) with a pre-registered 63-trading-day horizon and writes a status JSON; resolution needs no new code at all, because the daily chain already runs `scripts/run_resolve_evidence.py`, which fills the outcome against real forward returns vs SPY. The lane therefore owns exactly three artefacts — a detector, a runner, a status file — and borrows the whole predict-then-resolve honesty machinery.

**Why shadow and not capital:** verified against `docs/research/history-study-report.json` while writing this plan — the r_3m insider cell measures **+2.55% ± 0.67pp pooled but only +0.77% ± 0.79pp in the validate window (t0 > 2021-12-31, n=3,355)**, i.e. out of sample it does not clear a single stderr, and its hit rate there is 42.9%. That number is not in the P2a Outcome table and it is the strongest single argument in this plan: the signal is real enough to keep measuring forward and far too thin to fund.

**Why the evidence ledger and not `entry_predictions`:** `evidence_predictions` carries `source` as its track identity, so `stats_by_source` gives the shadow lane its own honest track for free. Writing shadow rows into `entry_predictions` would contaminate the entry champion's track (`resolved_stats` aggregates all rows) and would surface a shadow score as a ticker's champion score via `latest_scores` → `/api/radar` — a silent identity change the spec forbids.

**Tech Stack:** Python 3.11+ (uv), stdlib `sqlite3`/`json`/`statistics`, pandas only inside the existing resolver. No new dependencies. Gate: `uv run pytest -q` green (currently 1732 collected) + `uv run ruff check .` clean before every commit.

---

## Non-Goals

Each of these is excluded on measured grounds, not on taste. Naming them is part of the deliverable.

1. **No congress lane. It is killed here, on the numbers.** The P2a post-fix rerun measured 23,274 congress/executive purchase events with 16–21k measurements per horizon: r_1w **+0.15% ± 0.03pp** (directions disagree across the time split), r_1m +0.06% ± 0.07pp, r_3m −0.22% ± 0.13pp, r_6m −0.63% ± 0.19pp, r_12m **−0.39% ± 0.33pp** (directions disagree). Validate hit rates 51.5 / 47.3 / 44.7 / 43.1 / 39.7. There is no economically meaningful edge in either direction, and the two horizons at the ends of the grid cannot even agree on a sign. The biased 1.9%-coverage slice that had suggested a strong NEGATIVE medium-horizon edge shrank to −0.2…−0.6% under full coverage, so neither a long nor a short lane is supported. Killing a lane before it burns 60 days of paper track is exactly what the study was built for. Congress stays what it already is: a live evidence feed that annotates pitches and raises labelled alerts.
2. **No news/Benzinga lane.** Blocked on an unmeasured input: the spec's P2 precursor (a Benzinga/Alpaca-News publish→delivery latency probe over ~a week) has not run. Without it there is no way to know whether a news lane can act at minute latency or is stuck on the 30–45 min RSS floor, and the answer decides the lane's design. Not in this plan.
3. **No promotion mechanism.** No code path in this plan can move the shadow lane toward capital — not a gate, not a flag, not a "promote if" branch. A promotion decision needs ≥60 days of forward shadow track plus resolved predictions, and it is Nico's call on the numbers this lane produces. The status file states the review preconditions; it never evaluates them into a recommendation.
4. **No capital, no broker, no positions.** No Alpaca call, no order, no P&L, no equity curve, no sizing. The lane registers predictions and measures them.
5. **No frontend, no API surface.** `frontend/` belongs to a parallel session; `api.py` would only exist to render something the log and the status JSON already say. v1 is log + JSON.
6. **No new data source and no backfill collectors in the live path.** `evidence/backfill_form4.py` measured the prior from SEC quarterly bulk ZIPs; it is never called here.
7. **No second horizon.** Only r_3m is registered (rationale in Task 1). r_1w is not registered as a parallel hypothesis.

---

## Coordination / file ownership (hard constraint)

A parallel autopilot session owns `src/equity_scout/st_session.py`, `src/equity_scout/alpaca_*.py`, `scripts/run_shortterm.py`, `PLAN.md` and `frontend/`. **This plan touches NONE of them.** It also does not edit `scripts/install_crontab.sh`, `scripts/daily_copilot.sh`, `scripts/intraday_copilot.sh` or `scripts/session_lane.sh` — the lane gets its OWN wrapper script and an install snippet Nico runs once.

Commit only explicit paths (`git add <path> <path>`, never `-A`). Work on the current branch `autopilot/work` (repo loop convention).

## Hard constraints (inherited, restated)

- Free data only; nothing that costs money; paper/shadow only — the LOOP.md live-trading line is untouched and this lane cannot reach a broker even in principle.
- `DISCLAIMER` on every surface the lane produces (status JSON, README section).
- `EDGAR_USER_AGENT` degrade-to-unconfigured: no user agent ⇒ no Form-4 events ⇒ the lane reports `unconfigured` instead of "no clusters found". A dead source must never look like a quiet one (`evidence/base.py` status contract).
- Determinism in tests: no network, no wall clock in library code (`now` injected), fake events built in-test.
- The LLM scores, ranks and interprets nothing here. Detection is a `set` of names and a `len()`.
- Append-only ledger semantics: one open→resolved transition per row, never a back-filled guess.

---

## File-structure map

| Path | Status | Responsibility |
|---|---|---|
| `src/equity_scout/evidence/base.py` | edit (+3 lines) | new source constant `SOURCE_INSIDER_SHADOW` |
| `src/equity_scout/evidence/insider_shadow.py` | NEW | pure detection: cluster rule, pre-registered horizon, prior; no I/O |
| `src/equity_scout/evidence/ledger.py` | edit | trading-day due stamps (additive), `open_tickers`, `resolved_returns` |
| `src/equity_scout/ml/prediction_ledger.py` | edit (rename) | `_resolve_after` → public `resolve_after_stamp` (single source of the Wave-1 conversion) |
| `scripts/fix_resolve_after_2026_08_05.py` | edit (3 lines) | follow the rename |
| `scripts/run_resolve_evidence.py` | edit | Wave-1 shifted-window guard + observable `not_observable` counter |
| `scripts/run_insider_shadow.py` | NEW | the daily runner: detect → skip open → register → status JSON → print |
| `scripts/insider_shadow_lane.sh` | NEW | cron wrapper (mirrors `session_lane.sh`; sources `.env`, execs the runner) |
| `tests/test_evidence_insider_shadow.py` | NEW | detection rules |
| `tests/test_run_insider_shadow.py` | NEW | runner + status file |
| `tests/test_evidence_ledger.py` | edit | horizon-unit + helper tests |
| `tests/test_run_resolve_evidence.py` | edit | shifted-window guard + counter |
| `README.md` | edit (2 inserts) | lane section + cron line |
| `.state/insider_shadow_status.json` | runtime artefact | written by the runner; `.state/` is gitignored |

---

### Task 1: Detection module — the cluster rule and the pre-registered horizon

**Files:** Create `src/equity_scout/evidence/insider_shadow.py`, `tests/test_evidence_insider_shadow.py`; edit `src/equity_scout/evidence/base.py`.

- [ ] **Step 1 (failing tests):** Create `tests/test_evidence_insider_shadow.py`:

```python
"""Insider-cluster shadow detection: the live 3-distinct-insider rule, PIT t0, no duplicates."""
from __future__ import annotations

from equity_scout.evidence.base import SOURCE_CONGRESS, SOURCE_INSIDER, SOURCE_INSIDER_SHADOW
from equity_scout.evidence.insider_shadow import (
    SHADOW_HORIZON_TRADING_DAYS,
    STUDY_PRIOR,
    detect_clusters,
    shadow_events,
)


def _insider_event(ticker: str, insider: str, filing_date: str, key: str) -> dict:
    """One stored evidence_events row as events_in_window hands it back."""
    return {
        "source": SOURCE_INSIDER,
        "ticker": ticker,
        "event_key": key,
        "event_date": filing_date,
        "details": {"insider": insider, "filing_date": filing_date, "role": "director"},
    }


def _cluster_rows(ticker: str = "AAA", n: int = 3) -> list[dict]:
    return [
        _insider_event(ticker, f"Insider {i}", f"2026-08-0{i + 1}", f"acc{i}-2026-08-0{i + 1}")
        for i in range(n)
    ]


def test_two_insiders_are_not_a_cluster():
    assert detect_clusters({"AAA": _cluster_rows(n=2)}) == []


def test_three_distinct_insiders_are_a_cluster():
    clusters = detect_clusters({"AAA": _cluster_rows(n=3)})
    assert [c.ticker for c in clusters] == ["AAA"]
    assert clusters[0].insiders == ("Insider 0", "Insider 1", "Insider 2")


def test_same_insider_filing_three_times_is_not_a_cluster():
    """Three filings by ONE person is routine accumulation, not independent conviction."""
    rows = [
        _insider_event("AAA", "Solo Buyer", f"2026-08-0{i + 1}", f"acc{i}") for i in range(3)
    ]
    assert detect_clusters({"AAA": rows}) == []


def test_other_sources_never_count_toward_the_cluster():
    rows = _cluster_rows(n=2) + [
        {
            "source": SOURCE_CONGRESS,
            "ticker": "AAA",
            "event_key": "c1",
            "event_date": "2026-08-04",
            "details": {"politician": "Jane Doe"},
        }
    ]
    assert detect_clusters({"AAA": rows}) == []


def test_t0_is_the_latest_filing_date_in_the_cluster():
    """Only when the LAST buy was filed was the full cluster knowable (P2a PIT rule)."""
    clusters = detect_clusters({"AAA": _cluster_rows(n=3)})
    assert clusters[0].t0 == "2026-08-03"


def test_shadow_event_carries_the_pre_registered_horizon():
    events = shadow_events(detect_clusters({"AAA": _cluster_rows(n=3)}))
    assert len(events) == 1
    event = events[0]
    assert event.source == SOURCE_INSIDER_SHADOW
    assert event.ticker == "AAA"
    assert event.event_key == "2026-08-03-cluster3"
    assert event.event_date == "2026-08-03"
    assert event.details["horizon_trading_days"] == SHADOW_HORIZON_TRADING_DAYS
    assert event.details["n_insiders"] == 3
    assert event.details["shadow_only"] is True


def test_a_grown_cluster_gets_a_distinct_event_key():
    """A fourth buyer is a different fact; the ledger's UNIQUE key must be able to see it."""
    three = shadow_events(detect_clusters({"AAA": _cluster_rows(n=3)}))[0]
    four = shadow_events(detect_clusters({"AAA": _cluster_rows(n=4)}))[0]
    assert three.event_key != four.event_key


def test_tickers_with_an_open_prediction_are_skipped():
    """One open shadow prediction per ticker: re-registering the same signal would inflate
    n with two almost perfectly correlated outcomes."""
    clusters = detect_clusters({"AAA": _cluster_rows(n=3), "BBB": _cluster_rows("BBB", 3)})
    events = shadow_events(clusters, skip_tickers=frozenset({"AAA"}))
    assert [e.ticker for e in events] == ["BBB"]


def test_prior_is_the_measured_study_cell():
    """The forward track must never be readable without the prior it exists to test."""
    assert STUDY_PRIOR["n_measured"] == 13694
    assert STUDY_PRIOR["mean_relative_return"] == 0.0255
    assert STUDY_PRIOR["stderr"] == 0.0067
    assert STUDY_PRIOR["hit_rate_validate"] == 0.4292
    # The out-of-sample pair is the reason this is a shadow lane: +0.77% +/- 0.79pp.
    assert STUDY_PRIOR["validate_mean_relative_return"] < STUDY_PRIOR["validate_stderr"]
    assert "Ausreißern" in STUDY_PRIOR["caveat"]
```

- [ ] **Step 2 (run, expect fail):** `uv run pytest tests/test_evidence_insider_shadow.py -q` → `ModuleNotFoundError: No module named 'equity_scout.evidence.insider_shadow'` (collection error), exit non-zero.

- [ ] **Step 3 (implement the constant):** In `src/equity_scout/evidence/base.py`, directly after the `SOURCE_STATEMENT = "statement"` block, add:

```python
# v15 P2 shadow lane (evidence/insider_shadow.py): pre-registered PAPER predictions on
# Form-4 insider CLUSTERS. Its own source string on purpose — `stats_by_source` keeps
# the lane's forward track separate from the per-filing `insider` track, so a lane's
# numbers can never be mixed into the collector's (spec: no silent identity changes to
# existing tracks). Nothing under this source ever touches capital.
SOURCE_INSIDER_SHADOW = "insider_shadow"
```

- [ ] **Step 4 (implement the module):** Create `src/equity_scout/evidence/insider_shadow.py`:

```python
"""Insider-cluster SHADOW lane (v15 P2): pre-registered predictions, never capital.

WHY A SHADOW LANE AND NOT A TRADING LANE. The P2a backfill measured 27,681 insider-
cluster events 2006->2026 (docs/research/history-study-report.json, post-fix rerun
2026-08-07). Insider clusters were the ONLY evidence class that survived full coverage:
r_3m +2.55% +/- 0.67pp on 13,694 measurements, r_1w +2.08% +/- 0.97pp. The same table
measured the reasons NOT to trade it yet:

  * out of sample (t0 > 2021-12-31) the r_3m cell shrinks from +3.13% to +0.77% +/-
    0.79pp on 3,355 events — below one stderr, i.e. the pooled effect is fit-period
    carried;
  * the validate-window hit rate at r_3m is 42.9% and decays 51.1 -> 32.9 from r_1w to
    r_12m, so a positive mean sits on a sub-coin-flip breadth (outliers, not edge);
  * the report gated 162 cell-horizons of which ~81 agreeing directions are expected
    from noise alone;
  * 13,837 of the 27,681 cluster tickers are no longer tradable at all (insider
    mortality is real), so every number above is an upper bound.

A positive mean on a sub-50% hit rate is exactly the shape that looks like an edge in a
study and feels like a losing streak in a depot.

So this module registers predictions and nothing else. No capital, no broker order, no
position, no promotion rule: promotion needs >= 60 days of forward shadow track and is
Nico's decision, deliberately not implemented anywhere in this code.

DETECTION USES THE LIVE PATH. Fresh Form 4 filings arrive through evidence/form4.py
(scripts/run_evidence.py -> evidence_events) and the cluster rule is
aggregate.MIN_INSIDERS (>= 3 distinct insiders), the same constant the live evidence
alert applies to the same rows. The P2a backfill collectors (evidence/backfill_form4.py,
SEC quarterly bulk ZIPs) are NOT used here: they measured the prior, this lane acts on
fresh filings. The universe is therefore whatever the live collector scans (the current
watchlist, form4.py's documented scope) — a coverage limit that is reported on the
status surface, not a bug.
"""
from __future__ import annotations

from dataclasses import dataclass

from equity_scout.evidence.aggregate import MIN_INSIDERS
from equity_scout.evidence.base import (
    SOURCE_INSIDER,
    SOURCE_INSIDER_SHADOW,
    EvidenceEvent,
)

# Pre-registered before the first prediction and frozen: 63 trading days = the study's
# r_3m cell (+2.55% +/- 0.67pp, ~3.8 stderr), the strongest surviving cell. ONE horizon
# on purpose — r_1w (+2.08% +/- 0.97pp, ~2.1 stderr) is deliberately NOT registered as a
# second hypothesis: two horizons per event double the tests for one signal and halve
# what a pass means. A second horizon may be added AFTER this one has a verdict, as a
# new registration with its own start date, never retro-fitted onto this track.
SHADOW_HORIZON_TRADING_DAYS = 63

# Trailing window of collected Form-4 events a cluster may span. 30 days mirrors BOTH
# the live alert window (scripts/run_notify.EVIDENCE_WINDOW_DAYS) and the collector's own
# filing bound (form4.DEFAULT_MAX_FILING_AGE_DAYS): a cluster the alert path could not
# see must not appear here either.
DEFAULT_WINDOW_DAYS = 30

# The prior this lane exists to test, verbatim from the P2a rerun table. Carried onto
# every surface so the forward track is never read without it.
STUDY_PRIOR = {
    "source": "docs/research/history-study-report.json (P2a post-fix rerun, 2026-08-07)",
    "cell": "insider clusters, r_3m (63 Handelstage)",
    "n_measured": 13694,
    "mean_relative_return": 0.0255,
    "stderr": 0.0067,
    "hit_rate_all": 0.4698,
    "hit_rate_fit": 0.483,
    "hit_rate_validate": 0.4292,
    # Out of sample (t0 > 2021-12-31) the same cell measures +0.77% +/- 0.79pp on 3,355
    # events — the pooled +2.55% is carried by the fit period and does not survive one
    # stderr in the validate window. This single pair of numbers is the reason the lane
    # is a shadow track and not a depot sleeve.
    "validate_mean_relative_return": 0.0077,
    "validate_stderr": 0.0079,
    "validate_n": 3355,
    "caveat": (
        "Positiver Mittelwert bei einer Trefferquote UNTER 50 % — der Effekt wird von "
        "wenigen Ausreißern getragen, nicht von der Breite. Out of Sample (ab 2022) "
        "schrumpft er von +3,13 % auf +0,77 % ± 0,79pp, bleibt also unter einer "
        "Standardabweichung. Die Trefferquote im Validierungsfenster fällt zusätzlich mit "
        "dem Horizont (51,1 % auf 1W → 32,9 % auf 12M). Dazu Survivorship: 13.837 der "
        "27.681 Cluster-Ticker sind nicht mehr handelbar, die gemessenen Werte sind eine "
        "Obergrenze."
    ),
}


@dataclass(frozen=True)
class ShadowCluster:
    """One ticker's insider cluster as it is visible TODAY: >= MIN_INSIDERS distinct
    named buyers among the Form-4 events inside the trailing window."""

    ticker: str
    insiders: tuple[str, ...]
    t0: str  # latest filing date in the cluster — only then was the full cluster knowable
    source_event_keys: tuple[str, ...]


def _insider_name(event: dict) -> str | None:
    return (event.get("details") or {}).get("insider")


def _filing_date(event: dict) -> str:
    return (event.get("details") or {}).get("filing_date") or event["event_date"]


def detect_clusters(
    events_by_ticker: dict[str, list[dict]], *, min_insiders: int = MIN_INSIDERS
) -> list[ShadowCluster]:
    """Tickers whose collected Form-4 events carry >= min_insiders DISTINCT named buyers.

    Same rule and same rows as aggregate.select_evidence_alerts' insider reason line
    (distinct `details["insider"]`, None dropped) — mirrored rather than shared because
    the two answer different questions: the alert asks "is this worth a look", this asks
    "what exactly am I measuring from when". A parser fallback name ("unbekannt") counts
    as one buyer here exactly as it does there; diverging would make the shadow track
    measure a different population than the alerts show.
    """
    clusters: list[ShadowCluster] = []
    for ticker, events in sorted(events_by_ticker.items()):
        insider_events = [e for e in events if e["source"] == SOURCE_INSIDER]
        names = sorted({_insider_name(e) for e in insider_events} - {None})
        if len(names) < min_insiders:
            continue
        clusters.append(
            ShadowCluster(
                ticker=ticker.upper(),
                insiders=tuple(names),
                t0=max(_filing_date(e) for e in insider_events),
                source_event_keys=tuple(sorted(e["event_key"] for e in insider_events)),
            )
        )
    return clusters


def shadow_events(
    clusters: list[ShadowCluster], *, skip_tickers: frozenset[str] = frozenset()
) -> list[EvidenceEvent]:
    """One prediction event per cluster, minus tickers that already carry an OPEN shadow
    prediction.

    The skip is what keeps the sample honest: re-detecting the same cluster tomorrow, or
    the same cluster grown by a fourth buyer, is the SAME signal on the same ticker over
    an overlapping window — two rows whose outcomes are almost perfectly correlated would
    inflate n without adding information. The event_key still encodes t0 and cluster size,
    so a genuinely new cluster on that ticker AFTER the open one resolves is a new row.
    """
    events: list[EvidenceEvent] = []
    for cluster in clusters:
        if cluster.ticker in skip_tickers:
            continue
        events.append(
            EvidenceEvent(
                source=SOURCE_INSIDER_SHADOW,
                ticker=cluster.ticker,
                event_key=f"{cluster.t0}-cluster{len(cluster.insiders)}",
                event_date=cluster.t0,
                details={
                    "insiders": list(cluster.insiders),
                    "n_insiders": len(cluster.insiders),
                    "horizon_trading_days": SHADOW_HORIZON_TRADING_DAYS,
                    "source_event_keys": list(cluster.source_event_keys),
                    "shadow_only": True,
                },
            )
        )
    return events
```

- [ ] **Step 5 (run, expect pass):** `uv run pytest tests/test_evidence_insider_shadow.py -q` → `9 passed`, exit 0.

- [ ] **Step 6 (gate + commit):**

```bash
uv run pytest -q && uv run ruff check .
git add src/equity_scout/evidence/insider_shadow.py src/equity_scout/evidence/base.py tests/test_evidence_insider_shadow.py
git commit -m "feat(evidence): insider-cluster shadow detection with a pre-registered horizon"
```

Expected: pytest `1741 passed` (1732 + 9), ruff `All checks passed!`, one commit.

---

### Task 2a: Trading-day due stamps + track helpers in the evidence ledger

**Why:** `log_evidence` stamps `resolve_after` in CALENDAR days while `run_resolve_evidence` measures `horizon_days` in TRADING days (`relative_forward_return` counts index positions). That is the exact mismatch Wave 1 fixed for `entry_predictions`; the evidence ledger still carries it. Left alone, every shadow row would go "due" ~30 days before it is measurable and be retried mutely each night. The fix is additive — `horizon_unit` defaults to the current behaviour, so no existing source's stamps change.

**Files:** Edit `src/equity_scout/ml/prediction_ledger.py`, `scripts/fix_resolve_after_2026_08_05.py`, `src/equity_scout/evidence/ledger.py`, `tests/test_evidence_ledger.py`.

- [ ] **Step 1 (failing tests):** Append to `tests/test_evidence_ledger.py`:

```python
def test_trading_horizon_stamps_later_than_a_calendar_horizon(tmp_path):
    """63 trading days are ~93 calendar days: `due` must mean MEASURABLE (Wave-1 lesson)."""
    from datetime import datetime, timedelta

    from equity_scout.evidence.ledger import HORIZON_UNIT_TRADING

    db = str(tmp_path / "ev.db")
    log_evidence(db, [_event(key="cal")], now=NOW, horizon_days=63)
    log_evidence(
        db, [_event(key="trd")], now=NOW, horizon_days=63, horizon_unit=HORIZON_UNIT_TRADING
    )
    stamps = {
        row["event_key"]: row["resolve_after"]
        for row in due_evidence(db, "2030-01-01T00:00:00+00:00")
    }
    assert datetime.fromisoformat(stamps["cal"]) - datetime.fromisoformat(NOW) == timedelta(
        days=63
    )
    assert datetime.fromisoformat(stamps["trd"]) - datetime.fromisoformat(NOW) == timedelta(
        days=93
    )


def test_unknown_horizon_unit_is_refused(tmp_path):
    db = str(tmp_path / "ev.db")
    with pytest.raises(ValueError, match="horizon_unit"):
        log_evidence(db, [_event()], now=NOW, horizon_days=10, horizon_unit="fortnights")


def test_open_tickers_are_scoped_to_one_source(tmp_path):
    from equity_scout.evidence.ledger import open_tickers

    db = str(tmp_path / "ev.db")
    log_evidence(db, [_event(ticker="AAA", key="a")], now=NOW, horizon_days=1)
    log_evidence(
        db, [_event(source=SOURCE_NEWS_THEME, ticker="BBB", key="b")], now=NOW, horizon_days=1
    )
    assert open_tickers(db, source=SOURCE_CONGRESS) == {"AAA"}
    assert open_tickers(db, source=SOURCE_NEWS_THEME) == {"BBB"}

    row_id = due_evidence(db, "2026-07-20T00:00:00+00:00")[0]["id"]
    resolve_evidence(
        db, row_id, realized_relative_return=0.01, resolved_at="2026-07-20T00:00:00+00:00"
    )
    assert open_tickers(db, source=SOURCE_CONGRESS) == set()  # resolved rows are not open


def test_resolved_returns_are_raw_and_ordered(tmp_path):
    """stats_by_source reports the mean; a shadow track also needs its stderr, so the
    caller must be able to see the individual returns."""
    from equity_scout.evidence.ledger import resolved_returns

    db = str(tmp_path / "ev.db")
    log_evidence(db, [_event(key="a"), _event(key="b")], now=NOW, horizon_days=1)
    for row, value in zip(due_evidence(db, "2026-07-20T00:00:00+00:00"), (0.05, -0.01)):
        resolve_evidence(
            db, row["id"], realized_relative_return=value,
            resolved_at="2026-07-20T00:00:00+00:00",
        )
    assert resolved_returns(db, source=SOURCE_CONGRESS) == [0.05, -0.01]
    assert resolved_returns(db, source=SOURCE_NEWS_THEME) == []
```

`_event` in that file already accepts `source`, `ticker` and `key`; `pytest` is already imported.

- [ ] **Step 2 (run, expect fail):** `uv run pytest tests/test_evidence_ledger.py -q` → 4 failures (`ImportError: cannot import name 'HORIZON_UNIT_TRADING'`, `open_tickers`, `resolved_returns`; `TypeError: log_evidence() got an unexpected keyword argument 'horizon_unit'`).

- [ ] **Step 3 (make the Wave-1 conversion public):** In `src/equity_scout/ml/prediction_ledger.py` rename the private helper (line 61) and its call site (line 79):

```python
def resolve_after_stamp(now: str, horizon_days: int) -> str:
    """The TRADING-day horizon as a calendar date — deliberately late, never early.

    Public because the evidence ledger needs the identical conversion (v15 P2): the
    rule must exist exactly once, or the two ledgers drift apart the way the keep-rules
    did in P2a.
    """
    calendar_days = math.ceil(horizon_days * 7 / 5) + RESOLVE_BUFFER_DAYS
    return (datetime.fromisoformat(now) + timedelta(days=calendar_days)).isoformat()
```

and inside `log_predictions`: `resolve_after = resolve_after_stamp(now, horizon_days)`.

In `scripts/fix_resolve_after_2026_08_05.py` update the import and its two uses:

```python
from equity_scout.ml.prediction_ledger import resolve_after_stamp
```

```python
    changes = [
        (resolve_after_stamp(created, horizon), row_id)
        for row_id, created, horizon, old in rows
        if resolve_after_stamp(created, horizon) != old
    ]
```

Verify nothing else referenced the old name: `grep -rn "_resolve_after" --include=*.py src scripts tests` → only the unrelated test NAME `test_due_predictions_after_resolve_after` in `tests/test_prediction_ledger.py`.

- [ ] **Step 4 (implement in the evidence ledger):** In `src/equity_scout/evidence/ledger.py` add the import and the unit constants below `DEFAULT_HORIZON_DAYS`:

```python
from equity_scout.ml.prediction_ledger import resolve_after_stamp
```

```python
# `horizon_days` is measured in TRADING days by the resolver (relative_forward_return
# counts index positions), but historically stamped in CALENDAR days here — so rows went
# due before they were measurable and were retried mutely (the Wave-1 finding, applied to
# this ledger). The unit is now explicit and ADDITIVE: "calendar" keeps every existing
# source's stamps byte-identical, "trading" makes `due` mean "measurable" for new lanes.
HORIZON_UNIT_CALENDAR = "calendar"
HORIZON_UNIT_TRADING = "trading"
```

Replace the `log_evidence` signature and its stamp line:

```python
def log_evidence(
    db_path: str,
    events: list[EvidenceEvent],
    *,
    now: str,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    horizon_unit: str = HORIZON_UNIT_CALENDAR,
) -> int:
    """Append one open row per event; the UNIQUE key makes re-logging a no-op, so a
    re-collected fact can never inflate the sample. Returns the number of new rows."""
    init_evidence_ledger(db_path)
    if horizon_unit == HORIZON_UNIT_TRADING:
        resolve_after = resolve_after_stamp(now, horizon_days)
    elif horizon_unit == HORIZON_UNIT_CALENDAR:
        resolve_after = (datetime.fromisoformat(now) + timedelta(days=horizon_days)).isoformat()
    else:
        raise ValueError(f"unknown horizon_unit: {horizon_unit!r}")
```

(the body below the stamp is unchanged), and append the two read helpers at the end of the module:

```python
def open_tickers(db_path: str, *, source: str) -> set[str]:
    """Tickers with a still-OPEN row for that source — the shadow lane's duplicate guard
    (one open prediction per ticker; see evidence/insider_shadow.shadow_events)."""
    init_evidence_ledger(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT ticker FROM evidence_predictions"
            " WHERE source = ? AND resolved_at IS NULL",
            (source,),
        ).fetchall()
    return {row[0] for row in rows}


def resolved_returns(db_path: str, *, source: str) -> list[float]:
    """Realized relative returns of that source's RESOLVED rows, oldest first.

    `stats_by_source` reports the mean; a track whose prior is "positive mean, sub-50%
    hit rate" is not readable without a stderr, and a stderr needs the raw values.
    """
    init_evidence_ledger(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT realized_relative_return FROM evidence_predictions"
            " WHERE source = ? AND resolved_at IS NOT NULL ORDER BY id",
            (source,),
        ).fetchall()
    return [float(row[0]) for row in rows]
```

- [ ] **Step 5 (run, expect pass):** `uv run pytest tests/test_evidence_ledger.py tests/test_prediction_ledger.py -q` → all pass, exit 0.

- [ ] **Step 6 (gate + commit):**

```bash
uv run pytest -q && uv run ruff check .
git add src/equity_scout/evidence/ledger.py src/equity_scout/ml/prediction_ledger.py scripts/fix_resolve_after_2026_08_05.py tests/test_evidence_ledger.py
git commit -m "feat(evidence): trading-day due stamps and per-source track helpers in the evidence ledger"
```

Expected: `1745 passed`, ruff clean.

---

### Task 2b: The evidence resolver stops measuring shifted windows

**Why:** `run_resolve_evidence._realized_relative_return` starts measuring at the first panel date ≥ `created_at`. If the fetched panel does not reach back to `created_at` (a young listing, a provider gap), it silently measures a LATER window and books it as this row's outcome. Wave 1 fixed precisely this in `run_resolve_predictions.py:55-59`; the evidence resolver — the one that will resolve the shadow track — never got the guard. The run summary also never said how many due rows it could not measure.

**Files:** Edit `scripts/run_resolve_evidence.py`, `tests/test_run_resolve_evidence.py`.

- [ ] **Step 1 (failing tests):** In `tests/test_run_resolve_evidence.py`, update the two exact-dict assertions and add the guard test:

```python
    assert result == {"resolved": 1, "not_observable": 0, "still_open": 1}
```

```python
    assert result == {"resolved": 0, "not_observable": 1, "still_open": 1}
```

```python
def test_panel_starting_after_created_at_leaves_the_row_open(tmp_path):
    """Wave-1 lesson: a panel that begins AFTER the row was created would measure a
    shifted window and call it this row's outcome. Stay open instead."""
    db = str(tmp_path / "ev.db")
    log_evidence(db, [_event("AAA", "early")], now="2024-01-02T00:00:00+00:00",
                 horizon_days=HORIZON)
    result = run_resolve_evidence(
        db, now="2026-03-01T00:00:00+00:00", fetch_prices=_fetch(_panel())
    )
    assert result == {"resolved": 0, "not_observable": 1, "still_open": 1}
```

(`_panel()` starts 2025-06-01, so a row created 2024-01-02 predates it.)

- [ ] **Step 2 (run, expect fail):** `uv run pytest tests/test_run_resolve_evidence.py -q` → 3 failures; the new one fails on `{'resolved': 1, ...}` — proof the shifted window IS currently measured.

- [ ] **Step 3 (implement):** In `scripts/run_resolve_evidence.py` replace `_realized_relative_return` and the counter/summary:

```python
def _realized_relative_return(
    panel: PricePanel, ticker: str, created_at: str, horizon_days: int
) -> float | None:
    """Ticker-minus-SPY forward return over `horizon_days` trading days from the first
    panel date on/after created_at; None (row stays open) if the panel lacks the ticker,
    starts after created_at, or does not carry the full forward window."""
    closes = panel.closes
    symbol = yf_symbol(ticker)
    if symbol not in closes.columns or BENCHMARK not in closes.columns:
        return None
    pair = closes[[symbol, BENCHMARK]].dropna()
    as_of = _as_of_timestamp(created_at)
    if len(pair) == 0 or pair.index[0] > as_of:
        # Panel does not reach back to the day the row was created: measuring from its
        # first date would silently score a SHIFTED window (Wave-1 finding, see
        # plans/2026-08-05-v15-wave1-resolve-honesty.md). Stay open.
        return None
    on_or_after = pair.index[pair.index >= as_of]
    if len(on_or_after) == 0:
        return None
    return relative_forward_return(
        pair[symbol], pair[BENCHMARK], on_or_after[0], horizon_days
    )
```

```python
def run_resolve_evidence(
    db_path: str,
    *,
    now: str,
    fetch_prices: Callable[[list[str], str], PricePanel],
) -> dict:
    """Resolve every due evidence row. Returns {resolved, not_observable, still_open};
    `not_observable` counts due rows the panel could not measure yet — a silent no-op is
    how the entry ledger hid a 26-day outage (Wave 1), so this one counts out loud."""
    due = due_evidence(db_path, now)
    resolved = 0
    not_observable = 0
    if due:
        tickers = sorted({yf_symbol(d["ticker"]) for d in due} | {BENCHMARK})
        start = min(_as_of_timestamp(d["created_at"]) for d in due).date().isoformat()
        panel = fetch_prices(tickers, start)
        for row in due:
            rel = _realized_relative_return(
                panel, row["ticker"], row["created_at"], row["horizon_days"]
            )
            if rel is None:
                not_observable += 1
                continue  # forward window not yet fully observable — resolve later
            if resolve_evidence(
                db_path, row["id"], realized_relative_return=rel, resolved_at=now
            ):
                resolved += 1
    still_open = sum(entry["n_open"] for entry in stats_by_source(db_path).values())
    return {"resolved": resolved, "not_observable": not_observable, "still_open": still_open}
```

and in `main()`:

```python
    print(
        f"Evidenz aufgelöst: {result['resolved']} Zeile(n)"
        f" ({result['not_observable']} fällig, aber ohne volles Vorwärtsfenster);"
        f" noch offen: {result['still_open']}."
    )
```

- [ ] **Step 4 (run, expect pass):** `uv run pytest tests/test_run_resolve_evidence.py -q` → `4 passed`.

- [ ] **Step 5 (gate + commit):**

```bash
uv run pytest -q && uv run ruff check .
git add scripts/run_resolve_evidence.py tests/test_run_resolve_evidence.py
git commit -m "fix(evidence): never resolve a shifted window, and count unmeasurable due rows"
```

Expected: `1746 passed`, ruff clean.

---

### Task 3: The runner — detect, skip, register

**Files:** Create `scripts/run_insider_shadow.py`, `tests/test_run_insider_shadow.py`.

- [ ] **Step 1 (failing tests):** Create `tests/test_run_insider_shadow.py`:

```python
"""Insider shadow lane runner: registers pre-registered predictions, never trades."""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone

from equity_scout.evidence.base import SOURCE_INSIDER, SOURCE_INSIDER_SHADOW, EvidenceEvent
from equity_scout.evidence.ledger import stats_by_source
from equity_scout.evidence.storage import record_events
from scripts.run_insider_shadow import main, run_insider_shadow

NOW = "2026-08-10T18:45:00+00:00"
ENV = {"EDGAR_USER_AGENT": "Nico Sutheimer (nico@example.com)"}


def _seed_cluster(db: str, ticker: str = "AAA", n: int = 3) -> None:
    record_events(
        db,
        [
            EvidenceEvent(
                source=SOURCE_INSIDER,
                ticker=ticker,
                event_key=f"acc{i}-{ticker}",
                event_date=f"2026-08-0{i + 1}",
                details={"insider": f"Insider {i}", "filing_date": f"2026-08-0{i + 1}"},
            )
            for i in range(n)
        ],
        now=NOW,
    )


def _seed_cluster_today(db: str, ticker: str = "AAA", n: int = 3) -> None:
    """`main()` reads the wall clock, so its fixtures must be dated RELATIVE to today —
    hard-coded dates would silently fall out of the 30-day window and turn this into a
    test that starts failing on a calendar date."""
    today = datetime.now(timezone.utc)
    days = [(today - timedelta(days=i + 1)).date().isoformat() for i in range(n)]
    record_events(
        db,
        [
            EvidenceEvent(
                source=SOURCE_INSIDER,
                ticker=ticker,
                event_key=f"acc{i}-{ticker}",
                event_date=days[i],
                details={"insider": f"Insider {i}", "filing_date": days[i]},
            )
            for i in range(n)
        ],
        now=today.isoformat(timespec="seconds"),
    )


def _shadow_rows(db: str) -> list[tuple]:
    with sqlite3.connect(db) as conn:
        return conn.execute(
            "SELECT ticker, event_key, horizon_days, created_at, resolve_after"
            " FROM evidence_predictions WHERE source = ?",
            (SOURCE_INSIDER_SHADOW,),
        ).fetchall()


def test_cluster_is_registered_once_with_a_trading_day_stamp(tmp_path):
    db = str(tmp_path / "es.db")
    _seed_cluster(db)

    result = run_insider_shadow(db, now=NOW, env=ENV)

    assert result["status"] == "ok"
    assert result["clusters"] == 1 and result["registered"] == 1
    rows = _shadow_rows(db)
    assert len(rows) == 1
    ticker, event_key, horizon, created_at, resolve_after = rows[0]
    assert (ticker, event_key, horizon) == ("AAA", "2026-08-03-cluster3", 63)
    # 63 trading days ~ 93 calendar days: due means measurable.
    assert datetime.fromisoformat(resolve_after) - datetime.fromisoformat(created_at) == (
        timedelta(days=93)
    )


def test_second_run_registers_nothing_while_the_prediction_is_open(tmp_path):
    db = str(tmp_path / "es.db")
    _seed_cluster(db)
    run_insider_shadow(db, now=NOW, env=ENV)

    result = run_insider_shadow(db, now="2026-08-11T18:45:00+00:00", env=ENV)

    assert result["registered"] == 0 and result["skipped_open"] == 1
    assert len(_shadow_rows(db)) == 1


def test_two_insiders_register_nothing(tmp_path):
    db = str(tmp_path / "es.db")
    _seed_cluster(db, n=2)
    result = run_insider_shadow(db, now=NOW, env=ENV)
    assert result["clusters"] == 0 and result["registered"] == 0
    assert _shadow_rows(db) == []


def test_events_outside_the_window_do_not_form_a_cluster(tmp_path):
    db = str(tmp_path / "es.db")
    _seed_cluster(db)
    result = run_insider_shadow(db, now="2026-11-01T18:45:00+00:00", env=ENV)
    assert result["clusters"] == 0 and result["insider_events"] == 0


def test_no_events_and_no_user_agent_reports_unconfigured(tmp_path):
    """A dead source must never look like a quiet one (evidence/base.py status contract)."""
    db = str(tmp_path / "es.db")
    result = run_insider_shadow(db, now=NOW, env={})
    assert result["status"] == "unconfigured"
    assert "EDGAR_USER_AGENT" in result["detail"]
    assert result["registered"] == 0


def test_no_events_with_a_user_agent_is_an_honest_quiet_day(tmp_path):
    db = str(tmp_path / "es.db")
    result = run_insider_shadow(db, now=NOW, env=ENV)
    assert result["status"] == "ok" and result["registered"] == 0


def test_dry_run_detects_but_writes_nothing(tmp_path):
    db = str(tmp_path / "es.db")
    _seed_cluster(db)
    result = run_insider_shadow(db, now=NOW, env=ENV, apply=False)
    assert result["clusters"] == 1 and result["registered"] == 0
    assert _shadow_rows(db) == []


def test_main_exits_zero_and_prints_a_summary(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "es.db")
    _seed_cluster_today(db)
    monkeypatch.setattr(sys, "argv", ["run_insider_shadow.py", "--db", db])

    assert main() == 0

    out = capsys.readouterr().out
    assert "Schatten-Lane" in out and "AAA" in out
    assert stats_by_source(db)[SOURCE_INSIDER_SHADOW]["n_open"] == 1
```

- [ ] **Step 2 (run, expect fail):** `uv run pytest tests/test_run_insider_shadow.py -q` → `ModuleNotFoundError: No module named 'scripts.run_insider_shadow'`.

- [ ] **Step 3 (implement):** Create `scripts/run_insider_shadow.py`:

```python
"""Insider-cluster SHADOW lane (v15 P2): register pre-registered predictions, trade nothing.

Reads the Form-4 events the LIVE collector already stored (`evidence_events`, filled by
scripts/run_evidence.py), detects >= 3-distinct-insider clusters inside the trailing
window and registers ONE prediction per fresh cluster in the evidence ledger under its
own source `insider_shadow`, horizon 63 TRADING days (pre-registered from the P2a study,
see evidence/insider_shadow.py). Resolution is not this script's job: the daily chain's
`run_resolve_evidence.py` step fills the outcomes against real forward returns vs SPY.

NO capital, NO broker order, NO position, NO promotion — this lane produces a track
record and nothing else. Whether it ever earns capital is Nico's decision on those
numbers, and there is deliberately no code path here that could make it.

Idempotent by construction: the ledger's UNIQUE(source, ticker, event_key) plus the
one-open-prediction-per-ticker skip mean a second run on the same day registers nothing.

Usage:
    uv run python scripts/run_insider_shadow.py [--db equity_scout.db]
        [--window-days 30] [--dry-run]
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.evidence.base import SOURCE_INSIDER, SOURCE_INSIDER_SHADOW
from equity_scout.evidence.edgar import resolve_user_agent
from equity_scout.evidence.insider_shadow import (
    DEFAULT_WINDOW_DAYS,
    SHADOW_HORIZON_TRADING_DAYS,
    detect_clusters,
    shadow_events,
)
from equity_scout.evidence.ledger import (
    HORIZON_UNIT_TRADING,
    log_evidence,
    open_tickers,
)
from equity_scout.evidence.storage import events_in_window


def run_insider_shadow(
    db_path: str,
    *,
    now: str,
    env: dict,
    window_days: int = DEFAULT_WINDOW_DAYS,
    apply: bool = True,
) -> dict:
    """Detect clusters in the collected Form-4 events and register the fresh ones.

    Returns {status, detail, insider_events, clusters, skipped_open, registered,
    registered_tickers}. `status` is "unconfigured" when there is nothing to look at AND
    no EDGAR user agent is configured — without that distinction an unconfigured
    collector would read as "no insiders bought anything", which is a different claim.
    """
    grouped = events_in_window(db_path, window_days=window_days, now=now)
    insider_events = sum(
        1 for events in grouped.values() for e in events if e["source"] == SOURCE_INSIDER
    )
    if insider_events == 0 and resolve_user_agent(env) is None:
        return {
            "status": "unconfigured",
            "detail": (
                "EDGAR_USER_AGENT fehlt — der Form-4-Kollektor sammelt nichts, die Lane "
                "hat also nichts zu messen (keine Aussage über Insider-Käufe)"
            ),
            "insider_events": 0,
            "clusters": 0,
            "skipped_open": 0,
            "registered": 0,
            "registered_tickers": [],
        }

    clusters = detect_clusters(grouped)
    already_open = frozenset(open_tickers(db_path, source=SOURCE_INSIDER_SHADOW))
    events = shadow_events(clusters, skip_tickers=already_open)
    registered = (
        log_evidence(
            db_path,
            events,
            now=now,
            horizon_days=SHADOW_HORIZON_TRADING_DAYS,
            horizon_unit=HORIZON_UNIT_TRADING,
        )
        if apply and events
        else 0
    )
    return {
        "status": "ok",
        "detail": (
            f"{insider_events} Insider-Ereignis(se) im {window_days}-Tage-Fenster"
            f" -> {len(clusters)} Cluster"
        ),
        "insider_events": insider_events,
        "clusters": len(clusters),
        "skipped_open": len(clusters) - len(events),
        "registered": registered,
        "registered_tickers": [e.ticker for e in events],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument(
        "--dry-run", action="store_true", help="detect and report, register nothing"
    )
    args = parser.parse_args()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = run_insider_shadow(
        args.db, now=now, env=dict(os.environ), window_days=args.window_days,
        apply=not args.dry_run,
    )
    mode = " [dry-run]" if args.dry_run else ""
    print(
        f"Insider-Schatten-Lane{mode} [{result['status']}]: {result['detail']};"
        f" neu registriert: {result['registered']}"
        f" ({result['skipped_open']} mit offener Vorhersage übersprungen)."
    )
    if result["registered_tickers"]:
        print("Registriert (Papier, ohne Kapital): " + ", ".join(result["registered_tickers"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4 (run, expect pass):** `uv run pytest tests/test_run_insider_shadow.py -q` → `8 passed`.

- [ ] **Step 5 (gate + commit):**

```bash
uv run pytest -q && uv run ruff check .
git add scripts/run_insider_shadow.py tests/test_run_insider_shadow.py
git commit -m "feat(evidence): insider shadow lane runner with one open prediction per ticker"
```

Expected: `1754 passed`, ruff clean.

---

### Task 4: Status JSON — the prior, the track, the review preconditions

**Files:** Edit `scripts/run_insider_shadow.py`, `tests/test_run_insider_shadow.py`.

- [ ] **Step 1 (failing tests):** First fix a side effect the new default introduces: `test_main_exits_zero_and_prints_a_summary` (Task 3) would otherwise write the real `.state/insider_shadow_status.json` in the repo. Change its argv to

```python
    monkeypatch.setattr(
        sys, "argv",
        ["run_insider_shadow.py", "--db", db, "--status-out", str(tmp_path / "status.json")],
    )
```

Then append to `tests/test_run_insider_shadow.py`:

```python
def test_status_carries_disclaimer_prior_and_promotion_preconditions(tmp_path):
    from equity_scout.constants import DISCLAIMER
    from scripts.run_insider_shadow import build_status

    db = str(tmp_path / "es.db")
    _seed_cluster(db)
    result = run_insider_shadow(db, now=NOW, env=ENV)

    status = build_status(result, now=NOW, db_path=db)

    assert status["disclaimer"] == DISCLAIMER
    assert status["shadow_only"] is True
    assert status["capital"] == 0
    assert status["pre_registration"]["horizon_trading_days"] == 63
    assert status["pre_registration"]["n_hypotheses"] == 1
    assert status["pre_registration"]["prior"]["n_measured"] == 13694
    assert status["promotion"]["implemented"] is False
    assert status["promotion"]["decision_owner"] == "Nico"
    assert status["promotion"]["min_resolved_for_review"] == 30
    assert status["promotion"]["min_days_for_review"] == 60
    assert status["track"]["n_open"] == 1
    assert status["track"]["n_resolved"] == 0
    assert status["track"]["stderr"] is None  # nothing resolved: no fabricated precision


def test_status_computes_a_stderr_once_two_rows_resolved(tmp_path):
    from equity_scout.evidence.ledger import due_evidence, resolve_evidence
    from scripts.run_insider_shadow import build_status

    db = str(tmp_path / "es.db")
    _seed_cluster(db)
    _seed_cluster(db, ticker="BBB")
    run_insider_shadow(db, now=NOW, env=ENV)
    for row, value in zip(due_evidence(db, "2027-01-01T00:00:00+00:00"), (0.10, -0.02)):
        resolve_evidence(
            db, row["id"], realized_relative_return=value,
            resolved_at="2027-01-01T00:00:00+00:00",
        )

    status = build_status(
        run_insider_shadow(db, now="2027-01-02T00:00:00+00:00", env=ENV),
        now="2027-01-02T00:00:00+00:00", db_path=db,
    )

    assert status["track"]["n_resolved"] == 2
    assert status["track"]["mean_relative_return"] == 0.04
    assert status["track"]["stderr"] == 0.06
    assert "Ausreißern" in status["pre_registration"]["prior"]["caveat"]


def test_main_writes_the_status_file(tmp_path, monkeypatch):
    import json

    db = str(tmp_path / "es.db")
    out = tmp_path / "state" / "insider_shadow_status.json"
    _seed_cluster_today(db)
    monkeypatch.setattr(
        sys, "argv",
        ["run_insider_shadow.py", "--db", db, "--status-out", str(out)],
    )

    assert main() == 0

    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["last_run"]["registered"] == 1
    assert written["shadow_only"] is True
```

- [ ] **Step 2 (run, expect fail):** `uv run pytest tests/test_run_insider_shadow.py -q` → 3 failures (`ImportError: cannot import name 'build_status'`, unknown argument `--status-out`).

- [ ] **Step 3 (implement):** In `scripts/run_insider_shadow.py` extend the imports:

```python
import json
import statistics
from pathlib import Path
```

```python
from equity_scout.constants import DEFAULT_DB_PATH, DISCLAIMER
from equity_scout.evidence.insider_shadow import (
    DEFAULT_WINDOW_DAYS,
    SHADOW_HORIZON_TRADING_DAYS,
    STUDY_PRIOR,
    detect_clusters,
    shadow_events,
)
from equity_scout.evidence.ledger import (
    HORIZON_UNIT_TRADING,
    log_evidence,
    open_tickers,
    resolved_returns,
    stats_by_source,
)
```

and add below `run_insider_shadow`:

```python
# Runtime state, not a report: .state/ is gitignored, so a daily rewrite creates no repo
# churn and no dashboard depends on it (the frontend belongs to another strand).
DEFAULT_STATUS_OUT = ".state/insider_shadow_status.json"

# Review PRECONDITIONS, not a promotion rule: they say when it is worth LOOKING at the
# track, never what to conclude. The arena gate's trade/PF criteria do not apply — this
# lane has no trades and no P&L, only resolved predictions.
MIN_RESOLVED_FOR_REVIEW = 30
MIN_DAYS_FOR_REVIEW = 60


def build_status(result: dict, *, now: str, db_path: str) -> dict:
    """The lane's whole public surface: what it is, what it registered, what it measured.

    The track block reports mean AND stderr AND hit rate together on purpose — the prior
    is "positive mean at a sub-50% hit rate", so any one of the three alone would mislead.
    """
    returns = resolved_returns(db_path, source=SOURCE_INSIDER_SHADOW)
    stats = stats_by_source(db_path).get(SOURCE_INSIDER_SHADOW, {})
    stderr = (
        round(statistics.stdev(returns) / len(returns) ** 0.5, 4) if len(returns) >= 2 else None
    )
    return {
        "lane": SOURCE_INSIDER_SHADOW,
        "generated_at": now,
        "shadow_only": True,
        "capital": 0,
        "broker_orders": 0,
        "what_this_is": (
            "Papier-Schattenlane: registriert vorab festgelegte Vorhersagen zu Insider-"
            "Clustern (>= 3 unabhängige Käufer) und misst sie gegen SPY. Kein Kapital, "
            "keine Orders, keine automatische Beförderung."
        ),
        "universe": (
            "die Ticker, die der Live-Form-4-Kollektor abdeckt (aktuelle Watchlist, "
            "evidence/form4.py) — keine Vollabdeckung des Universums"
        ),
        "pre_registration": {
            "horizon_trading_days": SHADOW_HORIZON_TRADING_DAYS,
            "n_hypotheses": 1,
            "why_one": (
                "Nur die r_3m-Zelle ist registriert. r_1w (+2,08 % ± 0,97pp) bleibt "
                "bewusst ungetestet: zwei Horizonte pro Ereignis verdoppeln die Tests "
                "für ein Signal und halbieren die Aussage eines Treffers."
            ),
            "prior": STUDY_PRIOR,
        },
        "last_run": {
            "status": result["status"],
            "detail": result["detail"],
            "insider_events": result["insider_events"],
            "clusters": result["clusters"],
            "skipped_open": result["skipped_open"],
            "registered": result["registered"],
            "registered_tickers": result["registered_tickers"],
        },
        "track": {
            "n_resolved": stats.get("n_resolved", 0),
            "n_open": stats.get("n_open", 0),
            "hit_rate": stats.get("hit_rate"),
            "mean_relative_return": stats.get("mean_relative_return"),
            "stderr": stderr,
            "reading_note": (
                "Mittelwert, Stderr und Trefferquote gehören zusammen gelesen: ein "
                "positiver Mittelwert bei einer Trefferquote unter 50 % heißt "
                "Ausreißer-getragen, nicht breit verdient."
            ),
        },
        "promotion": {
            "implemented": False,
            "decision_owner": "Nico",
            "min_resolved_for_review": MIN_RESOLVED_FOR_REVIEW,
            "min_days_for_review": MIN_DAYS_FOR_REVIEW,
            "note": (
                "Diese Lane kann sich nicht selbst befördern — es gibt keinen Codepfad "
                "dafür. Die Schwellen sagen, ab wann ein Blick lohnt, nicht was folgt. "
                "Erste Auflösungen frühestens ~93 Kalendertage nach der ersten "
                "Registrierung (63 Handelstage Horizont)."
            ),
        },
        "disclaimer": DISCLAIMER,
    }


def write_status(path: str, status: dict) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
```

In `main()`, add the argument and the write (after the existing prints):

```python
    parser.add_argument("--status-out", default=DEFAULT_STATUS_OUT)
```

```python
    write_status(args.status_out, build_status(result, now=now, db_path=args.db))
    print(f"Status: {args.status_out}")
```

- [ ] **Step 4 (run, expect pass):** `uv run pytest tests/test_run_insider_shadow.py -q` → `11 passed`.

- [ ] **Step 5 (gate + commit):**

```bash
uv run pytest -q && uv run ruff check .
git add scripts/run_insider_shadow.py tests/test_run_insider_shadow.py
git commit -m "feat(evidence): shadow-lane status file with prior, track stderr and review preconditions"
```

Expected: `1757 passed`, ruff clean.

---

### Task 5: Cron wrapper, install snippet, README

**Files:** Create `scripts/insider_shadow_lane.sh`; edit `README.md`.

- [ ] **Step 1 (wrapper):** Create `scripts/insider_shadow_lane.sh` (mirrors `scripts/session_lane.sh`'s shape — own script, own log, `.env` sourced by the shell because this repo has no python-dotenv):

```bash
#!/usr/bin/env bash
# The insider-cluster SHADOW lane (v15 P2), once per weekday evening AFTER the daily
# chain has collected fresh Form 4 filings (scripts/daily_copilot.sh, 18:00).
#
# Why it is its OWN script and cron line rather than a step in daily_copilot.sh:
# - Ownership. A parallel session owns the intraday/session chain; this lane must be
#   addable and removable without touching a shared chain script.
# - Blast radius. The lane only ever INSERTs ledger rows; it must never be able to delay
#   or fail the pitch delivery, and a broken pitch step must never skip the lane.
# - Cadence. Filings arrive daily, resolution runs in the daily chain anyway — one run
#   per weekday is the whole requirement.
#
# The lane is idempotent (UNIQUE ledger key + one-open-prediction-per-ticker skip), so a
# missed evening costs nothing: the next run registers the same cluster.
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR" || exit 1
PY="$REPO_DIR/.venv/bin/python"

# No python-dotenv in this repo — the shell sources .env, same as every other chain here.
# Without EDGAR_USER_AGENT the lane reports `unconfigured` instead of "no clusters".
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

exec "$PY" scripts/run_insider_shadow.py
```

```bash
chmod +x scripts/insider_shadow_lane.sh
bash -n scripts/insider_shadow_lane.sh   # syntax check, expect no output
```

- [ ] **Step 2 (README — lane section):** In `README.md`, insert directly BEFORE the line `## Auto-Depot (vision v10)` (i.e. after the "**Alert escalation:** …" paragraph that ends the evidence section). *(The block below is fenced with FOUR backticks so its inner ```bash fences survive the copy — insert the inner content, not the outer fence.)*

````markdown
### Insider-Cluster-Schattenlane (v15 P2)

Die historische Studie (P2a, `docs/research/history-study-report.json`, Stand 2026-08-07)
hat 50.955 punktgenaue Ereignisse 2006→2026 aufgelöst. Ergebnis in einem Satz: **Kongress-
und Executive-Käufe zeigen auf 16–21k Messungen pro Horizont keinen wirtschaftlich
relevanten Vorsprung** (r_1w +0,15 % ± 0,03pp bis r_12m −0,39 % ± 0,33pp, Richtungen an
beiden Enden uneins) — deshalb gibt es **keine Kongress-Lane**, die Quelle bleibt reine
Annotation. Übrig bleiben **Insider-Cluster**: r_3m +2,55 % ± 0,67pp auf 13.694 Messungen —
out of sample aber nur noch +0,77 % ± 0,79pp bei 42,9 % Trefferquote, also von Ausreißern
getragen und unter einer Standardabweichung.

Genau dafür gibt es diese Lane — und sie handelt **nichts**:

```bash
# Frische >=3-Insider-Cluster erkennen und je EINE Vorhersage vorab registrieren
uv run python scripts/run_insider_shadow.py --db equity_scout.db          # schreibt
uv run python scripts/run_insider_shadow.py --dry-run                      # nur zeigen
```

- **Kein Kapital, keine Orders, keine Position, keine automatische Beförderung.** Die Lane
  registriert pro Cluster eine Vorhersage im bestehenden Evidenz-Ledger (Quelle
  `insider_shadow`, Horizont **63 Handelstage**, vorab festgelegt) und lässt sie vom
  ohnehin täglich laufenden `run_resolve_evidence.py` gegen echte Kurse vs SPY auflösen.
- **Eine offene Vorhersage pro Ticker**: dasselbe Cluster morgen erneut zu registrieren
  würde n mit fast identischen Ergebnissen aufblähen.
- **Ein Horizont, eine Hypothese.** r_1w bleibt ungetestet, damit ein Treffer etwas heißt.
- Status nach jedem Lauf: `.state/insider_shadow_status.json` (Prior, Lauf-Zähler, Track
  mit Mittelwert + Stderr + Trefferquote, Review-Vorbedingungen, Disclaimer).
- Ob daraus je Kapital wird, entscheidet **Nico** nach ≥60 Tagen Schattenspur und ≥30
  aufgelösten Vorhersagen. Es gibt keinen Codepfad, der das automatisch tut.
````

- [ ] **Step 3 (README — cron):** In the `## Automation (cron)` section, insert a paragraph directly after the paragraph ending "…even when the box slept through the night slot." *(again four backticks outside, insert the inner content)*:

````markdown
**Insider-Schattenlane (v15 P2).** Eigene Cron-Zeile, bewusst NICHT in
`install_crontab.sh` aufgenommen (der Installer verwaltet nur die Kern-Chains und lässt
unbekannte Zeilen unangetastet). Einmalig installieren:

```bash
LINE="45 18 * * 1-5 flock -n /tmp/equity-scout-insider-shadow.lock $PWD/scripts/insider_shadow_lane.sh >> $PWD/insider_shadow.log 2>&1"
crontab -l 2>/dev/null | grep -qF "insider_shadow_lane.sh" \
  || (crontab -l 2>/dev/null; echo "$LINE") | crontab -
crontab -l | grep insider_shadow
```

18:45 Mo–Fr, also nach der Tages-Chain (18:00), die die frischen Form-4-Filings sammelt.
Ein verpasster Abend kostet nichts — die Lane ist idempotent.
````

- [ ] **Step 4 (gate + commit):**

```bash
uv run pytest -q && uv run ruff check .
git add scripts/insider_shadow_lane.sh README.md
git commit -m "chore(evidence): cron wrapper and docs for the insider shadow lane"
```

Expected: `1757 passed`, ruff clean.

---

### Task 6: First live run, cron install, Outcome

- [ ] **Step 1 (dry run):**

```bash
uv run python scripts/run_insider_shadow.py --dry-run
```

Expected: one line `Insider-Schatten-Lane [dry-run] [ok|unconfigured]: N Insider-Ereignis(se) im 30-Tage-Fenster -> M Cluster; neu registriert: 0 (…)`. `unconfigured` here would be a finding (EDGAR_USER_AGENT was verified present 2026-07-24 — if it says unconfigured, stop and report instead of "fixing" .env).

- [ ] **Step 2 (real run):**

```bash
uv run python scripts/run_insider_shadow.py
```

Expected: the same line without `[dry-run]`, plus `Status: .state/insider_shadow_status.json`.

- [ ] **Step 3 (verify the ledger, stdlib sqlite3 — the `sqlite3` CLI is NOT installed on this box, Wave-1 Outcome):**

```bash
uv run python -c "
import sqlite3
con = sqlite3.connect('file:equity_scout.db?mode=ro', uri=True)
for row in con.execute(\"SELECT ticker, event_key, horizon_days, created_at, resolve_after FROM evidence_predictions WHERE source='insider_shadow' ORDER BY id\"):
    print(row)
print('offen:', con.execute(\"SELECT COUNT(*) FROM evidence_predictions WHERE source='insider_shadow' AND resolved_at IS NULL\").fetchone()[0])
"
```

Expected: `resolve_after` ≈ `created_at` + 93 days on every row; `horizon_days` = 63.

- [ ] **Step 4 (read the status file):** `cat .state/insider_shadow_status.json` — check `shadow_only: true`, `capital: 0`, `promotion.implemented: false`, the prior block, and that `track.stderr` is `null` while nothing is resolved.

- [ ] **Step 5 (idempotency):** run `uv run python scripts/run_insider_shadow.py` a second time → `neu registriert: 0 (N mit offener Vorhersage übersprungen)`, and the row count from Step 3 is unchanged.

- [ ] **Step 6 (cron install — state-changing OUTSIDE the repo, announce before running):** the guarded snippet from the README's automation section, then `crontab -l | grep insider_shadow` to confirm exactly one line. Confirm the existing lines are untouched (`crontab -l | grep -c equity-scout` before/after differs by exactly 1).

- [ ] **Step 7 (Outcome):** Fill this plan's `## Outcome` with: commits per task, the live counters (insider events in window, clusters, registered tickers), the `resolve_after` dates of the first rows (i.e. when the first resolutions can physically land), whether cron was installed, and any deviation. **The lane's numbers are evidence for a later decision, never a recommendation** — the Outcome must not contain a promotion suggestion.

```bash
git add docs/superpowers/plans/2026-08-07-v15-p2-insider-shadow-lane.md
git commit -m "docs(evidence): insider shadow lane outcome — first live registrations"
```

---

## Expected proof

After Task 6 the repo has a lane that cannot trade: `evidence_predictions` carries N rows under source `insider_shadow` with a 63-trading-day horizon and a `resolve_after` ~93 calendar days out, `.state/insider_shadow_status.json` states the prior it is testing next to an empty track, and `grep -rn "insider_shadow" --include=*.py src scripts` shows no import of any broker, order, position or promotion module. The first resolutions land ~93 days after the first registration; only then does the track begin to say anything, and what it says is Nico's to interpret.

If the lane's forward track ends up flat or negative, that is a RESULT — the same kind of cheap kill the congress lane just received, one horizon at a time.

---

## Self-Review (performed against the spec section and the controller's rulings)

Checked before this plan was handed over; findings fixed inline rather than left as notes.

1. **Spec P2 said two lanes (`insider` + `congress`) registered in `shortterm_storage.LANES` with runners in `run_shortterm.py`.** This plan builds one lane, outside the arena. Justified and deliberate: the congress lane is killed by the measurement the spec itself asked for (Non-Goal 1, with numbers), and `run_shortterm.py` / `frontend/` are owned by a parallel session. Consequence honestly stated: this lane has no arena panel, no 10k paper equity and no arena promotion gate — it is a prediction track, weaker than the spec's "lane", and that is the point at this evidence level.
2. **"Both lanes start at 10k paper" (spec) vs "NO capital" (controller ruling).** Controller wins; the plan carries `capital: 0` on the status surface so the divergence from the spec is visible, not silent.
3. **Ledger choice.** First draft used `entry_predictions` ("the Wave-1 ledger"). Rejected during review: `resolved_stats` aggregates every row and `latest_scores` feeds `/api/radar`, so shadow rows would contaminate the entry champion's track and surface as a ticker's champion score. Switched to `evidence_predictions`, whose `source` column IS the track identity — and inherited the two Wave-1 lessons explicitly (Tasks 2a/2b) instead of assuming they applied.
4. **Scope creep check on Tasks 2a/2b.** Both edit shared evidence infrastructure. Kept because the shadow track's numbers depend on them (a calendar-stamped due date makes "due" meaningless; an unguarded resolver would book a shifted window as this lane's outcome), both are additive with defaults unchanged, and both mirror an already-ratified Wave-1 fix. Blast radius stated in the tasks. Nothing else in the resolver was touched — the missing `not_observable` counter was in scope only because the same three lines were already being edited.
5. **File-ownership constraint re-verified** against the task list: no `st_session.py`, no `alpaca_*.py`, no `scripts/run_shortterm.py`, no `PLAN.md`, no `frontend/`, no edit to `install_crontab.sh`, `daily_copilot.sh` or `session_lane.sh`. The one shared-file edit outside evidence (`ml/prediction_ledger.py`) is a rename in a file no other strand owns; its only external caller is a 2026-08-05 one-off script, updated in the same step.
6. **Detection source re-verified:** `detect_clusters` reads `evidence_events` rows written by `evidence/form4.py`; `evidence/backfill_form4.py` is imported nowhere in the plan. The distinction (backfill measured the prior, the lane acts on fresh filings) is in the module docstring, the architecture block and Non-Goal 6.
7. **Honesty guardrails re-verified:** DISCLAIMER on the status file and the README section; `unconfigured` distinguished from "quiet"; deterministic tests with hand-built events and no network; free data only; no LLM anywhere in the path; `now` injected everywhere, wall clock only in `main()`.
8. **YAGNI pass.** Cut during review: an `insider_shadow_positions` table, an equity curve, a per-cluster conviction score, a Telegram alert, an `/api/insider-shadow` endpoint, a second horizon, and a `promotion_ready` boolean. Each would have been a portfolio manager growing inside a measurement.
9. **Task-count discipline:** 6 tasks (2a/2b are two commits of one concern), inside the 5–7 target.
10. **Every quoted number re-read from `docs/research/history-study-report.json`**, not copied from the P2a Outcome prose. Two corrections came out of that: the validate hit rate is 0.4292 (not 0.429 as rounded in the table) and r_1w validate is 51.1% (not 51.0%) — and the decisive fact, the r_3m validate-window collapse to +0.77% ± 0.79pp, appears in the JSON but in no prose table. It is now carried in `STUDY_PRIOR`, the module docstring, the architecture block and the README, because a shadow lane whose surfaces omit its own out-of-sample weakness is a marketing surface.
11. **Time-bomb check on the tests:** the two `main()` tests use the wall clock, so their fixtures are dated relative to today (`_seed_cluster_today`); everything else injects `now`. No test can start failing on a calendar date.

## Outcome

**Ausgeführt 2026-08-09 (Sonntag), Branch `autopilot/work`. Alle 6 Tasks umgesetzt, Gate je Commit grün.**

### Commits
| Task | Commit | Inhalt |
|---|---|---|
| 1 | `005f209` | Detection-Modul + `SOURCE_INSIDER_SHADOW` (9 Tests) |
| 2a | `eee23cc` | Handelstag-Stempel + `open_tickers`/`resolved_returns`, `_resolve_after` → `resolve_after_stamp` (4 Tests) |
| 2b | `cc1f15f` | Resolver misst kein verschobenes Fenster mehr + `not_observable`-Zähler (1 Test) |
| 3 | `dd5e6aa` | Runner (8 Tests) |
| 4 | `41bf660` | Status-JSON mit Prior, Track-Stderr, Review-Vorbedingungen (3 Tests) |
| 5 | `9772e7c` | Cron-Wrapper + README |

Gate am Ende: **1833 pytest grün**, ruff repo-weit sauber. 25 neue Tests.

### Task 2b: der Defekt war real und ist bewiesen
Der neue Test `test_panel_starting_after_created_at_leaves_the_row_open` schlug vor dem Fix
mit `{'resolved': 1}` fehl — der Resolver hat also tatsächlich ein verschobenes Fenster
gemessen und als Ergebnis der Zeile gebucht. Jetzt bleibt die Zeile offen und zählt als
`not_observable`.

### Live-Läufe (Task 6)
Dry-Run, echter Lauf und zweiter Lauf (Idempotenz) alle `[ok]`, Exit 0:

```
Insider-Schatten-Lane [ok]: 1 Insider-Ereignis(se) im 30-Tage-Fenster -> 0 Cluster;
neu registriert: 0 (0 mit offener Vorhersage übersprungen).
```

**Registriert: 0 Zeilen.** Es gibt derzeit kein einziges 3-Insider-Cluster, also auch keine
`resolve_after`-Daten. Das ist kein Defekt der Lane, sondern der Zustand ihres Inputs —
und der ist der eigentliche Befund dieser Runde:

### Befund: der Input ist fast leer (nicht im Plan vorhergesehen)
`evidence_events` enthält in der **gesamten Historie genau 1** Insider-Ereignis
(30.07.2026). Zum Vergleich, dieselben 30 Tage: congress 671, news_theme 216, voice 207,
edgar_8k 38. Drei Ursachen, gemessen statt vermutet:

1. **Der Form-4-Kollektor war bis 2026-08-08 defekt** (SEC-xsl-Präfix im `primaryDocument`,
   gefixt in der Nacht 07.→08.08.). Der Fix ist bis heute durch **keinen** Werktags-Lauf
   gegangen: 08.08. war Samstag, 09.08. Sonntag, die Daily-Chain läuft Mo–Fr 18:00. Der
   erste echte Sammellauf mit funktionierendem Kollektor ist **Montag, 10.08., 18:00**.
2. **Live-Verify des Kollektors (2026-08-09, gegen echtes EDGAR):** Status `ok`,
   „5/12 Ticker geprüft → 0 Ereignisse; 0 ohne CIK-Mapping; 7 nicht-US übersprungen;
   0 PIT-Verstöße verworfen". Der Kollektor läuft also, er findet nur nichts.
3. **Strukturelle Sichtfeld-Grenze:** 17 der 30 Watchlist-Titel sind US-Emittenten und
   damit überhaupt Form-4-fähig (57 %); 13 sind es nicht (`.NS`, `.T`, `.SA`, `.L`, `.AX`,
   `.BR`). Die 17 US-Titel sind überwiegend Small Caps und Closed-End-Fonds (GLU, GGN, GAM,
   ETO, PKBK, CNOB, FRST …), wo drei *verschiedene* Insider-Käufe innerhalb von 30 Tagen
   selten sind. Die im Status-JSON als `universe` benannte Abdeckungsgrenze ist in der
   Praxis also deutlich bindender, als der Plan sie angenommen hat.

**Konsequenz für die Erwartungshaltung:** die Lane wird voraussichtlich sehr wenige
Vorhersagen registrieren. Bis 30 aufgelöste Vorhersagen (die Review-Vorbedingung im
Status-JSON) zusammenkommen, kann es bei dieser Watchlist sehr lange dauern — die erste
Auflösung überhaupt kann frühestens ~93 Kalendertage nach der ersten Registrierung landen,
und die erste Registrierung steht noch aus. Das ist eine Messung der Datenlage, keine
Aussage über die Güte des Signals.

### Cron
Installiert am 2026-08-09, additiv geprüft: 10 equity-scout-Zeilen vorher, 11 nachher,
Differenz exakt 1, die anderen unangetastet.
`45 18 * * 1-5 flock -n /tmp/equity-scout-insider-shadow.lock …/scripts/insider_shadow_lane.sh >> …/insider_shadow.log 2>&1`

### Beweis „kann nicht handeln"
`grep` über `evidence/insider_shadow.py` + `scripts/run_insider_shadow.py` findet die Wörter
`alpaca`/`place_bracket`/`close_position`/`LaneBook`/`promotion` ausschließlich in
Kommentaren und Statustexten — kein Import eines Broker-, Order-, Positions- oder
Promotion-Moduls. Status-JSON verifiziert: `shadow_only: true`, `capital: 0`,
`broker_orders: 0`, `promotion.implemented: false`, `decision_owner: "Nico"`, Prior mit
`n_measured: 13694` und Disclaimer vorhanden, `track.stderr: null` solange nichts aufgelöst ist.

### Abweichungen vom Plan
1. **`--dry-run` schreibt die Status-Datei trotzdem.** Der Plan erwartet in Task 6 Step 1
   nur eine Ausgabezeile, der Code schreibt zusätzlich `Status: …`. Bewusst so belassen:
   die Status-Datei ist Laufzeit-State (`.state/`, gitignored), kein Ledger-Eintrag — der
   Dry-Run registriert weiterhin nichts.
2. **Erwartete Testzahlen im Plan stimmen nicht** (1741/1745/1746/1754/1757). Der Plan wurde
   gegen 1732 Tests geschrieben; der Basisstand war zum Ausführungszeitpunkt 1759 (u. a.
   durch den Session-Lane-Fix desselben Tages). Die *Differenzen* stimmen exakt: +9/+4/+1/+8/+3.
3. **Task 6 Step 3/4 konnten nichts zeigen**, weil 0 Zeilen registriert wurden — statt der
   `resolve_after`-Prüfung an echten Zeilen steht die Abdeckungsmessung oben.
