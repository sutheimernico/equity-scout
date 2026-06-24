# HANDOFF — Multi-Strategy + ML (Stand 2026-06-25)

Stand nach der großen Ausbau-Session. Alles auf Branch **`feat/multi-strategy-ml`** (NICHT nach
`main` gemerged — Nico reviewt + merged). Gate grün: `uv run pytest -q` + `uv run ruff check .` +
`npm run typecheck --prefix frontend` + `npm run build --prefix frontend`.

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

## Lokal starten
```bash
uv run python scripts/run_backtest.py --refresh   # holt ETF-Panel (yfinance) → data/prices/, druckt Metriken+Sweep
cd frontend && npm install && npm run build && cd ..
uv run python scripts/run_api.py --port 8000      # http://127.0.0.1:8000  (erster /api/ml-Request trainiert ~Sek.)

# Continuous research loop im Hintergrund (läuft solange der Laptop an ist, resumable):
nohup uv run python scripts/run_research.py > research.log 2>&1 &   # Auto-Research-Tab aktualisiert live
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
