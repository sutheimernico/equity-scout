# Trading Copilot — Phase 4: Entry-Quality ML with Honest Online Learning

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A model that scores each watchlist entry 0–100 = P(the stock beats SPY over a forward horizon), trained on a price-derived historical backfill with purged walk-forward out-of-sample validation, promoted through a versioned champion/challenger registry, and held honest by an immutable predict-then-resolve prediction ledger — so "the model improves" is a queryable fact, not a claim.

**Architecture:** Reuse the existing ML discipline (`ml/meta_model.purged_walk_forward`, `_build_model`, the StandardScaler→predict_proba loop, the one-class base-rate fallback) — imported, not copied. New modules live under `ml/`. Features are strictly PRICE-DERIVED (regime columns from `ml/features.regime_features`, price-momentum, entry-zone geometry from `entry.compute_entry_plan`) so a historical backfill has NO look-ahead. Labels are relative forward return (stock − SPY over the horizon). Fundamentals are deliberately excluded from the backfill (yfinance has no history → any fundamentals backfill would be look-ahead, ADR 0003); the live `signal_readings` log keeps accumulating the full point-in-time picture for a future fundamentals-aware model. The model artifact is pickled into a versioned SQLite registry; champion/challenger promotion is gated on an out-of-sample score. The prediction ledger logs every live score and a resolver fills in the realized outcome once the horizon elapses.

**Tech Stack:** Python 3.11, scikit-learn ≥1.4 (LogisticRegression/RandomForest + `roc_auc_score`/`brier_score_loss`/`log_loss`/`calibration_curve`), pandas/numpy, stdlib `pickle`/`sqlite3`, yfinance (behind existing lazy seams). **No new dependencies.**

**Spec:** `docs/superpowers/specs/2026-07-04-trading-copilot-design.md` (§5.2)
**Builds on:** Phase 1 (`radar_storage` watchlists + `signal_readings`), Phase 3 (nothing hard, but the arena consumes scores later), `ml/meta_model`, `ml/features`, `data/etf_panel.load_etf_panel`, `market.PricePanel`, `metrics`.

**Conventions that bind every task** (unchanged): English code/docstrings, German user-facing strings with correct umlauts; pure functions + DI seams; `now`/`as_of` injected (datetime.now only in `main()`); imports top-of-file (ruff E402); gate `.venv/bin/python -m pytest && .venv/bin/ruff check .` before EVERY commit (baseline 305 passed — report true totals, never stack `-q`); strict TDD; one commit per task; include plan-doc checkbox edits in commits. Reviews currently run on Opus 4.8 (Sonnet out of credits).

**Honesty invariants (the phase's core promise — a review MUST reject any violation):**
1. NO fundamentals in the backfill training features — price-derived only. Any historical `.info`/fundamentals lookup is look-ahead.
2. Every reported model number is OUT-OF-SAMPLE (purged walk-forward). No in-sample metric is ever presented as performance.
3. The prediction ledger is append-only and resolved against REAL forward prices — never back-filled with a guess.
4. The model SCORES/RANKS entry attractiveness; it never forecasts a price or gives advice. The 0–100 is a calibrated probability, labeled as such.
5. Champion is replaced by a challenger only on a strictly better out-of-sample score.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/equity_scout/ml/entry_eval.py` | create | relative-return labels + classification metrics (AUC/Brier/logloss/calibration/Rank-IC) |
| `src/equity_scout/ml/entry_features.py` | create | price-derived feature row per (ticker, as_of) — no fundamentals |
| `src/equity_scout/ml/entry_dataset.py` | create | historical backfill dataset builder (features + relative-return labels) |
| `src/equity_scout/ml/entry_model.py` | create | `EntryModel` (fit/score 0–100) + walk-forward OOS evaluation |
| `src/equity_scout/ml/model_registry.py` | create | versioned pickled-model registry + champion/challenger promotion |
| `src/equity_scout/ml/prediction_ledger.py` | create | append-only predict-then-resolve ledger + drift snapshot |
| `scripts/run_train_entry.py` | create | CLI: backfill → walk-forward → register challenger → promote if better |
| `scripts/run_resolve_predictions.py` | create | CLI: resolve due predictions against realized forward returns |
| `src/equity_scout/api.py` | modify | `GET /api/model` (registry, calibration, drift, resolved ledger stats) |
| `tests/test_entry_eval.py`, `test_entry_features.py`, `test_entry_dataset.py`, `test_entry_model.py`, `test_model_registry.py`, `test_prediction_ledger.py`, `test_run_train_entry.py`, `test_run_resolve_predictions.py` | create | per-module |
| `tests/test_api.py` | modify | `/api/model` |

Horizons: primary `HORIZON_DAYS = 20` (~4 weeks), secondary `SECONDARY_HORIZON_DAYS = 60` (~12 weeks) — constants in `entry_eval.py`.

---

### Task 1: Relative-return labels + classification metrics (`entry_eval.py`)

**Files:**
- Create: `src/equity_scout/ml/entry_eval.py`
- Test: `tests/test_entry_eval.py`

- [x] **Step 1: Write the failing tests**

```python
"""Entry-eval tests: relative-return labels + OOS classification metrics."""
from __future__ import annotations

import numpy as np
import pandas as pd

from equity_scout.ml.entry_eval import (
    HORIZON_DAYS,
    beats_benchmark_label,
    classification_scores,
    rank_ic,
)


def _prices(values: list[float]) -> pd.Series:
    idx = pd.date_range("2026-01-01", periods=len(values), freq="B")
    return pd.Series(values, index=idx)


def test_beats_benchmark_label_is_relative_not_absolute():
    # stock +10% over the horizon, benchmark +4% → beats (1). Both up, but relative wins.
    stock = _prices([100.0] * 1 + [110.0] * (HORIZON_DAYS + 1))
    bench = _prices([100.0] * 1 + [104.0] * (HORIZON_DAYS + 1))
    at = stock.index[0]
    assert beats_benchmark_label(stock, bench, at, horizon_days=HORIZON_DAYS) == 1
    # stock +2%, benchmark +5% → loses (0) even though the stock rose
    stock2 = _prices([100.0] + [102.0] * (HORIZON_DAYS + 1))
    bench2 = _prices([100.0] + [105.0] * (HORIZON_DAYS + 1))
    assert beats_benchmark_label(stock2, bench2, at, horizon_days=HORIZON_DAYS) == 0


def test_beats_benchmark_label_none_without_full_horizon():
    stock = _prices([100.0, 101.0])
    bench = _prices([100.0, 100.5])
    assert beats_benchmark_label(stock, bench, stock.index[0], horizon_days=HORIZON_DAYS) is None


def test_classification_scores_reward_a_good_ranker():
    y = np.array([0, 0, 1, 1, 1, 0, 1, 0])
    good = np.array([0.1, 0.2, 0.8, 0.7, 0.9, 0.3, 0.6, 0.25])
    scores = classification_scores(y, good)
    assert 0.8 <= scores["auc"] <= 1.0
    assert 0.0 <= scores["brier"] <= 0.25
    assert scores["n"] == 8
    assert "log_loss" in scores and "base_rate" in scores
    assert scores["base_rate"] == 0.5


def test_classification_scores_single_class_auc_is_none_not_crash():
    y = np.array([1, 1, 1])
    scores = classification_scores(y, np.array([0.6, 0.7, 0.8]))
    assert scores["auc"] is None  # AUC undefined with one class — reported honestly, not faked
    assert scores["n"] == 3


def test_rank_ic_detects_monotonic_ranking():
    scores = np.array([0.1, 0.4, 0.6, 0.9])
    realized = np.array([-0.02, 0.01, 0.03, 0.08])  # higher score → higher realized rel-return
    assert rank_ic(scores, realized) > 0.9
    assert rank_ic(scores, -realized) < -0.9
```

- [x] **Step 2: Run tests to verify they fail** — `.venv/bin/python -m pytest tests/test_entry_eval.py -v` → `ModuleNotFoundError`.

- [x] **Step 3: Write the implementation**

```python
"""Labels and out-of-sample metrics for the entry-quality model.

Label = did the stock BEAT the benchmark (SPY) over the forward horizon — a relative
return, not an absolute one (spec §5.2). Metrics are classification/ranking metrics
(AUC, Brier, log-loss, Rank-IC) because the model outputs a probability, not a return.
Everything here is computed on OUT-OF-SAMPLE predictions by the caller — this module
has no notion of train/test, it just scores arrays honestly (AUC is None, never faked,
when a fold has one class).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

HORIZON_DAYS = 20  # ~4 weeks, the primary forward horizon
SECONDARY_HORIZON_DAYS = 60  # ~12 weeks


def forward_return(prices: pd.Series, at: pd.Timestamp, horizon_days: int) -> float | None:
    """Simple return from `at` to `horizon_days` trading days later. None if the series
    does not extend a full horizon past `at`."""
    if at not in prices.index:
        return None
    pos = prices.index.get_loc(at)
    end = pos + horizon_days
    if end >= len(prices):
        return None
    start_px, end_px = float(prices.iloc[pos]), float(prices.iloc[end])
    if start_px <= 0:
        return None
    return end_px / start_px - 1.0


def relative_forward_return(
    stock: pd.Series, benchmark: pd.Series, at: pd.Timestamp, horizon_days: int
) -> float | None:
    """Stock forward return minus benchmark forward return over the same window."""
    s = forward_return(stock, at, horizon_days)
    b = forward_return(benchmark, at, horizon_days)
    if s is None or b is None:
        return None
    return s - b


def beats_benchmark_label(
    stock: pd.Series, benchmark: pd.Series, at: pd.Timestamp, *, horizon_days: int
) -> int | None:
    """1 if the stock's forward return exceeds the benchmark's, else 0. None if the
    horizon is not fully observable (no peeking past the data)."""
    rel = relative_forward_return(stock, benchmark, at, horizon_days)
    return None if rel is None else int(rel > 0.0)


def classification_scores(y_true: np.ndarray, y_prob: np.ndarray) -> dict:
    """OOS classification metrics. AUC is None (not faked) when y_true is single-class."""
    y_true = np.asarray(y_true, dtype=int)
    y_prob = np.asarray(y_prob, dtype=float)
    n = int(len(y_true))
    base_rate = float(y_true.mean()) if n else 0.0
    single_class = len(np.unique(y_true)) < 2
    auc = None if single_class else float(roc_auc_score(y_true, y_prob))
    # log_loss needs both labels present; guard the single-class case honestly
    ll = None if single_class else float(log_loss(y_true, y_prob, labels=[0, 1]))
    return {
        "n": n,
        "base_rate": round(base_rate, 4),
        "auc": None if auc is None else round(auc, 4),
        "brier": round(float(brier_score_loss(y_true, y_prob)), 4) if n else None,
        "log_loss": None if ll is None else round(ll, 4),
    }


def rank_ic(scores: np.ndarray, realized: np.ndarray) -> float:
    """Spearman rank correlation between model scores and realized relative returns —
    the honest 'does a higher score actually mean a better outcome' number."""
    s = pd.Series(np.asarray(scores, dtype=float))
    r = pd.Series(np.asarray(realized, dtype=float))
    if len(s) < 2 or s.nunique() < 2 or r.nunique() < 2:
        return 0.0
    return round(float(s.corr(r, method="spearman")), 4)
```

- [x] **Step 4: Run tests** — all PASS.
- [x] **Step 5: Gate and commit**

```bash
.venv/bin/python -m pytest && .venv/bin/ruff check .
git add src/equity_scout/ml/entry_eval.py tests/test_entry_eval.py
git commit -m "feat: add relative-return labels and OOS classification metrics"
```

---

### Task 2: Price-derived feature builder (`entry_features.py`)

**Files:**
- Create: `src/equity_scout/ml/entry_features.py`
- Test: `tests/test_entry_features.py`

Feature row for one (ticker, as_of) from PAST prices only. Combines: the market-regime columns (reuse `ml.features.regime_features` on the benchmark — same value for every ticker on a date, that's fine, it's market context) and per-stock price geometry: `mom_1m`/`mom_3m`/`mom_6m` (trailing returns), `dist_sma200` (price/200d-mean − 1), `drawdown_1y` (price/252d-max − 1), `vol_3m` (annualized 63d stdev). NO fundamentals. `FEATURE_COLUMNS` is the ordered, single-source feature list.

- [x] **Step 1: Write the failing tests** — assert: `build_feature_row(stock_closes, market_context_row, as_of)` returns a dict with exactly `FEATURE_COLUMNS` keys; a deep-drawdown synthetic series yields negative `drawdown_1y` and `dist_sma200`; insufficient history (`< 252` closes before `as_of`) returns `None` (honest: can't build a full feature row); momentum signs correct on monotone up/down series. Full test code following the `entry.py`/`signals.py` synthetic-history style.
- [x] **Step 2: Run → fail.**
- [x] **Step 3: Implement** — `FEATURE_COLUMNS: tuple[str, ...]` (market-context names from a documented subset of `regime_features` + the per-stock names), `build_feature_row(stock: pd.Series, context: dict[str, float], as_of: pd.Timestamp) -> dict | None`, and `market_context(panel, benchmark="SPY") -> pd.DataFrame` (thin wrapper over `regime_features` selecting the reused columns). Pure; all rolling windows use only data at/asof `as_of`. Document the no-fundamentals invariant in the module docstring. (Market-context columns are `mkt_`-prefixed in the row to avoid the `mom_3m` name collision with the per-stock momentum.)
- [x] **Step 4: Run → pass.**
- [x] **Step 5: Commit** `feat: add price-derived entry feature builder (no fundamentals)`.

---

### Task 3: Historical backfill dataset (`entry_dataset.py`)

**Files:**
- Create: `src/equity_scout/ml/entry_dataset.py`
- Test: `tests/test_entry_dataset.py`

Assemble `(X, y, meta)` from a `PricePanel` of stock tickers + benchmark over history: for each ticker and each sampled as_of date (monthly `rebalance_dates`), build the feature row (Task 2) and the `beats_benchmark_label` (Task 1); keep only rows where BOTH the features and the full-horizon label exist. `meta` carries `(ticker, as_of, relative_return)` per row for Rank-IC and attribution.

- [x] **Step 1: Failing tests** — with a synthetic 2-ticker + benchmark panel (build via `PricePanel(pd.DataFrame(...))`), `build_backfill_dataset(panel, tickers, benchmark="SPY", horizon_days=HORIZON_DAYS)` returns aligned `X` (DataFrame, columns == FEATURE_COLUMNS), `y` (0/1 Series), `meta` (DataFrame with ticker/as_of/relative_return); rows near the panel's end (no full horizon) are dropped; a ticker with too-short history contributes nothing but doesn't crash; label balance is reported. Full test code.
- [x] **Step 2: Run → fail.**
- [x] **Step 3: Implement** `build_backfill_dataset(panel, tickers, *, benchmark="SPY", horizon_days=HORIZON_DAYS, min_history=252) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]`. Reuse `entry_features.market_context` once for the panel, then loop tickers × rebalance dates. Deterministic ordering (sort by as_of then ticker) so walk-forward splits are reproducible.
- [x] **Step 4: Run → pass.**
- [x] **Step 5: Commit** `feat: add historical backfill dataset builder for entry model`.

---

### Task 4: Entry model + walk-forward evaluation (`entry_model.py`)

**Files:**
- Create: `src/equity_scout/ml/entry_model.py`
- Test: `tests/test_entry_model.py`

Wrap the reused `_build_model` + StandardScaler. `EntryModel` holds the fitted scaler+estimator+feature order; `.score_many(X) -> np.ndarray` of 0–100 integers (`round(predict_proba[:,1]*100)`); `.score_row(dict) -> int`. `train_entry_model(X, y, *, model="random_forest") -> EntryModel`. `walk_forward_evaluate(X, y, meta, *, model, n_splits, horizon_days) -> dict` reuses `ml.meta_model.purged_walk_forward` over the sorted unique as_of dates (group-aware: all rows sharing an as_of go to the same side of a split — the split is on DATES, rows are selected by membership), producing OOS probabilities → `entry_eval.classification_scores` + `rank_ic` against `meta.relative_return`. One-class-train fold falls back to base rate (mirror meta_model).

- [x] **Step 1: Failing tests** — a learnable synthetic dataset (feature linearly separable-ish from label) trains to OOS AUC > 0.6; `score_many` returns ints in [0,100] monotonic in the signal; walk-forward returns `{"auc","brier","rank_ic","n_oos","n_splits_used","feature_importance"}`; a pure-noise dataset yields AUC ≈ 0.5 (no fake edge); reproducible (seeded). Full test code.
- [x] **Step 2: Run → fail.**
- [x] **Step 3: Implement.** Group-by-date walk-forward: build `date_index = sorted(meta.as_of.unique())`, run `purged_walk_forward` on that DatetimeIndex, map train/test dates → row masks via `meta.as_of.isin(...)`. This keeps the horizon-purge meaningful (a label's window is tied to its as_of). Document why grouping matters (rows on the same date share look-ahead exposure).
- [x] **Step 4: Run → pass.**
- [x] **Step 5: Commit** `feat: add entry-quality model with purged walk-forward evaluation`.

---

### Task 5: Versioned model registry (`model_registry.py`)

**Files:**
- Create: `src/equity_scout/ml/model_registry.py`
- Test: `tests/test_model_registry.py`

SQLite table `entry_models(version INTEGER PK AUTOINCREMENT, created_at, model_kind TEXT, feature_columns TEXT, n_train INTEGER, metrics_json TEXT, is_champion INTEGER DEFAULT 0, artifact BLOB)`. The fitted `EntryModel` is `pickle`d into `artifact`. `register_challenger(db, model, *, metrics, now) -> version`. `champion(db) -> (version, EntryModel, metrics) | None`. `promote_if_better(db, version, *, metric_key="auc") -> bool` — compares the candidate's OOS metric to the current champion's; promotes (sets `is_champion`, unsets the old) ONLY if strictly greater (None/degenerate champion → auto-promote the first trained model). `registry_summary(db) -> dict` (version list with metrics + created_at + champion flag, newest first) for the API.

- [x] **Step 1: Failing tests** (tmp_path): register two models, promote; champion round-trips the pickled model and can `.score_row`; a worse challenger does NOT displace the champion; the first model auto-promotes; `promote_if_better` is idempotent; `registry_summary` shape. Pickle a tiny real `EntryModel` trained on a 20-row synthetic set. Full test code.
- [x] **Step 2: Run → fail.**
- [x] **Step 3: Implement.** Guard pickle load with a clear error if the class shape changed. `metric_key` comparison treats `None` as −inf (an un-scored challenger never wins). Champion flip is one transaction.
- [x] **Step 4: Run → pass.**
- [x] **Step 5: Commit** `feat: add versioned entry-model registry with champion/challenger promotion`.

---

### Task 6: Prediction ledger + drift (`prediction_ledger.py`)

**Files:**
- Create: `src/equity_scout/ml/prediction_ledger.py`
- Test: `tests/test_prediction_ledger.py`

The honesty centerpiece. Table `entry_predictions(id PK, created_at, model_version INTEGER, ticker, score INTEGER, horizon_days INTEGER, features_json TEXT, resolve_after TEXT, resolved_at TEXT, realized_relative_return REAL, label INTEGER, correct INTEGER)` — append-only for the prediction; a SINGLE later UPDATE per row fills the resolution columns (documented: the only mutation, one-way open→resolved, never re-resolved). `log_predictions(db, *, model_version, scored: list[tuple[ticker, score, features]], now, horizon_days)` sets `resolve_after = now + horizon_days` (calendar days, a safe over-estimate of trading days). `due_predictions(db, now) -> list[dict]` = unresolved with `resolve_after <= now`. `resolve_prediction(db, prediction_id, *, realized_relative_return, resolved_at)` (computes label = int(rel>0), correct vs score>=50). `resolved_stats(db, model_version=None) -> dict` — realized hit-rate, mean realized rel-return by score-bucket, Rank-IC of score vs realized, n_resolved/n_open. `drift_snapshot(training_feature_means: dict, recent_features: list[dict]) -> dict` — per-feature z-shift of recent live features vs the training means (simple, honest distribution-shift flag).

- [x] **Step 1: Failing tests** (tmp_path): log 3 predictions → all open, none due before `resolve_after`; `due_predictions` returns them once `now` passes `resolve_after`; resolving one sets label/correct and it leaves the open set; double-resolve is refused (stays at first resolution); `resolved_stats` computes hit-rate + rank_ic over resolved rows only; append-only (resolving never deletes/duplicates; count stable); `drift_snapshot` flags a shifted feature and not a stable one. Full test code.
- [x] **Step 2: Run → fail.**
- [x] **Step 3: Implement.** `resolve_prediction` UPDATE guarded `WHERE id=? AND resolved_at IS NULL` (rowcount==1 → applied, else already resolved). `resolved_stats` reuses `entry_eval.rank_ic`.
- [x] **Step 4: Run → pass.**
- [x] **Step 5: Commit** `feat: add append-only prediction ledger with resolution and drift snapshot`.

---

### Task 7: Train + resolve CLIs (`run_train_entry.py`, `run_resolve_predictions.py`)

**Files:**
- Create: `scripts/run_train_entry.py`, `scripts/run_resolve_predictions.py`
- Test: `tests/test_run_train_entry.py`, `tests/test_run_resolve_predictions.py`

`run_train_entry`: load/refresh a stock+SPY `PricePanel` (reuse `data/etf_panel.load_etf_panel` with a distinct snapshot path, tickers from the latest universe/watchlist or a `--tickers` list), `build_backfill_dataset`, `walk_forward_evaluate` for the configured model kind(s), `train_entry_model` on the full set, `register_challenger` with the OOS metrics, `promote_if_better`. Print an honest German summary (OOS AUC/Brier/Rank-IC, promoted yes/no). This is the nightly-retrain entrypoint (Phase 5 wires it to cron). `run_resolve_predictions`: `due_predictions`, fetch realized relative returns via an injectable `fetch_prices` (default `load_etf_panel` for the due tickers + SPY over the needed window), `resolve_prediction` each. Both: `run_*()` core takes injected data/fetch seams (no network in tests), `main()` thin argparse; datetime.now only in main().

- [ ] **Step 1: Failing tests** — inject a synthetic panel / fetch fake: train CLI builds a dataset, evaluates, registers a model, promotes the first one, exit 0; second run registers v2 and promotes only if better (assert champion logic end-to-end); resolve CLI resolves due predictions via the fake and leaves not-yet-due ones open; both `main()` paths with monkeypatched loaders (no network), exit 0. Follow `tests/test_run_lanes.py` patterns.
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement both CLIs.**
- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit** `feat: add entry-model train and prediction-resolve CLIs`.

---

### Task 8: `GET /api/model` + phase gate

**Files:**
- Modify: `src/equity_scout/api.py`, `tests/test_api.py`

`GET /api/model` → `{"available": bool, "champion": {version, created_at, model_kind, metrics} | None, "registry": [...registry_summary...], "resolved": {...resolved_stats...}, "drift": {...} | None, "disclaimer": DISCLAIMER}`. `available:false` when no model registered. Route before StaticFiles mount; reuse `model_registry.registry_summary`/`champion` + `prediction_ledger.resolved_stats`. Framing in the disclaimer stays "scores rank entry attractiveness, out-of-sample; not a forecast, not advice."

- [ ] **Step 1: Failing test** — empty → available:false; after registering a model + resolving a couple predictions → champion present with metrics, registry non-empty, resolved stats present, disclaimer present.
- [ ] **Step 2: Run → fail (404).**
- [ ] **Step 3: Implement route.**
- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Gate + live smoke + outcome.**
  - Full gate `.venv/bin/python -m pytest && .venv/bin/ruff check .`.
  - Live smoke (network): `python scripts/run_train_entry.py --db equity_scout.db --tickers <a few watchlist tickers>` — record OOS AUC/Brier/Rank-IC and whether a model was promoted; then `GET /api/model` shape. Honest recording: if OOS AUC ≈ 0.5, SAY SO — a null result is a valid, honest outcome and must not be dressed up.
  - Extend the README copilot section (train/resolve commands + `/api/model`).
  - Append the outcome section + one `AUTOPILOT_LOG.md` line; commit `docs: record phase-4 entry-ml outcome`.

---

## Self-review notes (spec coverage)

- Spec §5.2 Entry-Quality-Score 0–100 = P(beat benchmark): Tasks 1 (label), 4 (score_many → 0–100 from predict_proba).
- Spec §5.2 combines sub-signals + market context: Task 2 (price-momentum geometry + regime_features market context) — fundamentals deliberately deferred to the live-log model (honesty invariant #1, ADR 0003).
- Spec §5.2 nightly walk-forward retraining: Task 4 (`walk_forward_evaluate` reuses `purged_walk_forward`) + Task 7 (`run_train_entry` is the nightly entrypoint; Phase 5 crons it).
- Spec §5.2 champion/challenger, versioned registry, metrics: Task 5.
- Spec §5.2 drift monitoring: Task 6 (`drift_snapshot`) + Task 8 (surfaced).
- Spec §5.2 immutable prediction ledger resolved against reality: Task 6 (append-only, one-way resolve) + Task 7 (`run_resolve_predictions`).
- Honesty invariants: enforced in module docstrings + tests (single-class AUC=None, noise→AUC≈0.5, OOS-only, one-way resolve, strict promotion). Reviews must reject any in-sample-as-performance or fundamentals-in-backfill violation.
- Deliberate scope cuts: the live fundamentals-aware model waits for `signal_readings` history (ADR 0003 — months); FRED macro features optional/off by default (already gated in `regime_features`); no hyperparameter search loop here (the registry + a fixed small model set is enough for v1 — the existing research loop pattern can be adopted later if the backfill shows a real edge worth searching).
- Type consistency: `FEATURE_COLUMNS` single-sourced in `entry_features.py`; `HORIZON_DAYS`/`SECONDARY_HORIZON_DAYS` in `entry_eval.py`; `EntryModel` is the only pickled artifact; the score is always `round(proba*100)` in exactly one place.
