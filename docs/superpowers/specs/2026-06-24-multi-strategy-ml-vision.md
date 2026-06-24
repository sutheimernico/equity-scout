# Vision-Spec: Multi-Strategy Paper-Trading + selbstlernendes ML-Meta-Modell

**Stand:** 2026-06-24 · **Status:** VISION (nicht final beschlossen — der nächste Chat erarbeitet
Design + Plan selbst über `brainstorming` → `writing-plans`, diese Spec ist sein Startpunkt).
Baut auf dem bestehenden `equity-scout` auf (Funnel + Paper-Bot + Dashboard, alles auf `main`).

---

## 1 · Nicos Vision (wörtlich sinngemäß, 2026-06-24)

> „Ich hätte gerne richtig geile Software für Investition. Du investierst schon mit einem
> Demo-Account regelbasiert. Ich möchte, dass du dir **mehrere Strategien aus dem Internet ziehst**
> — tranchenweise einkaufen, gegen die Volatilität gehalten, solche Verfahren, dafür gibt es ja
> auch Paper. Durchforste dafür wirklich das ganze Internet. Jede Strategie soll **als eigener
> Demo-Account** laufen, oben in einem **Reiter umschaltbar**, sodass man sieht, wie gut die laufen.
> Zusätzlich soll es ein **Machine-Learning-Modell** geben, das du mit all diesen Verfahren anlernst
> und das dann gute Entscheidungen trifft, **wann gekauft wird und wann nicht**. Das soll sich
> **stetig verbessern, dauerhaft an einer Feedbackschleife** sein: wenn es nicht gut lief, warum —
> und das analysieren. Wie du es umsetzt, ist deine Sache. Arbeite in einem Loop autonom darauf hin,
> orchestriere und organisiere alles selbst."

**Permissions (von Nico erteilt):** Volle lokale Autonomie. Docker erlaubt, beliebige **kostenlose**
APIs/Keys aus dem Internet ziehen, alles selbst aufsetzen — **solange es lokal läuft und keine
Kosten verursacht**. Keine Permission-Rückfragen mehr. (In `.claude/settings.json` hinterlegt.)
Nicht übergehbar bleiben nur die Safety-Nets aus `~/private/AUTOPILOT.md`: kein Echtgeld, kein
`rm -rf`/`push --force`/`reset --hard`, `.env` nie lesen/committen, kein bezahlter Dienst.

## 2 · Wo wir stehen (die Basis)

`equity-scout` ist gebaut und läuft (Details: `README.md`, `PLAN.md`, `docs/`):
- **Funnel:** globales Universum (yfinance + Cache) → Daten-Gate → Faktor-Scoring (Value/Quality/
  Momentum/Growth/Low-Vol, sektor-relativ, rank-basiert) → 3 Risiko-Buckets.
- **Paper-Bot:** ein einfacher Buy-and-Hold-Account (Picks ≥ Score 70, gleichgewichtet, vs. SPY-
  Benchmark). `src/equity_scout/portfolio.py`, `portfolio_storage.py`, `scripts/run_paper.py`.
- **Dashboard:** React 19 + Vite, helles Theme, deutsch; Score-Transparenz-Drilldown, Depot-View.
- **Honest-Harness-Framing** + Disclaimer überall. ~50 Tests + ruff grün.

Das ist genau **ein** Account mit **einer** Strategie. Die Vision verallgemeinert das auf **N
Strategien als N Accounts** + eine **ML-Meta-Schicht** darüber.

## 3 · Die Strategie-Familien (recherchiert — Kandidaten für je einen Paper-Account)

Volle Recherche mit Formeln/Quellen/Caveats: Recherche-Block in der Chat-Historie dieses Specs;
hier die verdichtete Liste mit Machbarkeits-Tier (freie Tagesdaten).

**Tier A — sofort realistisch (Handvoll liquider ETFs, Tages-/Monatssignale, long-only):**
1. **DCA / tranchenweises Einkaufen** (+ Value Averaging, Edleson). Fester Betrag je Periode.
2. **Volatility Targeting** — Positionsgröße `σ_target/σ̂` mit Leverage-Cap. (Moreira/Muir 2017;
   Harvey et al. 2018.)
3. **Risk Parity / inverse-Vol** über mehrere Assets. (Maillard/Roncalli/Teiletche 2010; AQR 2012.)
4. **Time-Series-Momentum / Trend (MA-Crossover, Faber 10-Monats-SMA; TSMOM 12-1).** (Moskowitz/
   Ooi/Pedersen 2012; Faber 2007.)
5. **Dual Momentum / GEM** (Antonacci 2012) — absolutes + relatives Momentum, 3 Assets.
6. **60/40 + Equal-Weight 1/N** als Pflicht-**Benchmarks** (DeMiguel et al. 2009).

**Tier B — machbar mit Vorbehalt:** 7. **Min-Variance / Low-Vol** (Ledoit-Wolf-Shrinkage; gut für
~5–15 ETFs). 8. **Cross-sectional Momentum** (braucht großes Universum; Survivorship-Bias beißt
hier am härtesten → als optimistische Obergrenze flaggen).

**Tier C — lauffähig, Edge fraglich:** 9. **Mean-Reversion** (RSI(2)/Bollinger). Code trivial, aber
Short-Term-Reversal-Prämie real von Spreads aufgezehrt → als Lehr-/Risiko-Übung framen.

**Startempfehlung:** mit Tier A beginnen (inkl. der Benchmarks), B/C nur mit expliziten Caveats.

## 4 · Architektur-Skizze (Vorschlag — der nächste Chat verfeinert)

**Strategie-Interface (Seam).** Jede Strategie implementiert ein gemeinsames Protokoll, z.B.
`Strategy.decide(date, market_data, portfolio_state) -> list[TargetOrder]` (Paper-Orders:
Ziel-Gewicht/Tranche je Asset). So sind alle Strategien austauschbar + testbar mit Fake-Daten.

**N Paper-Accounts.** Pro Strategie ein eigenes, persistiertes Paper-Portfolio (Erweiterung des
bestehenden `portfolio.py`: aktuell Buy-and-Hold → generalisieren auf Rebalancing/Tranchen/Vol-
Scaling, mit Kosten + Slippage + Turnover-Tracking). Ein Scheduler-Lauf rückt **alle** Accounts vor.

**Dashboard-Reiter.** Oben pro Strategie ein Tab; je Account: Equity-Kurve vs. Benchmark, Kennzahlen
(CAGR/Sharpe/Sortino/MaxDD/Turnover **nach Kosten**), aktuelle Positionen, letzte Orders + Begründung.
Ein „Vergleich"-Tab listet alle Strategien nebeneinander.

**ML-Meta-Schicht (eigener Tab).** Siehe §5.

**Tech (Vorschlag):** Python/uv-Backend (bestehend), FastAPI + React (bestehend), evtl. Docker-
Compose für Scheduler + ggf. ML-Training. Backtest-/Allokations-Libs erwägen (vectorbt, bt,
PyPortfolioOpt, riskfolio-lib) — neue Deps nur mit Begründung, gepinnt.

## 5 · ML-Meta-Modell + Feedbackschleife

**Ziel (ehrlich):** Kein Renditeprognose-Orakel. Ein **Meta-Modell, das entscheidet, ob/wie stark
einem Strategie-Signal gefolgt wird** — und das aus seinen Fehlern lernt.

**Ansatz: Meta-Labeling (López de Prado).**
1. Primär-Signale = die N Strategien (liefern Seite: kaufen/halten/meiden).
2. Bets labeln (Triple-Barrier: Gewinn-/Stop-/Zeit-Barriere — was zuerst trifft).
3. Meta-Label binär: war es richtig, dem Signal zu folgen?
4. Meta-Modell M2 (Features: welche Strategien feuern + Konviktion + Kontext wie rollierende Vola/
   Regime + jüngste Trefferquote) → `P(folgen)` + Positionsgröße ∝ Wahrscheinlichkeit.

**Feedbackschleife (das „stetig verbessern"):** periodisches Re-Training auf neuen Forward-Daten;
pro geschlossenem/bewertetem Bet **Attribution loggen** (welche Signale, welcher Kontext, warum
falsch); diese Logs sind das Trainingsmaterial der nächsten Runde. **Selbstverbesserung = diszipli-
niertes Re-Training mit Leakage-Schutz**, kein Magie-Versprechen.

**Validierung ohne Leakage (Pflicht):** purged + embargoed Walk-Forward-CV (López de Prado, *AFML*
Kap. 7), Sample-Weighting nach Label-Uniqueness, nie zufällig shufflen. Performance immer **OOS** +
**nach Kosten** + gegen 60/40-Benchmark. **Deflated Sharpe Ratio** statt Roh-Sharpe (zählt die Zahl
der Trials). Quelle: López de Prado (2018), *Advances in Financial Machine Learning*.

## 6 · Methodik-Leitplanken (nicht verhandelbar)

- **Paper-only. Niemals Echtgeld/Order-Routing.**
- **Look-ahead vermeiden:** `position[t] = signal[t-1]`, Fill bei t+1; Daten nur bis `t` zum Fitten.
- **Kosten + Slippage immer** (Retail-Floor ~5–10 bps Round-Trip), Turnover mitberichten, Kosten-
  Sensitivität (0/5/10/20 bps).
- **Survivorship/Look-ahead bei yfinance dokumentieren** (kein Point-in-Time, delistete fehlen) →
  Cross-sectional-Ergebnisse als optimistische Obergrenze.
- **Walk-forward statt In-Sample; nur OOS berichten. Trials ehrlich zählen (DSR).**
- **Jede Strategie + das Meta-Modell gegen 60/40 + Buy-and-Hold nach Kosten benchmarken.**
- **Ehrliches Wertversprechen:** Prozess/Bildung/Risikomanagement, **nicht** Alpha. McLean & Pontiff
  (2016): publizierte Prämien zerfallen ~58% nach Veröffentlichung. Nach Retail-Kosten + Gratis-Daten
  ist der erwartete Netto-Edge niedrig bis null. Das wird überall klar geframt.

## 7 · Constraints / Setup

- **Lokal & kostenlos.** Daten: yfinance (Caching + Backoff Pflicht — 2024/25 verschärftes Rate-
  Limiting, 429 ab ~950 Tickern), SEC EDGAR, FRED (kostenlos, Key gratis), Stooq als Fallback.
  Keine bezahlten Feeds. Docker erlaubt, lokal.
- **AUTOPILOT-tauglich:** Gate = `pytest` grün + `ruff` clean. Branch `autopilot/work`, Nico merged
  `main`. Disk ist Memory (PLAN.md/Logs). Schon im Register (`~/private/AUTOPILOT.md`).

## 8 · Was der nächste Chat tun soll (Vorgehen)

1. **Lies:** diese Spec, `README.md`, `PLAN.md`, `AUTOPILOT_LOG.md`, `docs/factors.md`, den Code in
   `src/equity_scout/` (v.a. `portfolio.py`, `pipeline.py`, `api.py`, `frontend/src/`).
2. **`brainstorming`** → klär die offenen Entscheidungen (§10) und schneide v1 zu (welche 3–4 Tier-A-
   Strategien zuerst). **Nicht alle 9 auf einmal** — vertical slice: erst das Strategie-Interface +
   2–3 Strategien + Multi-Account-Persistenz + Reiter-UI, dann iterativ erweitern, ML zuletzt.
3. **`writing-plans`** → Plan in `PLAN.md`-Phasen (Strategie-Interface → erste Strategien → Multi-
   Account-Dashboard-Reiter → Kosten/Metriken-Harness → weitere Strategien → ML-Meta-Schicht →
   Feedbackschleife). Pro Strategie eigene Backtest-/Forward-Verifikation.
4. **Umsetzen im Loop**, TDD, kleine Commits, Gate grün, Phasen einzeln nach `main` mergen.
5. **Pro Strategie + fürs ML-Modell:** Methodik-Review (Look-ahead/Kosten/Walk-forward) — der
   `council`-Skill für model-diverse Zweitmeinung bei riskanten Methodik-Entscheidungen.

## 9 · Offene Entscheidungen (für Nico / den nächsten Chat)

- **v1-Strategie-Set:** welche 3–4 zuerst? (Vorschlag: DCA-Tranchen, Vol-Targeting, Trend/MA-
  Crossover, + 60/40-Benchmark.)
- **Universum je Strategie:** Multi-Asset-ETF-Korb (für Allokations-Strategien) vs. das bestehende
  Aktien-Universum (für Momentum/Low-Vol). Vermutlich beides, je Strategie.
- **Rebalancing-Kadenz:** täglich vs. monatlich (monatlich = weniger Turnover/Kosten, realistischer).
- **ML erst, wenn ≥3 Strategien Forward-Historie haben** (sonst kein Trainingsmaterial). Bis dahin
  sammeln die Paper-Accounts Daten.
- **Backtest-Lib** (vectorbt/bt) vs. eigene Engine wie im bestehenden Code.
