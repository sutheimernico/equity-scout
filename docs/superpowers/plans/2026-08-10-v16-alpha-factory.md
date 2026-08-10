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

- [ ] **T1 Low-Vol-Anomalie** (`strategies/low_vol.py`) — die N Assets mit der niedrigsten
      realisierten Vola, invers-vol gewichtet. Eigene Familie: wählt nach RISIKO, nicht nach
      Rendite. Quellen: Haugen & Baker 1991, Blitz & van Vliet 2007, Frazzini & Pedersen 2014
      („Betting Against Beta").
- [ ] **T2 Cross-Sectional Momentum** (`strategies/cross_momentum.py`) — Top-N nach 12-1-Momentum
      mit Skip-Month gegen die Kurzfrist-Umkehr, plus absoluter Momentum-Filter je Slot.
      Jegadeesh & Titman 1993; Asness/Moskowitz/Pedersen 2013.
- [ ] **T3 Mean-Reversion** (`strategies/mean_reversion.py`) — kauft die N am stärksten
      überverkauften Titel (z-Score des Abstands zum gleitenden Mittel), aber nur im
      Aufwärtsregime des Marktes. Gegenläufig zu T2, damit die Familien sich nicht doppeln.
- [ ] **T4 Risk Parity** (`strategies/risk_parity.py`) — invers-Vol über ALLE Assetklassen statt
      Auswahl; keine Prognose, nur Risikoausgleich. Qian 2005; Asness/Frazzini/Pedersen 2012.
- [ ] **T5 Backtests messen und ehrlich berichten** — inkl. Nullbefund.
- [ ] **T6 Doku + Wächter** — CronCreate-Resume, PLAN/LOG/Session-Doc/Memory.

## Bewusste Grenzen dieser Welle

- **Keine neue Datenquelle, keine Kosten.** Alles läuft auf vorhandenen Panels.
- **Keine Aufnahme in den laufenden Ensemble-Blend.** Das würde die Forward-Historie des
  Ensembles rückwirkend umschreiben — dieselbe Regel, die v8 für die Sektor-Rotation gesetzt
  hat. Die neuen Familien starten als eigene Sleeves mit eigenem Forward-Track.
- **Keine Depot-Aufnahme ohne Gate.** Ein neuer Sleeve muss dieselbe Promotion-Hürde nehmen
  wie eine Arena-Lane; nichts wird per Hand ins Auto-Depot gehoben.

## Outcome

_(nach den Backtests mit gemessenen Zahlen gefüllt — auch bei Nullbefund)_
