# Plan: v16 „Alpha-Fabrik" — mehr Strategiefamilien (2026-08-10)

## Auftrag

Nico: „Ich will reich werden und du sollst alles dafür tun … Bring die Applikation auf eine
10/10 womit keine andere Applikation mithalten kann." Dann: „Mach das in einer Loop zuende,
ich bin jetzt weg."

## Bewertung, die den Auftrag geschärft hat

| Achse | Note | Belege (heute gemessen) |
|---|---|---|
| Maschine/Engineering | **8/10** | 140 Module, 24k Zeilen, 1883 Tests, 31 Endpoints, 12 Strategien, 16 Evidenzquellen, echter Paper-Broker, gemessene Slippage, Watchdog, Handy-Cockpit |
| Geldverdienen | **2/10** | Depot +0,9 % vs SPY +3,3 % · Session −2,4 % vs +4,0 % · Swing +0,2 % vs +4,2 % · Crypto −6,1 % · kein ML-Champion (AUC 0,47–0,50) |
| Gesamt | **5/10** | Infrastruktur Oberklasse, Ertrag noch nicht |

Die Lücke sitzt nicht in der Oberfläche. Sie sitzt darin, dass **alle 12 Strategien aus
derselben Familie kommen** (Momentum/Allokation über ETFs) — die Maschine probiert zu wenige
verschiedene Ideen aus, um einen echten Gewinner zu finden. Jede zusätzliche, ANDERS
begründete Familie ist eine eigene Chance auf Edge; mehr Oberfläche ist keine.

## Datenlage (geprüft, nicht angenommen)

- `data/prices/entry_panel.csv`: **31 Einzeltitel × 5.115 Tage (2007-01-02 → 2026-08-07)**,
  alle mit voller Historie → trägt Querschnitts-Strategien.
- `data/prices/etf_panel.csv`: 21 ETFs × 2.045 Tage (2018-06-19 → …).
- **Survivorship-Bias, ausdrücklich:** die 31 Titel sind die HEUTIGE Watchlist. Ein
  Querschnitts-Backtest darauf ist optimistisch verzerrt — dieselbe Einschränkung, die
  `MODEL_CAVEATS` für das ML-Modell schon trägt. Die neuen Strategien laufen deshalb
  standardmäßig über das ETF-Panel (survivorship-frei, weil Index-ETFs nicht verschwinden)
  und können per Parameter auf das Aktien-Panel gezeigt werden.

## Tasks

- [x] **T1 Low-Vol-Anomalie** (`strategies/low_vol.py`) — die N Assets mit der niedrigsten
      realisierten Vola, invers-vol gewichtet. Eigene Familie: wählt nach RISIKO, nicht nach
      Rendite. Quellen: Haugen & Baker 1991, Blitz & van Vliet 2007, Frazzini & Pedersen 2014
      („Betting Against Beta").
- [x] **T2 Cross-Sectional Momentum** (`strategies/cross_momentum.py`) — Top-N nach 12-1-Momentum
      mit Skip-Month gegen die Kurzfrist-Umkehr, plus absoluter Momentum-Filter je Slot.
      Jegadeesh & Titman 1993; Asness/Moskowitz/Pedersen 2013.
- [x] **T3 Mean-Reversion** (`strategies/mean_reversion.py`) — kauft die N am stärksten
      überverkauften Titel (z-Score des Abstands zum gleitenden Mittel), aber nur im
      Aufwärtsregime des Marktes. Gegenläufig zu T2, damit die Familien sich nicht doppeln.
- [x] **T4 Risk Parity** (`strategies/risk_parity.py`) — invers-Vol über ALLE Assetklassen statt
      Auswahl; keine Prognose, nur Risikoausgleich. Qian 2005; Asness/Frazzini/Pedersen 2012.
- [x] **T5 Backtests messen und ehrlich berichten** — inkl. Nullbefund.
- [x] **T6 Doku + Wächter** — CronCreate-Resume, PLAN/LOG/Session-Doc/Memory.
- [x] **T7 (ungeplant, der Multiplikator)** Die vier Familien in den v14-Suchraum aufnehmen
      (`ml/strategy_search.py`, 43 → 82 Konfigurationen). Ohne das bleiben sie für immer auf
      den Startwerten stehen, die ich aus der Literatur genommen habe, und der Nightly-Loop
      tunt weiter nur die fünf alten. Jetzt prüft die Maschine meine Annahmen selbst nach.

## Bewusste Grenzen dieser Welle

- **Keine neue Datenquelle, keine Kosten.** Alles läuft auf vorhandenen Panels.
- **Keine Aufnahme in den laufenden Ensemble-Blend.** Das würde die Forward-Historie des
  Ensembles rückwirkend umschreiben — dieselbe Regel, die v8 für die Sektor-Rotation gesetzt
  hat. Die neuen Familien starten als eigene Sleeves mit eigenem Forward-Track.
- **Keine Depot-Aufnahme ohne Gate.** Ein neuer Sleeve muss dieselbe Promotion-Hürde nehmen
  wie eine Arena-Lane; nichts wird per Hand ins Auto-Depot gehoben.

## Outcome

Commit `1aacab3`, Gate 1905 Tests grün + ruff clean. 22 neue Tests, alle vier Familien in der
Registry, alle vier mit erstem Forward-Advance (Konten live in `forward_paper.db`).

### Backtest über das echte ETF-Panel (2.045 Tage, 2018-06-19 → 2026-08-07, 10 bps Kosten)

| Strategie | CAGR | Sharpe | MaxDD | Vol | Turnover |
|---|---|---|---|---|---|
| Permanent Portfolio | 8,4 % | 1,04 | −17,6 % | 8,0 % | 0,4× |
| **Cross-Sectional Momentum (12-1)** | **15,3 %** | **1,00** | **−25,4 %** | 15,3 % | 6,2× |
| Multi-Strategie-Mix | 9,1 % | 0,91 | −19,1 % | 10,1 % | 3,7× |
| 60/40 | 9,9 % | 0,88 | −21,3 % | 11,4 % | 0,3× |
| SPY buy & hold | 15,3 % | 0,84 | −33,7 % | 19,3 % | 0× |
| **Risk Parity (naiv)** | 6,4 % | 0,78 | −19,8 % | 8,4 % | 1,2× |
| **Low-Vol-Anomalie** | 3,7 % | 0,61 | −16,2 % | 6,3 % | 3,3× |
| **Mean-Reversion (10 Tage)** | 2,7 % | 0,31 | −27,6 % | 10,5 % | 16,0× |

### Was das heißt — einer von vier trägt

- **Cross-Sectional Momentum ist der Fund.** Gleiche Rendite wie SPY (15,3 %) bei 8 Punkten
  weniger Drawdown und der zweitbesten Sharpe im Feld von 13. Genau die Familie, die die
  Literatur am breitesten stützt. **Aber:** 8 Jahre, überwiegend Bullenmarkt, In-Sample, und
  6,2× Turnover heißt, dass die Kostenannahme trägt oder kippt. Ein Backtest ist keine
  Evidenz — deshalb zählt ab heute nur der Forward-Track.
- **Risk Parity** verhält sich wie erwartet: ruhig, unspektakulär, unleveraged. Nützlich als
  Diversifikator, nicht als Renditemotor.
- **Low-Vol enttäuscht messbar** — 3,7 % CAGR. Konsistent mit dem dokumentierten Verblassen
  der Anomalie in US-Aktien seit ~2018, und der Backtest beginnt im Juni 2018. Niedrigster
  Drawdown des ganzen Feldes (−16,2 %), aber die Rendite trägt das nicht.
- **Mean-Reversion ist gescheitert, und zwar erwartbar:** 16× Turnover bei 2,7 % CAGR. Der
  eigene Docstring hat es vorhergesagt („das Erste, was Kosten auffressen"). Kandidat zum
  Ausbau der Haltedauer oder zum Abschalten — die Entscheidung braucht Forward-Daten, nicht
  eine zweite Backtest-Runde auf denselben 8 Jahren.

### T7: Suchraum 43 → 82, und ein Befund gegen die Literatur

Beste Konfiguration je Familie, gemessen über das echte ETF-Panel. **In-Sample über 82
Kandidaten** — genau die Zahl, für die die Deflated-Sharpe-Hürde des Ledgers existiert:

| Familie | beste Sharpe | CAGR | MaxDD | Turnover | Parameter |
|---|---|---|---|---|---|
| cross_momentum | 1,08 | 19,5 % | −23,2 % | 6,7× | lookback 12, **skip 0**, top_n 2 |
| risk_parity | 0,83 | 7,2 % | −19,7 % | 1,1× | max_weight 0,25 |
| mean_reversion | 0,78 | 6,8 % | −13,5 % | 14,0× | window 10, top_n 5 |
| low_vol | 0,65 | 4,5 % | −15,9 % | 2,3× | top_n 7, window 126 |

**`skip_months=0` gewinnt.** Der Skip-Month ist für US-Einzelaktien gut belegt (Jegadeesh &
Titman 1993) und überträgt sich auf dieses 21-ETF-Universum offenbar nicht — plausibel, weil
die Kurzfrist-Umkehr ein Einzeltitel-Effekt ist (Bid-Ask-Bounce, Liquidität) und ein
Index-ETF beides wegdiversifiziert. Genau deshalb ist der Parameter als FRAGE in den Suchraum
gegangen statt als gesetzte Antwort. Mean-Reversion springt mit den besten Parametern von
Sharpe 0,31 auf 0,78 — bleibt aber bei 14× Turnover das kostenanfälligste Buch im Feld.

### Bewusst nicht getan

- **Produktions-Defaults NICHT auf die Grid-Gewinner gesetzt.** Acht Jahre anzupassen wäre
  Overfitting, und geänderte Parameter sind eine neue Strategie-Identität, die die
  Forward-Tracks umschreiben würde — dieselbe Regel, die der Modul-Docstring von
  `strategy_search.py` schon festhält. Der Nightly bewertet sie ab jetzt mit korrekter Hürde.
- **Kein Hand-Promoten ins Auto-Depot.** Cross-Sectional Momentum muss dieselbe
  Promotion-Hürde nehmen wie jede Arena-Lane (≥30 Trades, ≥60 Tage, Netto > 0, PF ≥ 1,1).
- Kein zweiter Backtest-Durchlauf zur Rettung von Low-Vol und Mean-Reversion auf denselben
  8 Jahren. Was über sie entscheidet, ist der Forward-Track, der heute begonnen hat.

### Wo die Bewertung jetzt steht

Die Maschine ist von 12 auf 16 Strategien gewachsen, der Suchraum von 43 auf 82, und der
Nightly-Loop prüft ab heute Nacht selbstständig weiter. Die 2/10 auf der Geld-Achse bleibt
2/10, bis ein Forward-Track etwas anderes zeigt — das ist keine Bescheidenheit, sondern die
einzige Zahl, die nicht in-sample ist. Der Unterschied zu heute Mittag: es gibt jetzt einen
Kandidaten, der SPY bei geringerem Drawdown matcht, und eine Maschine, die ihn ohne mich
weiter prüft.
