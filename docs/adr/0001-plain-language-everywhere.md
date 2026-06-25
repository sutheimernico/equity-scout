# ADR 0001 — Plain-language explanations everywhere

**Status:** Accepted (2026-06-25)

## Context

The dashboard is full of finance/ML jargon: factor names, "Sharpe", "Sortino", "Calmar",
"Deflated Sharpe", "Max Drawdown", "Turnover", strategy names ("Vol-Targeting", "GEM / Dual
Momentum", "DAA", "Permanent Portfolio"), ML terms ("Triple-Barrier", "Walk-Forward", "PBO",
"DSR-Hürde"), screener terms ("Composite-Score", "Perzentil", "Buckets"), and the entry-level
terms ("Fibonacci", "ATR", "Swing-Tief").

The primary (and only) user is **not a finance expert**. Numbers and terms shown without
explanation are useless to him — a value like "Fib 38.2 %" or "ATR" carries no meaning. A
dashboard that requires prior knowledge to read fails its purpose.

## Decision

**Every surface must be understandable without prior finance/ML knowledge.** Concretely:

- Keep the technical term **visible** (the user picks it up over time), but **always** pair it
  with a plain-language explanation *right there* — never leave a bare number/term.
- Default mechanism: a **collapsed disclosure** (e.g. "Was bedeuten diese Niveaus?", default
  closed so the surface stays tidy) or a short inline note. The explanation is one click away,
  not a wall of text.
- Explanations are in **plain German**, one sentence per term, no jargon-to-explain-jargon. State
  honest caveats ("Faustregel, kein Naturgesetz"); never imply a buy/sell signal or price forecast
  (consistent with the project's honesty framing).
- Spell out cryptic abbreviations in labels ("Fib" → "Fibonacci").

This applies to **the whole dashboard**, not just where a problem was first noticed.

## Status of rollout

- **Done:** entry-levels block (`frontend/src/components/EntryPlanBlock.tsx`) — Fibonacci spelled
  out + a "Was bedeuten diese Niveaus?" glossary covering every level type and the "zum Kurs"
  column. This is the reference pattern.
- **To do (pending Nico's approval of the pattern):** strategy-tab metrics (Sharpe/Sortino/Calmar/
  Deflated Sharpe/Max Drawdown/Turnover), strategy names, ML tab (Triple-Barrier/Walk-Forward/PBO/
  DSR), screener (Composite/Perzentil/Buckets). Some of these already have `METRIC_HELP` /
  `STRATEGY_PITCH` text in `frontend/src/format.ts` — reuse and surface it consistently.

## Consequences

- Every new metric, term, or visualization added to the dashboard must ship with a plain-language
  explanation — this is a definition-of-done item, not an afterthought.
- Slight extra surface area (the disclosures), mitigated by keeping them collapsed by default.
- A consistent explanation mechanism (the disclosure / inline-note pattern) should be reused rather
  than reinvented per tab.
