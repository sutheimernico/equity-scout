# Trading Copilot — Phase 1: Radar Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Explainable entry sub-signals (Dip-Quality, Value-Gap, Momentum) over funnel finalists, combined into a persisted, queryable watchlist with per-stock entry zones — plus public-repo hygiene.

**Architecture:** Pure functions over existing funnel artifacts (`Pick.breakdown` percentiles + `entry.compute_entry_plan` levels). New modules follow the repo's established seams: frozen dataclasses, no network in pure code, one SQLite storage module per concern with idempotent init, CLI script per concern, FastAPI route added to `create_app`. The composite combiner is a documented static placeholder that Phase 4's ML layer replaces; sub-signal readings are logged append-only from day one as future training data.

**Tech Stack:** Python 3.11, stdlib `sqlite3`, FastAPI, pytest, ruff. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-04-trading-copilot-design.md` (§5.1, §9, §12)

**Conventions that bind every task** (from the codebase, do not deviate):
- Code/docstrings/tests English; user-facing strings (reasons, notes) German (ADR 0001).
- Frozen dataclasses; pure functions; network only behind lazy imports inside functions.
- Deterministic time: `created_at` is always injected by the caller, never `datetime.now()` inside pure code.
- Gate before every commit: `python -m pytest -q && ruff check .` — never commit red.
- Tests assert bounds/ordering and reason substrings, not brittle exact floats.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `.gitignore` | modify | ignore runtime artifacts (`*.log`, root `*.db`) |
| `src/equity_scout/signals.py` | create | `SignalReading` + three sub-signal functions + static composite |
| `src/equity_scout/radar.py` | create | entry zone derivation, `WatchlistEntry`/`Watchlist`, `build_watchlist` |
| `src/equity_scout/radar_storage.py` | create | SQLite persistence: watchlist snapshots + append-only signal readings |
| `scripts/run_radar.py` | create | CLI: latest funnel run → histories → watchlist → DB + JSON artifact |
| `src/equity_scout/api.py` | modify | add `GET /api/radar` |
| `tests/test_signals.py` | create | sub-signal + composite tests |
| `tests/test_radar.py` | create | zone + watchlist builder tests |
| `tests/test_radar_storage.py` | create | persistence round-trip tests |
| `tests/test_run_radar.py` | create | CLI end-to-end with fakes |
| `tests/test_api.py` | modify | radar endpoint test |

---

### Task 1: Repo hygiene — untrack runtime artifacts

The repo is public; committed logs/DBs (`api.log`, `forward.log`, `research.log`, `research_ledger.db`, `equity_scout.db`, `equity_scout_cache.db`, `forward_paper.db`) are run byproducts and must leave tracking. Files stay on disk (`--cached`), only git tracking changes.

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Confirm which artifacts are actually tracked**

Run: `git ls-files | grep -E '\.(log|db)$'`
Expected: the tracked subset of the files listed above. Only these get `git rm --cached`.

- [ ] **Step 2: Untrack them (files stay on disk)**

```bash
git rm --cached --ignore-unmatch api.log forward.log research.log \
  research_ledger.db equity_scout.db equity_scout_cache.db forward_paper.db
```

- [ ] **Step 3: Append to `.gitignore`** (read it first; keep existing entries, add only what is missing)

```gitignore
# runtime artifacts — never commit (public repo)
*.log
/*.db
```

Note: `/*.db` (root-anchored) — do NOT use a bare `*.db`, that would also ignore intentional fixture DBs under `tests/` if any are ever added.

- [ ] **Step 4: Verify clean state**

Run: `git status --short` — expected: deletions staged for the tracked artifacts, `.gitignore` modified, and the artifact files now listed under nothing (ignored). Then run the gate: `python -m pytest -q && ruff check .` — expected: all pass (this task touches no code).

- [ ] **Step 5: Commit**

```bash
git add .gitignore
git commit -m "chore: untrack runtime artifacts (logs, sqlite dbs) for public repo"
```

---

### Task 2: `SignalReading` + Dip-Quality signal

**Files:**
- Create: `src/equity_scout/signals.py`
- Test: `tests/test_signals.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for entry sub-signals. Histories are synthetic and deterministic."""
from __future__ import annotations

from equity_scout.entry import compute_entry_plan
from equity_scout.signals import SignalReading, dip_quality


def downtrend_history(
    n: int = 260, start: float = 100.0, end: float = 72.0
) -> tuple[list[float], list[float], list[float]]:
    """Linear decline over n days; highs/lows hug the closes."""
    step = (end - start) / (n - 1)
    closes = [start + step * i for i in range(n)]
    highs = [c * 1.01 for c in closes]
    lows = [c * 0.99 for c in closes]
    return closes, highs, lows


def flat_history(
    n: int = 260, level: float = 100.0
) -> tuple[list[float], list[float], list[float]]:
    closes = [level + (0.4 if i % 2 else -0.4) for i in range(n)]
    highs = [c * 1.01 for c in closes]
    lows = [c * 0.99 for c in closes]
    return closes, highs, lows


def test_dip_quality_rewards_deep_dip_in_quality_stock():
    plan = compute_entry_plan("AAA", *downtrend_history())
    strong = dip_quality({"quality": 0.9}, plan)
    weak = dip_quality({"quality": 0.1}, plan)
    assert isinstance(strong, SignalReading)
    assert strong.name == "dip_quality"
    assert 0.0 <= weak.score < strong.score <= 1.0
    assert "52-Wochen-Hoch" in strong.reason


def test_dip_quality_is_low_without_a_dip():
    plan = compute_entry_plan("BBB", *flat_history())
    reading = dip_quality({"quality": 0.9}, plan)
    assert reading.score < 0.15


def test_dip_quality_missing_quality_percentile_scores_zero():
    plan = compute_entry_plan("CCC", *downtrend_history())
    assert dip_quality({}, plan).score == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_signals.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'equity_scout.signals'` (or ImportError).

- [ ] **Step 3: Write the implementation**

```python
"""Entry sub-signals: transparent, rule-based scores in [0, 1] with readable reasons.

Pure functions over already-computed funnel artifacts (the Pick's factor-percentile
breakdown + the EntryPlan reference levels). No network. `breakdown` is passed as a
plain dict so both live `Pick.breakdown` and JSON-round-tripped stored runs work.

The composite here is a static weighted mean — a documented placeholder that the ML
layer (Phase 4) replaces. The sub-signals themselves stay rule-based forever: they are
the explainable part, and style attribution depends on them.

Framing: readings measure entry-PRICE attractiveness of an already-vetted stock.
They are reference information, not buy recommendations (same stance as entry.py).
"""
from __future__ import annotations

from dataclasses import dataclass

from equity_scout.entry import EntryPlan

# A -30% drawdown (or deeper) counts as a "full" dip; shallower dips scale linearly.
_FULL_DIP_DRAWDOWN = 0.30


@dataclass(frozen=True)
class SignalReading:
    name: str  # "dip_quality" | "value_gap" | "momentum"
    score: float  # [0, 1]
    reason: str  # user-facing, German (ADR 0001)


def dip_quality(breakdown: dict[str, float], plan: EntryPlan) -> SignalReading:
    """Meaningful pullback in a fundamentally strong stock.

    depth  = drawdown from the 52w high, saturating at -30%
    score  = depth x quality percentile (no quality data -> 0, honestly)
    """
    quality = float(breakdown.get("quality", 0.0))
    depth = min(max(-plan.drawdown_from_high, 0.0) / _FULL_DIP_DRAWDOWN, 1.0)
    score = round(depth * quality, 4)
    reason = (
        f"Kurs {plan.drawdown_from_high * 100:+.1f} % vom 52-Wochen-Hoch; "
        f"Qualitäts-Perzentil im Funnel: {quality * 100:.0f}."
    )
    return SignalReading("dip_quality", score, reason)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_signals.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Gate and commit**

```bash
python -m pytest -q && ruff check .
git add src/equity_scout/signals.py tests/test_signals.py
git commit -m "feat: add SignalReading and dip-quality entry sub-signal"
```

---

### Task 3: Value-Gap signal

**Files:**
- Modify: `src/equity_scout/signals.py`
- Test: `tests/test_signals.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_signals.py`; reuse the history helpers from Task 2)

```python
from equity_scout.signals import value_gap


def test_value_gap_rewards_discount_below_anchor_in_cheap_stock():
    plan = compute_entry_plan("AAA", *downtrend_history())  # price well below sma200
    cheap = value_gap({"value": 0.9}, plan)
    rich = value_gap({"value": 0.1}, plan)
    assert cheap.name == "value_gap"
    assert 0.0 <= rich.score < cheap.score <= 1.0
    assert "200-Tage-Schnitt" in cheap.reason


def test_value_gap_zero_above_anchor():
    closes, highs, lows = downtrend_history()
    closes.extend([c * 1.6 for c in closes[-40:]])  # rally far above the long-term mean
    highs.extend([c * 1.01 for c in closes[-40:]])
    lows.extend([c * 0.99 for c in closes[-40:]])
    plan = compute_entry_plan("DDD", closes, highs, lows)
    reading = value_gap({"value": 0.9}, plan)
    assert reading.score == 0.0
    assert "keine Bewertungslücke" in reading.reason


def test_value_gap_zero_without_sma200_data():
    plan = compute_entry_plan("EEE", *downtrend_history(n=50))
    # sma() falls back to fewer closes, so sma200 exists; force the None branch directly:
    from dataclasses import replace

    reading = value_gap({"value": 0.9}, replace(plan, sma200=None))
    assert reading.score == 0.0
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `python -m pytest tests/test_signals.py -v`
Expected: Task-2 tests PASS, new tests FAIL with `ImportError: cannot import name 'value_gap'`.

- [ ] **Step 3: Write the implementation** (append to `signals.py`)

```python
# A 20% discount to the 200-day SMA counts as a "full" value gap.
_FULL_GAP_DISCOUNT = 0.20


def value_gap(breakdown: dict[str, float], plan: EntryPlan) -> SignalReading:
    """Price notably below the long-term anchor in a stock the funnel ranks cheap.

    Only fires below the 200-day SMA — above it there is no gap by definition.
    score = value percentile x (0.3 + 0.7 x discount), discount saturating at -20%.
    The 0.3 floor keeps 'just crossed under the anchor' from scoring zero.
    """
    value = float(breakdown.get("value", 0.0))
    if plan.sma200 is None or plan.sma200 <= 0:
        return SignalReading(
            "value_gap", 0.0, "Kein 200-Tage-Schnitt verfügbar (zu wenig Kurshistorie)."
        )
    rel = plan.price / plan.sma200 - 1.0
    if rel > 0:
        return SignalReading(
            "value_gap",
            0.0,
            f"Kurs {rel * 100:+.1f} % über dem 200-Tage-Schnitt — keine Bewertungslücke.",
        )
    discount = min(-rel / _FULL_GAP_DISCOUNT, 1.0)
    score = round(value * (0.3 + 0.7 * discount), 4)
    reason = (
        f"Kurs {rel * 100:+.1f} % unter dem 200-Tage-Schnitt; "
        f"Value-Perzentil im Funnel: {value * 100:.0f}."
    )
    return SignalReading("value_gap", score, reason)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_signals.py -v` — expected: all PASS.

- [ ] **Step 5: Gate and commit**

```bash
python -m pytest -q && ruff check .
git add src/equity_scout/signals.py tests/test_signals.py
git commit -m "feat: add value-gap entry sub-signal"
```

---

### Task 4: Momentum (anti-falling-knife) signal

**Files:**
- Modify: `src/equity_scout/signals.py`
- Test: `tests/test_signals.py`

- [ ] **Step 1: Write the failing tests** (append)

```python
from equity_scout.signals import momentum


def stabilized_history() -> tuple[list[float], list[float], list[float]]:
    """Decline, then a flat-to-rising tail: dip that has stopped falling."""
    closes, highs, lows = downtrend_history(n=230)
    tail_start = closes[-1]
    tail = [tail_start * (1.0 + 0.001 * i) for i in range(30)]
    closes = closes + tail
    highs = [c * 1.01 for c in closes]
    lows = [c * 0.99 for c in closes]
    return closes, highs, lows


def test_momentum_prefers_stabilized_over_falling_knife():
    s_closes, s_highs, s_lows = stabilized_history()
    f_closes, f_highs, f_lows = downtrend_history()
    stable = momentum(
        {"momentum": 0.6}, compute_entry_plan("AAA", s_closes, s_highs, s_lows), s_closes
    )
    knife = momentum(
        {"momentum": 0.6}, compute_entry_plan("BBB", f_closes, f_highs, f_lows), f_closes
    )
    assert stable.name == "momentum"
    assert 0.0 <= knife.score < stable.score <= 1.0
    assert "fällt weiter" in knife.reason or "20-Tage" in knife.reason


def test_momentum_missing_percentile_scores_zero():
    closes, highs, lows = stabilized_history()
    plan = compute_entry_plan("CCC", closes, highs, lows)
    assert momentum({}, plan, closes).score == 0.0
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `python -m pytest tests/test_signals.py -v`
Expected: new tests FAIL with `ImportError: cannot import name 'momentum'`.

- [ ] **Step 3: Write the implementation** (append; add `from equity_scout.entry import EntryPlan, sma` to the existing import — one import line total)

```python
# Falling knives keep a fraction of their momentum score, not zero: the funnel's 6m
# momentum percentile still carries information; the stabilization filter dampens it.
_KNIFE_DAMPING = 0.3


def momentum(
    breakdown: dict[str, float], plan: EntryPlan, closes: list[float]
) -> SignalReading:
    """Trend filter against catching falling knives.

    Uses the funnel's 6m momentum percentile, damped to 30% while the price still
    sits below its 20-day SMA (i.e. the dip has not stabilized yet).
    """
    mom = float(breakdown.get("momentum", 0.0))
    sma20 = sma(closes, window=20)
    stabilized = sma20 is not None and plan.price >= sma20
    if stabilized:
        score = round(mom, 4)
        reason = (
            f"Kurs auf/über dem 20-Tage-Schnitt (stabilisiert); "
            f"Momentum-Perzentil im Funnel: {mom * 100:.0f}."
        )
    else:
        score = round(mom * _KNIFE_DAMPING, 4)
        reason = (
            f"Kurs unter dem 20-Tage-Schnitt — fällt weiter (fallendes Messer); "
            f"Momentum-Perzentil {mom * 100:.0f} wird gedämpft."
        )
    return SignalReading("momentum", score, reason)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_signals.py -v` — expected: all PASS.

- [ ] **Step 5: Gate and commit**

```bash
python -m pytest -q && ruff check .
git add src/equity_scout/signals.py tests/test_signals.py
git commit -m "feat: add momentum anti-falling-knife sub-signal"
```

---

### Task 5: Static composite score

**Files:**
- Modify: `src/equity_scout/signals.py`
- Test: `tests/test_signals.py`

- [ ] **Step 1: Write the failing tests** (append)

```python
from equity_scout.signals import composite_score


def test_composite_is_weighted_mean_in_unit_interval():
    readings = [
        SignalReading("dip_quality", 1.0, "r"),
        SignalReading("value_gap", 1.0, "r"),
        SignalReading("momentum", 1.0, "r"),
    ]
    assert composite_score(readings) == 1.0
    zeros = [SignalReading(r.name, 0.0, "r") for r in readings]
    assert composite_score(zeros) == 0.0


def test_composite_ignores_unknown_signal_names():
    readings = [
        SignalReading("dip_quality", 1.0, "r"),
        SignalReading("someday_ml", 1.0, "r"),
    ]
    assert 0.0 < composite_score(readings) < 1.0
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `python -m pytest tests/test_signals.py -v` — expected: `ImportError: cannot import name 'composite_score'`.

- [ ] **Step 3: Write the implementation** (append)

```python
# Static combiner weights — PLACEHOLDER until the ML layer (Phase 4) learns the
# weighting. Dip-quality leads: "quality at a discount" is the copilot's core style.
_COMPOSITE_WEIGHTS = {"dip_quality": 0.40, "value_gap": 0.35, "momentum": 0.25}


def composite_score(readings: list[SignalReading]) -> float:
    """Weighted mean of known sub-signals in [0, 1]. Unknown names are ignored."""
    return round(
        sum(_COMPOSITE_WEIGHTS[r.name] * r.score for r in readings if r.name in _COMPOSITE_WEIGHTS),
        4,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_signals.py -v` — expected: all PASS.

- [ ] **Step 5: Gate and commit**

```bash
python -m pytest -q && ruff check .
git add src/equity_scout/signals.py tests/test_signals.py
git commit -m "feat: add static composite entry score (pre-ML placeholder)"
```

---

### Task 6: Entry zone + watchlist builder

**Files:**
- Create: `src/equity_scout/radar.py`
- Test: `tests/test_radar.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for entry-zone derivation and the watchlist builder."""
from __future__ import annotations

from equity_scout.entry import compute_entry_plan
from equity_scout.radar import Watchlist, build_watchlist, entry_zone
from tests.test_signals import downtrend_history, stabilized_history


def test_entry_zone_is_ordered_and_at_or_below_anchor():
    plan = compute_entry_plan("AAA", *downtrend_history())
    zone = entry_zone(plan)
    assert zone is not None
    low, high = zone
    assert 0 < low < high
    assert plan.sma200 is None or high <= plan.sma200


def _finalist(ticker: str, bucket: str = "core") -> dict:
    return {
        "ticker": ticker,
        "name": f"{ticker} AG",
        "bucket": bucket,
        "breakdown": {"value": 0.8, "quality": 0.8, "momentum": 0.6, "growth": 0.5},
    }


def test_build_watchlist_sorts_by_composite_and_skips_missing_history():
    histories = {
        "DIP": downtrend_history(),
        "FLAT": stabilized_history(),
        "GONE": ([], [], []),
    }
    wl = build_watchlist(
        [_finalist("DIP"), _finalist("FLAT"), _finalist("GONE")],
        histories,
        created_at="2026-07-04T12:00:00",
    )
    assert isinstance(wl, Watchlist)
    assert wl.created_at == "2026-07-04T12:00:00"
    tickers = [e.ticker for e in wl.entries]
    assert set(tickers) == {"DIP", "FLAT"}
    composites = [e.composite for e in wl.entries]
    assert composites == sorted(composites, reverse=True)
    assert "GONE" in wl.skipped  # honest: missing data is reported, never silently dropped


def test_watchlist_entry_carries_readings_zone_and_proximity():
    wl = build_watchlist(
        [_finalist("DIP")], {"DIP": downtrend_history()}, created_at="2026-07-04T12:00:00"
    )
    entry = wl.entries[0]
    assert {r.name for r in entry.readings} == {"dip_quality", "value_gap", "momentum"}
    assert entry.entry_zone_low < entry.entry_zone_high
    assert entry.in_zone == (entry.entry_zone_low <= entry.price <= entry.entry_zone_high)
    # proximity: relative distance of price to the zone's upper edge (<= 0 means at/inside)
    assert abs(entry.proximity - (entry.price / entry.entry_zone_high - 1.0)) < 1e-9
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_radar.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'equity_scout.radar'`.

- [ ] **Step 3: Write the implementation**

```python
"""Watchlist builder: funnel finalists -> entry zones + sub-signal readings.

Pure: histories are passed in (fetched by the CLI), finalists are plain dicts
(shape of a JSON-round-tripped Pick: ticker/name/bucket/breakdown) so both live
runs and stored runs feed the same code path.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from equity_scout.entry import EntryPlan, compute_entry_plan
from equity_scout.signals import (
    SignalReading,
    composite_score,
    dip_quality,
    momentum,
    value_gap,
)

History = tuple[list[float], list[float], list[float]]  # closes, highs, lows


@dataclass(frozen=True)
class WatchlistEntry:
    ticker: str
    name: str
    bucket: str
    price: float
    entry_zone_low: float
    entry_zone_high: float
    proximity: float  # price / zone_high - 1.0; <= 0 means at or inside the zone
    in_zone: bool
    composite: float
    readings: list[SignalReading]
    reference_note: str  # EntryPlan.reference_note, carried through for the UI/pitch


@dataclass(frozen=True)
class Watchlist:
    created_at: str
    entries: list[WatchlistEntry]  # sorted by composite, best first
    skipped: dict[str, str] = field(default_factory=dict)  # ticker -> reason


def entry_zone(plan: EntryPlan) -> tuple[float, float] | None:
    """Derive [low, high] from the plan's support levels, capped at the 200-day SMA.

    high = best (highest) support, but never above the long-term anchor
    low  = worst (lowest) support minus one ATR of buffer (if ATR is known)
    None when the plan has no support levels at all (degenerate history).
    """
    supports = [lvl.price for lvl in plan.levels if lvl.kind == "support"]
    if not supports:
        return None
    high = max(supports)
    if plan.sma200 is not None:
        high = min(high, plan.sma200)
    low = min(supports) - (plan.atr or 0.0)
    if low >= high:  # single tight support cluster: pad a 2% band below
        low = high * 0.98
    return round(low, 2), round(high, 2)


def build_watchlist(
    finalists: list[dict], histories: dict[str, History], created_at: str
) -> Watchlist:
    """Score every finalist with usable history; report the rest under `skipped`."""
    entries: list[WatchlistEntry] = []
    skipped: dict[str, str] = {}
    for pick in finalists:
        ticker = pick["ticker"]
        closes, highs, lows = histories.get(ticker, ([], [], []))
        if len([c for c in closes if c and c > 0]) < 2:
            skipped[ticker] = "keine verwertbare Kurshistorie"
            continue
        plan = compute_entry_plan(ticker, closes, highs, lows)
        zone = entry_zone(plan)
        if zone is None:
            skipped[ticker] = "keine Support-Levels ableitbar"
            continue
        low, high = zone
        breakdown = pick.get("breakdown", {})
        readings = [
            dip_quality(breakdown, plan),
            value_gap(breakdown, plan),
            momentum(breakdown, plan, closes),
        ]
        entries.append(
            WatchlistEntry(
                ticker=ticker,
                name=pick.get("name", ticker),
                bucket=pick.get("bucket", ""),
                price=plan.price,
                entry_zone_low=low,
                entry_zone_high=high,
                proximity=round(plan.price / high - 1.0, 4),
                in_zone=low <= plan.price <= high,
                composite=composite_score(readings),
                readings=readings,
                reference_note=plan.reference_note,
            )
        )
    entries.sort(key=lambda e: e.composite, reverse=True)
    return Watchlist(created_at=created_at, entries=entries, skipped=skipped)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_radar.py -v` — expected: all PASS.

- [ ] **Step 5: Gate and commit**

```bash
python -m pytest -q && ruff check .
git add src/equity_scout/radar.py tests/test_radar.py
git commit -m "feat: add entry-zone derivation and watchlist builder"
```

---

### Task 7: Radar persistence (`radar_storage.py`)

Follows the repo's storage pattern exactly (see `storage.py`): raw `sqlite3`, idempotent `CREATE TABLE IF NOT EXISTS`, JSON snapshot column, per-function connections via context manager. Adds the append-only `signal_readings` table — Phase 4's training data starts accumulating now.

**Files:**
- Create: `src/equity_scout/radar_storage.py`
- Test: `tests/test_radar_storage.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Round-trip tests for radar persistence (tmp_path SQLite, as in test_storage.py)."""
from __future__ import annotations

import sqlite3

from equity_scout.radar import build_watchlist
from equity_scout.radar_storage import (
    init_radar_db,
    load_latest_watchlist,
    save_watchlist,
)
from tests.test_radar import _finalist
from tests.test_signals import downtrend_history


def _watchlist():
    return build_watchlist(
        [_finalist("DIP")], {"DIP": downtrend_history()}, created_at="2026-07-04T12:00:00"
    )


def test_save_and_load_latest_watchlist_round_trip(tmp_path):
    db = str(tmp_path / "radar.db")
    save_watchlist(db, _watchlist())
    loaded = load_latest_watchlist(db)
    assert loaded is not None
    assert loaded["created_at"] == "2026-07-04T12:00:00"
    assert loaded["entries"][0]["ticker"] == "DIP"
    assert loaded["entries"][0]["readings"][0]["name"] == "dip_quality"


def test_load_latest_returns_none_on_empty_db(tmp_path):
    db = str(tmp_path / "radar.db")
    init_radar_db(db)
    assert load_latest_watchlist(db) is None


def test_save_appends_signal_readings_rows(tmp_path):
    db = str(tmp_path / "radar.db")
    save_watchlist(db, _watchlist())
    save_watchlist(db, _watchlist())  # second snapshot appends, never overwrites
    with sqlite3.connect(db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM signal_readings").fetchone()[0]
    assert count == 6  # 2 snapshots x 1 ticker x 3 readings
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_radar_storage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'equity_scout.radar_storage'`.

- [ ] **Step 3: Write the implementation**

```python
"""SQLite persistence for radar watchlists.

Two tables, same style as storage.py (raw sqlite3, JSON snapshot column):
- watchlists:      one row per radar run (full snapshot, newest wins for the API)
- signal_readings: append-only log of every sub-signal reading — this is the
  training-data seed for the ML combiner (Phase 4). Never UPDATE or DELETE here.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.radar import Watchlist


def init_radar_db(db_path: str = DEFAULT_DB_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS watchlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                data TEXT NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS signal_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                ticker TEXT NOT NULL,
                signal TEXT NOT NULL,
                score REAL NOT NULL,
                price REAL NOT NULL,
                reason TEXT NOT NULL
            )"""
        )


def save_watchlist(db_path: str, watchlist: Watchlist) -> int:
    """Persist one snapshot + append its readings. Returns the snapshot row id."""
    init_radar_db(db_path)
    payload = json.dumps(asdict(watchlist), ensure_ascii=False)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO watchlists (created_at, data) VALUES (?, ?)",
            (watchlist.created_at, payload),
        )
        conn.executemany(
            "INSERT INTO signal_readings (created_at, ticker, signal, score, price, reason)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [
                (watchlist.created_at, e.ticker, r.name, r.score, e.price, r.reason)
                for e in watchlist.entries
                for r in e.readings
            ],
        )
        return int(cursor.lastrowid)


def load_latest_watchlist(db_path: str = DEFAULT_DB_PATH) -> dict | None:
    """Newest snapshot as a plain dict (JSON round-trip), or None if none exists."""
    init_radar_db(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT data FROM watchlists ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return json.loads(row[0]) if row else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_radar_storage.py -v` — expected: all PASS.

- [ ] **Step 5: Gate and commit**

```bash
python -m pytest -q && ruff check .
git add src/equity_scout/radar_storage.py tests/test_radar_storage.py
git commit -m "feat: persist radar watchlists and append-only signal readings"
```

---

### Task 8: Radar CLI (`scripts/run_radar.py`)

**Files:**
- Create: `scripts/run_radar.py`
- Test: `tests/test_run_radar.py`

Before writing: skim `scripts/run_scout.py` and `storage.load_latest_run` for the exact shape of a stored run (`buckets` is `{bucket_name: [pick_dict, ...]}` where each pick dict is `dataclasses.asdict(Pick)` — instrument nested under `"instrument"`). The `_finalists_from_run` helper below flattens that shape; if the actual stored shape differs, adapt the helper (and its test) to reality — reality wins over this plan.

- [ ] **Step 1: Write the failing tests**

```python
"""CLI end-to-end with fakes: stored run -> watchlist in DB + JSON artifact."""
from __future__ import annotations

import json

from equity_scout.radar_storage import load_latest_watchlist
from scripts.run_radar import _finalists_from_run, run_radar
from tests.test_signals import downtrend_history


def _stored_run() -> dict:
    def pick(ticker: str) -> dict:
        return {
            "instrument": {"ticker": ticker, "name": f"{ticker} Inc", "sector": "Tech"},
            "bucket": "core",
            "rank": 1,
            "composite": 0.8,
            "breakdown": {"value": 0.8, "quality": 0.9, "momentum": 0.5, "growth": 0.6},
        }

    return {"created_at": "2026-07-04T06:00:00", "buckets": {"core": [pick("DIP")]}}


def test_finalists_from_run_flattens_buckets():
    finalists = _finalists_from_run(_stored_run())
    assert finalists == [
        {
            "ticker": "DIP",
            "name": "DIP Inc",
            "bucket": "core",
            "breakdown": {"value": 0.8, "quality": 0.9, "momentum": 0.5, "growth": 0.6},
        }
    ]


def test_run_radar_writes_db_snapshot_and_json_artifact(tmp_path):
    db = str(tmp_path / "radar.db")
    out = tmp_path / "watchlist.json"
    count = run_radar(
        run=_stored_run(),
        db_path=db,
        json_out=str(out),
        created_at="2026-07-04T12:00:00",
        fetch_history=lambda ticker: downtrend_history(),
    )
    assert count == 1
    snapshot = load_latest_watchlist(db)
    assert snapshot["entries"][0]["ticker"] == "DIP"
    artifact = json.loads(out.read_text())
    assert artifact["created_at"] == "2026-07-04T12:00:00"
    assert artifact["entries"][0]["entry_zone_high"] > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_run_radar.py -v`
Expected: FAIL — cannot import from `scripts.run_radar`.

- [ ] **Step 3: Write the implementation**

```python
"""Radar CLI: latest funnel run -> entry-signal watchlist.

Usage:
    python scripts/run_radar.py [--db equity_scout.db] [--json-out watchlist.json]

Reads the newest screener run from the DB (run scripts/run_scout.py first),
fetches 1y of history per finalist, computes sub-signals + entry zones, stores
the watchlist snapshot and writes an optional JSON artifact (the file the
GitHub Actions tier will commit back in Phase 5).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timezone

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.entry import fetch_entry_history
from equity_scout.radar import History, build_watchlist
from equity_scout.radar_storage import save_watchlist
from equity_scout.storage import load_latest_run


def _finalists_from_run(run: dict) -> list[dict]:
    """Flatten a stored run's buckets into the finalist dicts radar.build_watchlist eats."""
    finalists: list[dict] = []
    for bucket, picks in run.get("buckets", {}).items():
        for pick in picks:
            instrument = pick.get("instrument", {})
            finalists.append(
                {
                    "ticker": instrument.get("ticker", ""),
                    "name": instrument.get("name", ""),
                    "bucket": bucket,
                    "breakdown": pick.get("breakdown", {}),
                }
            )
    return finalists


def run_radar(
    run: dict,
    db_path: str,
    json_out: str | None,
    created_at: str,
    fetch_history: Callable[[str], History] = fetch_entry_history,
) -> int:
    """Build, persist and (optionally) export the watchlist. Returns entry count."""
    finalists = _finalists_from_run(run)
    histories = {f["ticker"]: fetch_history(f["ticker"]) for f in finalists}
    watchlist = build_watchlist(finalists, histories, created_at=created_at)
    save_watchlist(db_path, watchlist)
    if json_out:
        with open(json_out, "w", encoding="utf-8") as fh:
            json.dump(asdict(watchlist), fh, ensure_ascii=False, indent=2)
    for ticker, reason in watchlist.skipped.items():
        print(f"skipped {ticker}: {reason}")
    return len(watchlist.entries)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()
    run = load_latest_run(args.db)
    if run is None:
        print("No screener run found — run scripts/run_scout.py first.", file=sys.stderr)
        return 1
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    count = run_radar(run, db_path=args.db, json_out=args.json_out, created_at=created_at)
    print(f"Watchlist saved: {count} entries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Note: if `load_latest_run` returns something other than a plain dict (check its signature in `storage.py`), adapt the `main()` wiring — `run_radar()` itself must keep taking a plain dict.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_run_radar.py -v` — expected: all PASS.

- [ ] **Step 5: Gate and commit**

```bash
python -m pytest -q && ruff check .
git add scripts/run_radar.py tests/test_run_radar.py
git commit -m "feat: add radar CLI producing watchlist snapshot and JSON artifact"
```

---

### Task 9: `GET /api/radar` endpoint

**Files:**
- Modify: `src/equity_scout/api.py` (inside `create_app`, next to the `/api/latest` route)
- Test: `tests/test_api.py` (append; follow the file's existing TestClient/fixture style)

- [ ] **Step 1: Write the failing test** (append to `tests/test_api.py`, reusing its existing app/client fixture pattern — read the file first and match it; the sketch below shows intent, adapt fixture names to what exists)

```python
def test_radar_endpoint_returns_latest_watchlist_or_empty(tmp_path):
    from fastapi.testclient import TestClient

    from equity_scout.api import create_app
    from equity_scout.radar import build_watchlist
    from equity_scout.radar_storage import save_watchlist
    from tests.test_radar import _finalist
    from tests.test_signals import downtrend_history

    db = str(tmp_path / "radar.db")
    client = TestClient(create_app(db_path=db))
    empty = client.get("/api/radar")
    assert empty.status_code == 200
    assert empty.json()["watchlist"] is None

    save_watchlist(
        db,
        build_watchlist(
            [_finalist("DIP")], {"DIP": downtrend_history()}, created_at="2026-07-04T12:00:00"
        ),
    )
    loaded = client.get("/api/radar")
    assert loaded.status_code == 200
    body = loaded.json()
    assert body["watchlist"]["entries"][0]["ticker"] == "DIP"
    assert "disclaimer" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api.py -v -k radar`
Expected: FAIL — 404 on `/api/radar`.

- [ ] **Step 3: Implement the route** (inside `create_app`, mirroring the closure style of the existing routes; MUST be added before the `StaticFiles` mount at the bottom)

```python
    @app.get("/api/radar")
    def radar() -> JSONResponse:
        watchlist = load_latest_watchlist(db_path)
        return JSONResponse({"watchlist": watchlist, "disclaimer": DISCLAIMER})
```

Add the import at the top of `api.py`: `from equity_scout.radar_storage import load_latest_watchlist`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_api.py -v` — expected: all PASS (old and new).

- [ ] **Step 5: Gate and commit**

```bash
python -m pytest -q && ruff check .
git add src/equity_scout/api.py tests/test_api.py
git commit -m "feat: expose latest radar watchlist via GET /api/radar"
```

---

### Task 10: Phase gate — full verification + plan outcome

- [ ] **Step 1: Full gate**

Run: `python -m pytest -q && ruff check .`
Expected: entire suite green (was ~200+ tests before this phase; now more), ruff clean. If anything is red: fix before proceeding — never close a phase red.

- [ ] **Step 2: Real-world smoke (uses network; skip gracefully if offline)**

Run: `python scripts/run_radar.py --db equity_scout.db --json-out /tmp/watchlist.json`
Expected: either `Watchlist saved: N entries.` (N > 0, JSON artifact valid) — or exit 1 with the "run scripts/run_scout.py first" hint (then run `python scripts/run_scout.py` once and retry). Record the observed output in the outcome section.

- [ ] **Step 3: Append outcome section to THIS plan document**

Add at the bottom: what was implemented, deviations from the plan (e.g. the stored-run shape in Task 8), open follow-ups, and the smoke-test evidence from Step 2.

- [ ] **Step 4: Log and commit**

```bash
git add docs/superpowers/plans/2026-07-04-trading-copilot-phase-1-radar.md AUTOPILOT_LOG.md
git commit -m "docs: record phase-1 radar outcome"
```

(Append a one-line note to `AUTOPILOT_LOG.md` in the repo root, matching its existing line format.)

---

## Self-review notes (spec coverage)

- Spec §5.1 sub-signals with reason strings + style attribution end-to-end: Tasks 2–5 (readings persisted per style in Task 7 — attribution data exists from day one).
- Spec §4.1 "finalist watchlist + entry levels per stock": Tasks 6–8.
- Spec §9 repo hygiene: Task 1.
- Spec §5.2/§6/§7 (ML, notifications, lanes): explicitly OUT of Phase 1 — Phases 2–4.
- Placeholder scan: the one intentional placeholder is `_COMPOSITE_WEIGHTS` (documented as Phase-4 replacement target) — that is a design decision, not a plan gap.
- Type consistency: `History` tuple alias defined once in `radar.py` and imported by the CLI; `SignalReading` names are string literals in three places (signals, weights dict, tests) — kept as literals to match the repo's plain-data style.
