# Strang C — Ehrlichkeits-Analytik (Spec)

Stand 2026-06-25. Dritter Strang. Branch `feat/multi-strategy-ml`. Drei unabhängige Teile, je einzeln
committed.

## C1 — Per-Bet-Attribution ("warum lag es daneben")

**Problem:** Das Meta-Modell meldet nur Aggregate (`n_bets`, `oos_hit_rate`). Man sieht nicht, *welche*
Entscheidungen falsch waren und in *welchem Regime*.

**Lösung:** Die Per-Bet-Daten existieren lokal in `run_meta_model` (`oos` Prob pro Datum, `y_oos` Label,
`X` Features). `MetaResult` um `bets: list[BetRecord]` erweitern.
```
BetRecord(date, probability, decision: "follow"|"avoid", label: int, correct: bool, features: dict)
```
Neue `ml/attribution.py`: `attribution_summary(bets) -> dict` mit Trefferquote, Fehlerzahl, den
selbstsichersten Fehlentscheidungen (`worst`, nach |prob−0.5| absteigend), und einem **Regime-Kontrast**
(Ø Feature-Wert bei korrekten vs. falschen Bets — zeigt, in welchem Regime das Modell schwächelt).
Durchgereicht via `build_ml_report` → `/api/ml`. UI: „Selbstanalyse"-Sektion im ML-Meta-Tab
(Strang-A-Primitives): Fehlerliste + Regime-Kontrast-Balken.

## C2 — PBO (Probability of Backtest Overfitting)

**Problem:** Echtes CSCV-PBO (Bailey/López de Prado) braucht eine Performance-Matrix (Config × Zeit-
Block). Das Ledger speichert nur aggregierte Trial-Metriken — die Matrix fehlt, und die 1350 Trials
nachzurüsten würde sie entwerten.

**Entscheidung:** PBO als **on-demand-Berechnung** statt Ledger-Umbau. `ml/pbo.py`:
`block_sharpe_matrix(panel, configs, n_blocks)` rechnet die OOS-Equity je Config frisch (`run_meta_model`),
teilt sie in `n_blocks` Zeit-Blöcke → Sharpe-Matrix; `probability_of_backtest_overfitting(matrix)`
führt CSCV aus (alle C(n,n/2)-Splits, Rang der in-sample-besten Config out-of-sample, PBO = Anteil mit
OOS-Rang unter Median). CLI `scripts/run_pbo.py` nimmt die Top-N-Configs aus dem Ledger + Default,
persistiert das Ergebnis (`pbo`-Tabelle im Ledger-DB). `/api/research` liest es mit; UI: PBO-Kachel im
Auto-Research-Tab. Trade-off (langsam, daher CLI/persistiert statt live) wird dokumentiert.

## C3 — FRED-Regime-Features (VIX, Term-Spread, HY-Spread)

**Entscheidung:** Über die **öffentliche `fredgraph.csv`-URL ohne API-Key** ladbar (`VIXCLS`, `T10Y2Y`,
`BAMLH0A0HYM2`) — keine Key-Blockade, keine neue Dependency (httpx ist vorhanden). `ml/fred.py`:
`fred_features(dates) -> pd.DataFrame` lädt + cached (CSV-Snapshot wie das ETF-Panel) + aligned/ffill
auf die Panel-Daten; bei Netzwerk-/Datenfehler leerer DataFrame (sauberer Skip). `regime_features(panel,
asset, *, include_fred=False)` mergt die FRED-Spalten optional. `FRED_FEATURE_NAMES = ("vix",
"term_spread", "hy_spread")`. **Opt-in, nicht im Default-Search-Space** — sonst würden FRED-Verfügbarkeit
und die bestehenden Trials inkonsistent. Ein Flag/Feature-Liste kann sie ins Meta-Modell aufnehmen.

## Gate

`uv run pytest -q` + `uv run ruff check .` + FE `typecheck` + `build` grün. Neue Tests: Attribution-
Aggregation, CSCV-PBO auf konstruierter Matrix (bekanntes Ergebnis), FRED-Merge/Skip.

## Abgrenzung / YAGNI

Kein Ledger-Schema-Umbau für PBO (on-demand stattdessen). FRED-Features nicht automatisch in den
Loop-Search-Space (opt-in). Kein neuer ML-Lerner (CatBoost) — war optional im Backlog, nicht nötig.
