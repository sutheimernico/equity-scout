# Entry-Levels + Tranchen-Plan pro Aktie — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pro Screener-Pick einen "Einstiegs-Plan" anzeigen — regelbasierte Referenz-Levels (200-Tage-Schnitt, Fibonacci-Retracements, jüngstes Swing-Tief, ATR-Pullback-Zone, 52W-Tief/Drawdown) plus einen Tranchen-Plan (DCA-Baseline + optionaler Drawdown-Scale-in) — über einen neuen Backend-Endpoint und einen Block im PickCard-Drilldown.

**Architecture:** Reine Level-Mathematik lebt in einem neuen Modul `src/equity_scout/entry.py` als pure Funktionen + frozen dataclasses (`EntryLevel`, `Tranche`, `EntryPlan`) — kein Network, voll unit-testbar gegen konstruierte Kurs-Arrays. Der Network-Fetch (`fetch_entry_history`) importiert yfinance lazy und holt 1-Jahres-History (Close/High/Low) mit `with_retry` — exakt das Muster aus `data/yf_provider.py`. Ein neuer Endpoint `GET /api/entry/{ticker}` in `api.py` validiert den Ticker, holt + rechnet + cached (Tages-Key, damit Levels über Nacht frisch werden). Das Frontend lädt den Plan lazy beim Aufklappen der PickCard und rendert ihn mit den Strang-A-Primitives (`Bar`, `Metric`, `Disclosure`, `Explain`).

**Tech Stack:** Python (FastAPI, yfinance, dataclasses), pytest + TestClient, React/TypeScript (plain `fetch`, bestehende `ui/`-Primitives).

**Framing (nicht verhandelbar):** Referenz-Levels, KEIN "kauf bei X", keine Kursprognose. Das Attraktivitäts-Flag heißt neutral "Referenzzone erreicht" (kein Kaufsignal). Ehrlicher Befund prominent: gestaffeltes DCA schlägt "Buy the Dip" in ~70 % der Fälle (Maggiulli) — DCA ist der solide Default, Drawdown-Scale-in eine Option ohne Edge. `DISCLAIMER` wie überall.

---

## File Structure

**Backend:**
- Create `src/equity_scout/entry.py` — pure Level-Mathematik (`sma`, `fib_levels`, `recent_swing_low`, `atr`), Tranchen-Logik, `compute_entry_plan()`, dataclasses `EntryLevel`/`Tranche`/`EntryPlan`, und der Network-Fetch `fetch_entry_history()` (lazy yfinance, getrennt von den pure Funktionen).
- Modify `src/equity_scout/api.py` — neuer Endpoint `GET /api/entry/{ticker}` (Validierung, Cache mit Tages-Key, ruft Fetch + `compute_entry_plan`).

**Backend-Tests:**
- Create `tests/test_entry.py` — Level-Mathematik gegen konstruierte Arrays + `compute_entry_plan` Ende-zu-Ende mit bekannten Werten.
- Modify `tests/test_api.py` — Endpoint-Test mit gemocktem Fetch (kein Network).

**Frontend:**
- Modify `frontend/src/api.ts` — Types `EntryLevel`/`Tranche`/`EntryPlan` + `fetchEntry(ticker)`.
- Create `frontend/src/components/EntryPlanBlock.tsx` — der Einstiegs-Plan-Block (lazy, eigener Fetch-State).
- Modify `frontend/src/components/PickCard.tsx` — `<EntryPlanBlock>` im Drilldown einbinden (neben `StockChart`).
- Modify `frontend/src/index.css` (oder die bestehende Stylesheet-Datei) — minimale Styles für die neuen Klassen, falls nötig (zuerst bestehende Klassen wiederverwenden).

---

## Task 1: Pure Level-Mathematik in `entry.py`

**Files:**
- Create: `src/equity_scout/entry.py`
- Test: `tests/test_entry.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_entry.py
import math

from equity_scout.entry import atr, fib_levels, recent_swing_low, sma


def test_sma_uses_last_window():
    # last 3 of [1,2,3,4,5,6] -> mean(4,5,6) = 5.0
    assert sma([1, 2, 3, 4, 5, 6], window=3) == 5.0


def test_sma_falls_back_to_all_when_short():
    # fewer points than window -> mean of all
    assert sma([10, 20], window=200) == 15.0


def test_sma_empty_is_none():
    assert sma([], window=3) is None


def test_fib_levels_from_high_low():
    # range 100..200; retracement from the high: high - range*ratio
    levels = fib_levels(high=200.0, low=100.0)
    assert levels["0.382"] == 200.0 - 100.0 * 0.382
    assert levels["0.5"] == 150.0
    assert math.isclose(levels["0.618"], 200.0 - 100.0 * 0.618)


def test_recent_swing_low_finds_latest_local_min():
    # local minima at index 2 (value 1) and index 8 (value 2); latest is value 2
    closes = [9, 5, 1, 5, 9, 8, 6, 4, 2, 4, 7]
    assert recent_swing_low(closes, k=2) == 2.0


def test_recent_swing_low_none_when_monotone():
    assert recent_swing_low([1, 2, 3, 4, 5], k=2) is None


def test_atr_is_mean_true_range():
    # constant daily range of 2 (high-low), no gaps -> ATR = 2.0
    highs = [12, 12, 12, 12, 12]
    lows = [10, 10, 10, 10, 10]
    closes = [11, 11, 11, 11, 11]
    assert atr(highs, lows, closes, window=4) == 2.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_entry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'equity_scout.entry'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/equity_scout/entry.py
"""Rule-based entry reference levels + tranche plan for a single stock.

Pure math (sma/fib/swing-low/atr/compute_entry_plan) is network-free and unit-tested.
The yfinance fetch is isolated at the bottom (lazy import), mirroring data/yf_provider.py.

Framing: these are REFERENCE levels, not buy signals. No price prediction.
"""
from __future__ import annotations

import math


def _clean(values: list[float]) -> list[float]:
    return [v for v in values if isinstance(v, (int, float)) and math.isfinite(v) and v > 0]


def sma(closes: list[float], window: int) -> float | None:
    """Simple moving average of the last `window` closes (or all, if fewer). None if empty."""
    clean = _clean(closes)
    if not clean:
        return None
    tail = clean[-window:]
    return sum(tail) / len(tail)


def fib_levels(high: float, low: float) -> dict[str, float]:
    """Fibonacci retracement levels measured down from the 52w high: high - range*ratio.
    0.618 is the classic 'prime entry' (capitulation) zone."""
    rng = high - low
    return {ratio: high - rng * float(ratio) for ratio in ("0.382", "0.5", "0.618")}


def recent_swing_low(closes: list[float], k: int = 5) -> float | None:
    """Most recent local minimum: a close strictly lower than the k closes on each side."""
    clean = _clean(closes)
    n = len(clean)
    for i in range(n - k - 1, k - 1, -1):
        window = clean[i - k : i + k + 1]
        if clean[i] == min(window) and window.count(clean[i]) == 1:
            return clean[i]
    return None


def _true_ranges(highs: list[float], lows: list[float], closes: list[float]) -> list[float]:
    trs: list[float] = []
    for i in range(1, len(closes)):
        prev_close = closes[i - 1]
        trs.append(max(highs[i] - lows[i], abs(highs[i] - prev_close), abs(lows[i] - prev_close)))
    return trs


def atr(highs: list[float], lows: list[float], closes: list[float], window: int = 14) -> float | None:
    """Average True Range over the last `window` days. None if too little data."""
    if len(closes) < 2 or not (len(highs) == len(lows) == len(closes)):
        return None
    trs = _true_ranges(highs, lows, closes)
    if not trs:
        return None
    tail = trs[-window:]
    return sum(tail) / len(tail)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_entry.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/equity_scout/entry.py tests/test_entry.py
git commit -m "feat(entry): pure level math (sma, fib, swing-low, atr)"
```

---

## Task 2: `EntryPlan` dataclasses + `compute_entry_plan` + Tranchen

**Files:**
- Modify: `src/equity_scout/entry.py`
- Test: `tests/test_entry.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_entry.py
from equity_scout.entry import compute_entry_plan


def _ramp_then_dip() -> tuple[list[float], list[float], list[float]]:
    # 260 trading days: rise 100->200 then pull back to 160. Highs/Lows bracket closes by ±1.
    rising = [100 + i * (100 / 199) for i in range(200)]   # 100 .. 200
    falling = [200 - i * (40 / 59) for i in range(1, 61)]  # ~199.3 .. 160
    closes = rising + falling
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    return closes, highs, lows


def test_compute_entry_plan_core_levels():
    closes, highs, lows = _ramp_then_dip()
    plan = compute_entry_plan("TEST", closes, highs, lows)

    assert plan.ticker == "TEST"
    assert plan.price == closes[-1]                 # last close ~160
    assert plan.high_52w == max(highs)              # ~201
    assert plan.low_52w == min(lows)                # ~99
    assert plan.sma200 is not None
    # current price (~160) is below the 200-day SMA of a long uptrend -> below "fair value"
    assert plan.price < plan.sma200
    # drawdown from the high is negative
    assert plan.drawdown_from_high < 0


def test_compute_entry_plan_tranches_sum_to_one():
    closes, highs, lows = _ramp_then_dip()
    plan = compute_entry_plan("TEST", closes, highs, lows)

    assert len(plan.dca_tranches) == 4
    assert math.isclose(sum(t.fraction for t in plan.dca_tranches), 1.0)
    assert math.isclose(sum(t.fraction for t in plan.dip_tranches), 1.0)
    # DCA tranches are time-based (no trigger price); dip tranches have descending triggers
    assert all(t.trigger_price is None for t in plan.dca_tranches)
    triggers = [t.trigger_price for t in plan.dip_tranches]
    assert triggers == sorted(triggers, reverse=True)


def test_compute_entry_plan_levels_present():
    closes, highs, lows = _ramp_then_dip()
    plan = compute_entry_plan("TEST", closes, highs, lows)
    labels = {lvl.label for lvl in plan.levels}
    assert "200-Tage-Schnitt" in labels
    assert "Fib 61.8 %" in labels


def test_compute_entry_plan_handles_short_history():
    # Two points only — must not crash, sma falls back, atr is None.
    plan = compute_entry_plan("X", [100.0, 110.0], [101.0, 111.0], [99.0, 109.0])
    assert plan.price == 110.0
    assert plan.atr is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_entry.py -v`
Expected: FAIL with `ImportError: cannot import name 'compute_entry_plan'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/equity_scout/entry.py
from dataclasses import dataclass, field


@dataclass(frozen=True)
class EntryLevel:
    label: str          # "200-Tage-Schnitt", "Fib 61.8 %", "Jüngstes Tief", "−1 ATR"
    price: float
    kind: str           # "anchor" | "support" | "volatility"
    note: str


@dataclass(frozen=True)
class Tranche:
    label: str                      # "Tranche 1", "Jetzt", "bei −7 %"
    fraction: float                 # share of capital in [0,1]
    trigger_price: float | None     # None = time-based (DCA); else the price that arms it


@dataclass(frozen=True)
class EntryPlan:
    ticker: str
    price: float
    sma200: float | None
    high_52w: float
    low_52w: float
    drawdown_from_high: float       # negative fraction, e.g. -0.20
    atr: float | None
    levels: list[EntryLevel]
    dca_tranches: list[Tranche]
    dip_tranches: list[Tranche]
    near_reference: bool            # neutral: price is at/below the reference zone — NOT a buy signal
    reference_note: str


_FIB_LABEL = {"0.382": "Fib 38.2 %", "0.5": "Fib 50 %", "0.618": "Fib 61.8 %"}


def compute_entry_plan(
    ticker: str, closes: list[float], highs: list[float], lows: list[float]
) -> EntryPlan:
    """Build the full reference-level + tranche plan from 1y of daily OHLC closes."""
    clean = _clean(closes)
    price = clean[-1]
    high_52w = max(_clean(highs)) if _clean(highs) else price
    low_52w = min(_clean(lows)) if _clean(lows) else price
    sma200 = sma(closes, window=200)
    atr_val = atr(highs, lows, closes, window=14)
    drawdown = price / high_52w - 1.0 if high_52w > 0 else 0.0
    fibs = fib_levels(high_52w, low_52w)
    swing = recent_swing_low(closes, k=5)

    levels: list[EntryLevel] = []
    if sma200 is not None:
        rel = price / sma200 - 1.0
        levels.append(EntryLevel(
            "200-Tage-Schnitt", round(sma200, 2), "anchor",
            f"Langfrist-Anker. Preis liegt {rel * 100:+.1f} % dazu.",
        ))
    for ratio, lvl in fibs.items():
        levels.append(EntryLevel(
            _FIB_LABEL[ratio], round(lvl, 2), "support",
            "Retracement vom 52-Wochen-Hoch zum -Tief." if ratio == "0.618"
            else "Fibonacci-Retracement-Level.",
        ))
    if swing is not None:
        levels.append(EntryLevel(
            "Jüngstes Tief", round(swing, 2), "support", "Letztes lokales Kurstief (Support)."
        ))
    if atr_val is not None:
        levels.append(EntryLevel(
            "−1 ATR", round(price - atr_val, 2), "volatility",
            "Eine durchschnittliche Tagesschwankung unter dem Kurs.",
        ))
        levels.append(EntryLevel(
            "−2 ATR", round(price - 2 * atr_val, 2), "volatility",
            "Zwei Tagesschwankungen unter dem Kurs (tiefere Pullback-Zone).",
        ))

    # Baseline: 4 equal, time-staggered DCA tranches (no price trigger).
    dca = [Tranche(f"Tranche {i + 1}", 0.25, None) for i in range(4)]

    # Option: scale in on drawdown. Thirds at now / -7 % / -15 % relative to the current price.
    dip = [
        Tranche("Jetzt", 1 / 3, round(price, 2)),
        Tranche("bei −7 %", 1 / 3, round(price * 0.93, 2)),
        Tranche("bei −15 %", 1 / 3, round(price * 0.85, 2)),
    ]

    # Neutral "reference zone" flag — confluence of below-fair-value AND near a support level.
    near_support = swing is not None and price <= swing * 1.05
    near_support = near_support or price <= fibs["0.618"] * 1.02
    below_anchor = sma200 is not None and price <= sma200
    near_reference = bool(below_anchor and near_support)
    if near_reference:
        note = "Kurs unter dem 200-Tage-Schnitt und nahe einem Support — eine der Referenzzonen."
    elif below_anchor:
        note = "Kurs unter dem 200-Tage-Schnitt, aber über den Support-Levels."
    else:
        note = "Kurs über dem 200-Tage-Schnitt — keine der Referenzzonen erreicht."

    return EntryPlan(
        ticker=ticker, price=round(price, 2), sma200=round(sma200, 2) if sma200 else None,
        high_52w=round(high_52w, 2), low_52w=round(low_52w, 2),
        drawdown_from_high=round(drawdown, 4), atr=round(atr_val, 2) if atr_val else None,
        levels=levels, dca_tranches=dca, dip_tranches=dip,
        near_reference=near_reference, reference_note=note,
    )
```

Note: `field` import is included for parity with the codebase even if unused here — remove it if ruff flags it (F401). Prefer: only import `dataclass`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_entry.py -v`
Expected: PASS (10 tests total)

- [ ] **Step 5: Ruff check (catch the unused `field` import etc.)**

Run: `uv run ruff check src/equity_scout/entry.py`
Expected: clean (fix any F401 by trimming the import to `from dataclasses import dataclass`)

- [ ] **Step 6: Commit**

```bash
git add src/equity_scout/entry.py tests/test_entry.py
git commit -m "feat(entry): EntryPlan with reference levels + tranche plan"
```

---

## Task 3: Network-Fetch `fetch_entry_history`

**Files:**
- Modify: `src/equity_scout/entry.py`

Network code is isolated and NOT unit-tested (mirrors `data/yf_provider.py`, where only the pure transform is tested). It is exercised via the API test in Task 4 with a monkeypatched fetch.

- [ ] **Step 1: Add the fetch function**

```python
# append to src/equity_scout/entry.py
def fetch_entry_history(ticker: str) -> tuple[list[float], list[float], list[float]]:
    """Fetch 1y of daily Close/High/Low for `ticker`. Lazy yfinance import + retry, like
    YFinanceProvider.fetch_quote. Returns ([], [], []) on persistent failure (caller handles)."""
    import yfinance as yf

    from equity_scout.data.fetch import with_retry

    def _hist() -> tuple[list[float], list[float], list[float]]:
        h = yf.Ticker(ticker).history(period="1y", interval="1d")
        if h.empty:
            return [], [], []
        return (
            [float(c) for c in h["Close"].tolist()],
            [float(c) for c in h["High"].tolist()],
            [float(c) for c in h["Low"].tolist()],
        )

    try:
        return with_retry(_hist, attempts=3)
    except Exception:
        return [], [], []
```

- [ ] **Step 2: Verify it imports + ruff is clean**

Run: `uv run python -c "from equity_scout.entry import fetch_entry_history; print('ok')"`
Expected: `ok`

Run: `uv run ruff check src/equity_scout/entry.py`
Expected: clean

- [ ] **Step 3: Commit**

```bash
git add src/equity_scout/entry.py
git commit -m "feat(entry): isolated yfinance 1y OHLC fetch"
```

---

## Task 4: Backend-Endpoint `GET /api/entry/{ticker}`

**Files:**
- Modify: `src/equity_scout/api.py` (add import + endpoint; the new route goes BEFORE the `StaticFiles` mount, alongside the other `/api/*` routes — e.g. after the `/api/forward` block at line ~143)
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_api.py
import equity_scout.entry as entry_mod
from equity_scout.api import create_app


def test_entry_endpoint_returns_plan(tmp_path, monkeypatch):
    # Monkeypatch the network fetch so the test never touches yfinance.
    closes = [100 + i for i in range(260)]
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    monkeypatch.setattr(entry_mod, "fetch_entry_history", lambda t: (closes, highs, lows))

    client = TestClient(create_app(str(tmp_path / "x.db")))
    resp = client.get("/api/entry/AAPL")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["plan"]["ticker"] == "AAPL"
    assert "disclaimer" in body
    assert len(body["plan"]["dca_tranches"]) == 4


def test_entry_endpoint_rejects_bad_ticker(tmp_path):
    client = TestClient(create_app(str(tmp_path / "x.db")))
    resp = client.get("/api/entry/..%2Fetc")  # path-traversal-ish junk
    # FastAPI may 404 the malformed path, or our validator 400s a decoded bad ticker.
    assert resp.status_code in (400, 404)


def test_entry_endpoint_unavailable_on_empty_history(tmp_path, monkeypatch):
    monkeypatch.setattr(entry_mod, "fetch_entry_history", lambda t: ([], [], []))
    client = TestClient(create_app(str(tmp_path / "x.db")))
    resp = client.get("/api/entry/ZZZZ")
    assert resp.status_code == 200
    assert resp.json()["available"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api.py -k entry -v`
Expected: FAIL with 404 (route not defined yet)

- [ ] **Step 3: Add the endpoint**

Add this import near the top of `api.py` (after the other `from equity_scout...` imports, ~line 21):

```python
import re
```

Add the endpoint inside `create_app`, after the `/api/forward` block (before the `@app.post("/api/chat")` route). Note: it calls `entry.fetch_entry_history` via the module (not a direct import) so the test's monkeypatch takes effect:

```python
    _TICKER_RE = re.compile(r"^[A-Za-z0-9.\-]{1,15}$")
    entry_cache: dict[str, dict] = {}  # key: "TICKER:YYYY-MM-DD" -> payload (daily-fresh)

    @app.get("/api/entry/{ticker}")
    def entry(ticker: str) -> JSONResponse:
        from datetime import date

        import equity_scout.entry as entry_mod

        t = ticker.strip().upper()
        if not _TICKER_RE.match(t):
            return JSONResponse({"error": "Ungültiges Ticker-Symbol."}, status_code=400)
        cache_key = f"{t}:{date.today().isoformat()}"
        if cache_key in entry_cache:
            return JSONResponse(entry_cache[cache_key])
        closes, highs, lows = entry_mod.fetch_entry_history(t)
        if len(closes) < 2:
            payload = {"available": False, "ticker": t, "disclaimer": DISCLAIMER}
            entry_cache[cache_key] = payload
            return JSONResponse(payload)
        plan = entry_mod.compute_entry_plan(t, closes, highs, lows)
        payload = {"available": True, "plan": asdict(plan), "disclaimer": DISCLAIMER}
        entry_cache[cache_key] = payload
        return JSONResponse(payload)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_api.py -k entry -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Full backend gate**

Run: `uv run pytest -q && uv run ruff check .`
Expected: all green (was 147 tests + the new ones)

- [ ] **Step 6: Commit**

```bash
git add src/equity_scout/api.py tests/test_api.py
git commit -m "feat(api): GET /api/entry/{ticker} — reference levels + tranches (daily-cached)"
```

---

## Task 5: Frontend types + `fetchEntry`

**Files:**
- Modify: `frontend/src/api.ts` (append after the `askChat` block, ~line 275)

- [ ] **Step 1: Add types + fetch helper**

```typescript
// --- Per-stock entry reference levels + tranche plan (src/equity_scout/entry.py) ---

export interface EntryLevel {
  label: string;
  price: number;
  kind: "anchor" | "support" | "volatility";
  note: string;
}

export interface Tranche {
  label: string;
  fraction: number;
  trigger_price: number | null;
}

export interface EntryPlan {
  ticker: string;
  price: number;
  sma200: number | null;
  high_52w: number;
  low_52w: number;
  drawdown_from_high: number;
  atr: number | null;
  levels: EntryLevel[];
  dca_tranches: Tranche[];
  dip_tranches: Tranche[];
  near_reference: boolean;
  reference_note: string;
}

export interface EntryResponse {
  available: boolean;
  ticker?: string;
  plan?: EntryPlan;
  disclaimer: string;
}

export async function fetchEntry(ticker: string): Promise<EntryResponse> {
  const response = await fetch(`/api/entry/${encodeURIComponent(ticker)}`);
  if (!response.ok) throw new Error(`/api/entry returned ${response.status}`);
  return response.json();
}
```

- [ ] **Step 2: Typecheck**

Run: `npm run typecheck --prefix frontend`
Expected: clean

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api.ts
git commit -m "feat(fe): EntryPlan types + fetchEntry client"
```

---

## Task 6: `EntryPlanBlock` component + wire into `PickCard`

**Files:**
- Create: `frontend/src/components/EntryPlanBlock.tsx`
- Modify: `frontend/src/components/PickCard.tsx`
- Possibly modify: the global stylesheet for `.entry-*` classes (reuse existing classes first; only add CSS if the layout is broken)

- [ ] **Step 1: Create the component**

The block lazy-loads its own data when mounted (it is only mounted inside the `open` drilldown, so the fetch fires on expand). It positions every reference level on a single Bar spanning the 52-week low→high range, so the user reads the confluence visually. Tranches render as a small table. The honest DCA-beats-the-dip note is prominent.

```tsx
// frontend/src/components/EntryPlanBlock.tsx
import { useEffect, useState } from "react";

import { type EntryPlan, type EntryResponse, fetchEntry } from "../api";
import { eur, pct } from "../format";
import { Bar } from "./ui/Bar";
import { Disclosure } from "./ui/Disclosure";
import { Explain } from "./ui/Explain";

// Map an absolute price onto the 52w low→high range as a [0,1] fraction (for the Bar marker).
function frac(price: number, low: number, high: number): number {
  return high > low ? (price - low) / (high - low) : 0;
}

export function EntryPlanBlock({ ticker }: { ticker: string }) {
  const [state, setState] = useState<EntryResponse | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    fetchEntry(ticker)
      .then((r) => alive && setState(r))
      .catch(() => alive && setError(true));
    return () => {
      alive = false;
    };
  }, [ticker]);

  if (error) return <p className="block-hint">Einstiegs-Daten nicht verfügbar.</p>;
  if (!state) return <p className="block-hint">Einstiegs-Levels werden geladen …</p>;
  if (!state.available || !state.plan)
    return <p className="block-hint">Keine ausreichende Kurshistorie für {ticker}.</p>;

  const p: EntryPlan = state.plan;
  const priceFrac = frac(p.price, p.low_52w, p.high_52w);

  return (
    <div className="entry-plan">
      <div className="entry-head">
        <span className="entry-title">Einstiegs-Referenz</span>
        <span className={p.near_reference ? "entry-flag on" : "entry-flag"}>
          {p.near_reference ? "Referenzzone erreicht" : "über Referenzzone"}
        </span>
      </div>
      <Explain tone="hint">{p.reference_note} Kein Kaufsignal, keine Kursprognose.</Explain>

      {/* Current price on the 52w range */}
      <div className="entry-range">
        <span className="entry-range-label">
          Kurs {p.price} · 52W {p.low_52w}–{p.high_52w} · vom Hoch {pct(p.drawdown_from_high)}
        </span>
        <Bar value={priceFrac} max={1} marker={{ at: priceFrac, label: "Kurs" }} />
      </div>

      {/* Reference levels, each placed on the same 52w range */}
      <div className="entry-levels">
        {p.levels.map((lvl) => (
          <div className="entry-level" key={lvl.label} title={lvl.note}>
            <span className="entry-level-name">{lvl.label}</span>
            <Bar
              value={frac(lvl.price, p.low_52w, p.high_52w)}
              max={1}
              tone={lvl.kind === "anchor" ? "accent" : undefined}
              marker={{ at: priceFrac }}
            />
            <span className="entry-level-price tnum">{lvl.price}</span>
          </div>
        ))}
      </div>

      {/* Tranche plans */}
      <Disclosure summary="Tranchen-Plan (gestaffelt einsteigen)">
        <Explain tone="info">
          Solider Default: <strong>gestaffeltes DCA</strong> — gleiche Beträge über Zeit. „Buy the
          Dip" verliert historisch in ~70 % der Fälle gegen stures DCA (Maggiulli). Der
          Drawdown-Plan unten ist eine Option ohne nachgewiesenen Edge.
        </Explain>
        <div className="tranche-table">
          <div className="tranche-col">
            <div className="tranche-col-head">DCA · gleichmäßig</div>
            {p.dca_tranches.map((t) => (
              <div className="tranche-row" key={t.label}>
                <span>{t.label}</span>
                <span className="tnum">{Math.round(t.fraction * 100)} %</span>
              </div>
            ))}
          </div>
          <div className="tranche-col">
            <div className="tranche-col-head">Drawdown-Scale-in (Option)</div>
            {p.dip_tranches.map((t) => (
              <div className="tranche-row" key={t.label}>
                <span>{t.label}</span>
                <span className="tnum">
                  {Math.round(t.fraction * 100)} %{t.trigger_price ? ` · ${t.trigger_price}` : ""}
                </span>
              </div>
            ))}
          </div>
        </div>
      </Disclosure>
    </div>
  );
}
```

Note: `eur` is imported but only use it if you decide to show euro amounts; otherwise drop the import to keep typecheck/ruff-equivalent (eslint) clean. The snippet above does not use `eur` — **remove it from the import** before committing.

- [ ] **Step 2: Wire into PickCard**

In `frontend/src/components/PickCard.tsx`, add the import and render the block right after the `StockChart` wrapper (inside the `open` drilldown, after line 58):

```tsx
import { EntryPlanBlock } from "./EntryPlanBlock";
```

```tsx
          <div onClick={(e) => e.stopPropagation()}>
            <StockChart ticker={pick.instrument.ticker} />
          </div>

          <div onClick={(e) => e.stopPropagation()}>
            <EntryPlanBlock ticker={pick.instrument.ticker} />
          </div>
```

- [ ] **Step 3: Typecheck + build**

Run: `npm run typecheck --prefix frontend && npm run build --prefix frontend`
Expected: clean build (drop the unused `eur` import if typecheck complains)

- [ ] **Step 4: Minimal CSS if needed**

Open the dashboard, expand a pick. If the entry block is unstyled/broken, add minimal rules to the existing stylesheet (find it via the existing `.drill` / `.factor-row` rules). Reuse `.tnum`, `.block-hint`, `.explain` which already exist. Suggested additions:

```css
.entry-plan { margin-top: 0.75rem; display: flex; flex-direction: column; gap: 0.5rem; }
.entry-head { display: flex; align-items: center; justify-content: space-between; }
.entry-flag { font-size: 0.75rem; opacity: 0.6; }
.entry-flag.on { opacity: 1; font-weight: 600; }
.entry-level { display: grid; grid-template-columns: 7rem 1fr 4rem; align-items: center; gap: 0.5rem; }
.entry-level-name { font-size: 0.8rem; }
.tranche-table { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-top: 0.5rem; }
.tranche-row { display: flex; justify-content: space-between; font-size: 0.85rem; }
.tranche-col-head { font-weight: 600; font-size: 0.8rem; margin-bottom: 0.25rem; }
```

- [ ] **Step 5: Rebuild + commit**

```bash
npm run build --prefix frontend
git add frontend/src/components/EntryPlanBlock.tsx frontend/src/components/PickCard.tsx frontend/src/index.css
git commit -m "feat(fe): entry-plan block in pick drilldown (levels + tranches)"
```

---

## Task 7: Full gate + restart API + doc outcome

**Files:**
- Modify: `docs/superpowers/plans/2026-06-25-entry-levels-tranchen.md` (Outcome section)
- Possibly modify: `HANDOFF.md` (mark To-Do 1 done)

- [ ] **Step 1: Full gate**

Run:
```bash
uv run pytest -q && uv run ruff check . && npm run typecheck --prefix frontend && npm run build --prefix frontend
```
Expected: all green.

- [ ] **Step 2: Restart the API to serve the new build + endpoint**

```bash
fuser -k 8000/tcp 2>/dev/null; sleep 1
uv run python scripts/run_api.py --port 8000
```
(run in background; then `curl -s http://127.0.0.1:8000/api/entry/AAPL | head -c 400` to smoke-test — expect a JSON plan. This hits the live network; if rate-limited, `available:false` is acceptable, not a failure.)

- [ ] **Step 3: Append an Outcome section to this plan**

Document what was built, any deviations (e.g. cache TTL decision, CSS added), and open points (visual review is Nico's — no browser tooling here).

- [ ] **Step 4: Commit the docs**

```bash
git add docs/superpowers/plans/2026-06-25-entry-levels-tranchen.md HANDOFF.md
git commit -m "docs: entry-levels plan outcome + handoff update"
```

---

## Self-Review

**Spec coverage (against HANDOFF To-Do 1):**
- 200-Tage-SMA ✓ (Task 1 `sma`, Task 2 level "200-Tage-Schnitt", anchor)
- Fibonacci 38.2/50/61.8 ✓ (Task 1 `fib_levels`, Task 2 levels; 61.8 highlighted in note)
- Jüngstes Swing-Low ✓ (Task 1 `recent_swing_low`, Task 2 level "Jüngstes Tief")
- ATR-Pullback-Zone ✓ (Task 1 `atr`, Task 2 levels "−1 ATR"/"−2 ATR")
- 52W-Tief + Drawdown vom Hoch ✓ (Task 2 `high_52w`/`low_52w`/`drawdown_from_high`)
- Confluence "attraktiv" ✓ (Task 2 `near_reference` — neutral framing, not a buy signal)
- DCA-Baseline (4–6 Tranchen) ✓ (Task 2 `dca_tranches`, 4 equal)
- Drawdown-Scale-in als Option ✓ (Task 2 `dip_tranches`, now/-7%/-15%)
- Ehrlicher Befund "DCA schlägt Buy-the-Dip ~70 %" ✓ (Task 6 Explain block)
- Backend `/api/entry/{ticker}`, gecacht ✓ (Task 4, daily-key cache)
- Frontend-Block im PickCard-Drilldown, lazy ✓ (Task 6, mounted in `open`)
- Tests gegen konstruiertes Array ✓ (Task 1+2)
- Disclaimer ✓ (every response carries DISCLAIMER)

**Placeholder scan:** No TBD/TODO; every code step has full code. Two import-hygiene notes flagged inline (`field` in entry.py, `eur` in EntryPlanBlock) — these are real reminders, not placeholders.

**Type consistency:** `compute_entry_plan`/`fetch_entry_history` names match across Tasks 2–4. `EntryPlan` fields (`near_reference`, `reference_note`, `dca_tranches`, `dip_tranches`) identical in Python dataclass (Task 2), API payload (Task 4), TS interface (Task 5), and component (Task 6). `Bar` marker prop matches its real signature (`{at, label?}`). `Disclosure`/`Explain` props match their real signatures.

**Open decision for Nico (not blocking):** Cache uses a daily key (no TTL timer). If intraday-fresh levels are wanted, swap to a `time.time()` TTL — flagged but not built (YAGNI).

---

## Outcome (2026-06-25)

**Status: DONE.** All 7 tasks implemented via subagent-driven development (fresh implementer per task + two-stage spec/quality review). Built on branch `feat/entry-levels` (NOT merged — Nico reviews/merges). Gate green: **169 pytest passed**, ruff clean, frontend typecheck + build clean. Live smoke-test against real yfinance succeeded (`GET /api/entry/AAPL` → price 279.71, SMA200 268.85, 52w 198.47–317.40, all 7 levels, 4 DCA + 3 dip tranches, `near_reference: false`).

**Commits (in order):**
- `008cb23` / `68d80f8` — Task 1: pure level math (sma/fib/swing-low/atr) + the review fix (row-wise OHLC clean in `atr` so yfinance NaN rows don't propagate to NaN).
- `6ae9b7e` / `d8853cb` — Task 2: `EntryPlan`/`EntryLevel`/`Tranche` dataclasses + `compute_entry_plan` + the review fixes (ValueError guard on empty input; consistent ATR-zero state; single-expression `near_support`; clarifying comments).
- `438dfc7` / `eee07a6` — Task 3: isolated yfinance 1y OHLC fetch + the review fix (consolidate to one `dropna()`'d slice → aligned equal-length series; skip missing-column tickers to avoid burning retries).
- `1807722` / `322755c` — Task 4: `GET /api/entry/{ticker}` (ticker regex, daily-key cache) + cache-hit & dotted-ticker tests.
- `d0daa8c` — Task 5: TS types (exact mirror of the dataclass) + `fetchEntry`.
- `0193d33` / `9f5a540` — Task 6: `EntryPlanBlock` + PickCard wiring + CSS + the review fix (composite React keys on levels/tranches).

**Deviations from the plan (all improvements, surfaced by review):**
1. `atr()` cleans OHLC row-wise (plan passed raw series) — yfinance NaN rows no longer poison the ATR.
2. `compute_entry_plan` raises `ValueError` on <2 valid closes; the endpoint wraps it in `try/except` → `available:false` (plan's separate `len(closes)<2` check folded into one source of truth).
3. ATR is gated behind `len(clean) > 14` so a 1–2-point history yields `atr=None` instead of a meaningless value; flat-price ATR of `0.0` consistently produces neither ATR levels nor an `atr` field.
4. `fetch_entry_history` returns aligned equal-length series via a single `dropna()`'d DataFrame slice.

**Open / Nico's call (not blocking):**
- **Visual acceptance** of the EntryPlanBlock UI (level bars on the 52w range, tranche table, the neutral "Referenzzone erreicht"/"über Referenzzone" flag) — no browser tooling in this build env, so this is Nico's to eyeball.
- **Cache TTL:** daily key (no intraday refresh) — swap to `time.time()` TTL only if wanted.
- The "thin ATR from selectively-missing H/L" edge (review Minor) was deliberately NOT hardened — yfinance gaps drop whole OHLC rows together, so it's not a real failure mode; documented in a code comment instead.

**Next (per HANDOFF To-Do 2):** "Pitching" — meaning still unclear; clarify with Nico before building.
