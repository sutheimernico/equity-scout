# HANDOFF — Multi-Strategy + ML (Stand 2026-06-25)

Stand nach der großen Ausbau-Session. Alles auf Branch **`feat/multi-strategy-ml`** (NICHT nach
`main` gemerged — Nico reviewt + merged). Gate grün: `uv run pytest -q` + `uv run ruff check .` +
`npm run typecheck --prefix frontend` + `npm run build --prefix frontend`.

> **Hinweis:** Die Multi-Strategy-Arbeit unten ist inzwischen auf `main` gemerged (samt Post-Merge-
> Iterationen: Chat-Default `qwen2.5:7b` statt `llama3.2`, hover-Pies, TradingView-1-Jahr-Charts,
> Design-Politur). Aktueller Stand + voller Verlauf: Auto-Memory (`equity-scout-multistrategy-ml.md`).

## Entry-Levels + Tranchen pro Aktie (2026-06-25, Branch `feat/entry-levels` — NICHT gemerged)
To-Do 1 aus der letzten Session umgesetzt: pro Screener-Pick regelbasierte **Referenz-Levels**
(200-Tage-SMA, Fibonacci 38.2/50/61.8 %, jüngstes Swing-Tief, −1/−2 ATR, 52W-Tief + Drawdown) plus
zwei **Tranchen-Pläne** (DCA-Baseline 4× gleich; Drawdown-Scale-in jetzt/−7 %/−15 % als Option ohne
Edge). Backend `GET /api/entry/{ticker}` (`src/equity_scout/entry.py` — pure Mathe getrennt vom
yfinance-Fetch; Ticker-Regex; Cache mit Tages-Key) → JSON `EntryPlan`. Frontend: `EntryPlanBlock`
im `PickCard`-Drilldown (lazy beim Aufklappen, Levels als Marker auf der 52W-Range-Bar, Tranchen-
Tabelle). **Framing neutral**: „Referenzzone erreicht", kein Kaufsignal, Disclaimer. Gate grün
(169 pytest). Live-Smoke gegen echtes yfinance ok. Plan + Outcome:
`docs/superpowers/plans/2026-06-25-entry-levels-tranchen.md`. **Wartet auf Nicos Review/Merge** +
visuelle UI-Abnahme. Nächstes To-Do: „Pitching" (Bedeutung unklar — erst klären).

## Ausbaurunde 2026-06-25 — 4 Stränge, ALLE DONE
Nach dem unten beschriebenen Multi-Strategy-Stand: 4-Strang-Runde, komplett umgesetzt auf
`feat/multi-strategy-ml` (NICHT gemerged — Nico reviewt/merged). Gate je Strang grün.
- **A UX/Design-Fundament**: wiederverwendbare UI-Primitives (`frontend/src/components/ui/`), Zahlen mit
  Bezugsrahmen-Ankern, progressive Offenlegung (Disclosure), Section-Header pro Tab, tote CSS weg; Lilac bleibt.
- **B Forward-Paper**: Strategien laufen fortlaufend vorwärts — `forward_paper.py`+`forward_storage.py`
  (`forward_paper.db`), CLI `scripts/run_forward_paper.py` (täglich/Cron), `/api/forward`, „Live (Forward)"-Tab.
- **C Ehrlichkeits-Analytik**: C1 Per-Bet-Attribution/Selbstanalyse (ML-Tab), C2 CSCV-PBO via
  `scripts/run_pbo.py` → Auto-Research-Tab (erstes Ergebnis PBO≈0.69 = eher Glück), C3 FRED-Makro-Features
  (`ml/fred.py`, public CSV, kein Key) im Loop-Suchraum wenn Snapshot da.
- **D Lokaler Chatbot**: `chat.py` + `/api/chat` + „Assistent"-Tab, Ollama-basiert (kein RAG, kompakter
  Daten-Snapshot in den Prompt). Setup: `ollama serve` + `ollama pull llama3.2` (oder `OLLAMA_MODEL`).
Specs+Outcomes je Strang: `docs/superpowers/specs/2026-06-25-strang-{a,b,c,d}-*.md`.
Offen/visuell: Browser-Abnahme der UI durch Nico (kein lokales Screenshot-Tooling in der Build-Umgebung);
Forward-Track braucht reale Tage, um eine Kurve zu zeigen. Strang A: wiederverwendbare UI-Primitives
(`frontend/src/components/ui/`), Zahlen mit Bezugsrahmen-Ankern, progressive Offenlegung (Disclosure),
Section-Header pro Tab, tote CSS entfernt; Lilac bleibt. Strang B: Strategien laufen fortlaufend
vorwärts — `forward_paper.py` (`ForwardAccount`+`advance_account`, idempotent) + `forward_storage.py`
(`forward_paper.db`), CLI `scripts/run_forward_paper.py` (täglich/Cron laufen lassen), `GET /api/forward`,
„Live (Forward)"-Tab im Strategien-Dashboard. Screener-Demodepot bleibt (anderes Konzept).
Specs: `docs/superpowers/specs/2026-06-25-strang-{a,b}-*.md`.

## Was jetzt steht (gebaut + live-verifiziert)
1. **Recherche** (`docs/research/2026-06-24-strategy-ml-data-research.md`): 4 Stränge, Quellen,
   challenged die alte Spec. Kernfunde: TAA-Familie war die Lücke (DAA etc.), Intraday = Scheinpfad,
   `mlfinlab` proprietär (vermieden), Backtest-Historie = ML-Trainingsmaterial.
2. **Backtest-Engine** (`engine.py`): gewichtsbasiert, look-ahead-safe (decide sieht nur `< t`),
   Turnover-Kosten. `MarketView` (`market.py`) ist der Look-ahead-Guard.
3. **6 Strategien** (`strategies/`): DCA, 60/40, Permanent Portfolio, Vol-Targeting, GEM, DAA.
   Seam: `decide(as_of, market) -> list[TargetWeight]`, alle state-free. ETF-Korb: `etf_universe.py`.
4. **Ehrliche Metriken** (`metrics.py`): CAGR/Vol/Sharpe/Sortino/MaxDD/Calmar/Turnover +
   **Deflated Sharpe / PSR** (eigene Impl, kein Lib-Dep).
5. **Dashboard** (`frontend/`): Top-Nav (Strategien | Aktien-Screener), pro Strategie ein Reiter mit
   SVG-Equity-Kurve vs 60/40, Metrik-Kacheln, Allokation, Kosten-Sweep; Vergleichs-Tab; **ML-Meta-Tab**.
   API: `/api/strategies`, `/api/ml` (`strategy_service.py`, `api.py`).
6. **ML-Meta-Modell** (`ml/`): Triple-Barrier-Meta-Labeling, Regime-Features (orthogonal),
   Elastic-Net-Logistic, **purged + embargoed Walk-Forward**. Live 2007-26: 69% OOS-Trefferquote,
   MaxDD halbiert vs SPY (-23% vs -55%). Dashboard-Tab "ML-Meta".
7. **Continuous Research Loop** (`ml/search.py` + `ledger.py` + `research_loop.py`): sucht laufend
   Modell-Konfigs (config-getriebenes `MetaConfig`: features × {elastic_net, random_forest} ×
   lookback × horizon × barrier), bewertet OOS, schreibt ins SQLite-Ledger (idempotent pro Config).
   **DSR-Hürde steigt mit der Trial-Zahl → eingebauter Overfitting-Schutz.** Champion = höchste DSR.
   `scripts/run_research.py` (endlos, resumable), `/api/research` + Dashboard-Tab "Auto-Research"
   (live, 5s-Poll). Die Suche fand bereits eine bessere Config als das Default-Modell.
8. **Multi-Strategie-Mix** (`strategies/ensemble.py`): gleichgewichteter Blend aus Permanent +
   Vol-Targeting + GEM + DAA (1/N, kein in-sample-Tuning). Live: Sharpe 0.87 (schlägt jede aktive
   Einzelstrategie), MaxDD -19.1% — Diversifikation über Strategie-Typen.
9. **Kaufempfehlung** (`frontend/.../AllocationAdvisor.tsx`): pro Strategie ein „was jetzt kaufen“-
   Block — Betrag eingeben → konkrete €-Aufteilung je ETF (lesbare Namen) + Cash-Rest + Tranchen-
   Hinweis. Regelbasierte Vorgabe, keine Anlageberatung. Strategie-Pitches stehen über jedem Tab.
   Dashboard-Nav jetzt: **Strategien | Machine Learning | Aktien-Screener** (ML eigene Kategorie).

**Frontend nach Backend-Strategie-Änderungen neu bauen + API neu starten** (build_reports cached die
Strategieliste): `npm run build --prefix frontend` + API-Server killen (über Port: `fuser -k 8000/tcp`,
NICHT `pkill -f run_api` — matcht den eigenen Befehl) + neu starten.

## Lokal starten
```bash
uv run python scripts/run_backtest.py --refresh   # holt ETF-Panel (yfinance) → data/prices/, druckt Metriken+Sweep
cd frontend && npm install && npm run build && cd ..
uv run python scripts/run_api.py --port 8000      # http://127.0.0.1:8000  (erster /api/ml-Request trainiert ~Sek.)

# Continuous research loop im Hintergrund (läuft solange der Laptop an ist, resumable):
nohup uv run python scripts/run_research.py > research.log 2>&1 &   # Auto-Research-Tab aktualisiert live

# Forward-Paper fortschreiben (täglich/Cron; idempotent pro Tag) → „Live (Forward)"-Tab:
uv run python scripts/run_forward_paper.py --refresh

# PBO über die Top-Configs berechnen (langsam, gelegentlich) → Auto-Research-Tab:
uv run python scripts/run_pbo.py

# Lokaler Chatbot („Assistent"-Tab): Ollama lokal starten + Modell ziehen
ollama serve & ollama pull llama3.2   # Modell wählbar über OLLAMA_MODEL
```

## Was als Nächstes (noch offen)
Plan + Phasen-Backlog: `docs/superpowers/plans/2026-06-24-multi-strategy-v2.md`.
- **Attribution / Selbstanalyse** („wenn es nicht gut lief, warum"): pro OOS-Bet
  Entscheidung+Ergebnis+Regime-Kontext loggen; die lehrreichsten Fehlentscheidungen zeigen.
- **Forward-Paper-Persistenz**: Multi-Account-DB-Schema, damit die Accounts real über die Zeit
  vorwärtslaufen (nicht nur Backtest).
- **PBO** (Probability of Backtest Overfitting) über das Ledger als zweite Overfitting-Diagnostik.
- **FRED-Regime-Features** (VIX, Term-Spread, HY-Spread) als ML-Feature-Anreicherung (Key gratis,
  Registrierung → ggf. „Needs Nico"). Optional CatBoost als dritter Lerner.

## Nicht verhandelbar (bleibt)
Paper-only, kein Look-ahead, Kosten immer, Walk-forward/OOS, gegen 60/40 + Buy-and-Hold nach Kosten.
Ehrliches Framing: Prozess/Bildung/Risiko, kein Alpha-Versprechen. Disclaimer auf jeder Surface.
