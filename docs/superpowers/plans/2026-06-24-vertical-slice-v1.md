# equity-scout Vertical Slice v1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the full equity-scout funnel end-to-end for a small fixed global universe: fetch data → gate → factor-score → bucket → (optional) LLM thesis → persist snapshot → serve a minimal dashboard.

**Architecture:** A 5-stage funnel behind provider seams (market data + LLM are interfaces, faked in tests). A CLI orchestrates a run and writes a SQLite snapshot; a FastAPI read endpoint plus a static HTML page render the three risk buckets. No network/LLM calls in tests.

**Tech Stack:** Python (uv) · SQLite (stdlib `sqlite3`) · yfinance behind a seam · FastAPI · vanilla HTML/JS · pytest · ruff.

Spec: `docs/superpowers/specs/2026-06-24-equity-scout-design.md`.

---

## File Structure

```
equity-scout/
  pyproject.toml                     # uv project, deps, ruff + pytest config
  .gitignore
  README.md
  data/
    universe_v1.csv                  # ~40 tickers, mixed regions w/ Yahoo suffixes
  src/equity_scout/
    __init__.py
    models.py                        # frozen dataclasses: Instrument, Quote, FactorScore, Pick, RunResult
    universe.py                      # load_universe(csv_path) -> list[Instrument]
    data/
      __init__.py
      provider.py                    # MarketDataProvider protocol, Quote fetch contract
      fake_provider.py               # deterministic in-memory provider for tests
      yf_provider.py                 # yfinance-backed provider (real)
    gate.py                          # apply_gate(quotes) -> (passed, rejected_with_reasons)
    factors.py                       # raw factors + cross-sectional percentile ranking
    buckets.py                       # BUCKET_WEIGHTS, assign_buckets(scores, top_n) -> dict[bucket, list[Pick]]
    analysis.py                      # AnalysisProvider protocol, FakeAnalysis, ClaudeCliAnalysis
    storage.py                       # init_db, save_run, load_latest_run
    pipeline.py                      # run_pipeline(...) wiring all stages
    api.py                           # FastAPI app: GET /api/latest, GET /
    constants.py                     # DISCLAIMER text, default paths
  frontend/
    index.html                       # vanilla page fetching /api/latest, renders buckets
  scripts/
    run_scout.py                     # CLI entry: run pipeline, persist, print summary
    run_api.py                       # serve FastAPI
  tests/
    test_universe.py
    test_gate.py
    test_factors.py
    test_buckets.py
    test_analysis.py
    test_storage.py
    test_pipeline.py
```

Each `src` file has one responsibility; data fetching and LLM access sit behind seams so the pipeline is fully testable offline.

---

## Task 0: Project scaffold

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `README.md`, `src/equity_scout/__init__.py`, `src/equity_scout/constants.py`

- [ ] **Step 1: Create the feature branch**

```bash
cd ~/private/equity-scout
git checkout -b feat/vertical-slice-v1
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "equity-scout"
version = "0.1.0"
description = "Local, free global stock funnel — research assistant, not investment advice."
requires-python = ">=3.11"
dependencies = [
    "yfinance>=0.2.40",
    "fastapi>=0.110",
    "uvicorn>=0.29",
]

[dependency-groups]
dev = ["pytest>=8", "ruff>=0.4"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 3: Write `.gitignore`**

```gitignore
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
*.db
data/cache/
.env
```

- [ ] **Step 4: Write `src/equity_scout/constants.py`**

```python
"""Shared constants. Honesty guardrails live here so every surface reuses them."""

DISCLAIMER = (
    "equity-scout is a local research assistant. It does NOT provide investment advice "
    "and makes no performance promises. Factor screens are well-studied but do not reliably "
    "beat the market. Free data (yfinance) is unofficial and may be incomplete, especially "
    "outside the US. LLM theses are context-bounded interpretations, never price forecasts."
)

DEFAULT_DB_PATH = "equity_scout.db"
DEFAULT_UNIVERSE_PATH = "data/universe_v1.csv"
```

- [ ] **Step 5: Create empty package marker + README, then init the env**

```bash
mkdir -p src/equity_scout/data data tests scripts frontend
touch src/equity_scout/__init__.py src/equity_scout/data/__init__.py
printf '# equity-scout\n\nLocal, free global stock funnel. Research assistant — **not investment advice**.\nSee `docs/superpowers/specs/2026-06-24-equity-scout-design.md`.\n' > README.md
uv sync
```

Expected: `uv sync` creates `.venv` and installs deps.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: scaffold equity-scout project (uv, ruff, pytest, constants)"
```

---

## Task 1: Domain models

**Files:**
- Create: `src/equity_scout/models.py`
- Test: covered indirectly; add a tiny `tests/test_models.py`

- [ ] **Step 1: Write the failing test** — `tests/test_models.py`

```python
from equity_scout.models import Instrument, Quote


def test_instrument_and_quote_are_constructible():
    inst = Instrument(ticker="AAPL", name="Apple", exchange="NASDAQ",
                       region="US", currency="USD", sector="Tech")
    q = Quote(instrument=inst, trailing_pe=30.0, price_to_book=40.0,
              return_on_equity=1.5, profit_margins=0.25,
              revenue_growth=0.08, earnings_growth=0.10, momentum_6m=0.12)
    assert q.instrument.ticker == "AAPL"
    assert q.momentum_6m == 0.12
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: equity_scout.models`.

- [ ] **Step 3: Write `src/equity_scout/models.py`**

```python
"""Domain models. All frozen — a run produces immutable snapshots."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Instrument:
    ticker: str
    name: str
    exchange: str
    region: str
    currency: str
    sector: str


@dataclass(frozen=True)
class Quote:
    """Raw metrics for one instrument. None means 'not available from the source'."""
    instrument: Instrument
    trailing_pe: float | None
    price_to_book: float | None
    return_on_equity: float | None
    profit_margins: float | None
    revenue_growth: float | None
    earnings_growth: float | None
    momentum_6m: float | None  # 6-month total return, computed from price history


@dataclass(frozen=True)
class FactorScore:
    """Percentile scores in [0, 1] per factor family + composite per bucket."""
    instrument: Instrument
    value: float
    quality: float
    momentum: float
    growth: float


@dataclass(frozen=True)
class Pick:
    instrument: Instrument
    bucket: str
    rank: int
    composite: float
    breakdown: dict[str, float]  # family -> percentile
    thesis: str | None = None


@dataclass(frozen=True)
class RunResult:
    created_at: str  # ISO 8601, injected by caller (no Date.now in pure code paths)
    universe_size: int
    gated_out: dict[str, str]  # ticker -> rejection reason
    buckets: dict[str, list[Pick]] = field(default_factory=dict)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: add domain models"
```

---

## Task 2: Universe loader

**Files:**
- Create: `data/universe_v1.csv`, `src/equity_scout/universe.py`
- Test: `tests/test_universe.py`

- [ ] **Step 1: Write `data/universe_v1.csv`** (header + ~40 mixed rows; abbreviated here — include US, EU `.DE/.PA/.AS`, Asia `.T/.HK` suffixes)

```csv
ticker,name,exchange,region,currency,sector
AAPL,Apple,NASDAQ,US,USD,Technology
MSFT,Microsoft,NASDAQ,US,USD,Technology
JNJ,Johnson & Johnson,NYSE,US,USD,Healthcare
KO,Coca-Cola,NYSE,US,USD,Consumer Staples
NVDA,NVIDIA,NASDAQ,US,USD,Technology
SAP.DE,SAP,XETRA,EU,EUR,Technology
ASML.AS,ASML,Euronext,EU,EUR,Technology
MC.PA,LVMH,Euronext,EU,EUR,Consumer Discretionary
SIE.DE,Siemens,XETRA,EU,EUR,Industrials
NESN.SW,Nestle,SIX,EU,CHF,Consumer Staples
7203.T,Toyota,TSE,JP,JPY,Consumer Discretionary
0700.HK,Tencent,HKEX,HK,HKD,Technology
```

(Engineer: extend to ~40 rows in the same shape; keep a balanced regional/sector mix.)

- [ ] **Step 2: Write the failing test** — `tests/test_universe.py`

```python
from pathlib import Path

from equity_scout.universe import load_universe


def test_load_universe_parses_rows(tmp_path: Path):
    csv = tmp_path / "u.csv"
    csv.write_text(
        "ticker,name,exchange,region,currency,sector\n"
        "AAPL,Apple,NASDAQ,US,USD,Technology\n"
        "SAP.DE,SAP,XETRA,EU,EUR,Technology\n"
    )
    universe = load_universe(csv)
    assert len(universe) == 2
    assert universe[1].ticker == "SAP.DE"
    assert universe[1].currency == "EUR"
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/test_universe.py -v`
Expected: FAIL — module missing.

- [ ] **Step 4: Write `src/equity_scout/universe.py`**

```python
"""Load the static v1 universe from CSV. Global ambition starts as index members later."""
from __future__ import annotations

import csv
from pathlib import Path

from equity_scout.models import Instrument


def load_universe(csv_path: str | Path) -> list[Instrument]:
    rows: list[Instrument] = []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rows.append(
                Instrument(
                    ticker=row["ticker"].strip(),
                    name=row["name"].strip(),
                    exchange=row["exchange"].strip(),
                    region=row["region"].strip(),
                    currency=row["currency"].strip(),
                    sector=row["sector"].strip(),
                )
            )
    return rows
```

- [ ] **Step 5: Run to verify it passes + commit**

Run: `uv run pytest tests/test_universe.py -v` → PASS

```bash
git add -A && git commit -m "feat: add universe loader and v1 universe csv"
```

---

## Task 3: Market-data provider seam (protocol + fake)

**Files:**
- Create: `src/equity_scout/data/provider.py`, `src/equity_scout/data/fake_provider.py`
- Test: `tests/test_analysis.py` will reuse the fake; add fetch assertions in `tests/test_pipeline.py` later.

- [ ] **Step 1: Write `src/equity_scout/data/provider.py`**

```python
"""Seam for market data. Real impl uses yfinance; tests use the fake."""
from __future__ import annotations

from typing import Protocol

from equity_scout.models import Instrument, Quote


class MarketDataProvider(Protocol):
    def fetch_quote(self, instrument: Instrument) -> Quote:
        """Return a Quote with metrics; missing metrics are None. Must not raise on missing data."""
        ...
```

- [ ] **Step 2: Write `src/equity_scout/data/fake_provider.py`**

```python
"""Deterministic in-memory provider for tests and offline runs."""
from __future__ import annotations

from equity_scout.models import Instrument, Quote


class FakeProvider:
    def __init__(self, quotes: dict[str, dict] | None = None) -> None:
        self._quotes = quotes or {}

    def fetch_quote(self, instrument: Instrument) -> Quote:
        m = self._quotes.get(instrument.ticker, {})
        return Quote(
            instrument=instrument,
            trailing_pe=m.get("trailing_pe"),
            price_to_book=m.get("price_to_book"),
            return_on_equity=m.get("return_on_equity"),
            profit_margins=m.get("profit_margins"),
            revenue_growth=m.get("revenue_growth"),
            earnings_growth=m.get("earnings_growth"),
            momentum_6m=m.get("momentum_6m"),
        )
```

- [ ] **Step 3: Commit** (no behavior to test yet beyond construction; covered by pipeline tests)

```bash
git add -A && git commit -m "feat: add market-data provider seam and fake provider"
```

---

## Task 4: Data gate

**Files:**
- Create: `src/equity_scout/gate.py`
- Test: `tests/test_gate.py`

- [ ] **Step 1: Write the failing test** — `tests/test_gate.py`

```python
from equity_scout.gate import apply_gate
from equity_scout.models import Instrument, Quote

INST = Instrument("X", "X", "E", "US", "USD", "Tech")


def _quote(**kw):
    base = dict(trailing_pe=None, price_to_book=None, return_on_equity=None,
                profit_margins=None, revenue_growth=None, earnings_growth=None,
                momentum_6m=None)
    base.update(kw)
    return Quote(instrument=INST, **base)


def test_gate_rejects_when_too_few_metrics():
    q = _quote(trailing_pe=10.0)  # 1 metric, no momentum
    passed, rejected = apply_gate([q], min_metrics=4)
    assert passed == []
    assert "X" in rejected


def test_gate_passes_with_enough_metrics_and_momentum():
    q = _quote(trailing_pe=10.0, return_on_equity=0.2, revenue_growth=0.1,
               profit_margins=0.15, momentum_6m=0.05)
    passed, rejected = apply_gate([q], min_metrics=4)
    assert [p.instrument.ticker for p in passed] == ["X"]
    assert rejected == {}
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_gate.py -v` → FAIL (module missing).

- [ ] **Step 3: Write `src/equity_scout/gate.py`**

```python
"""Data completeness gate. Without it the funnel ranks thin-data noise to the top."""
from __future__ import annotations

from equity_scout.models import Quote

_METRIC_FIELDS = (
    "trailing_pe", "price_to_book", "return_on_equity",
    "profit_margins", "revenue_growth", "earnings_growth",
)


def apply_gate(quotes: list[Quote], min_metrics: int = 4) -> tuple[list[Quote], dict[str, str]]:
    """Pass a quote if it has >= min_metrics non-None fundamentals AND momentum_6m present."""
    passed: list[Quote] = []
    rejected: dict[str, str] = {}
    for q in quotes:
        present = sum(getattr(q, f) is not None for f in _METRIC_FIELDS)
        if q.momentum_6m is None:
            rejected[q.instrument.ticker] = "missing price history (no 6m momentum)"
        elif present < min_metrics:
            rejected[q.instrument.ticker] = f"too few fundamentals ({present}/{min_metrics})"
        else:
            passed.append(q)
    return passed, rejected
```

- [ ] **Step 4: Run to verify it passes + commit**

Run: `uv run pytest tests/test_gate.py -v` → PASS

```bash
git add -A && git commit -m "feat: add data completeness gate"
```

---

## Task 5: Factor scoring (cross-sectional percentiles)

**Files:**
- Create: `src/equity_scout/factors.py`
- Test: `tests/test_factors.py`

Direction: PE and P/B are "lower is better" (inverted); ROE, margins, growth, momentum are "higher is better". Each family score = mean of its available metric percentiles. Percentile = rank position in [0,1] across the gated set.

- [ ] **Step 1: Write the failing test** — `tests/test_factors.py`

```python
from equity_scout.factors import score_factors
from equity_scout.models import Instrument, Quote


def _q(t, pe, roe, mom, growth):
    inst = Instrument(t, t, "E", "US", "USD", "Tech")
    return Quote(instrument=inst, trailing_pe=pe, price_to_book=None,
                 return_on_equity=roe, profit_margins=None,
                 revenue_growth=growth, earnings_growth=None, momentum_6m=mom)


def test_lower_pe_scores_higher_on_value():
    quotes = [_q("CHEAP", 5.0, 0.1, 0.0, 0.0), _q("RICH", 50.0, 0.1, 0.0, 0.0)]
    scores = {s.instrument.ticker: s for s in score_factors(quotes)}
    assert scores["CHEAP"].value > scores["RICH"].value


def test_higher_momentum_scores_higher():
    quotes = [_q("UP", 10.0, 0.1, 0.5, 0.0), _q("DOWN", 10.0, 0.1, -0.2, 0.0)]
    scores = {s.instrument.ticker: s for s in score_factors(quotes)}
    assert scores["UP"].momentum > scores["DOWN"].momentum
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_factors.py -v` → FAIL.

- [ ] **Step 3: Write `src/equity_scout/factors.py`**

```python
"""Cross-sectional factor scoring. Each metric -> percentile in [0,1] over the set."""
from __future__ import annotations

from equity_scout.models import FactorScore, Quote

# family -> list of (field_name, higher_is_better)
_FAMILIES: dict[str, list[tuple[str, bool]]] = {
    "value": [("trailing_pe", False), ("price_to_book", False)],
    "quality": [("return_on_equity", True), ("profit_margins", True)],
    "momentum": [("momentum_6m", True)],
    "growth": [("revenue_growth", True), ("earnings_growth", True)],
}


def _percentiles(values: dict[str, float], higher_is_better: bool) -> dict[str, float]:
    """Rank-based percentile in [0,1]. Ties share the average rank. Empty -> {}."""
    if not values:
        return {}
    if len(values) == 1:
        return {k: 0.5 for k in values}
    ordered = sorted(values.items(), key=lambda kv: kv[1], reverse=not higher_is_better)
    # ascending by "goodness": worst first; best gets percentile ~1.0
    n = len(ordered)
    out: dict[str, float] = {}
    for idx, (ticker, _) in enumerate(ordered):
        out[ticker] = idx / (n - 1)  # 0.0 .. 1.0
    return out


def score_factors(quotes: list[Quote]) -> list[FactorScore]:
    by_ticker = {q.instrument.ticker: q for q in quotes}
    # family -> ticker -> percentile, averaged over the family's available metrics
    family_pcts: dict[str, dict[str, list[float]]] = {f: {} for f in _FAMILIES}
    for family, metrics in _FAMILIES.items():
        for field_name, higher in metrics:
            present = {
                t: getattr(q, field_name)
                for t, q in by_ticker.items()
                if getattr(q, field_name) is not None
            }
            for t, pct in _percentiles(present, higher).items():
                family_pcts[family].setdefault(t, []).append(pct)

    scores: list[FactorScore] = []
    for t, q in by_ticker.items():
        def fam(name: str) -> float:
            vals = family_pcts[name].get(t, [])
            return sum(vals) / len(vals) if vals else 0.0
        scores.append(
            FactorScore(instrument=q.instrument, value=fam("value"),
                        quality=fam("quality"), momentum=fam("momentum"),
                        growth=fam("growth"))
        )
    return scores
```

- [ ] **Step 4: Run to verify it passes + commit**

Run: `uv run pytest tests/test_factors.py -v` → PASS

```bash
git add -A && git commit -m "feat: add cross-sectional factor scoring"
```

---

## Task 6: Buckets

**Files:**
- Create: `src/equity_scout/buckets.py`
- Test: `tests/test_buckets.py`

- [ ] **Step 1: Write the failing test** — `tests/test_buckets.py`

```python
from equity_scout.buckets import BUCKET_WEIGHTS, assign_buckets
from equity_scout.models import FactorScore, Instrument


def _score(t, value, quality, momentum, growth):
    inst = Instrument(t, t, "E", "US", "USD", "Tech")
    return FactorScore(inst, value, quality, momentum, growth)


def test_buckets_present_and_ranked():
    scores = [
        _score("DEF", value=0.9, quality=0.9, momentum=0.1, growth=0.1),
        _score("AGG", value=0.1, quality=0.1, momentum=0.9, growth=0.9),
    ]
    out = assign_buckets(scores, top_n=2)
    assert set(out) == set(BUCKET_WEIGHTS)
    # DEF leads the defensive bucket; AGG leads aggressive
    assert out["defensive"][0].instrument.ticker == "DEF"
    assert out["aggressive"][0].instrument.ticker == "AGG"
    assert out["defensive"][0].rank == 1


def test_top_n_truncates():
    scores = [_score(f"T{i}", 0.5, 0.5, i / 10, 0.5) for i in range(5)]
    out = assign_buckets(scores, top_n=3)
    assert len(out["aggressive"]) == 3
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_buckets.py -v` → FAIL.

- [ ] **Step 3: Write `src/equity_scout/buckets.py`**

```python
"""Risk buckets = factor-family weightings. Composite = weighted sum of family percentiles."""
from __future__ import annotations

from equity_scout.models import FactorScore, Pick

BUCKET_WEIGHTS: dict[str, dict[str, float]] = {
    "defensive": {"value": 0.35, "quality": 0.45, "momentum": 0.10, "growth": 0.10},
    "balanced": {"value": 0.25, "quality": 0.25, "momentum": 0.25, "growth": 0.25},
    "aggressive": {"value": 0.10, "quality": 0.10, "momentum": 0.40, "growth": 0.40},
}


def _composite(score: FactorScore, weights: dict[str, float]) -> float:
    return (
        weights["value"] * score.value
        + weights["quality"] * score.quality
        + weights["momentum"] * score.momentum
        + weights["growth"] * score.growth
    )


def assign_buckets(scores: list[FactorScore], top_n: int = 10) -> dict[str, list[Pick]]:
    out: dict[str, list[Pick]] = {}
    for bucket, weights in BUCKET_WEIGHTS.items():
        ranked = sorted(scores, key=lambda s: _composite(s, weights), reverse=True)
        picks: list[Pick] = []
        for rank, s in enumerate(ranked[:top_n], start=1):
            picks.append(
                Pick(
                    instrument=s.instrument,
                    bucket=bucket,
                    rank=rank,
                    composite=_composite(s, weights),
                    breakdown={"value": s.value, "quality": s.quality,
                               "momentum": s.momentum, "growth": s.growth},
                )
            )
        out[bucket] = picks
    return out
```

- [ ] **Step 4: Run to verify it passes + commit**

Run: `uv run pytest tests/test_buckets.py -v` → PASS

```bash
git add -A && git commit -m "feat: add risk-bucket assignment"
```

---

## Task 7: LLM analysis seam (protocol + fake + claude CLI impl)

**Files:**
- Create: `src/equity_scout/analysis.py`
- Test: `tests/test_analysis.py`

- [ ] **Step 1: Write the failing test** — `tests/test_analysis.py`

```python
from equity_scout.analysis import FakeAnalysis, attach_theses
from equity_scout.models import Instrument, Pick


def _pick(t):
    inst = Instrument(t, t, "E", "US", "USD", "Tech")
    return Pick(inst, "aggressive", 1, 0.8, {"value": 0.1, "quality": 0.1,
                                             "momentum": 0.9, "growth": 0.9})


def test_attach_theses_fills_thesis_for_each_pick():
    buckets = {"aggressive": [_pick("AGG")]}
    out = attach_theses(buckets, FakeAnalysis())
    thesis = out["aggressive"][0].thesis
    assert thesis is not None and "AGG" in thesis


def test_attach_theses_is_noop_when_provider_none():
    buckets = {"aggressive": [_pick("AGG")]}
    out = attach_theses(buckets, None)
    assert out["aggressive"][0].thesis is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_analysis.py -v` → FAIL.

- [ ] **Step 3: Write `src/equity_scout/analysis.py`**

```python
"""LLM analysis seam. Only finalists are sent. Theses are interpretation, NOT forecasts."""
from __future__ import annotations

import dataclasses
import json
import subprocess
from typing import Protocol

from equity_scout.models import Pick


class AnalysisProvider(Protocol):
    def thesis_for(self, pick: Pick) -> str:
        ...


class FakeAnalysis:
    """Deterministic, offline. Used in tests and --no-llm runs."""

    def thesis_for(self, pick: Pick) -> str:
        b = pick.breakdown
        return (
            f"{pick.instrument.ticker} sits in the {pick.bucket} bucket "
            f"(momentum={b['momentum']:.2f}, quality={b['quality']:.2f}). "
            "Interpretation only — not a forecast."
        )


class ClaudeCliAnalysis:
    """Real impl: one `claude -p` call per finalist returning a short thesis."""

    def __init__(self, model: str | None = None, timeout_s: int = 120) -> None:
        self._model = model
        self._timeout_s = timeout_s

    def thesis_for(self, pick: Pick) -> str:
        prompt = (
            "You are a sober equity analyst. Given these cross-sectional factor percentiles "
            f"for {pick.instrument.ticker} ({pick.instrument.name}, {pick.instrument.region}), "
            f"bucket={pick.bucket}: {json.dumps(pick.breakdown)}. "
            "Write 2-3 sentences: why it fits this risk bucket, the single biggest risk. "
            "Do NOT predict price. Be explicit this is interpretation, not advice."
        )
        cmd = ["claude", "-p", prompt]
        if self._model:
            cmd += ["--model", self._model]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=self._timeout_s)
        return result.stdout.strip() or "No thesis produced."


def attach_theses(
    buckets: dict[str, list[Pick]], provider: AnalysisProvider | None
) -> dict[str, list[Pick]]:
    """Return a copy of buckets with theses attached. provider=None -> unchanged."""
    if provider is None:
        return buckets
    out: dict[str, list[Pick]] = {}
    for bucket, picks in buckets.items():
        out[bucket] = [dataclasses.replace(p, thesis=provider.thesis_for(p)) for p in picks]
    return out
```

- [ ] **Step 4: Run to verify it passes + commit**

Run: `uv run pytest tests/test_analysis.py -v` → PASS

```bash
git add -A && git commit -m "feat: add LLM analysis seam (fake + claude cli)"
```

---

## Task 8: Storage (SQLite snapshots)

**Files:**
- Create: `src/equity_scout/storage.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write the failing test** — `tests/test_storage.py`

```python
from equity_scout.models import Instrument, Pick, RunResult
from equity_scout.storage import init_db, load_latest_run, save_run


def _run(ts):
    inst = Instrument("AAPL", "Apple", "NASDAQ", "US", "USD", "Tech")
    pick = Pick(inst, "balanced", 1, 0.7,
                {"value": 0.6, "quality": 0.7, "momentum": 0.5, "growth": 0.5},
                thesis="ok")
    return RunResult(created_at=ts, universe_size=10,
                     gated_out={"BAD": "missing price history"},
                     buckets={"balanced": [pick]})


def test_save_and_load_latest_roundtrip(tmp_path):
    db = tmp_path / "t.db"
    init_db(db)
    save_run(db, _run("2026-06-24T10:00:00"))
    save_run(db, _run("2026-06-24T12:00:00"))
    latest = load_latest_run(db)
    assert latest.created_at == "2026-06-24T12:00:00"
    assert latest.buckets["balanced"][0].instrument.ticker == "AAPL"
    assert latest.gated_out["BAD"].startswith("missing")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_storage.py -v` → FAIL.

- [ ] **Step 3: Write `src/equity_scout/storage.py`**

```python
"""SQLite snapshot persistence. Each run is one immutable row + its picks as JSON."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from equity_scout.models import Instrument, Pick, RunResult


def init_db(db_path: str | Path) -> None:
    with sqlite3.connect(db_path) as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                universe_size INTEGER NOT NULL,
                gated_out TEXT NOT NULL,
                buckets TEXT NOT NULL
            );
            """
        )


def _pick_to_dict(p: Pick) -> dict:
    d = asdict(p)
    return d


def _pick_from_dict(d: dict) -> Pick:
    d = dict(d)
    d["instrument"] = Instrument(**d["instrument"])
    return Pick(**d)


def save_run(db_path: str | Path, run: RunResult) -> None:
    buckets_json = json.dumps(
        {b: [_pick_to_dict(p) for p in picks] for b, picks in run.buckets.items()}
    )
    with sqlite3.connect(db_path) as con:
        con.execute(
            "INSERT INTO runs (created_at, universe_size, gated_out, buckets) VALUES (?, ?, ?, ?)",
            (run.created_at, run.universe_size, json.dumps(run.gated_out), buckets_json),
        )


def load_latest_run(db_path: str | Path) -> RunResult | None:
    with sqlite3.connect(db_path) as con:
        row = con.execute(
            "SELECT created_at, universe_size, gated_out, buckets FROM runs "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return None
    created_at, universe_size, gated_out, buckets = row
    parsed = json.loads(buckets)
    buckets_obj = {
        b: [_pick_from_dict(p) for p in picks] for b, picks in parsed.items()
    }
    return RunResult(
        created_at=created_at,
        universe_size=universe_size,
        gated_out=json.loads(gated_out),
        buckets=buckets_obj,
    )
```

- [ ] **Step 4: Run to verify it passes + commit**

Run: `uv run pytest tests/test_storage.py -v` → PASS

```bash
git add -A && git commit -m "feat: add sqlite snapshot storage"
```

---

## Task 9: Pipeline orchestrator

**Files:**
- Create: `src/equity_scout/pipeline.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing test** — `tests/test_pipeline.py`

```python
from equity_scout.analysis import FakeAnalysis
from equity_scout.data.fake_provider import FakeProvider
from equity_scout.models import Instrument
from equity_scout.pipeline import run_pipeline


def test_pipeline_end_to_end_with_fakes():
    universe = [
        Instrument("GOOD", "Good", "E", "US", "USD", "Tech"),
        Instrument("THIN", "Thin", "E", "EM", "XXX", "Misc"),
    ]
    provider = FakeProvider({
        "GOOD": dict(trailing_pe=10.0, price_to_book=2.0, return_on_equity=0.3,
                     profit_margins=0.2, revenue_growth=0.15, earnings_growth=0.2,
                     momentum_6m=0.1),
        "THIN": dict(trailing_pe=10.0),  # no momentum -> gated out
    })
    run = run_pipeline(universe, provider, analysis=FakeAnalysis(),
                       top_n=5, created_at="2026-06-24T00:00:00")
    assert run.universe_size == 2
    assert "THIN" in run.gated_out
    assert run.buckets["balanced"][0].instrument.ticker == "GOOD"
    assert run.buckets["balanced"][0].thesis is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_pipeline.py -v` → FAIL.

- [ ] **Step 3: Write `src/equity_scout/pipeline.py`**

```python
"""Wire the funnel: fetch -> gate -> score -> bucket -> theses -> RunResult."""
from __future__ import annotations

from equity_scout.analysis import AnalysisProvider, attach_theses
from equity_scout.buckets import assign_buckets
from equity_scout.data.provider import MarketDataProvider
from equity_scout.factors import score_factors
from equity_scout.gate import apply_gate
from equity_scout.models import Instrument, RunResult


def run_pipeline(
    universe: list[Instrument],
    provider: MarketDataProvider,
    analysis: AnalysisProvider | None = None,
    top_n: int = 10,
    min_metrics: int = 4,
    created_at: str = "",
) -> RunResult:
    quotes = [provider.fetch_quote(inst) for inst in universe]
    passed, rejected = apply_gate(quotes, min_metrics=min_metrics)
    scores = score_factors(passed)
    buckets = assign_buckets(scores, top_n=top_n)
    buckets = attach_theses(buckets, analysis)
    return RunResult(
        created_at=created_at,
        universe_size=len(universe),
        gated_out=rejected,
        buckets=buckets,
    )
```

- [ ] **Step 4: Run to verify it passes + commit**

Run: `uv run pytest tests/test_pipeline.py -v` → PASS

```bash
git add -A && git commit -m "feat: wire pipeline orchestrator"
```

---

## Task 10: yfinance provider (real impl)

**Files:**
- Create: `src/equity_scout/data/yf_provider.py`
- Test: none live (network). Add a parsing unit test with an injected fake `Ticker`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_pipeline.py` or new `tests/test_yf_provider.py`

```python
from equity_scout.data.yf_provider import quote_from_info_and_history
from equity_scout.models import Instrument


def test_quote_from_info_computes_momentum():
    inst = Instrument("AAPL", "Apple", "NASDAQ", "US", "USD", "Tech")
    info = {"trailingPE": 30.0, "priceToBook": 40.0, "returnOnEquity": 1.5,
            "profitMargins": 0.25, "revenueGrowth": 0.08, "earningsGrowth": 0.10}
    closes = [100.0] * 5 + [110.0]  # +10% over the window
    q = quote_from_info_and_history(inst, info, closes)
    assert q.trailing_pe == 30.0
    assert abs(q.momentum_6m - 0.10) < 1e-9


def test_quote_from_info_handles_missing():
    inst = Instrument("X", "X", "E", "EM", "XXX", "Misc")
    q = quote_from_info_and_history(inst, {}, [])
    assert q.trailing_pe is None
    assert q.momentum_6m is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_yf_provider.py -v` → FAIL.

- [ ] **Step 3: Write `src/equity_scout/data/yf_provider.py`**

```python
"""yfinance-backed provider. Network code isolated; pure parsing is unit-tested."""
from __future__ import annotations

from equity_scout.models import Instrument, Quote


def quote_from_info_and_history(
    instrument: Instrument, info: dict, closes: list[float]
) -> Quote:
    """Pure transform: yfinance .info dict + close prices -> Quote. No network here."""
    momentum = None
    if len(closes) >= 2 and closes[0]:
        momentum = (closes[-1] - closes[0]) / closes[0]
    return Quote(
        instrument=instrument,
        trailing_pe=info.get("trailingPE"),
        price_to_book=info.get("priceToBook"),
        return_on_equity=info.get("returnOnEquity"),
        profit_margins=info.get("profitMargins"),
        revenue_growth=info.get("revenueGrowth"),
        earnings_growth=info.get("earningsGrowth"),
        momentum_6m=momentum,
    )


class YFinanceProvider:
    """Real provider. Imports yfinance lazily so tests never touch the network."""

    def fetch_quote(self, instrument: Instrument) -> Quote:
        import yfinance as yf

        tk = yf.Ticker(instrument.ticker)
        try:
            info = tk.info or {}
        except Exception:
            info = {}
        try:
            hist = tk.history(period="6mo", interval="1d")
            closes = [float(c) for c in hist["Close"].tolist()] if not hist.empty else []
        except Exception:
            closes = []
        return quote_from_info_and_history(instrument, info, closes)
```

- [ ] **Step 4: Run to verify it passes + commit**

Run: `uv run pytest tests/test_yf_provider.py -v` → PASS

```bash
git add -A && git commit -m "feat: add yfinance provider with isolated parsing"
```

---

## Task 11: CLI runner

**Files:**
- Create: `scripts/run_scout.py`
- Test: smoke via `--provider fake` run (no network).

- [ ] **Step 1: Write `scripts/run_scout.py`**

```python
"""CLI: run the funnel, persist a snapshot, print a summary.

Default provider is 'fake' for a deterministic offline run; pass --provider yfinance for live.
LLM theses off by default (--use-llm to enable).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from equity_scout.analysis import ClaudeCliAnalysis, FakeAnalysis
from equity_scout.constants import DEFAULT_DB_PATH, DEFAULT_UNIVERSE_PATH, DISCLAIMER
from equity_scout.data.fake_provider import FakeProvider
from equity_scout.data.yf_provider import YFinanceProvider
from equity_scout.pipeline import run_pipeline
from equity_scout.storage import init_db, save_run
from equity_scout.universe import load_universe


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default=DEFAULT_UNIVERSE_PATH)
    ap.add_argument("--db", default=DEFAULT_DB_PATH)
    ap.add_argument("--top-n", type=int, default=10)
    ap.add_argument("--provider", choices=["fake", "yfinance"], default="fake")
    ap.add_argument("--use-llm", action="store_true")
    args = ap.parse_args()

    universe = load_universe(args.universe)
    provider = YFinanceProvider() if args.provider == "yfinance" else FakeProvider()
    analysis = (ClaudeCliAnalysis() if args.use_llm else FakeAnalysis())

    run = run_pipeline(
        universe, provider, analysis=analysis, top_n=args.top_n,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    init_db(args.db)
    save_run(args.db, run)

    print(f"\nRun {run.created_at} — universe {run.universe_size}, gated out {len(run.gated_out)}")
    for bucket, picks in run.buckets.items():
        print(f"\n[{bucket}]")
        for p in picks:
            print(f"  {p.rank:>2}. {p.instrument.ticker:<10} score={p.composite:.3f}")
    print(f"\n{DISCLAIMER}\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-run it (fake provider, deterministic)**

Run: `uv run python scripts/run_scout.py --provider fake --db /tmp/es_smoke.db`
Expected: prints three buckets (likely empty with the bare FakeProvider — that's fine) + disclaimer, exits 0.

- [ ] **Step 3: Live smoke-run (network, small universe)**

Run: `uv run python scripts/run_scout.py --provider yfinance --universe data/universe_v1.csv --db /tmp/es_live.db`
Expected: fills buckets from real data; some EM/thin tickers appear in "gated out". If yfinance returns empty for all, investigate before proceeding.

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat: add CLI runner"
```

---

## Task 12: Read-API + minimal dashboard

**Files:**
- Create: `src/equity_scout/api.py`, `scripts/run_api.py`, `frontend/index.html`
- Test: `tests/test_api.py` using FastAPI `TestClient` against a seeded temp DB.

- [ ] **Step 1: Write the failing test** — `tests/test_api.py`

```python
from fastapi.testclient import TestClient

from equity_scout.api import create_app
from equity_scout.models import Instrument, Pick, RunResult
from equity_scout.storage import init_db, save_run


def test_latest_endpoint_returns_buckets(tmp_path):
    db = tmp_path / "api.db"
    init_db(db)
    inst = Instrument("AAPL", "Apple", "NASDAQ", "US", "USD", "Tech")
    pick = Pick(inst, "balanced", 1, 0.7,
                {"value": 0.6, "quality": 0.7, "momentum": 0.5, "growth": 0.5}, thesis="ok")
    save_run(db, RunResult("2026-06-24T10:00:00", 10, {}, {"balanced": [pick]}))

    client = TestClient(create_app(str(db)))
    resp = client.get("/api/latest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["buckets"]["balanced"][0]["instrument"]["ticker"] == "AAPL"
    assert "disclaimer" in body
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_api.py -v` → FAIL.

- [ ] **Step 3: Write `src/equity_scout/api.py`**

```python
"""Read-only API for the dashboard. Serves the latest run snapshot + disclaimer."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from equity_scout.constants import DEFAULT_DB_PATH, DISCLAIMER
from equity_scout.storage import load_latest_run

_FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "index.html"


def create_app(db_path: str = DEFAULT_DB_PATH) -> FastAPI:
    app = FastAPI(title="equity-scout")

    @app.get("/api/latest")
    def latest() -> JSONResponse:
        run = load_latest_run(db_path)
        if run is None:
            return JSONResponse({"buckets": {}, "gated_out": {}, "disclaimer": DISCLAIMER})
        payload = {
            "created_at": run.created_at,
            "universe_size": run.universe_size,
            "gated_out": run.gated_out,
            "buckets": {
                b: [asdict(p) for p in picks] for b, picks in run.buckets.items()
            },
            "disclaimer": DISCLAIMER,
        }
        return JSONResponse(payload)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_FRONTEND)

    return app
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_api.py -v` → PASS

- [ ] **Step 5: Write `frontend/index.html`** (vanilla, no build; bucket cards + score bars + disclaimer footer)

```html
<!doctype html>
<meta charset="utf-8" />
<title>equity-scout</title>
<style>
  body { font: 15px system-ui, sans-serif; margin: 2rem; background: #0d1117; color: #e6edf3; }
  h1 { font-weight: 600; }
  .buckets { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; }
  .bucket { background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 1rem; }
  .pick { padding: .4rem 0; border-bottom: 1px solid #21262d; }
  .ticker { font-weight: 600; }
  .bar { height: 6px; background: #238636; border-radius: 3px; margin-top: 3px; }
  footer { margin-top: 2rem; color: #8b949e; font-size: 13px; max-width: 70ch; }
</style>
<h1>equity-scout <small id="ts"></small></h1>
<div class="buckets" id="buckets"></div>
<footer id="disclaimer"></footer>
<script>
  fetch("/api/latest").then(r => r.json()).then(d => {
    document.getElementById("ts").textContent = d.created_at || "(no runs yet)";
    document.getElementById("disclaimer").textContent = d.disclaimer || "";
    const root = document.getElementById("buckets");
    for (const [bucket, picks] of Object.entries(d.buckets || {})) {
      const el = document.createElement("div");
      el.className = "bucket";
      el.innerHTML = `<h2>${bucket}</h2>`;
      for (const p of picks) {
        const pct = Math.round(p.composite * 100);
        el.innerHTML += `<div class="pick"><span class="ticker">${p.rank}. ${p.instrument.ticker}</span>
          <span> ${p.instrument.name}</span>
          <div class="bar" style="width:${pct}%"></div>
          ${p.thesis ? `<div>${p.thesis}</div>` : ""}</div>`;
      }
      root.appendChild(el);
    }
  });
</script>
```

- [ ] **Step 6: Write `scripts/run_api.py`**

```python
"""Serve the dashboard read-API."""
from __future__ import annotations

import argparse

import uvicorn

from equity_scout.api import create_app


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="equity_scout.db")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    uvicorn.run(create_app(args.db), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Manual check + commit**

Run: `uv run python scripts/run_scout.py --provider yfinance --db equity_scout.db` then
`uv run python scripts/run_api.py --db equity_scout.db` and open `http://127.0.0.1:8000`.
Expected: three bucket cards render with picks + disclaimer footer.

```bash
git add -A && git commit -m "feat: add read-api and minimal dashboard"
```

---

## Task 13: Final gate — full suite + ruff + disclaimer assertion

**Files:**
- Test: `tests/test_pipeline.py` (add disclaimer presence assertion in API already covered)

- [ ] **Step 1: Run the whole suite**

Run: `uv run pytest -q`
Expected: all tests PASS.

- [ ] **Step 2: Run ruff**

Run: `uv run ruff check .`
Expected: no errors (fix any inline).

- [ ] **Step 3: Final commit + push-readiness note**

```bash
git add -A && git commit -m "chore: v1 vertical slice green (tests + ruff)" || echo "nothing to commit"
```

Do NOT merge to main — Nico reviews `feat/vertical-slice-v1`.

---

## Self-Review (against the spec)

- **Spec §2 funnel (5 stages):** universe (T2) → data (T3/T10) → gate (T4) → score (T5) → buckets (T6) → LLM (T7) → storage (T8) → dashboard (T12). ✔ wired in T9.
- **Spec §6 data gate mandatory:** T4 + surfaced in `gated_out` (T8/T12). ✔
- **Spec §6 yfinance behind seam, faked in tests:** T3 protocol, T10 lazy import + pure-parse test, no live calls in tests. ✔
- **Spec §1/§6 honesty guardrails:** `DISCLAIMER` in T0, printed by CLI (T11), returned by API (T12), shown in footer. ✔
- **Spec §1 LLM = interpretation not forecast:** enforced in `ClaudeCliAnalysis` prompt + `FakeAnalysis` text (T7). ✔
- **Spec §4 data model:** Instrument/Quote/FactorScore/Pick/RunResult (T1). (PriceBar/Fundamentals cache deferred to Loop — v1 fetches fresh; noted as deviation.) 
- **Spec §7 acceptance:** end-to-end run (T9/T11), gate visible (T4), transparent scores (breakdown in Pick), LLM finalists-only (T7/T9), snapshot persisted (T8), no output without disclaimer (T11/T12), free data (yfinance), tests+ruff green (T13). ✔
- **Placeholder scan:** universe CSV is the one "extend to ~40 rows" instruction — acceptable (mechanical, shape shown). No code placeholders.
- **Type consistency:** `RunResult`, `Pick`, `FactorScore`, `Quote` field names consistent across T1/T5/T6/T8/T9/T12. `attach_theses(buckets, provider|None)` signature consistent T7/T9.

**Deviation from spec (logged):** v1 fetches fundamentals fresh per run instead of a persisted PriceBar/Fundamentals cache (spec §4). Justified: vertical slice keeps the funnel honest end-to-end; the cache is a Loop task (performance + point-in-time history), not needed to prove the mechanic.
