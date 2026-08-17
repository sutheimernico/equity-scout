# Vollständiges Inventar: alles, was dieses Projekt gemessen hat (Stand 2026-08-17)

Nicos Auftrag: „Schau dir einfach alles an, was ist in der Applikation drin und was hast du dir
alles in der History widerlegt oder belegt? Was haben wir alles gemacht? Schau dir das alles an
und nimm das alles mit in die Pläne rein."

Dieses Dokument ist die Antwort und die Referenz für alle künftigen Wellen der Signal-Matrix.
Quellen: 28 Dokumente in `docs/research/`, die Phasen in `PLAN.md`, und der Code selbst.

---

## Teil 1 — Handelsregeln, die geprüft wurden

Jede Zeile ist eine Regel, die gemessen wurde. „Verdikt" ist der dokumentierte Befund; „in der
Matrix" sagt, ob und wie sie in der Signal-Matrix wieder auftaucht.

| Regel | Doku | Verdikt | in der Matrix |
|---|---|---|---|
| **ORB (Opening-Range-Breakout), intraday** | `session-lane-trades-against-the-evidence`, `orb-overnight-backtest` | widerlegt: 1.684 Ausbrüche intraday, dazu 2.550 Signale mit Overnight-Halten in 3 Armen — alle gegen den bedingungslosen Benchmark verloren; Lane **pausiert** | ja, als `breakout_high` auf ALLEN 8 Scheiben statt nur einer |
| **Ausbruch, Einstieg in Minute 1** | `breakout-first-minute` | Impuls existiert (+4,63 bp) und hält genau 1 Minute, danach monoton negativ; t = 0,94 auf nur 91 Ereignissen aus 7 Tagen — **datenlimitiert, nicht entschieden** | ja — jetzt auf 10 Jahren statt 7 Tagen |
| **5-Minuten-Reversal (Liquiditätsprämie)** | `minute-scale-trading` | Effekt hochsignifikant (Autokorrelation −0,0644, t = −32,1 auf 248.461 Fenstern), aber nach Kosten nur EINE positive Zelle (stärkstes Fünftel bei 4 bp: +1,86 bp) | ja, als `reversal_down` + `spike_fade` |
| **Gap-Fade (Lücke schließen)** | `gap-fade-backtest`, `gap-fade-executability` | einziger Kandidat, der brutto hielt (+228,68 bp bei den größten Lücken) — **aber der Effekt ist 15 Minuten nach Eröffnung weg**, und der vorbörsliche Kurs sagt die Lücke nicht vorher (`premarket-gap-prediction`). Lane läuft als Messinstrument | ja, als `gap_down`/`gap_up` |
| **Turn-of-Month** | `turn-of-month-backtest` | widerlegt (+4,66 % vs. +11,28 % Benchmark) | ja, implizit über die 1D/1W-Scheiben |
| **52-Wochen-Hoch kaufen** | `52-week-high-backtest` | widerlegt (+0,54 %, Trefferquote 52,6 %) | ja, als `breakout_high` auf 1D/1W |
| **Volumen-Kapitulation** | `capitulation-backtest` | widerlegt (+0,22 pp gegen Basis) | ja, als `volume_spike` × `reversal_down` |
| **Overnight-Drift** | `overnight-drift-backtest` | widerlegt als eigene Lane (4,01 bp) | ja, über die 1D-Scheibe |
| **Short-Term-Reversal (Tagesskala)** | `short-term-reversal-backtest` | widerlegt (+0,29 pp, t = 2,68 brutto, nach Kosten weg) | ja, als `consecutive_down` |
| **Earnings-Premium** | `earnings-premium-backtest` | widerlegt (+0,08 pp) | offen — Earnings-Nähe fehlt noch als Bedingung |
| **PEAD (Post-Earnings-Drift)** | `event-drift-both-directions` | widerlegt: 1.729 Meldungen, keine Gruppe signifikant; nach SCHLECHTEN Nachrichten fallen Titel **nicht** (+0,82 %), Short verliert | offen — Richtungsklassifikation der News fehlt |
| **Donchian 20/10 (Crypto)** | PLAN.md, `lane_review` | 15-Minuten-Ära: ~460 von 451 USD Verlust waren Gebühren; Tagesbar-Ära n = 4, Urteil offen | ja, als `breakout_high` |
| **Rebalance-Tag (Timing-Glück)** | `rebalance-timing-luck` | signalgetriebene Sleeves streuen 1,6–5,9 pp CAGR nur durch den Kalendertag; kein Offset gewinnt systematisch | eigene Achse, nicht Matrix |
| **Kongress-Käufe folgen** | `congress-and-insider-long-horizon` | **nachweislich negativ**: −17,55 pp gegen SPY über 12 Monate (t = −51,6); Placebo mit Zufallsdaten liefert +4,01 pp | offen — als Bedingung geplant |
| **Insider-Käufe folgen** | dito | Mittelwert positiv, Median −5,48 %, gegen SPY über 12 Monate −5,76 pp | offen — als Bedingung geplant |
| **Congress-Lane (kurzfristig)** | PLAN.md v15 P2a | evidenzbasiert tot | — |
| **Insider-Cluster** | PLAN.md v15 P2a | nur Schatten-Kandidat, dünn | offen als Bedingung |

## Teil 2 — Vorhersage-Signale (Modell-Features), die geprüft wurden

| Kandidat | Doku | Verdikt |
|---|---|---|
| 11 Verhaltensindikatoren × 3 Renditehorizonte, bis 19 Jahre | `w0-historical-check` | **kein einziger sagt Rendite voraus**; was trägt, sagt Risiko voraus, und davon **0 von 63 inkrementell** |
| VIX-Terminstruktur (VIX9D/VIX/VIX3M) | dito | roh Rank-IC 0,51 → **inkrementell 0,08**; W1 gestrichen |
| Marktbreite (% über 200d) | dito | bester Nicht-Vola-Prädiktor für RISIKO, schon in der Ampel verbaut |
| Fear-&-Greed-Komposit | dito | **schwächer als seine beste Zutat** — deshalb wird die Zutat (VIX) verwendet |
| Baker-Wurgler-Sentiment | `behavioural-indicator-landscape` | Literatur: 0,9 %/Monat — an unseren Daten **strukturell unsichtbar** (Auflösungsgrenze 3,47 %/Monat) |
| Insider-Evidenz als Feature | v15 P3 | +0,003 AUC — Nullbefund, Coverage 2,5 % |
| Volumen als Feature | v17 | −0,001 AUC — Nullbefund |
| Zielgröße/Horizont/Universum (Achse 2) | `fixed-universe-and-the-final-null-result` | kein Modell der Familie erreichte je die eigene Schwelle 0,55 |
| Der live scorende Champion | `champion-was-a-measurement-artifact` | **Messartefakt**: behauptete AUC 0,6195 aus 220 Zeilen, lieferte 0,5152 auf 3.281 |
| VIX als Vola-Prognose | `voltarget-uses-the-weaker-estimator` | **einziger positiver Befund der Serie**: rho 0,642 vs. 0,539, OOS bestätigt → eingebaut 2026-08-17 |
| RSI, MACD, Stochastik, Bollinger | `behavioural-indicator-landscape` | Kategorie A: reine Preistransformationen, Literatur einig negativ nach Kosten; „wir bauen daraus nichts" |

## Teil 3 — Bekannte, freie Datenquellen, die NIE gebaut wurden

Aus der Landkarte, mit Literatur-Evidenz, im Code nachweislich nicht vorhanden (geprüft
2026-08-17: kein Treffer für `AAII`, `short_interest`, `put_call` in `src/` oder `scripts/`):

| Quelle | Was sie messen würde | Literatur | Verfügbarkeit |
|---|---|---|---|
| **AAII-Sentiment-Umfrage** | was Privatanleger erwarten | extreme Bearishness → überdurchschnittliche 12-Monats-Renditen | frei, wöchentlich (Do) |
| **Short Interest (FINRA)** | wie viele gegen einen Titel wetten | extrem hohes SI → überdurchschnittliche Folgerenditen (Squeeze) | frei, 2×/Monat |
| **Put/Call-Ratio (CBOE)** | Absicherungs- vs. Spekulationsdruck | kontrazyklisch, gut untersucht | CSV-Endpunkt gab 403 — Quelle nötig |

Diese drei sind die einzigen Kategorie-B-Quellen (echte Verhaltensdaten, keine
Preistransformationen), die das Projekt kennt und nicht nutzt. Sie gehören in Welle 4.

## Teil 4 — Was daraus in die Matrix geht

**Grundsatz, der aus Teil 1+2 folgt:** Eine widerlegte Regel wird NICHT ausgeschlossen, sondern
wieder aufgenommen — weil jede dieser Widerlegungen auf **einer** Zeitskala und **ohne**
Bedingung gemessen wurde. Genau das ist die Frage der Matrix: funktioniert dieselbe Regel auf
einer anderen Skala oder unter einer Bedingung? Was NICHT wieder aufgenommen wird, sind
Behauptungen, die an der Datengrenze scheitern (Baker-Wurgler: 0,9 %/Monat gegen eine
Auflösungsgrenze von 3,47 %/Monat) — dort würde auch die Matrix nur „nicht messbar" liefern.

**Wellen-Reihenfolge, jede mit eigener Beweislast:**

1. **Welle 2 (läuft in der Nacht 17./18.08.):** 13 Signale × 4 Schwellen × 8 Zeitscheiben ×
   5 Haltedauern × 4 Kostenstufen × 23 Bedingungen, Tiefe 1.
2. **Welle 3:** Kombinationstiefe 2–4 (Nicos „vielleicht sind es drei, vier Parameter") plus die
   Tages-Regime-Bedingungen, die fertig berechnet vorliegen: Marktbreite, Zinskurve, SPY-vs-200d,
   Depot-Drawdown. Dazu Kongress/Insider als Bedingung — mit dem aus Teil 1 dokumentierten
   NEGATIVEN Vorzeichen als Erwartung.
3. **Welle 4:** die drei ungenutzten Kategorie-B-Quellen (AAII, Short Interest, Put/Call), jede
   erst nach einem eigenen Abruf-Baustein.
4. **Welle 5:** Fundamentaldaten (F-Score-Kriterien), sobald der Backfill-Kollektor steht;
   Zielhorizont ist auf 126 Tage vorregistriert.

**Was die Matrix strukturell NICHT leisten kann** — damit die Erwartung stimmt: Sie findet
Regeln, deren Effekt größer als die Handelskosten ist. Effekte unterhalb der Kostenschwelle
existieren nachweislich (der 5-Minuten-Reversal mit t = −32), sind aber für uns nicht handelbar.
Und sie kann keinen Effekt auflösen, der kleiner ist als die statistische Auflösung des jeweiligen
Horizonts — auf Minutenskala ist die sehr gut, auf Monatsskala schlecht.
