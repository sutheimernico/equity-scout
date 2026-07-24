# Vision v14 — Strategie-Parameter-Suche im Research-Loop (P7 / v5-P4)

**Datum:** 2026-07-24 · **Backlog-Referenz:** PLAN.md P7 („EIGENES Ledger + EIGENE DSR-Hürde,
Multiple-Testing-Trennung; v5-P4"), Original in
`docs/superpowers/plans/2026-07-12-signal-stack-v5.md` (L3/P4).

## Ziel

Der Research-Loop bekommt eine zweite Suchdimension: die Parameter der Rule-Strategien
(Vol-Target, GEM, DAA, Sektor-Rotation, 60/40). Jeder Trial ist ein After-Cost-Backtest
über das ETF-Panel, buchgeführt in einem EIGENEN Ledger mit EIGENER DSR-Hürde — die
Overfitting-Budgets der ML-Suche und der Strategie-Suche teilen sich nie eine Zählung.

## Harte Ehrlichkeitsgrenzen

1. **In-Sample, ehrlich gelabelt.** Ein Trial ist ein Whole-History-Backtest
   (`engine.run_backtest`, ME-Rebalance, 10 bps) — kein OOS-Beweis. Die DSR-Deflation
   (`expected_max_sharpe` über den EIGENEN Trial-Pool) ist das Overfitting-Budget, genau
   wie in `run_backtest.py` heute schon cross-strategy. Jede Surface trägt das Label.
2. **Keine automatische Übernahme.** Der „Champion" ist Anzeige/Evidenz. Produktive
   Sleeves behalten ihre Defaults — geänderte Parameter wären eine NEUE Strategie-Identität
   und würden Forward-Track-Records verfälschen (gleiches Argument wie registry.py zur
   Ensemble-Zusammensetzung). Übernahme = Nico-Entscheidung, ggf. als neue Sleeve-Identität
   mit frischem Forward-Track (v15-Kandidat).
3. **Multiple-Testing-Trennung.** `strategy_trials` hat einen eigenen Hurdle-Pool;
   `trials` (ML) bleibt unberührt. Kein Leverage > 1 im Suchraum (Backtest hat kein
   Borrow-Modell).

## Suchraum (endlich, deterministisch enumeriert, ~43 Configs)

| Strategie | Parameter-Grid |
|---|---|
| Volatility Targeting | target_vol {0.08, 0.10, 0.12, 0.15} × vol_window_days {21, 42, 63, 126} |
| Dual Momentum (GEM) | lookback_months {3, 6, 9, 12} |
| DAA | top_n {2, 3, 4} |
| Sektor-Rotation | top_n {2, 3, 4, 5} × lookback_months {(12,6), (6,3), (12,), (9,3)} |
| 60/40 | stock_weight {0.5, 0.6, 0.7, 0.8} |

Bewusst NICHT im Raum: Permanent Portfolio (Philosophie ist die fixe 4×25%-Allokation),
DCA (tranches wirkt nur in der Anlaufphase — im Whole-History-Backtest bedeutungslos),
Leverage-Caps > 1.0. Der Cursor läuft modulo Raumgröße: Ist der Raum ausgeschöpft,
re-evaluieren weitere Trials dieselben Configs per Upsert gegen die inzwischen längere
Historie — Trial-Zählung (= unique Configs) und damit die Hürde bleiben stabil, die
Metriken bleiben frisch.

## Bausteine

- `ml/strategy_search.py`: `STRATEGY_SPACE`, `all_configs()` (stabile Reihenfolge),
  `build_strategy(config)`, `evaluate_strategy_config(panel, config)` →
  `StrategyEvalResult` (sharpe_periodic/n_obs/skew/kurtosis für PSR + cagr, sharpe,
  sortino, max_drawdown, annual_turnover).
- `ml/strategy_ledger.py`: eigene Tabellen `strategy_trials` + `strategy_loop_state` in
  `research_ledger.db` (Konvention: eigene Buchführung, gleiche Datei); DSR on read
  gegen den eigenen Pool; `dsr_hurdle` von Geburt an im Schema (Q2-Muster);
  record/load/count/hurdle/champion/cursor analog `ledger.py`.
- `ml/strategy_research_loop.py`: `run_one_strategy_trial` (Hürde VOR Insert festhalten)
  + `run_strategy_research` (resumable Cursor).
- `scripts/run_strategy_research.py`: CLI nach `run_research.py`-Muster;
  `nightly_train.sh` Step `strategy_research --trials 25` nach `research_batch`.
- `/api/research`: neuer Block `strategy_search` (count, hurdle, Top-5 nach DSR,
  Beste-pro-Strategie, Ehrlichkeits-Label); Forschung-View im Dashboard zeigt die Karte.
- Doku: README-Absatz, PLAN.md-Haken, Plan-Doc-Outcome.

## Gate

`uv run pytest -q` + `uv run ruff check .` grün pro Welle; FE zusätzlich
typecheck + build bei der Dashboard-Welle. Live-Smoke: `run_strategy_research --trials 5`
gegen das echte Panel, dann `/api/research` prüfen.
