# Autotrader Review Upgrades Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the evidence-backed upgrades from the 2026-08-16 external review (literature research + repo audit): VIX-calibrated vol targeting, an honest real-money bar, a regime-clean crypto verdict, an inverse-vol allocator tilt, a rebalance-timing-luck measurement, an independent price cross-check, and the 126-day fundamentals horizon.

**Architecture:** Every change follows the repo's existing seams — pure logic in `src/equity_scout/`, I/O in `scripts/`, new logic ships with a test, behaviour changes to the live depot are marked as regime breaks. Two tasks are measurements, not builds (Task 5), or documentation of a pre-registered criterion (Task 3) — the repo's "measure before you build" rule.

**Tech Stack:** Python 3 / pandas / pytest / ruff (existing), React+TS frontend (Task 2 only), Stooq free CSV endpoint (Task 6, new read-only data source).

**Branch:** `autopilot/work` (loop convention). Gate per task: `uv run pytest -q` green AND `uv run ruff check .` clean. Conventional Commits, English.

---

## Review provenance & deliberate NON-goals

Source: external review session 2026-08-16 (literature agents + repo factsheet). The review's findings that map to tasks here:

| Review finding | Task |
|---|---|
| VIX forecasts 20d vol better than trailing (own study 2026-08-12, rho 0.642 vs 0.539); Harvey et al. 2018: vol scaling helps risk assets | Task 1 |
| Sharpe>1 + MaxDD<15% in 180d is above what CTAs sustain (SG CTA ~0.4 net) and statistically undecidable in 180d; own W0: return not predictable, risk is | Task 2 |
| Crypto verdict "negativ" mixes the 15-min era (fee-destroyed) with the daily era (n=0) — regime-mixed verdicts are the champion-artifact lesson again | Task 3 |
| Sharpe-softmax on 63 daily obs is the estimation-error trap (DeMiguel 2009); vol IS estimable on 63 obs → inverse-vol tilt | Task 4 |
| Rebalance-day choice creates large return dispersion (Hoffstein/Faber 2020); all sleeves rebalance ME | Task 5 (measure first) |
| yfinance is an unofficial scraper and the depot's single price source — a WRONG price is caught nowhere | Task 6 |
| Fundamentals act over quarters; the 10/20/60d target families are exhausted at coin-flip AUC (Achse 2) | Task 7 |

**Deliberately NOT in this plan:**

- **VIX term structure as regime signal 5** — the external literature recommends it, but the own W0 study (2026-08-11) already tested it INCREMENTALLY: rank-IC 0.51 raw → **0.08** after removing what VIX level + breadth already say. Verdict there: "W1 VIX-Terminstruktur — gestrichen." The in-house measurement on this exact setup beats the literature prior. Do not re-add without new evidence.
- **Tranching build** — Task 5 measures whether timing luck is material here first. Building tranched sleeves would also create new strategy identities with fresh forward tracks (repo rule); that decision needs the measurement and Nico's go.
- **PEAD / turn-of-month / overnight / short-term-reversal lanes** — all independently refuted by the 2026-08-16 backtest series AND the literature.
- **Any real-money anything** — LOOP.md iron constraint, unchanged.

**Nico decision gates inside this plan:** Task 2 threshold VALUES (defaults proposed, his veto), Task 3 (his 2026-08-16 standing decision was "leave crypto untouched" — Task 3 changes measurement honesty only, zero trading behaviour; confirm framing before executing).

---

### Task 1: VIX-calibrated forward-vol multiplier in VolTarget

The depot's `VolTarget` throttles on trailing 20-day vol — i.e. after vol has risen. The own study (docs/research/2026-08-12-voltarget-uses-the-weaker-estimator.md) proved VIX predicts the same window better but reads ~36% high (variance risk premium). Build constraints already recorded in PLAN.md: dimensionless multiplier `(calibrated VIX forecast) / (SPY trailing)` applied to the DEPOT's own trailing vol, never the SPY level; VIX outage → fall back to trailing, never "no risk".

**Files:**
- Create: `src/equity_scout/vol_forecast.py`
- Modify: `src/equity_scout/autotrader_protections.py` (RiskContext ~line 43-51, VolTarget ~line 159-187)
- Modify: `src/equity_scout/autotrader_engine.py` (`advance_depot` signature ~line 233-247, `RiskContext(...)` construction ~line 424-427)
- Modify: `scripts/run_autotrader.py` (`advance_autotrader` ~line 266, `main()` ~line 441)
- Test: `tests/test_vol_forecast.py` (new), `tests/test_autotrader_protections.py` (extend)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_vol_forecast.py`:

```python
"""vol_forecast: the VIX-calibrated multiplier for VolTarget (study 2026-08-12)."""
import math

import pandas as pd

from equity_scout.vol_forecast import (
    MULTIPLIER_CLAMP,
    TRAILING_WINDOW,
    VIX_DIVISOR,
    trailing_vol,
    vix_multiplier,
)


def _flat_closes(n: int = 40, daily_return: float = 0.01) -> pd.Series:
    # alternating +1%/-1% days -> stable, known trailing vol
    values, price = [], 100.0
    for i in range(n):
        price *= 1.0 + (daily_return if i % 2 == 0 else -daily_return)
        values.append(price)
    return pd.Series(values, index=pd.bdate_range("2026-01-01", periods=n))


def test_trailing_vol_needs_enough_history():
    assert trailing_vol(_flat_closes(n=TRAILING_WINDOW - 1)) is None


def test_trailing_vol_is_annualised_and_positive():
    vol = trailing_vol(_flat_closes())
    assert vol is not None and 0.1 < vol < 0.3  # ~1% daily -> ~16% annualised


def test_multiplier_is_forecast_over_trailing():
    closes = _flat_closes()
    spy_trailing = trailing_vol(closes)
    vix_level = 20.0
    expected = (vix_level / 100.0 / VIX_DIVISOR) / spy_trailing
    result = vix_multiplier(vix_level, closes)
    assert result is not None
    assert math.isclose(result, expected, rel_tol=1e-9)


def test_missing_inputs_yield_none():
    assert vix_multiplier(None, _flat_closes()) is None
    assert vix_multiplier(20.0, None) is None
    assert vix_multiplier(20.0, _flat_closes(n=5)) is None


def test_implausibly_low_ratio_is_distrusted_not_clipped():
    # a bad print (VIX 0.16 instead of 16) must NOT switch the protection off
    assert vix_multiplier(0.16, _flat_closes()) is None


def test_high_ratio_is_clipped_to_the_cap_not_distrusted():
    # a genuine spike must keep throttling (more throttle is the safe direction)
    result = vix_multiplier(500.0, _flat_closes())
    assert result == MULTIPLIER_CLAMP[1]
```

Extend `tests/test_autotrader_protections.py` (if the file already has a returns/ctx helper, reuse it instead of `_alternating_returns`):

```python
def _alternating_returns(daily: float, n: int = 30) -> pd.Series:
    # +daily/-daily alternating -> mean ~0, stdev ~daily; annualised ~daily*sqrt(252)
    values = [daily if i % 2 == 0 else -daily for i in range(n)]
    return pd.Series(values, index=pd.bdate_range("2026-01-01", periods=n))


def test_vol_target_without_multiplier_behaves_as_before():
    # trailing ~0.111 annualised, just UNDER the 0.12 target -> no action, exactly as today
    ctx = RiskContext(
        as_of=pd.Timestamp("2026-08-16"), depot_returns=_alternating_returns(0.007)
    )
    weights, event = VolTarget().apply({"SPY": 0.8}, ctx)
    assert weights == {"SPY": 0.8} and event is None


def test_vol_target_multiplier_scales_the_estimate():
    # same trailing vol, forecast multiplier 2.0 -> estimate ~0.222 > 0.12 -> throttles,
    # and the event names the forecast source
    ctx = RiskContext(
        as_of=pd.Timestamp("2026-08-16"),
        depot_returns=_alternating_returns(0.007),
        vol_multiplier=2.0,
    )
    weights, event = VolTarget().apply({"SPY": 0.8}, ctx)
    assert weights["SPY"] < 0.8
    assert event is not None and "VIX-Prognose" in event.detail
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_vol_forecast.py -q`
Expected: FAIL/ERROR with `ModuleNotFoundError: equity_scout.vol_forecast`

- [ ] **Step 3: Implement `src/equity_scout/vol_forecast.py`**

```python
"""VIX-calibrated forward-vol multiplier for the VolTarget protection (study 2026-08-12).

`VolTarget` throttles on the depot's TRAILING 20-day vol, i.e. after volatility has already
risen. The study (docs/research/2026-08-12-voltarget-uses-the-weaker-estimator.md, reproducible
via scripts/run_vol_forecast_study.py) showed the VIX predicts the same 20-day window better
(rho 0.642 vs 0.539 on 233 non-overlapping windows over 19 years) but reads ~36% high, because
implied vol carries the variance risk premium. Build rules, from the study + PLAN.md:

- DIMENSIONLESS multiplier only: (calibrated VIX forecast) / (SPY trailing vol), applied by the
  caller to the depot's OWN trailing vol. The depot is multi-asset with lower absolute vol, so
  the SPY level itself must never be used directly.
- The calibration divisor was fitted on 2007-2016 ONLY and held out of sample on 2017-2026
  (calibration ratio 1.07). It is a pinned constant here, never a live re-fit.
- Any missing or implausible input -> None; the caller falls back to the trailing estimator.
  A data gap must never be read as "no risk".
"""
from __future__ import annotations

import math

import pandas as pd

from equity_scout.market import TRADING_DAYS_PER_YEAR

VIX_DIVISOR = 1.341  # variance-risk-premium divisor: fitted < 2017, verified OOS >= 2017
TRAILING_WINDOW = 20  # VolTarget's own window — the multiplier answers ITS question
# Plausibility band for forecast/trailing. Asymmetric on purpose: an implausibly LOW ratio
# (bad VIX print like 0.16) would switch the protection off, so it is distrusted (None ->
# trailing fallback). An extreme HIGH ratio only over-throttles, which is the safe direction,
# so it is clipped to the cap instead of discarded.
MULTIPLIER_CLAMP = (0.5, 3.0)


def trailing_vol(closes: pd.Series | None, window: int = TRAILING_WINDOW) -> float | None:
    """Annualised stdev of the last `window` daily returns; None when too short/degenerate."""
    if closes is None:
        return None
    returns = closes.astype(float).pct_change().dropna()
    if len(returns) < window:
        return None
    vol = float(returns.iloc[-window:].std(ddof=1)) * math.sqrt(TRADING_DAYS_PER_YEAR)
    return vol if math.isfinite(vol) and vol > 0 else None


def vix_multiplier(vix_level: float | None, spy_closes: pd.Series | None) -> float | None:
    """Forecast/trailing ratio, or None when either leg is missing or implausible."""
    if vix_level is None:
        return None
    spy_trailing = trailing_vol(spy_closes)
    if spy_trailing is None:
        return None
    forecast = (float(vix_level) / 100.0) / VIX_DIVISOR  # VIX quotes percentage points
    if not math.isfinite(forecast) or forecast <= 0:
        return None
    ratio = forecast / spy_trailing
    low, high = MULTIPLIER_CLAMP
    if not math.isfinite(ratio) or ratio < low:
        return None
    return min(ratio, high)
```

- [ ] **Step 4: Extend `RiskContext` and `VolTarget` in `autotrader_protections.py`**

Add one field to `RiskContext` (after `drawdown`):

```python
    vol_multiplier: float | None = None  # VIX-forecast/trailing ratio (vol_forecast.py); None = trailing only
```

Replace the body of `VolTarget.apply` (keep signature):

```python
    def apply(
        self, weights: dict[str, float], ctx: RiskContext
    ) -> tuple[dict[str, float], RiskEvent | None]:
        returns = ctx.depot_returns
        if returns is None or len(returns) < self.window + 1 or not weights:
            return weights, None
        recent = returns.iloc[-self.window:]
        trailing = float(recent.std(ddof=1)) * math.sqrt(TRADING_DAYS_PER_YEAR)
        if not math.isfinite(trailing):
            return weights, None
        multiplier = ctx.vol_multiplier if ctx.vol_multiplier is not None else 1.0
        vol = trailing * multiplier
        if vol <= self.target:
            return weights, None
        factor = self.target / vol
        source = "VIX-Prognose" if ctx.vol_multiplier is not None else "trailing"
        return _scale(weights, factor), RiskEvent(
            protection=self.name,
            action=f"scale_{factor:.2f}",
            detail=(
                f"Depot-Vol ({source}) {vol:.1%} über Ziel {self.target:.0%} — "
                f"Exposure auf {factor:.0%} skaliert"
            ),
        )
```

Update the `VolTarget` docstring to state: estimator = own trailing vol × VIX-forecast multiplier when available (study 2026-08-12), trailing alone otherwise; behaviour change dated 2026-08-16, visible per-event via the `(VIX-Prognose)`/`(trailing)` label in the RiskEvent detail.

- [ ] **Step 5: Thread the multiplier through `advance_depot`**

In `src/equity_scout/autotrader_engine.py`, add to the `advance_depot` keyword parameters (after `depot_returns`):

```python
    vol_multiplier: float | None = None,
```

and extend the `RiskContext(...)` construction (~line 424):

```python
    ctx = RiskContext(
        as_of=today, regime_level=regime_level, depot_returns=depot_returns,
        drawdown=drawdown, breaker=account.breaker, vol_multiplier=vol_multiplier,
    )
```

- [ ] **Step 6: Wire it in `scripts/run_autotrader.py`**

Add import near the other `equity_scout` imports:

```python
from equity_scout.vol_forecast import vix_multiplier
```

Add a collector next to `_collect_regime_level` (same degradation philosophy — loud on stderr, never a crash):

```python
def _collect_vol_multiplier(panel: PricePanel) -> float | None:
    """VIX close -> VolTarget forecast multiplier; any failure -> None (trailing fallback).

    Loud on stderr for the same reason as _collect_regime_level: a permanently silent None
    means the depot quietly runs on the weaker estimator forever."""
    try:
        vix_panel = load_price_history(
            ["^VIX"], start="2024-01-01", snapshot="data/prices/vix_level.csv", refresh=True
        )
        vix_level = float(vix_panel.closes["^VIX"].dropna().iloc[-1])
    except Exception as err:  # noqa: BLE001 — feed down = honest fallback, not a crash
        print(f"Warnung: VIX nicht ladbar ({type(err).__name__}: {err}) — "
              "VolTarget nutzt trailing Vola.", file=sys.stderr)
        return None
    spy = panel.closes["SPY"].dropna() if "SPY" in panel.closes.columns else None
    multiplier = vix_multiplier(vix_level, spy)
    if multiplier is None:
        print("Warnung: VIX-Multiplikator nicht berechenbar — VolTarget nutzt trailing Vola.",
              file=sys.stderr)
    return multiplier
```

Add `vol_multiplier: float | None = None` to `advance_autotrader`'s keyword parameters and pass it into `advance_depot(...)` (next to `depot_returns=...`). In `main()`, pass `vol_multiplier=_collect_vol_multiplier(panel)` in the `advance_autotrader(...)` call.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/test_vol_forecast.py tests/test_autotrader_protections.py tests/test_autotrader_engine.py -q`
Expected: PASS (existing engine tests pass unchanged — the new parameter defaults to None).

- [ ] **Step 8: Dry-run against the live DB (consumer check — LOOP rule)**

Run: `uv run python scripts/run_autotrader.py --dry-run`
Expected: prints the sleeves + either a normal valuation or "Bereits aktuell"; if VIX fetch fails, the stderr warning appears and the run still completes. Nothing persisted.

- [ ] **Step 9: Documentation + PLAN.md bookkeeping**

- README "Auto-Depot" section: change the risk-layer sentence to say the 12% vol target uses the depot's trailing vol scaled by a VIX-forecast multiplier (study 2026-08-12), with trailing-only fallback.
- PLAN.md: check off the two open boxes under "Phase: Risiko-Schiene — VolTarget nutzt den schwächeren Schätzer (2026-08-12)" and append a one-line outcome (deployed date, constants: divisor 1.341, clamp 0.5–3.0).

- [ ] **Step 10: Gate + commit**

```bash
uv run pytest -q && uv run ruff check .
git add src/equity_scout/vol_forecast.py src/equity_scout/autotrader_protections.py \
        src/equity_scout/autotrader_engine.py scripts/run_autotrader.py \
        tests/test_vol_forecast.py tests/test_autotrader_protections.py README.md PLAN.md
git commit -m "feat(depot): VIX-calibrated forward-vol multiplier in VolTarget"
```

---

### Task 2: Reframe the real-money bar in `proof.py` as a risk goal

The current bar (`Sharpe > 1` after costs AND `MaxDD < 15 %` in 180 days) is set above what institutional CTAs sustain long-run and is statistically undecidable on 180 days — it can only ever fire on luck. The own W0 finding says what IS achievable: market-like return with materially less drawdown. **Values below are proposed defaults — Nico's veto before merge.**

**Files:**
- Modify: `src/equity_scout/proof.py:21-25` (thresholds), `proof.py:86-93` (benchmark drawdown)
- Modify: `frontend/src/api.ts:671-675`, `frontend/src/components/ProofView.tsx:203-210`
- Test: `tests/test_proof.py` (extend; check first whether threshold keys are pinned anywhere: `grep -rn "min_sharpe_after_costs" tests/`)

- [ ] **Step 1: Write the failing test**

In `tests/test_proof.py` (match existing test style there):

```python
def test_conviction_thresholds_are_the_risk_reframed_bar():
    from equity_scout.proof import CONVICTION_THRESHOLDS

    assert CONVICTION_THRESHOLDS == {
        "min_track_days": 730,
        "min_vs_benchmark_pct": 0.0,
        "max_drawdown_ratio_vs_benchmark": 0.60,
    }


def test_book_report_carries_benchmark_max_drawdown():
    curve = [("2026-01-01", 100.0), ("2026-01-02", 110.0), ("2026-01-03", 105.0)]
    bench = [("2026-01-01", 100.0), ("2026-01-02", 90.0), ("2026-01-03", 95.0)]
    from equity_scout.proof import book_report

    report = book_report(curve, label="t", benchmark_curve=bench)
    assert report["benchmark_max_drawdown_pct"] is not None
    assert abs(report["benchmark_max_drawdown_pct"] - 10.0) < 1e-9


def test_book_report_benchmark_drawdown_none_without_benchmark():
    curve = [("2026-01-01", 100.0), ("2026-01-02", 110.0)]
    from equity_scout.proof import book_report

    assert book_report(curve, label="t")["benchmark_max_drawdown_pct"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_proof.py -q`
Expected: FAIL (old threshold keys; missing report key)

- [ ] **Step 3: Implement in `proof.py`**

Replace the thresholds block (lines 19-25) with:

```python
# What WOULD justify trusting this system with real money (rendered on the proof surfaces so
# the bar is explicit, not vibes; the decision itself stays Nico's). Reframed 2026-08-16: the
# old bar (Sharpe > 1 AND MaxDD < 15 % in 180 days) sat above what institutional CTAs sustain
# long-run and 180 days cannot statistically separate Sharpe 1 from 0 — a bar that can only
# fire on luck. W0 (2026-08-11) showed what this data CAN deliver: returns are not predictable,
# risk is. So the bar now asks for exactly that, after costs, on a track long enough to mean
# something: not behind the benchmark, at materially lower drawdown.
CONVICTION_THRESHOLDS = {
    "min_track_days": 730,  # ~2 years — the shortest track that can carry this verdict
    "min_vs_benchmark_pct": 0.0,  # after costs, not behind the benchmark
    "max_drawdown_ratio_vs_benchmark": 0.60,  # depot MaxDD <= 60 % of the benchmark's MaxDD
}
```

In `book_report`, extend the benchmark block (currently lines 86-93) to also measure the benchmark's own max drawdown on the overlapping window:

```python
    vs_benchmark: float | None = None
    benchmark_max_drawdown: float | None = None
    if benchmark_curve:
        bench = _daily_series(benchmark_curve)
        overlap = bench.loc[(bench.index >= series.index[0]) & (bench.index <= series.index[-1])]
        if len(overlap) >= 2:
            benchmark_max_drawdown = float((1.0 - overlap / overlap.cummax()).max())
            if total_return is not None:
                bench_return = _total_return(overlap)
                if bench_return is not None:
                    vs_benchmark = (total_return - bench_return) * 100.0
```

Add to the returned dict (next to `max_drawdown_pct`):

```python
        "benchmark_max_drawdown_pct": (
            None if benchmark_max_drawdown is None else benchmark_max_drawdown * 100.0
        ),
```

Also add the key with value `None` to the early-return dict at the top of `book_report` (the `len(series) < 2` branch), so the shape is stable.

- [ ] **Step 4: Update the frontend**

`frontend/src/api.ts` — replace the `conviction` shape (lines 671-675):

```ts
  conviction?: {
    min_track_days: number;
    min_vs_benchmark_pct: number;
    max_drawdown_ratio_vs_benchmark: number;
  };
```

and add to `ProofBook` (near `max_drawdown_pct` at line ~661):

```ts
  benchmark_max_drawdown_pct: number | null;
```

`frontend/src/components/ProofView.tsx` — replace the Explain block (lines 203-211):

```tsx
      {data.conviction && (
        <Explain tone="hint">
          Was würde den Einsatz von echtem Geld rechtfertigen? Mindestens{" "}
          <b>{data.conviction.min_track_days} Tage</b> Track Record, nach Kosten{" "}
          <b>nicht hinter der Benchmark</b>, und ein maximaler Rückgang von höchstens{" "}
          <b>{Math.round(data.conviction.max_drawdown_ratio_vs_benchmark * 100)} %</b> des
          Benchmark-Rückgangs — Rendite liefert der Markt, die Maschine liefert Disziplin und
          Risikokontrolle. Und selbst dann bleibt es deine Entscheidung, nicht die des Systems.
        </Explain>
      )}
```

- [ ] **Step 5: Run tests + frontend build**

Run: `uv run pytest tests/test_proof.py tests/test_api.py -q` — PASS.
Run: `npm run build --prefix frontend` — clean (this also typechecks; if a separate `npm run typecheck --prefix frontend` script exists, run it too).

- [ ] **Step 6: Docs**

README "Kann das funktionieren?" + "Der Weg zu echtem Geld" paragraphs: replace the `proof.CONVICTION_THRESHOLDS`-Werte (≥ 180 Tage, Sharpe > 1, MaxDD < 15 %) with the new bar and one sentence why (risk goal instead of alpha goal, review 2026-08-16).

- [ ] **Step 7: Gate + commit**

```bash
uv run pytest -q && uv run ruff check .
git add src/equity_scout/proof.py tests/test_proof.py frontend/src/api.ts \
        frontend/src/components/ProofView.tsx README.md
git commit -m "feat(proof): reframe real-money bar as risk goal vs benchmark"
```

---

### Task 3: Regime-clean crypto verdict + pre-registered kill criterion

The crypto lane's verdict "negativ, statistisch entschieden" (32 trades, −451.60) is computed across two regimes: the fee-destroyed 15-minute era and the daily-bar era (since 2026-08-10, commit `c446017`) with n≈0. That is the champion-artifact lesson again — a verdict measured on a sample the rule no longer generates. **This task changes ZERO trading behaviour** (Nico's standing decision 2026-08-16: leave crypto untouched); it makes the nightly verdict measure the era that actually runs, and pre-registers the kill criterion in writing.

**Files:**
- Modify: `src/equity_scout/lane_review.py` (epoch filter in `review_lane`, ~line 53)
- Modify: `PLAN.md` (replace the open "Beobachten: Crypto-Lane auf Tagesbars" item), `README.md` (crypto lane bullet)
- Test: `tests/test_lane_review.py` (extend; create if missing)

- [ ] **Step 1: Write the failing test**

In `tests/test_lane_review.py`, following the existing trade-dict shape (`executed_at`, `ticker`, `side`, `qty`, `price`, `fees`, `reason`, `realized_pnl`):

```python
def _trade(executed_at: str, pnl: float) -> dict:
    return {
        "executed_at": executed_at, "ticker": "BTC/USD", "side": "sell",
        "qty": 1.0, "price": 100.0, "fees": 0.1, "reason": "channel_exit",
        "realized_pnl": pnl,
    }


def test_crypto_review_starts_at_the_daily_bars_epoch():
    from equity_scout.lane_review import MEASUREMENT_EPOCHS, review_lane

    assert MEASUREMENT_EPOCHS["crypto"] == "2026-08-10"
    trades = [_trade("2026-07-01T10:00:00", -400.0), _trade("2026-08-12T10:00:00", +5.0)]
    review = review_lane("crypto", trades)
    assert review.n_closed == 1  # the 15-minute-era trade is outside the verdict window
    assert any("2026-08-10" in note for note in review.notes)


def test_other_lanes_keep_their_full_history():
    from equity_scout.lane_review import review_lane

    trades = [_trade("2026-07-01T10:00:00", -1.0), _trade("2026-08-12T10:00:00", 2.0)]
    assert review_lane("swing", trades).n_closed == 2
```

(Field names verified against `lane_review.py:27-37` — `LaneReview` carries `n_closed` and `notes` exactly as asserted.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lane_review.py -q`
Expected: FAIL with `ImportError: cannot import name 'MEASUREMENT_EPOCHS'`

- [ ] **Step 3: Implement in `lane_review.py`**

Add near the top of the module:

```python
# Measurement epochs: a lane whose MECHANICS changed mid-track must not have its verdict
# computed across the break (the champion-artifact lesson: a number measured on a sample the
# rule no longer generates). The crypto lane moved from 15-minute to daily bars on 2026-08-10
# (commit c446017); its 15-minute-era trades are evidence about a retired rule. The full
# curve stays visible on every surface — only the VERDICT window starts at the epoch.
MEASUREMENT_EPOCHS: dict[str, str] = {"crypto": "2026-08-10"}
```

At the top of `review_lane`, before `pnls = _closed(trades)`:

```python
    epoch = MEASUREMENT_EPOCHS.get(lane)
    if epoch is not None:
        trades = [t for t in trades if str(t.get("executed_at") or "") >= epoch]
```

And append a note (where the other `notes` are collected):

```python
    if epoch is not None:
        notes.append(
            f"Bewertungsfenster ab {epoch} (Regime-Wechsel auf Tagesbars) — "
            "ältere Trades zählen nicht ins Urteil."
        )
```

Known, accepted edge: a position OPENED under the old regime but CLOSED after the epoch counts into the new window (trade rows carry the close timestamp). One transition trade at most; noting it here is cheaper than plumbing open timestamps through.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_lane_review.py -q` — PASS.

- [ ] **Step 5: Pre-register the kill criterion (docs, no code)**

- PLAN.md: replace the open item "Beobachten: ob die Crypto-Lane auf Tagesbars einen positiven Erwartungswert zeigt…" with:

```markdown
- [ ] **Crypto-Lane Kill-Kriterium (vorab registriert 2026-08-16):** Urteil ausschließlich auf
      Daily-Ära-Trades (lane_review.MEASUREMENT_EPOCHS, Epoche 2026-08-10). Nach ≥ 30
      geschlossenen Daily-Ära-Trades entscheidet significance.assess_trades: Verdict „negativ"
      ⇒ Cron-Zeile entfernen (Lane-Ende, Buch bleibt lesbar — Session-Lane-Präzedenz);
      „positiv" ⇒ Promotion-Gate wie jede Lane. Bei 20/10-Donchian über 4 Paare sind das
      grob 12–24 Monate — wer früher urteilen will, braucht ein anderes Kriterium, nicht
      dieselben Daten nochmal.
```

- README crypto lane bullet: add one sentence — verdict window starts 2026-08-10 (daily-bars regime), kill criterion ≥30 daily-era trades + verdict "negativ".

- [ ] **Step 6: Gate + commit**

```bash
uv run pytest -q && uv run ruff check .
git add src/equity_scout/lane_review.py tests/test_lane_review.py PLAN.md README.md
git commit -m "feat(arena): regime-clean crypto verdict window + pre-registered kill criterion"
```

---

### Task 4: Allocator tilt on inverse vol instead of Sharpe softmax

A Sharpe estimate over 63 daily observations has a standard error of ~2 annualised units — the softmax exponent is dominated by noise (DeMiguel/Garlappi/Uppal 2009: estimation error makes optimized weights lose to 1/N on short samples). Volatility IS estimable on 63 observations. The 50% equal-weight anchor, floor/cap, seasoned/young split, and monthly recompute all stay; only the tilt basis changes.

**Files:**
- Modify: `src/equity_scout/autotrader_allocator.py:154-181` (`blend_weights` tilt block + docstrings)
- Modify: `scripts/run_autotrader.py:217` (`resolve_allocation` stored-mode check) and `:457-461` (`mode_note`)
- Modify: `README.md` (Auto-Depot section wording)
- Test: `tests/test_autotrader_allocator.py` (extend + adjust pins)

- [ ] **Step 1: Write the failing tests**

In `tests/test_autotrader_allocator.py` (three sleeves on purpose: with only two, `_clip_renormalise` widens the cap to 1/n = 0.5 and pins both there, hiding the tilt):

```python
def _alternating(up: float, down: float, n: int = 70) -> pd.Series:
    values = [up if i % 2 == 0 else down for i in range(n)]
    return pd.Series(values, index=pd.bdate_range("2026-01-01", periods=n))


def test_tilt_prefers_the_lower_vol_sleeve():
    frame = pd.DataFrame({
        "calm": _alternating(0.002, -0.002),
        "mid": _alternating(0.010, -0.010),
        "wild": _alternating(0.020, -0.020),
    })
    allocation = blend_weights(frame, ["calm", "mid", "wild"])
    assert allocation.mode == "tilt_invvol"
    assert allocation.weights["calm"] > allocation.weights["mid"] > allocation.weights["wild"]


def test_sharpes_are_still_reported_but_do_not_drive_weights():
    frame = pd.DataFrame({
        "lucky_wild": _alternating(0.021, -0.019),  # positive drift, high vol -> best Sharpe
        "calm": _alternating(0.002, -0.002),
        "mid": _alternating(0.010, -0.010),
    })
    allocation = blend_weights(frame, ["lucky_wild", "calm", "mid"])
    assert allocation.sharpes["lucky_wild"] > allocation.sharpes["calm"]
    assert allocation.weights["calm"] > allocation.weights["lucky_wild"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_autotrader_allocator.py -q`
Expected: new tests FAIL (mode is "tilt", weights follow Sharpe)

- [ ] **Step 3: Implement in `blend_weights`**

Replace the softmax block (lines 154-159):

```python
    tail = overlap.iloc[-window:]
    # Sharpes stay REPORTED (dashboard/CLI transparency) but no longer drive weights: over 63
    # daily observations the Sharpe standard error is ~2 annualised units, so a softmax on it
    # ranks noise (DeMiguel et al. 2009; review 2026-08-16). Vol IS estimable on this window.
    sharpes = {name: _annualised_sharpe(tail[name]) for name in seasoned}
    vols = {
        name: float(tail[name].std(ddof=1)) * math.sqrt(TRADING_DAYS_PER_YEAR)
        for name in seasoned
    }
    inverse = {
        name: (1.0 / vol) if vol > 0 and math.isfinite(vol) else 0.0
        for name, vol in vols.items()
    }
    total_inverse = sum(inverse.values())
    if total_inverse <= 0:
        return SleeveAllocation(weights=equal, mode="anchor", window_obs=len(tail))
    tilt = {name: value / total_inverse for name, value in inverse.items()}
```

and in the blend below, use `tilt[name]` instead of `softmax[name]`, and return `mode="tilt_invvol"`.

Update the module docstring (Sharpe-softmax → inverse-vol, why) and the `SleeveAllocation.mode` comment (`"anchor" | "tilt_invvol"`; the retired `"tilt"` only exists in old DB rows).

- [ ] **Step 4: Retire stored `"tilt"` rows honestly in `resolve_allocation`**

In `scripts/run_autotrader.py:217`, the stored-weights reuse must not carry a retired scheme through the month. Change the condition to:

```python
    if (
        stored
        and stored[0]["month"] == month
        and stored[0]["mode"] in ("anchor", "tilt_invvol")
        and {r["strategy_name"] for r in stored} == set(sleeve_names)
    ):
```

and update `mode_note` in `main()`:

```python
    mode_note = (
        "Anker-Phase: zu wenig Forward-Historie für Performance-Tilt — reines Equal-Weight"
        if account.sleeve_mode == "anchor"
        else "Tilt: Inverse-Vol auf 63-Tage-Fenster, 50% Equal-Weight-Anker"
    )
```

- [ ] **Step 5: Fix the pins**

Run: `uv run pytest tests/test_autotrader_allocator.py tests/test_autotrader_storage.py -q` and update every existing test that pins `mode == "tilt"` or softmax-derived weight values. The invariants that MUST survive unchanged: weights sum to 1, floor/cap respected, young sleeves keep anchor shares, anchor mode below `MIN_OVERLAP_OBS`.

- [ ] **Step 6: Dry-run (consumer check)**

Run: `uv run python scripts/run_autotrader.py --dry-run`
Expected: allocation recomputes under `tilt_invvol` (stored `tilt` rows for this month are ignored), weights within floor/cap, no crash. Note the one-time reallocation size in the output for the commit message.

- [ ] **Step 7: Docs**

README Auto-Depot section: "Sharpe-softmax tilt" → "inverse-vol tilt (Sharpe weiterhin angezeigt, aber nicht gewichtsbestimmend — Begründung: Schätzfehler, DeMiguel 2009, Review 2026-08-16)".

- [ ] **Step 8: Gate + commit**

```bash
uv run pytest -q && uv run ruff check .
git add src/equity_scout/autotrader_allocator.py scripts/run_autotrader.py \
        tests/test_autotrader_allocator.py README.md
git commit -m "feat(depot): allocator tilt on inverse vol instead of Sharpe softmax"
```

---

### Task 5: Rebalance-timing-luck study (measurement, no live change)

All sleeves rebalance on month-end. Hoffstein/Faber/Braun (2020) show the rebalance-day choice alone creates large long-run dispersion. Before building tranching (which would create new sleeve identities), measure whether the effect is material on OUR panel and OUR strategies.

**Files:**
- Modify: `src/equity_scout/engine.py:56-64` (optional `rebalance_dates` override)
- Create: `scripts/run_timing_luck_study.py`
- Create (after running): `docs/research/2026-08-XX-rebalance-timing-luck.md` (XX = run date)
- Test: `tests/test_engine_rebalance_override.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_engine_rebalance_override.py`:

```python
"""run_backtest with explicit rebalance dates (timing-luck study support)."""
import pandas as pd

from equity_scout.engine import run_backtest
from equity_scout.market import PricePanel
from equity_scout.strategies.base import TargetWeight


class AlwaysLong:
    name = "always-long"

    def decide(self, as_of, market):
        return [TargetWeight("AAA", 1.0)]


def _panel() -> PricePanel:
    dates = pd.bdate_range("2026-01-01", periods=60)
    closes = pd.DataFrame({"AAA": [100.0 + i for i in range(60)]}, index=dates)
    return PricePanel(closes)


def test_override_dates_are_the_only_rebalances():
    panel = _panel()
    override = pd.DatetimeIndex([panel.dates[10], panel.dates[40]])
    result = run_backtest(AlwaysLong(), panel, rebalance_dates=override)
    assert [t.date for t in result.trades] == [
        panel.dates[10].date().isoformat()  # only the FIRST override trades (buy-in);
    ]                                        # date 40 has zero turnover on a held book
    assert result.weights_by_date.index.tolist() == [panel.dates[10], panel.dates[40]]


def test_default_behaviour_unchanged_without_override():
    panel = _panel()
    result = run_backtest(AlwaysLong(), panel)
    assert len(result.weights_by_date) >= 2  # monthly marks still happen
```

(If `weights_by_date` only records dates with turnover > eps, adjust the first assertion to check `trades` only — read `engine.py:104-107`: `weight_rows[date] = target` records EVERY rebalance date, turnover or not, so the assertion above holds.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_engine_rebalance_override.py -q`
Expected: FAIL with `TypeError: run_backtest() got an unexpected keyword argument 'rebalance_dates'`

- [ ] **Step 3: Implement the engine override**

In `engine.py`, extend the signature:

```python
def run_backtest(
    strategy: Strategy,
    panel: PricePanel,
    *,
    rebalance: str = "ME",
    rebalance_dates: pd.DatetimeIndex | None = None,
    costs_bps: float = 10.0,
    initial_capital: float = 1.0,
    sweep_bps: tuple[float, ...] = (),
) -> BacktestResult:
```

and replace line 69:

```python
    rebalance_dates_set = set(
        panel.rebalance_dates(rebalance) if rebalance_dates is None else rebalance_dates
    )
```

(rename the two usages of the old `rebalance_dates` local accordingly).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_engine_rebalance_override.py tests/test_engine.py -q` — PASS (test_engine.py exists and pins the default path).

- [ ] **Step 5: Write the study script**

Create `scripts/run_timing_luck_study.py`:

```python
#!/usr/bin/env python3
"""Rebalance timing luck across the rule sleeves (study, 2026-08).

All sleeves rebalance on the month-end panel date. Hoffstein/Faber/Braun (JII 2020) show the
CHOICE of rebalance day alone creates large long-run dispersion in exactly this strategy
class. This script measures that dispersion on OUR panel and OUR strategies: the same
strategy, after costs, rebalanced k trading days after month-end for k in OFFSETS.

Measurement only — it changes nothing live. If the spread is material, tranching (running the
offsets side by side and averaging) is the literature remedy; building that would create new
sleeve identities and is a separate, Nico-gated plan.

Run from the repo root (uses the cached ETF panel; --refresh to re-fetch):
    uv run python scripts/run_timing_luck_study.py
"""
from __future__ import annotations

import argparse
import math

import pandas as pd

from equity_scout.data.etf_panel import load_etf_panel
from equity_scout.engine import run_backtest
from equity_scout.etf_universe import ETF_TICKERS
from equity_scout.strategies.ensemble import EnsembleStrategy
from equity_scout.strategies.registry import default_strategies

OFFSETS = (0, 5, 10, 15)  # trading days after month-end — four weekly-staggered variants
COSTS_BPS = 10.0
TRADING_DAYS_PER_YEAR = 252


def shifted_dates(panel, offset: int) -> pd.DatetimeIndex:
    """Each month-end panel date moved `offset` trading days later (bounded at panel end)."""
    index = pd.DatetimeIndex(panel.dates)
    positions = index.get_indexer(panel.rebalance_dates("ME"))
    shifted = [index[min(p + offset, len(index) - 1)] for p in positions if p >= 0]
    return pd.DatetimeIndex(shifted).unique()


def cagr(equity: pd.Series) -> float:
    years = max(len(equity) / TRADING_DAYS_PER_YEAR, 1e-9)
    return (float(equity.iloc[-1]) / float(equity.iloc[0])) ** (1.0 / years) - 1.0


def sharpe(equity: pd.Series) -> float:
    returns = equity.pct_change().dropna()
    std = float(returns.std(ddof=1))
    if std <= 0 or not math.isfinite(std):
        return 0.0
    return float(returns.mean()) / std * math.sqrt(TRADING_DAYS_PER_YEAR)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--start", default="2007-01-01")
    args = parser.parse_args()

    panel = load_etf_panel(ETF_TICKERS, start=args.start, refresh=args.refresh)
    strategies = [s for s in default_strategies() if not isinstance(s, EnsembleStrategy)]

    print(f"Panel {panel.dates[0].date()}..{panel.dates[-1].date()} — "
          f"{len(strategies)} Strategien x Offsets {OFFSETS} Handelstage, {COSTS_BPS:.0f} bps\n")
    print(f"{'Strategie':<28}{'CAGR min..max':<22}{'Spread pp':>10}{'Sharpe min..max':>20}")
    for strategy in strategies:
        cagrs, sharpes = [], []
        for offset in OFFSETS:
            result = run_backtest(
                strategy, panel,
                rebalance_dates=shifted_dates(panel, offset), costs_bps=COSTS_BPS,
            )
            cagrs.append(cagr(result.equity))
            sharpes.append(sharpe(result.equity))
        spread_pp = (max(cagrs) - min(cagrs)) * 100.0
        print(f"{strategy.name:<28}"
              f"{min(cagrs):+.2%} .. {max(cagrs):+.2%}   "
              f"{spread_pp:>8.2f}"
              f"{min(sharpes):>10.2f} .. {max(sharpes):.2f}")
    print("\nLesart: der Spread ist reines Kalenderglück — dieselbe Regel, dieselben Kosten,")
    print("nur ein anderer Rebalance-Tag. Material (>~1 pp CAGR über mehrere Strategien)")
    print("=> Tranching-Plan lohnt; sonst ist Month-End fein und der Punkt ist gemessen erledigt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Run the study and write the research doc**

Run: `uv run python scripts/run_timing_luck_study.py` (first run may need `--refresh`; ~1-2 min).
Write `docs/research/<today>-rebalance-timing-luck.md`: the table, the verdict per the Lesart line, and the explicit build/no-build recommendation for tranching. Add the corresponding follow-up item (build tranching OR close the question) under a new phase note in `PLAN.md`.

- [ ] **Step 7: Gate + commit**

```bash
uv run pytest -q && uv run ruff check .
git add src/equity_scout/engine.py scripts/run_timing_luck_study.py \
        tests/test_engine_rebalance_override.py docs/research/ PLAN.md
git commit -m "feat(research): rebalance timing-luck study across rule sleeves"
```

---

### Task 6: Independent EOD price cross-check before the depot advance (Stooq)

yfinance is an unofficial scraper and the depot's only price source. A data GAP degrades honestly everywhere; a WRONG price is caught nowhere and books silently into the track record (the 15:57-intraday-as-close incident is the near-miss precedent). Stooq serves free, keyless EOD quotes — one independent reference, checked only where prices become bookings: the depot advance.

Fail direction, deliberately split: reference UNREACHABLE → warn + advance (a missing check must not stop the depot); reference CONTRADICTS the panel → abort the advance loudly (no booking on possibly-wrong prices; the guarded chain retries next slot).

**Files:**
- Create: `src/equity_scout/data/stooq.py`
- Create: `src/equity_scout/price_crosscheck.py`
- Modify: `scripts/run_autotrader.py` (`main()`, after `combined_panel`), `LOOP.md` (data-source list), `README.md` (one sentence)
- Test: `tests/test_stooq.py`, `tests/test_price_crosscheck.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_stooq.py`:

```python
from equity_scout.data.stooq import parse_quote_csv, stooq_symbol

CSV = "Symbol,Date,Time,Open,High,Low,Close,Volume\nSPY.US,2026-08-14,22:00:07,642.1,645.3,641.0,644.5,51234567\n"


def test_symbol_mapping():
    assert stooq_symbol("SPY") == "spy.us"


def test_parse_quote_csv_returns_date_and_close():
    assert parse_quote_csv(CSV) == ("2026-08-14", 644.5)


def test_parse_quote_csv_handles_nd_and_garbage():
    assert parse_quote_csv("Symbol,Date,Time,Open,High,Low,Close,Volume\nSPY.US,N/D,N/D,N/D,N/D,N/D,N/D,N/D\n") is None
    assert parse_quote_csv("") is None
    assert parse_quote_csv("<html>rate limited</html>") is None
```

Create `tests/test_price_crosscheck.py`:

```python
import pandas as pd

from equity_scout.price_crosscheck import TOLERANCE, crosscheck


def _panel(close: float, date: str = "2026-08-14") -> pd.DataFrame:
    return pd.DataFrame({"SPY": [close]}, index=pd.DatetimeIndex([pd.Timestamp(date)]))


def test_matching_prices_pass():
    assert crosscheck(_panel(644.5), {"SPY": ("2026-08-14", 644.5)}) == []


def test_divergence_beyond_tolerance_is_reported():
    problems = crosscheck(_panel(644.5), {"SPY": ("2026-08-14", 700.0)})
    assert len(problems) == 1 and "SPY" in problems[0]


def test_date_mismatch_is_skipped_not_flagged():
    # the reference being one day behind (holiday, fetch lag) is not a divergence
    assert crosscheck(_panel(644.5, date="2026-08-15"), {"SPY": ("2026-08-14", 700.0)}) == []


def test_unknown_ticker_is_ignored():
    assert crosscheck(_panel(644.5), {"QQQ": ("2026-08-14", 1.0)}) == []


def test_tolerance_is_two_percent():
    assert TOLERANCE == 0.02
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_stooq.py tests/test_price_crosscheck.py -q`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement `src/equity_scout/data/stooq.py`**

```python
"""Independent EOD close reference from Stooq (free CSV, no key) — the depot's price
cross-check source. https://stooq.com/q/l/?s=spy.us&f=sd2t2ohlcv&h&e=csv returns a one-line
CSV quote per symbol. This module only fetches and parses; the comparison logic lives in
price_crosscheck.py (pure). Second source on purpose: yfinance is an unofficial scraper, and
a WRONG price (unlike a missing one) is caught by no other gate before it books into the
depot's track record."""
from __future__ import annotations

import csv
import io
import urllib.request

STOOQ_QUOTE_URL = "https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=csv"
TIMEOUT_SECONDS = 10


def stooq_symbol(ticker: str) -> str:
    """US-listed tickers only — exactly what the depot's check set contains."""
    return f"{ticker.lower()}.us"


def parse_quote_csv(text: str) -> tuple[str, float] | None:
    """(iso_date, close) from one Stooq quote CSV; None for N/D rows, HTML, or garbage."""
    try:
        rows = list(csv.DictReader(io.StringIO(text)))
    except csv.Error:
        return None
    if not rows:
        return None
    row = rows[0]
    date, close = row.get("Date"), row.get("Close")
    if not date or date == "N/D" or close in (None, "", "N/D"):
        return None
    try:
        return date, float(close)
    except ValueError:
        return None


def fetch_latest_closes(tickers: list[str]) -> dict[str, tuple[str, float]]:
    """Latest (date, close) per ticker. A ticker that fails to parse is simply absent —
    the caller treats absence as 'no reference', never as agreement or divergence."""
    out: dict[str, tuple[str, float]] = {}
    for ticker in tickers:
        url = STOOQ_QUOTE_URL.format(symbol=stooq_symbol(ticker))
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
            text = response.read().decode("utf-8", errors="replace")
        parsed = parse_quote_csv(text)
        if parsed is not None:
            out[ticker] = parsed
    return out
```

- [ ] **Step 4: Implement `src/equity_scout/price_crosscheck.py`**

```python
"""Compare the depot panel's latest closes against an independent reference (pure logic).

Only dates BOTH sources have are compared — a reference that lags a day (holiday, fetch
timing) is 'no reference for today', never a divergence. The tolerance is wide (2 %): this
gate exists to catch WRONG prices (split/adjustment glitches, scraper breakage), not to
adjudicate cent-level differences between two EOD sources."""
from __future__ import annotations

import pandas as pd

TOLERANCE = 0.02
CHECK_TICKERS = ("SPY", "IEF", "GLD")  # three liquid, uncorrelated-source depot cornerstones


def crosscheck(
    panel_closes: pd.DataFrame,
    reference: dict[str, tuple[str, float]],
    *,
    tolerance: float = TOLERANCE,
) -> list[str]:
    """Human-readable divergence messages; empty list = no contradiction found."""
    problems: list[str] = []
    for ticker, (ref_date, ref_close) in reference.items():
        if ticker not in panel_closes.columns or ref_close <= 0:
            continue
        series = panel_closes[ticker].dropna()
        stamp = pd.Timestamp(ref_date)
        if series.empty or stamp not in series.index:
            continue
        ours = float(series.loc[stamp])
        if ours <= 0:
            continue
        deviation = abs(ours / ref_close - 1.0)
        if deviation > tolerance:
            problems.append(
                f"{ticker} {stamp.date().isoformat()}: Panel {ours:.2f} vs "
                f"Referenz {ref_close:.2f} ({deviation:.1%} > {tolerance:.0%})"
            )
    return problems
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_stooq.py tests/test_price_crosscheck.py -q` — PASS.

- [ ] **Step 6: Wire into `run_autotrader.main()`**

Imports:

```python
from equity_scout.data.stooq import fetch_latest_closes
from equity_scout.price_crosscheck import CHECK_TICKERS, crosscheck
```

In `main()`, directly after `panel = combined_panel(...)` and before the advance:

```python
    if os.environ.get("EQUITY_SCOUT_SKIP_CROSSCHECK") != "1":
        try:
            reference = fetch_latest_closes(list(CHECK_TICKERS))
        except Exception as err:  # noqa: BLE001 — a MISSING check must not stop the depot
            print(f"Warnung: Preis-Kreuzcheck nicht erreichbar ({type(err).__name__}: {err})"
                  " — Advance läuft ohne Referenz.", file=sys.stderr)
            reference = {}
        problems = crosscheck(panel.closes, reference)
        if problems:
            print("ABBRUCH: Panel widerspricht der unabhängigen Referenz — kein Advance auf"
                  " möglicherweise falschen Kursen (guarded chain holt den Slot nach):\n  "
                  + "\n  ".join(problems), file=sys.stderr)
            raise SystemExit(2)
```

- [ ] **Step 7: Live smoke + docs**

Run: `uv run python scripts/run_autotrader.py --dry-run` — expect either a silent pass (prices agree), or the honest warn-and-continue if Stooq is unreachable. Never an abort unless prices genuinely diverge — if it aborts, INVESTIGATE before proceeding (that is the gate working).

- LOOP.md hard-constraints bullet: extend the source list — "Data only from yfinance / SEC EDGAR (UA header) / public constituent lists / Stooq (free EOD quotes, read-only price cross-check)".
- README Automation section: one sentence — the nightly depot advance aborts (and the guarded chain retries) when the panel contradicts an independent Stooq reference by > 2 %.

- [ ] **Step 8: Gate + commit**

```bash
uv run pytest -q && uv run ruff check .
git add src/equity_scout/data/stooq.py src/equity_scout/price_crosscheck.py \
        scripts/run_autotrader.py tests/test_stooq.py tests/test_price_crosscheck.py \
        LOOP.md README.md
git commit -m "feat(depot): independent Stooq EOD cross-check before the advance"
```

---

### Task 7: Pin the fundamentals experiment to a 126-day horizon

Achse 2 exhausted the 10/20/60-day target families at coin-flip AUC on 54k OOS rows. Fundamentals (the PIT pipeline built 2026-08-12) act over quarters — testing them against the same short horizons would re-run a settled null. Pin the target BEFORE the backfill collector is built, so the experiment is pre-registered.

**Files:**
- Modify: `src/equity_scout/ml/entry_eval.py:26-28` (add constant)
- Modify: `PLAN.md` (fundamentals follow-up items)
- Test: `tests/test_entry_eval.py` (extend; file exists)

- [ ] **Step 1: Write the failing test**

```python
def test_fundamentals_horizon_is_six_months_and_distinct():
    from equity_scout.ml.entry_eval import (
        FUND_HORIZON_DAYS,
        HORIZON_DAYS,
        SECONDARY_HORIZON_DAYS,
        SHORT_HORIZON_DAYS,
    )

    assert FUND_HORIZON_DAYS == 126
    assert SHORT_HORIZON_DAYS < HORIZON_DAYS < SECONDARY_HORIZON_DAYS < FUND_HORIZON_DAYS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_entry_eval.py -q`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement**

In `src/equity_scout/ml/entry_eval.py`, after line 28:

```python
FUND_HORIZON_DAYS = 126  # ~6 months — the fundamentals experiment's target (family `entry_fund`).
# Pre-registered 2026-08-16, BEFORE the backfill collector exists: the 10/20/60d families are
# exhausted at coin-flip AUC (Achse 2, 2026-08-11), and fundamentals act over quarters, not
# weeks. Testing them against the settled short horizons would re-run a null result.
```

- [ ] **Step 4: Run test**

Run: `uv run pytest tests/test_entry_eval.py -q` — PASS.

- [ ] **Step 5: Update PLAN.md**

In the "Fundamentaldaten-Schiene" phase, amend the two open follow-up items: the backfill collector's monthly Stichtage feed a label with horizon `FUND_HORIZON_DAYS = 126` (family `entry_fund`), evaluated with the same `volume_index=None`-style additive proof as evidence/volume. Reference this plan.

- [ ] **Step 6: Gate + commit**

```bash
uv run pytest -q && uv run ruff check .
git add src/equity_scout/ml/entry_eval.py tests/ PLAN.md
git commit -m "feat(ml): pre-register 126d target horizon for the fundamentals experiment"
```

---

## Execution notes

- **Order matters for attribution:** Tasks 1 and 4 both change live depot behaviour. Deploy them on DIFFERENT nights (the 2026-08-12 lesson: two interventions in one night destroy cause attribution). Suggested: Task 1 → one nightly verified → Task 4. Tasks 2/3/5/6/7 are attribution-neutral (no trading change) and can interleave.
- **Track honesty:** Task 1 marks itself per-event (`VIX-Prognose` label), Task 4 via the stored `tilt_invvol` mode rows. No `protection_regime`-style account stamp is added — that field is single-use and already consumed by the 2026-08-10 cap change; the audit trail carries the dates.
- **Self-review before each commit** (CLAUDE.md): diff gegenlesen — correctness, simplicity, repo conventions.

## Outcome

_To be filled after execution: what shipped, deviations, open points._
