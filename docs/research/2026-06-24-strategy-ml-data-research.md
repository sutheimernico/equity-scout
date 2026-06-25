# Research: strategies, ML, data sources, metrics (2026-06-24)

Self-directed web research to **challenge and extend** the existing vision spec
(`docs/superpowers/specs/2026-06-24-multi-strategy-ml-vision.md`). Four parallel research
threads. This is the evidence base for the v2 plan; sources are linked so decisions are auditable.

**Bottom line:** the spec's methodology (paper-only, no look-ahead, costs always, walk-forward,
honest "process not alpha" framing) is sound and stays. Four substantive changes came out of the
research — see each section.

---

## 1 · Strategies — the spec's biggest gap is the TAA family

The existing 9-family list is solid but misses the best-documented, most-reproducible,
most-impressive-for-a-demo strategies that run on **free monthly data over a handful of ETFs**:
the tactical asset-allocation (TAA) family.

**Add (Tier A, free daily/monthly data is enough, long-only, ~6-10 ETFs):**
- **Faber GTAA** — hold each asset only while price > 10-month SMA, else cash; aggressive variant
  ranks by 13612-momentum and holds top-N. The "grandfather" of TAA, generalises the spec's
  Trend/MA-crossover to multi-asset. ([Faber 2007](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=962461), [allocatesmartly.com strategy list](https://allocatesmartly.com/list-of-strategies/))
- **VAA — Vigilant Asset Allocation** (Keller/Keuning 2017) — 13612W momentum; if *no* offensive
  asset has negative momentum → 100% best offensive asset; if any does → defensive bond asset.
  Aggressive crash-switch. ([TrendXplorer/IndexSwingTrader](https://indexswingtrader.blogspot.com/2017/07/breadth-momentum-and-vigilant-asset.html))
- **DAA — Defensive Asset Allocation** (Keller/Keuning 2018) — like VAA but with a separate
  **"canary" universe (VWO + BND)** as early warning; cash fraction = (# bad canary assets / 2).
  Smoothest equity curve of the family — **the showpiece.** ([ResearchGate: Breadth Momentum and the Canary Universe](https://www.researchgate.net/publication/326859452_Breadth_Momentum_and_the_Canary_Universe_Defensive_Asset_Allocation_DAA))
- **PAA — Protective Asset Allocation** (Keller/Keuning 2016) — cash fraction scales with breadth
  (# assets above their 12-month SMA). ([TrendXplorer](https://indexswingtrader.blogspot.com/))
- **Accelerating Dual Momentum** (Engineered Portfolio 2018) — momentum = sum of 1+3+6-month
  returns; best of {US, intl/EM small-cap}, both negative → long Treasuries. Popular, 3 assets,
  simple; caveat: short lookbacks → higher turnover, overfit-prone. ([engineeredportfolio.com](https://engineeredportfolio.com/2018/05/02/accelerating-dual-momentum-investing/))

**Add as passive benchmarks (better than 60/40 alone):**
- **Permanent Portfolio** (Browne) — fixed 25/25/25/25 stocks/long-Treasuries/cash/gold, yearly.
- **All-Weather** (Dalio, simplified) — ~30/55/7.5/7.5 stocks/bonds/gold/commodities, yearly.
  ([optimizedportfolio.com](https://www.optimizedportfolio.com/all-weather-portfolio/))
  These are *comparison lines*, not active accounts — they show whether the active TAA models beat
  "diversify dumbly + rebalance yearly".

**Drop (not cleanly doable with free data — flag in framing, do not build):**
- **QMJ / Betting-Against-Beta** — need point-in-time fundamentals + shorting + large universe.
  ([Asness/Frazzini/Pedersen QMJ](http://www.econ.yale.edu/~shiller/behfin/2013_04-10/asness-frazzini-pedersen.pdf))
- **Carry** — for ETFs ≈ dividend/roll yield; meaningful in FX/futures, not long-only ETFs.
- **CAPE sector rotation** — sector-CAPE data not free/current.
- **Cross-sectional momentum** — survivorship bias bites hardest (yfinance has no delisted names) →
  optimistic upper bound only.
- **Mean-reversion RSI(2)/Bollinger** — short-term-reversal premium real but eaten by spreads.
- **Intraday (any form)** — see §2.

### Intraday verdict: Scheinpfad, do not build
- yfinance gives 1m bars ~7 days, any intraday interval ~60 days back — hard Yahoo limit, not
  fixable. ([yfinance #356](https://github.com/ranaroussi/yfinance/issues/356)) 60 days is an anecdote
  window with not a single full regime → walk-forward (our mandated standard) is impossible.
- Per-trade intraday returns are tiny and dominated by spread+slippage+latency, exactly the
  quantities free composite feeds get most wrong. ([QuantStart](https://www.quantstart.com/articles/Successful-Backtesting-of-Algorithmic-Trading-Strategies-Part-II/))
- **Honest alternative:** stay on daily/monthly; "trade more often" → shorter *daily* lookbacks
  (accelerating momentum, weekly rebalance), not shorter intervals.

### ETF universe (tickers consistent with the source strategies)
Minimal v1 set (covers DCA / Vol-Targeting / GEM / DAA / 60-40 / Permanent):
**SPY, VEU, VWO, IEF, TLT, BND, BIL, GLD, DBC, VNQ.**
(GEM uses SPY/VEU/AGG~IEF/BIL; DAA canary uses VWO/BND; Permanent uses SPY/TLT/BIL/GLD.)
Caveat: yfinance is reliable for these US-listed ETFs; international/EM only via these US wrappers,
not foreign-exchange tickers.

---

## 2 · ML meta-model — Tree models win, mlfinlab is a trap

**Meta-labeling (López de Prado) is the right architecture** — strategies provide *side*, the model
learns *whether/how much* to follow. Binary label is data-sparse and less overfit-prone than a
direction oracle. ([Meta-Labeling](https://en.wikipedia.org/wiki/Meta-Labeling))
**Condition:** meta-features must be *orthogonal* to the primary signal (regime/breadth/correlation),
otherwise the meta-model finds no new information — documented failure mode. ([QuantConnect: not a silver bullet](https://www.quantconnect.com/forum/discussion/14706/why-meta-labeling-is-not-a-silver-bullet/))
Known pitfalls: label quality hinges on the vol estimator + barrier multipliers; the vertical
(time) barrier censors and biases; recent work finds static triple-barrier labels give ~0 OOS Sharpe
while adaptive variants do better. ([MDPI 2025](https://doi.org/10.3390/app152413204))

**Model choice** (tabular data, little history → tree ensembles beat deep learning;
[Grinsztajn 2022](https://www.semanticscholar.org/paper/Why-do-tree-based-models-still-outperform-deep-on-Grinsztajn-Oyallon/ef4a99f703bd6c51f86056313716c39ea48baeb8)):
- **Elastic-Net logistic — mandatory baseline.** Data-sparse, interpretable, calibrated
  probabilities (good for sizing). Every fancier model must beat it OOS or it's cut.
- **CatBoost — workhorse.** Ordered boosting = built-in regularisation, good defaults; robust on
  small data. LightGBM overfits small data, XGBoost needs more tuning. ([comparison](https://mljourney.com/lightgbm-vs-xgboost-vs-catboost-a-comprehensive-comparison/))
- **Random Forest — robust #2** (what AFML uses here).
- **LSTM/GRU/TCN — overkill** at daily frequency (too data-hungry).
- **Transformer — hype, unsuited.** A trivial linear model (DLinear) beats Transformer forecasters;
  the edge came from multi-step decoding, not attention. ([Zeng et al. AAAI 2023](https://ojs.aaai.org/index.php/AAAI/article/view/26317))
- **RL / FinRL — most dangerous.** DRL agents on *daily* data perform ~market; edge only appears at
  minute data; reproducibility/overfitting problems. ([FinRL-Meta, Springer 2023](https://link.springer.com/article/10.1007/s10994-023-06511-w))

**Features** (keep orthogonal to primary signal): which strategies fire + conviction + agreement;
realised vol / vol term structure / VIX; trend strength + breadth (% above MA); average pairwise
correlation (risk-on/off); strategy recent hit-rate / rolling Sharpe; account drawdown state.
**Regime detection:** prefer **simple vol-buckets** over HMM — HMM's documented failure modes
(lookahead contamination via smoothed states, too many states, structural instability) are exactly
our risks. ([QuantStart HMM](https://www.quantstart.com/articles/market-regime-detection-using-hidden-markov-models-in-qstrader/))

**Validation (more important than model choice):** purged K-fold + embargo, Combinatorial Purged CV
(CPCV) once enough history, sample-weighting by label uniqueness, **Deflated Sharpe Ratio + PBO** as
a hard accept gate, count trials, **calendar-based** re-training (not performance-triggered).
- **Library license reality (critical):** `mlfinlab` (Hudson & Thames) is **NOT open-source** —
  closed, ~£100/mo, off PyPI. **Do not depend on it.** ([license](https://github.com/hudson-and-thames/mlfinlab/blob/master/docs/source/additional_information/license.rst))
  Free/clean: **`purgedcv`** (MIT — purged/group K-fold, walk-forward, CPCV + DSR + min track record;
  [repo](https://github.com/eslazarev/purged-cross-validation)), **`skfolio`** (BSD — `CombinatorialPurgedCV`;
  [docs](https://skfolio.org/generated/skfolio.model_selection.CombinatorialPurgedCV.html)),
  scikit-learn + CatBoost (BSD). Avoid `timeseriescv` (unmaintained, correctness issues).

**Honest expectation:** ceiling is low — free daily data + retail costs + few strategies = very low
signal/noise. Expect **drawdown/risk reduction and avoiding bad trades, not a return miracle.** The
line between discipline and self-deception is §validation: re-training + selection is an extra trial
that must go into the DSR/PBO bookkeeping, or the feedback loop leaks overfitting back in.

---

## 3 · Data sources — yfinance primary, add FRED + one OHLCV fallback

**yfinance 2024-26 reality:** the ~950-ticker/429 limit is real; IP-based rate limits tightened
~Nov 2024; the `curl_cffi` switch in 2025 caused `YFRateLimitError` waves.
([#2128](https://github.com/ranaroussi/yfinance/issues/2128)) For an 8-10 ETF universe the volume
limit is a non-issue; the risk is *instability* → a fallback is worth it.
Best practice: let yfinance manage its session, batch `yf.download([...])`, exponential backoff,
**`auto_adjust=True` + `repair=True` set explicitly, pin the version, daily only, snapshot to
Parquet** (Yahoo silently changes history; reproducible backtests need a frozen snapshot).

**Free OHLCV fallbacks (no credit card):**
- **Tiingo** — 1000 calls/day, 500 symbols/mo, **has adjusted close** → best API fallback. ([pricing](https://www.tiingo.com/about/pricing))
- **Stooq** — no key/signup, ~25-symbol chunks, **no adjusted close** → zero-friction last resort,
  price/momentum sanity-checks only, not total-return. ([via pandas-datareader](https://pandas-datareader.readthedocs.io/en/latest/readers/stooq.html))
- Drop: Alpha Vantage (cut to 25/day), Finnhub (candles now premium → 403), Nasdaq Data Link
  (WIKI-EOD discontinued).

**FRED (free key, no card, 120 req/min) — regime features.** Use revision-free daily series as live
features: **T10Y2Y, T10Y3M** (yield-curve slope), **VIXCLS** (VIX), **BAMLH0A0HYM2** (HY OAS, credit
stress), **NFCI** (financial conditions, weekly), **STLFSI4** (note: only v4 exists), **T10YIE**
(breakeven inflation), **DGS10**. ([FRED API](https://fred.stlouisfed.org/docs/api/api_key.html))
**Look-ahead trap:** `CPIAUCSL`, `UNRATE`, `USREC` (NBER) are revised / lag-published / backdated →
only with ALFRED vintages or a publication lag, never as a raw live feature.

**Total-return is critical for allocation backtests.** yfinance Adj Close adjusts splits AND
dividends. The danger: price-return-only systematically biases asset selection toward
non-distributors (SPY) against TLT/IEF/VNQ — for TLT nearly the *entire* return is coupons.
([totalrealreturns/TLT](https://totalrealreturns.com/n/TLT)) Rule: compute returns from Adj Close
(`auto_adjust=True`, `repair=True`, pinned version, daily, Parquet snapshot); compute share counts /
transaction costs from **raw Close**.

**Drop for an ETF project:** SEC EDGAR (ETFs have no balance sheet → useless here; revisit for
single-name selection only); crypto via ccxt (scope-creep, geoblocking, different
data-generating-process → distribution shift not signal). Optionally test 1-2 daily `BTC-USD`
features from yfinance as a risk-on/off proxy, no ccxt needed.

---

## 4 · Metrics & backtest engine — own engine + quantstats, DSR mandatory

**Core dashboard metrics (6-8):** CAGR, annualised vol, **Sharpe** (×√252, i.i.d. rule-of-thumb —
overstates under autocorrelation), **Sortino** (downside deviation; set above-target returns to 0,
don't drop them), **Max Drawdown**, **Calmar** (CAGR/|MaxDD|) or **Ulcer Index** (depth *and*
duration), **Turnover** (the cost lever), and — **non-negotiable here** — **Deflated Sharpe Ratio**.
Raw Sharpe ignores that we test many strategies + an ML model; with enough trials, noise produces a
high Sharpe. DSR compares observed vs. the *expected max Sharpe across N trials* and corrects
skew/kurtosis. ([Bailey & López de Prado, SSRN 2460551](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551))
**PBO** (probability of backtest overfitting, via CSCV) as a periodic validation report, not a live
tile — it needs the full trial-return matrix. ([SSRN 2326253](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253))

**Cost model:** flat bps per round-trip on traded notional (= turnover × value), default **10 bps**
(retail-ETF realistic), plus a fixed sensitivity sweep **{0, 5, 10, 20} bps** in the report — makes
the turnover lever visible. Spread/market-impact models are overengineering at this scale.
([BSIC](https://bsic.it/backtesting-series-episode-5-transaction-cost-modelling/))

**Realism / common errors:** look-ahead (`position[t]=signal[t-1]`, fill at t close / t+1 open);
survivorship (yfinance has no delisted — minor for broad ETFs, severe for single names);
overfitting via parameter tuning (track trial count, run DSR/PBO); walk-forward + embargo, never a
single hold-out. ([Bailey/López de Prado "Pseudo-Mathematics", AMS Notices](https://www.ams.org/notices/201405/rnoti-p458.pdf))

**Backtest libraries — verdict: keep own engine, add metrics lib only.** A full backtest lib brings
no value for rule-based daily allocation that justifies its license/maintenance cost.
- vectorbt — Apache-2.0 **+ Commons Clause** (can't sell), dev moved to paid PRO → risk; overkill.
- backtrader — inactive, Py 3.10+ issues → avoid. zipline-reloaded — heavy ingest/bundles → overkill.
- bt (MIT) — closest to allocation use-case, fallback if own engine wobbles.
- PyPortfolioOpt (MIT) / riskfolio-lib (BSD) — only if we *optimise* weights (not rule-based).
- **quantstats (Apache-2.0, active)** — Sharpe/Sortino/Calmar/MaxDD/CAGR + tear-sheets out of the box.
- **empyrical-reloaded (Apache-2.0, active)** — lean metric primitives, good low-level backend.
Implement DSR/PBO ourselves (few lines per López de Prado — no maintained standard lib).

---

## Decisions taken (spec §9, resolved autonomously)

1. **v1 strategy set:** DCA · Dual-Momentum/GEM · Vol-Targeting · **DAA**, with **60/40 + Permanent
   Portfolio** as passive benchmarks. (DAA replaces the spec's plain Trend/MA — more robust and more
   impressive; it subsumes a trend rule.)
2. **Universe:** fixed 10-ETF basket for allocation strategies; the existing stock factor-funnel
   stays a separate concern (shares the data + portfolio layers, not the funnel).
3. **Rebalancing:** monthly default (Vol-Targeting may check more often).
4. **ML timing:** backtest history is the initial training material; forward-paper is the live
   feedback loop. Backtest and forward share the same Strategy + engine.
5. **Library stack:** own engine + quantstats/empyrical-reloaded + scikit-learn/CatBoost +
   purgedcv/skfolio for validation. No vectorbt/backtrader. **mlfinlab strictly avoided** (proprietary).
