# HANDOFF — Multi-Strategy + ML (für den nächsten Chat)

Du übernimmst `equity-scout` und baust es zu Nicos großer Vision aus: **mehrere systematische
Paper-Trading-Strategien als je eigener Demo-Account (im Dashboard per Reiter umschaltbar) + ein
selbstlernendes ML-Meta-Modell mit Feedbackschleife.**

## Lies das zuerst (in dieser Reihenfolge)
1. **`docs/superpowers/specs/2026-06-24-multi-strategy-ml-vision.md`** — die Vision-Spec. Enthält
   Nicos Vision wörtlich, die 9 recherchierten Strategie-Familien (mit Quellen + Machbarkeits-Tiers),
   die Architektur-Skizze, die ML-Meta-Labeling-Methodik, die Methodik-Leitplanken und die offenen
   Entscheidungen. **Das ist dein Startpunkt.**
2. `README.md`, `PLAN.md`, `AUTOPILOT_LOG.md`, `docs/factors.md`.
3. Der Code: `src/equity_scout/` (v.a. `portfolio.py`, `portfolio_storage.py`, `pipeline.py`,
   `factors.py`, `buckets.py`, `api.py`) und `frontend/src/`.

## Was schon steht (die Basis)
Funnel (globales Universum → Faktor-Score → 3 Buckets), **ein** Buy-and-Hold-Paper-Account vs. SPY,
React-Dashboard (hell, deutsch, Score-Transparenz + Depot-View). ~50 Tests + ruff grün, alles auf
`main`. Du verallgemeinerst „ein Account / eine Strategie" auf „N Accounts / N Strategien + ML".

## Arbeitsweise (von Nico autorisiert)
- **Volle lokale Autonomie**, keine Permission-Rückfragen. Lokal + kostenlos, Docker erlaubt, freie
  APIs/Keys ok (FRED/EDGAR/yfinance). Safety-Nets (kein Echtgeld, kein `rm -rf`/`push --force`,
  `.env` nie lesen) bleiben. Permissions liegen in `.claude/settings.json`.
- **Im Loop autonom orchestrieren:** `brainstorming` (offene Entscheidungen klären, v1 zuschneiden)
  → `writing-plans` → Umsetzung in Phasen, TDD, kleine Commits, Gate (`pytest`+`ruff`) grün, Phasen
  einzeln nach `main` mergen. **Vertical slice zuerst** — nicht alle 9 Strategien auf einmal.
- **Reihenfolge-Empfehlung:** Strategie-Interface (Seam) → 2–3 Tier-A-Strategien (z.B. DCA-Tranchen,
  Vol-Targeting, Trend/MA-Crossover) + 60/40-Benchmark → Multi-Account-Persistenz → Dashboard-Reiter
  + Kosten/Metriken-Harness (Sharpe/Sortino/MaxDD/Turnover nach Kosten) → weitere Strategien → erst
  dann ML-Meta-Schicht (braucht Forward-Historie) → Feedbackschleife.

## Nicht verhandelbar
Paper-only, kein Look-ahead (`position[t]=signal[t-1]`), Kosten+Slippage immer, Walk-forward statt
In-Sample, jede Strategie + das ML gegen 60/40 nach Kosten benchmarken. **Ehrliches Framing:**
Prozess/Bildung/Risiko — kein Alpha-Versprechen (publizierte Prämien zerfallen, Retail+Gratis-Daten
→ Netto-Edge ~null). Das ist ein Forschungs-Harness.

## Erste Aktion
Starte mit `brainstorming` und kläre §9 der Vision-Spec (v1-Strategie-Set, Universum je Strategie,
Rebalancing-Kadenz). Dann `writing-plans`. Dann bauen.
