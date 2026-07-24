# Plan v14 — Strategie-Parameter-Suche (P7)

Spec: `docs/superpowers/specs/2026-07-24-vision-v14-strategy-param-search.md`.
Jeder Task: kleiner Diff, Test dazu, Gate (`uv run pytest -q` + `uv run ruff check .`)
grün, Conventional Commit. FE-Task zusätzlich typecheck + build.

## Tasks

- [ ] T1 `ml/strategy_search.py`: STRATEGY_SPACE + `all_configs()` (deterministische,
      stabile Reihenfolge; ~43 Configs), `StrategyConfig` (frozen dataclass, `key()`),
      `build_strategy(config)` Factory. Tests: Raumgröße, Determinismus, Factory baut
      korrekte Instanzen mit Parametern, keine Duplikate in Keys.
- [ ] T2 `evaluate_strategy_config(panel, config)` → `StrategyEvalResult` (PSR-Statistiken
      + Metriken + annual_turnover) auf `engine.run_backtest`. Tests mit synthetischem
      Panel (deterministisch, offline).
- [ ] T3 `ml/strategy_ledger.py`: `init_strategy_ledger` (idempotent; eigene Tabellen
      `strategy_trials`/`strategy_loop_state` in research_ledger.db), `record_strategy_trial`
      (Upsert per config_key, dsr_hurdle verbatim), `load_strategy_trials` (DSR on read,
      EIGENER Pool), `strategy_trial_count`, `current_strategy_hurdle`, `strategy_champion`,
      Cursor. Tests analog `test_research.py` inkl. Trennungs-Test: ML-`trials`-Rows in
      derselben DB verändern die Strategie-Hürde NICHT (und umgekehrt).
- [ ] T4 `ml/strategy_research_loop.py`: `run_one_strategy_trial` (Hürde vor Insert),
      `run_strategy_research` (Cursor modulo Raumgröße, resumable). Tests.
- [ ] T5 `scripts/run_strategy_research.py` (CLI-Muster `run_research.py`) +
      `nightly_train.sh` Step `strategy_research` nach `research_batch`. Wrapper-Test nur
      falls Muster existiert; sonst Loop-Funktion gilt als getestet.
- [ ] T6 `/api/research` Block `strategy_search` (+ `research_view.py`), FE Forschung-View
      Karte mit Ehrlichkeits-Label. Gate inkl. FE typecheck + build.
- [ ] T7 Live-Smoke (`--trials 5` echtes Panel, API-Check), README-Absatz, PLAN.md
      (P7 abhaken mit Verweis), AUTOPILOT_LOG, Outcome-Abschnitt hier.

## Outcome

(nach Abschluss füllen)
