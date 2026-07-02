# ADR 0003 — Coupling the ML research loop to the stock factor-screener

**Status:** Proposed (2026-07-02) — decision deferred to Nico, not implemented.

## Context

equity-scout now contains two fairly different systems sharing one repo and one dashboard:

1. **Aktien-Screener** (`data/`, `factors.py`, `gate.py`, `buckets.py`, `analysis.py`): a
   cross-sectional, rule-based rank of ~1200 global stocks into risk buckets, purely deterministic —
   "no ML/AI model" is stated explicitly in the UI and `MethodologyNote`. An LLM only writes a
   post-hoc thesis for finalists; it never ranks or predicts.
2. **Strategien + ML research loop** (`strategies/`, `engine.py`, `ml/`): a handful of systematic
   ETF allocation strategies (10-ETF basket), a triple-barrier meta-model that learns *whether to
   follow* a trend-following primary signal (López de Prado, AFML ch. 3), evaluated via purged +
   embargoed walk-forward, with a continuous background search loop guarded by a rising
   Deflated-Sharpe hurdle and, as of ADR 0002, first-class PBO (CSCV).

The two were built at different times for different reasons (the screener is the v1 vertical slice;
the ML loop is the "NEXT MAJOR DIRECTION" from 2026-06-24) and currently do not share any modeling
code — only infrastructure (`market.py`/`PricePanel`, the dashboard shell, the API process). The
question raised for this phase-boundary self-challenge: should the ML loop's techniques or its
repo boundary be extended to cover the screener too?

## Options considered

### (a) Apply meta-labeling to the factor ranking, using qlib as a reference

**What this would mean technically.** The existing meta-model answers "should I follow *this one*
trend signal on *this one* asset, right now?" — a single time series, binary decision, triple-barrier
label. The screener's problem is different in kind: "does this cross-sectional rank of ~1200 stocks
by factor percentile predict which ones do better, going forward?" That is not a
signal-timing/sizing question, it's a **factor-validity** question. The standard tool for it in
quant equity research is the **Information Coefficient (Rank IC)** — the cross-sectional rank
correlation between the composite score at time *t* and forward return over some horizon — plus a
quantile/decile spread backtest (top-bucket vs. bottom-bucket forward return). This is exactly the
workflow **[Microsoft qlib](https://github.com/microsoft/qlib)** is built around (`Alpha158`/`Alpha360`
factor sets, `IC`/`RankIC` analysis, point-in-time data handlers, a model zoo for the *cross-sectional*
case). Triple-barrier meta-labeling, by contrast, is qlib's cousin-technique from a different corner
of the same literature (AFML) built for timing a directional bet, not for validating a ranking.
Concretely: **"meta-labeling the factor ranking" is a category mismatch** — the honest next step
toward the same rigor is Rank-IC tracking, not literally porting `ml/labeling.py`'s triple barrier
onto stock picks.

**Why not build it now — a real data gap, not just effort.** Both Rank-IC and proper meta-labeling
need **point-in-time fundamentals**: the P/E, ROE, growth, etc. as they were *known on the decision
date*, not today's snapshot. `yfinance` only ever gives the current snapshot (`data/yf_provider.py`
fetches `.info` live, no history) — reusing today's fundamentals to "backtest" past picks would be
look-ahead by construction, the same class of bug just fixed for `forward_paper.py` (see the
preceding commit). The universe is now historized (`data/universe_storage.py`, this session), which
solves survivorship bias in *membership*, but not point-in-time *fundamentals*. A partial, genuinely
free path exists for **US-listed names only**: SEC EDGAR's company-facts API returns historically
filed XBRL figures (already an allowed source per the iron principles), which combined with
yfinance's historical price series could reconstruct point-in-time value/quality/growth metrics for
US stocks — but not for the EU/JP majority of the universe (STOXX 600 + Nikkei 225 names don't file
with the SEC), so any IC/meta-labeling work today would be US-only and silently biased by that
subset — a caveat, not a blocker, but real enough that building the harness now would produce a
number that reads more authoritative than the data supports.

**Recommendation: not now.** The cheapest honest step that needs *no new data* is already close to
free given this session's run-history work: once enough calendar time has passed, `load_run_summaries`
already has dated picks + composite scores; adding realized-forward-return lookups (via yfinance,
same as today) and a Rank-IC calculation over that history is a small, self-contained follow-up
worth its own PLAN item later — after enough runs have accumulated to say anything statistically
meaningful (a handful of weekly runs is not enough; this needs months). Doing it before there is
enough history would be exactly the "backtest a coin flip and call it a strategy" trap this
project's own honesty framing warns against.

### (b) Split the ML research loop into its own repository

**Case for it.** The two systems now read as two different portfolio stories — "an honest,
rule-based factor screener with a completeness gate" vs. "a self-improving ML research loop with
overfitting guards" — and a reader (or a hiring manager skimming the repo) has to hold both framings
at once. Splitting could let each repo have a sharper README and a smaller test surface to reason
about (currently ~205 tests across both concerns in one `tests/` directory).

**Case against it, currently.** This is a **local, single-operator, free-only tool** — none of the
usual repo-split drivers apply: no separate deploy cadence, no separate team, no scaling boundary, no
dependency conflict forcing separation (both sides already share `pandas`/`numpy`; only
`scikit-learn`/`catboost` are ML-loop-only and cause no friction for the screener side). A split
would fragment currently-shared, load-bearing infrastructure: `market.py`/`PricePanel`, `engine.py`,
and `forward_paper.py` are used by *both* the plain strategies and the ML meta-model — a repo split
would force either a duplicated copy or a cross-repo dependency, for zero present benefit. The
dashboard is one React app with top-nav tabs across both; splitting the backend without splitting the
frontend just adds a second API process to run locally, for a tool whose whole point is
`uv run python scripts/run_api.py` simplicity.

**Recommendation: not now.** The module boundaries that would matter for a split already exist
(`strategies/`, `ml/`, `data/`, the screener's own top-level modules) — a repo split is a
one-way, non-trivial migration for a benefit (narrative clarity) that a good top-level README section
per concern can achieve today without it. Revisit if a *concrete* driver shows up: the ML loop
gaining a hard dependency the screener can't share, wanting independent CI/deploy, or the two halves
diverging enough that a reader genuinely can't tell what the repo is for from one README.

### (c) Status quo

Keep the two systems separate in technique (no meta-labeling ported to the screener) and together in
repo (no split), exactly as they are today.

## Decision

**(c), with one concrete, low-cost follow-up flagged for later:** track Rank-IC on the screener's
picks once enough dated run-history exists (a PLAN item to add when there's enough history to make
it meaningful — not now). No repo split; no meta-labeling port. Both (a) and (b) are rejected for
*today* on stated, concrete grounds above, not because they are wrong ideas in general — this ADR
should be revisited if the point-in-time-fundamentals gap closes (e.g. a free source is found beyond
SEC EDGAR's US-only coverage) or if a concrete repo-split driver appears.

**This ADR does not change any code.** Decision on whether/when to act on the Rank-IC follow-up, or
to revisit (a)/(b) later, is Nico's.
