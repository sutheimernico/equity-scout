# 2026-08-27 — Kaufplan-Ansicht + Vorschlags-Rückschau (Nachtschicht)

**Auftrag (Nico, 01:45, „ich geh pennen, arbeite das selber in einer Loop"):** Autotrader/App
weiterbringen; Vorschläge aktualisieren; **Score, ob die bisherigen Vorschläge gute Einstiege
gewesen wären**; eine Ansicht mit Kaufplan pro Aktie (kurz/lang, Kauflimit, Score, Verkaufsziel,
Tranchen, Geschäftsmodell, Warum, News, wer hat gekauft); Link per Telegram fürs Handy.

## Ausgangsbefund (gemessen, nicht geschätzt)
- Watchlist-Snapshot 2026-08-26 20:45: **30 Titel, davon 0 `in_zone`.** Die App-Ansicht
  „Kaufbereit" ist damit leer — genau in der Nacht, in der Nico kaufen will.
- Spitzenreiter ITC.NS (Score 69) steht **13 % UNTER** seiner Einstiegszone
  („Support gebrochen"), ist also ausdrücklich kein Kauf. Der Rest: Score 41 abwärts.
- 31 Pitches seit Juni, 16 distinct Ticker; die letzten 12 tragen fast durchgehend
  `verdict=red` und `status=expired`.
- **Es gibt keine Messung, ob die Vorschläge je etwas gebracht haben.** `/api/proof` misst die
  Paper-BÜCHER (Auto-Depot, Arena-Lanes), nicht die Vorschlagsliste. Das ist die Lücke.

## Tasks
- [ ] T1 `suggestion_review.py`: reine Messfunktionen für „hätte der Vorschlag getragen?"
      (Vorschlag → Rendite über Horizont → minus regionaler Benchmark → Aggregat mit
      unabhängigem n). Ehrlichkeitsregeln aus LOOP.md gelten: Stichprobenidentität stempeln,
      überlappende Fenster nicht als unabhängig zählen.
- [ ] T2 `scripts/run_suggestion_review.py`: Kurse holen (yfinance, hinter Naht), messen,
      Ergebnis in Tabelle `suggestion_reviews` schreiben.
- [ ] T3 `/api/rueckschau` + Panel: die Zahl, die Nico verlangt hat — mit Aussagekraft daneben.
- [ ] T4 `/api/kaufplan`: pro Titel EIN Kaufplan-Objekt (Horizont, Score, Limit/Zone, Tranchen,
      Ziel, Stop, Positionsgröße, Geschäft, Warum, News, wer kauft, Verkaufsregeln).
- [ ] T5 Kaufplan-Ansicht im Cockpit (Handy-first, 390 px).
- [ ] T6 Voll-Scout + Insights frisch (läuft seit 01:50 im Hintergrund).
- [ ] T7 Telegram: Link + Kurzfassung der Befunde.

## Harte Grenzen (unverändert)
Kein Echtgeld-Routing, keine bezahlten Feeds, keine neuen Konten. Jede Oberfläche trägt den
DISCLAIMER. Die Rückschau misst Vergangenheit — sie ist keine Prognose und wird nirgends als
eine dargestellt.
