# Pitch v2 — Plain Language + Tranches + KGV + Analyst Consensus

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development / executing-plans. Checkbox (`- [ ]`) steps.

**Goal:** Rewrite the Telegram/inbox pitch from a jargon-dense fact dump into a plain-German note a beginner understands: what the company is, why now, a concrete **tranche buy-in plan** (at which prices, in how many steps), the **KGV (P/E)** as a plain fact, and an **analyst-consensus** price target + implied upside — the target explicitly attributed to third-party analysts (not our forecast), with an honest "keine Schätzung verfügbar" when the free data has no coverage.

**Why / decision:** Nico (non-expert) found the current pitch too technical and asked for tranches, KGV, and price targets. Price targets clash with the project's core "no forecasts, not advice" stance — resolved (Nico's call): surface **real analyst consensus** from the free data source, clearly labelled as third-party opinions that are often wrong; never a self-invented target.

**Architecture:** `pitch.build_pitch` gets a plain-language layout consuming the watchlist `entry` plus an optional `fundamentals` dict. Tranches come from the already-computed `EntryPlan.dip_tranches` (now / −7 % / −15 %), carried into `WatchlistEntry` (additive JSON field, no migration). KGV + analyst target + analyst count come from a NEW `fundamentals.py` seam that lazily reads `yfinance .info` (US-heavy coverage; graceful partial/None). `notify` fetches fundamentals per candidate via an injectable seam and passes them to `build_pitch`. The Ollama seam still writes the plain "was/warum" prose (interpret-not-forecast) with a deterministic fallback.

**Tech Stack:** Python 3.11, stdlib, yfinance (behind a lazy seam), pytest, ruff. **No new deps.**
**Builds on:** Phase 1 (`radar.EntryPlan`/`WatchlistEntry`), Phase 2 (`pitch.py`, `notify.py`, `run_notify.py`).

**Conventions:** German user strings with umlauts; English code. Pure functions + DI seams; no network in tests; imports top-of-file; gate `.venv/bin/python -m pytest && .venv/bin/ruff check .` per commit (baseline 376 — report true totals); strict TDD; one commit per task; include plan-doc checkbox edits.

**Honesty invariants (a review MUST reject a violation):**
1. The analyst target is labelled as **third-party analyst consensus** ("Analysten (N Schätzungen)"), never the system's own view; missing coverage → literal "keine Analystenschätzung verfügbar", never a fabricated number.
2. Tranche prices are **reference levels to scale in**, framed as such — not a prediction of where the price will go.
3. The 0–100 score stays framed as "kein Kursversprechen".
4. The LLM prose interprets the given numbers only — no forecasts (unchanged guardrail).

---

### Task 1: Carry tranches into the watchlist entry

**Files:** `src/equity_scout/radar.py`, `tests/test_radar.py`.

`EntryPlan.dip_tranches` is a `list[Tranche]` (`label`, `fraction`, `trigger_price`) already built by `compute_entry_plan` (now / −7 % / −15 %). Add a `tranches: list[dict]` field to `WatchlistEntry` populated from `plan.dip_tranches` (as `{label, fraction, trigger_price}` dicts so it JSON-round-trips through `radar_storage` with no schema change — it lives in the `watchlists.data` blob).

- [x] **Step 1:** failing test — `build_watchlist` output entry has `tranches` = 3 dicts with `label`/`fraction`/`trigger_price`, trigger prices descending (now > −7 % > −15 %), summing `fraction` ≈ 1.0.
- [x] **Step 2:** run → fail.
- [x] **Step 3:** add the field + populate from `plan.dip_tranches` via `dataclasses.asdict` (or explicit dict). Keep it frozen-dataclass-consistent.
- [x] **Step 4:** run → pass; full gate.
- [x] **Step 5:** commit `feat: carry entry tranches into the watchlist entry`.

---

### Task 2: Fundamentals + analyst-consensus seam

**Files:** `src/equity_scout/fundamentals.py` (create), `tests/test_fundamentals.py`.

```python
"""Per-ticker fundamentals + third-party analyst consensus for the pitch.

Lazy yfinance `.info` read (US-heavy coverage; EU/JP often missing) behind a thin
function so the pitch path is testable and offline-safe. EVERYTHING is optional:
any missing field comes back None and the pitch renders an honest gap. The analyst
target is THIRD-PARTY consensus (sell-side analysts), never our own forecast — the
pitch labels it as such.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Fundamentals:
    trailing_pe: float | None       # KGV
    analyst_target: float | None    # mean sell-side target price
    analyst_count: int | None       # number of analyst opinions behind the target
    currency: str | None


def _finite(value: object) -> float | None:
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f > 0 else None


def from_info(info: dict) -> Fundamentals:
    """Pure: map a yfinance `.info`-shaped dict to Fundamentals (all fields optional)."""
    count = info.get("numberOfAnalystOpinions")
    try:
        count = int(count) if count is not None else None
    except (TypeError, ValueError):
        count = None
    return Fundamentals(
        trailing_pe=_finite(info.get("trailingPE")),
        analyst_target=_finite(info.get("targetMeanPrice")),
        analyst_count=count if (count or 0) > 0 else None,
        currency=info.get("currency") or None,
    )


def fetch_fundamentals(ticker: str) -> Fundamentals:
    """Live fetch via yfinance `.info` (lazy import, network). Returns an all-None
    Fundamentals on any failure — never raises into the pitch path."""
    try:
        import yfinance as yf

        info = yf.Ticker(ticker).info
        return from_info(info if isinstance(info, dict) else {})
    except Exception:
        return Fundamentals(None, None, None, None)
```

- [x] **Step 1:** failing tests for `from_info` — full info → all fields; missing/zero/negative/NaN `trailingPE`/`targetMeanPrice` → None; `numberOfAnalystOpinions` 0/None → None, positive → int; currency passthrough/empty→None. (No test hits the network; `fetch_fundamentals` is exercised only via `from_info` + a monkeypatched-yfinance smoke that asserts the all-None fallback on a raising stub.)
- [x] **Step 2–4:** implement (code above), run, gate.
- [x] **Step 5:** commit `feat: add fundamentals + analyst-consensus fetch seam`.

---

### Task 3: Rewrite the pitch (plain language + all sections)

**Files:** `src/equity_scout/pitch.py`, `tests/test_pitch.py`.

New layout (German, beginner-readable). `build_pitch(entry, fundamentals=None, ask=_ask_default)`:

```
📈 {ticker} — {name}
{LLM plain "was/warum" prose, or fallback}

Einstiegs-Score: {round(composite*100)}/100 ({niedrig<40 / mittel<70 / hoch}) — wie attraktiv der Einstieg gerade ist, kein Kursversprechen.

So könntest du einsteigen — in {n} Schritten:
• {label}: bei ~{trigger_price:.2f}{cur}
… (one line per tranche; if a tranche has no trigger_price, label it "zeitlich gestaffelt")
Nicht alles auf einmal — in Schritten kaufen glättet den Einstiegspreis.

Kennzahlen:
• KGV {trailing_pe:.0f} — Kurs-Gewinn-Verhältnis; grob „wie viele Jahresgewinne kostet die Aktie", niedriger = günstiger bewertet.   [omit line if None]
• {abs(drawdown_from_high or via readings)}… — keep it simple: "{proximity as % vs zone}"; reuse zone_note in plain form.

Analystensicht: Ø-Kursziel {analyst_target:.2f}{cur} ({analyst_count} Schätzungen) → {implied upside %:+.0f} % zum aktuellen Kurs. Fremde Analystenmeinungen, oft falsch — keine Garantie.
   [if analyst_target/count missing → "Analystensicht: keine Schätzung verfügbar (bei kleineren/nicht-US-Werten normal)."]

Risiko: {weakest reading reason, in plain words}

{SHORT_DISCLAIMER}
```

Rules:
- Score band words: `< 40` → "niedrig", `< 70` → "mittel", else "hoch".
- Implied upside = `analyst_target / price - 1` (only when both present and price > 0).
- Currency suffix: use `fundamentals.currency` if present (e.g. " USD"), else "".
- Analyst section: present ⟺ `analyst_target` AND `analyst_count` both non-None; else the honest "keine Schätzung verfügbar" line. NEVER compute or guess a target.
- KGV line omitted entirely when `trailing_pe` is None (no "—" clutter; honest absence).
- Keep the Ollama seam + `PITCH_LLM_UNAVAILABLE_PREFIX` fallback for the top prose only; the structured sections are deterministic.
- Keep the truncation-preserves-header+disclaimer guarantee (budget math) — but the structured sections (tranches/analyst) are short and should never be the part cut; cut the LLM prose first if over budget.
- `fundamentals=None` (not fetched / all-None) → KGV + analyst both render their honest-absence forms; tranches still render from the entry.

- [x] **Step 1:** failing tests — (a) plain layout: header, score band word, tranche lines with prices from `entry["tranches"]`, "in Schritten kaufen" note, disclaimer; (b) KGV rendered when present, line ABSENT when None; (c) analyst line with target + count + signed upside when present; (d) analyst honest-absence line when missing; (e) score-band thresholds (39→niedrig, 40→mittel, 70→hoch); (f) NEVER a fabricated target when fundamentals None (assert the "keine Schätzung" text, assert no stray number); (g) length cap preserves header + disclaimer; (h) LLM ChatError → deterministic fallback prose but sections still present.
- [x] **Step 2–4:** implement, run, gate.
- [x] **Step 5:** commit `feat: rewrite pitch in plain language with tranches, KGV, analyst consensus`.

---

### Task 4: Wire fundamentals into notify

**Files:** `src/equity_scout/notify.py`, `scripts/run_notify.py`, `tests/test_notify.py`.

`notify_watchlist` builds the pitch via `build=build_pitch`. Add an injectable `enrich: Callable[[str], Fundamentals] | None` (default `fundamentals.fetch_fundamentals`) so each candidate's fundamentals are fetched once and passed to the pitch builder. In tests inject a fake enrich (no network). `run_notify.main()` uses the real `fetch_fundamentals`; the fetch is the only new network and stays in `main()`/the seam, not in pure code.

- [x] **Step 1:** failing test — `notify_watchlist` with a fake `enrich` returning a known `Fundamentals` produces a pitch containing the analyst line; with `enrich` returning all-None → the honest-absence line; enrich is called once per candidate. Keep the existing selection/cooldown/resilience tests green.
- [x] **Step 2–4:** implement (thread `enrich` through; `build` becomes `lambda entry: build_pitch(entry, enrich(entry["ticker"]))` or an explicit two-arg build), run, gate.
- [x] **Step 5:** commit `feat: enrich notifications with fundamentals for the new pitch`.

---

### Task 5: Gate + live smoke + docs

- [ ] **Step 1:** full gate `.venv/bin/python -m pytest && .venv/bin/ruff check .`.
- [ ] **Step 2:** live smoke (network, uses `.env` if present — a real pitch only sends if a candidate is in-zone above threshold AND outside cooldown; a fresh `run_radar` may be needed for new candidates). At minimum: `.venv/bin/python -c` render a pitch for a real watchlist entry via `build_pitch(entry, fetch_fundamentals(entry["ticker"]))` and print it — confirm the new layout, real KGV, and either a real analyst line or the honest-absence line. Record the actual rendered pitch (note whether the analyst data was present for the sampled ticker).
- [ ] **Step 3:** README: one line noting the pitch now shows tranches, KGV, and third-party analyst consensus (labelled, not advice).
- [ ] **Step 4:** outcome section on this plan + one `AUTOPILOT_LOG.md` line; commit `docs: record pitch-v2 outcome`.

---

## Self-review notes
- Tranches: Task 1 (from `EntryPlan.dip_tranches`, reference levels, framed as scale-in not prediction).
- KGV + analyst consensus: Tasks 2–4; analyst target third-party-labelled with honest-absence fallback (invariant 1); KGV omitted when absent.
- Plain language: Task 3 (score bands, term explanations, tranche how-to sentence).
- Honesty: no fabricated targets, score = "kein Kursversprechen", LLM interpret-only — pinned by tests (f) + the review.
- Deliberate cuts: no historical analyst data (live `.info` only — coverage caveat stated in the honest-absence line); no per-ticker fundamentals persisted (fetched at notify time; the live prediction ledger and signal_readings remain the historical record).
