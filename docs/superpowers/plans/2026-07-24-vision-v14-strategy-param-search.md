# Plan v14 — Strategie-Parameter-Suche (P7)

Spec: `docs/superpowers/specs/2026-07-24-vision-v14-strategy-param-search.md`.
Jeder Task: kleiner Diff, Test dazu, Gate (`uv run pytest -q` + `uv run ruff check .`)
grün, Conventional Commit. FE-Task zusätzlich typecheck + build.

## Tasks

- [x] T1 `ml/strategy_search.py`: STRATEGY_SPACE + `all_configs()` (deterministische,
      stabile Reihenfolge; ~43 Configs), `StrategyConfig` (frozen dataclass, `key()`),
      `build_strategy(config)` Factory. Tests: Raumgröße, Determinismus, Factory baut
      korrekte Instanzen mit Parametern, keine Duplikate in Keys.
- [x] T2 `evaluate_strategy_config(panel, config)` → `StrategyEvalResult` (PSR-Statistiken
      + Metriken + annual_turnover) auf `engine.run_backtest`. Tests mit synthetischem
      Panel (deterministisch, offline).
- [x] T3 `ml/strategy_ledger.py`: `init_strategy_ledger` (idempotent; eigene Tabellen
      `strategy_trials`/`strategy_loop_state` in research_ledger.db), `record_strategy_trial`
      (Upsert per config_key, dsr_hurdle verbatim), `load_strategy_trials` (DSR on read,
      EIGENER Pool), `strategy_trial_count`, `current_strategy_hurdle`, `strategy_champion`,
      Cursor. Tests analog `test_research.py` inkl. Trennungs-Test: ML-`trials`-Rows in
      derselben DB verändern die Strategie-Hürde NICHT (und umgekehrt).
- [x] T4 `ml/strategy_research_loop.py`: `run_one_strategy_trial` (Hürde vor Insert),
      `run_strategy_research` (Cursor modulo Raumgröße, resumable). Tests.
- [x] T5 `scripts/run_strategy_research.py` (CLI-Muster `run_research.py`) +
      `nightly_train.sh` Step `strategy_research` nach `research_batch`. Wrapper-Test nur
      falls Muster existiert; sonst Loop-Funktion gilt als getestet.
- [x] T6 `/api/research` Block `strategy_search` (+ `research_view.py`), FE Forschung-View
      Karte mit Ehrlichkeits-Label. Gate inkl. FE typecheck + build.
- [x] T7 Live-Smoke (`--trials 5` echtes Panel, API-Check), README-Absatz, PLAN.md
      (P7 abhaken mit Verweis), AUTOPILOT_LOG, Outcome-Abschnitt hier.

## Outcome (2026-07-24)

Alle 7 Tasks umgesetzt, Gate pro Welle grün (voll: 1173+ Tests + ruff + FE
typecheck/build). Commits: T1+T2 (Suchraum+Evaluation), T3+T4 (Ledger+Loop), T5
(CLI+Nightly), T6 (API+FE), T7 (Doku+Smoke).

**Abweichungen vom Plan:**
- T6 deckte einen realen Randfall auf: legt `run_strategy_research` die Ledger-DB als
  Erstes an (ML-Loop lief nie), fehlt die `trials`-Tabelle und `/api/research` hätte
  einen 500 geworfen → ML-Ledger-Leser (`load_trials`/`trial_count`/`current_hurdle`)
  tolerieren jetzt symmetrisch fehlende Tabellen (Muster aus `strategy_ledger`).
- `research_summary` liefert den `strategy_search`-Block auf ALLEN Pfaden (auch DB-fehlt/
  ML-leer), damit die Dashboard-Karte unabhängig vom ML-Loop-Zustand erscheint.

**Offene Enden (bewusst):**
- Erste volle Grid-Abdeckung (43/43) erreicht der Nightly-Step nach 2 Nächten; danach
  Re-Evaluation per Wrap (gewollt).
- v15-Kandidat: Übernahme eines Strategie-Champions als NEUE Sleeve-Identität mit
  frischem Forward-Track (Promotions-Mechanik analog Arena-Gate).

**Live-Smoke:** 5 Trials gegen das echte Panel (2034 Tage; Hürde 0.000→0.005, Champion
Volatility Targeting target_vol 0.10 / window 21, DSR 0.97 — In-Sample, erwartungsgemäß
hoch bei noch niedriger Hürde), Dash-Service neu gestartet, `/api/research` liefert den
Block live; ML-Block unverändert.
