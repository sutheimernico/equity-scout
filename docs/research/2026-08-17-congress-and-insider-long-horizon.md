# Kongress- und Insider-Käufe über lange Horizonte: der Befund ist negativ, nicht neutral (2026-08-17)

Nicos Frage: „wenn so Kongressmitglieder irgendwas kaufen, dann mal tracken, ob das dann über die
Zeit eher stieg oder nicht, weil dann kann man ja darüber auch langfristige Trades eingehen."

Die Daten dafür lagen schon im Projekt und waren nie über alle Horizonte aggregiert ausgewertet:
`historical_events` enthält **23.274 Kongress-Käufe (2014–2026)** und **27.681 Insider-Käufe
(2006–2026)** — beide Kollektoren nehmen ausschließlich KÄUFE auf (`backfill_congress`:
„purchases only") — jeweils aufgelöst über **1 Woche, 1 Monat, 3, 6 und 12 Monate**.

## Ergebnis in drei Sätzen

1. **Kongress-Käufe schlagen den Markt nicht — sie verlieren gegen ihn, je länger man hält.**
   Über 12 Monate liegen sie **17,55 Prozentpunkte unter SPY** (t = −51,6 auf 16.358 Ereignissen),
   und nur **27,5 %** der Käufe schlagen den Index überhaupt.
2. **Insider-Käufe sehen im Mittelwert gut aus und sind es im Median nicht.** +7,91 % absolut über
   12 Monate klingt gut, liegt aber **5,76 pp unter SPY** (t = −3,5), und der Median-Kauf steht bei
   **−5,48 %**. Der positive Mittelwert kommt von wenigen Ausreißern; die typische Position verliert.
3. **Eine Placebo-Kontrolle schließt den naheliegenden Einwand aus.** Dieselben Titel zu ZUFÄLLIGEN
   Zeitpunkten gekauft liefern **+4,01 pp gegen SPY** (n = 3.564) — der Kongress-Effekt von
   −17,55 pp ist also **nicht** der bekannte „Median-Einzeltitel schlägt keinen Index"-Effekt,
   sondern liegt **21,6 Prozentpunkte darunter**. Die Auswahl selbst ist das Problem.

## Die Zahlen

Abnormale Rendite = eigene Rendite minus SPY über dasselbe Fenster, pro Ereignis gerechnet.

| Quelle | Horizont | n | Ø Titel | Ø SPY | **abnormal** | t | schlägt SPY |
|---|---|---|---|---|---|---|---|
| Kongress | 1 Woche | 20.792 | +0,15 % | +0,29 % | **−0,14 %** | −3,74 | 46,6 % |
| Kongress | 1 Monat | 20.114 | +0,06 % | +1,52 % | **−1,46 %** | −18,89 | 39,9 % |
| Kongress | 3 Monate | 19.218 | −0,22 % | +4,49 % | **−4,71 %** | −34,43 | 35,6 % |
| Kongress | 6 Monate | 18.544 | −0,63 % | +8,59 % | **−9,21 %** | −46,17 | 31,7 % |
| Kongress | 12 Monate | 16.358 | −0,39 % | +17,17 % | **−17,55 %** | −51,64 | 27,5 % |
| Insider | 1 Woche | 13.856 | +2,08 % | +0,27 % | +1,81 % | +1,87 | 49,5 % |
| Insider | 1 Monat | 13.856 | +10,49 % | +1,31 % | +9,18 % | +1,13 | 43,9 % |
| Insider | 3 Monate | 13.694 | +2,55 % | +3,51 % | −0,96 % | −1,42 | 39,8 % |
| Insider | 6 Monate | 13.492 | +4,12 % | +6,78 % | −2,67 % | −2,32 | 36,5 % |
| Insider | 12 Monate | 13.112 | +7,91 % | +13,67 % | −5,76 % | −3,51 | 32,9 % |

**Placebo-Kontrolle (12 Monate):** dieselben 297 Titel mit verfügbarer Kurshistorie, je 12
Zufallsstichtage, gleicher Horizont → abnormal **+4,01 %**, t = +1,51, schlägt SPY in 43,8 % der
Fälle. Zufällige Zeitpunkte in denselben Titeln sind also **besser** als die Kaufzeitpunkte der
Abgeordneten.

## Warum die Richtung des Befundes so eindeutig ist

Der monotone Verlauf ist das Überzeugende: −0,14 → −1,46 → −4,71 → −9,21 → −17,55 pp, und der
Anteil der Käufe, die den Index schlagen, fällt gleichmäßig von 46,6 % auf 27,5 %. Ein
Datenartefakt sieht selten so ordentlich aus. Und der t-Wert von −51,6 lässt keinen Raum: das
Ergebnis ist nicht „nicht nachweisbar", es ist nachweislich negativ.

Der plausible Mechanismus, ohne dass diese Messung ihn beweisen könnte: Abgeordnete kaufen, was
gerade in den Nachrichten ist und gut gelaufen ist — und die Nachricht ist zum Meldezeitpunkt
(bis zu 45 Tage Verzug) längst eingepreist. Der Kauf markiert damit eher das Ende einer Bewegung
als ihren Anfang.

## Was das für die Vision heißt

Ein „Kongressmitglied hat gekauft"-Baustein in einer Trade-Entscheidung wäre nach diesen Daten
**kein positiver, sondern ein negativer Indikator** — und zwar deutlich. Als Bedingung in der
Signal-Matrix bleibt er trotzdem interessant, aber mit umgekehrtem Vorzeichen zur Erwartung: die
sinnvolle Frage ist nicht „kauft er mit?", sondern ob die Abwesenheit solcher Käufe ein Filter
ist. Beides läuft in der Matrix mit, damit die Richtung gemessen und nicht angenommen wird.

## Grenzen

- **Nur Käufe, keine Verkäufe.** Die Kollektoren nehmen ausschließlich Käufe auf. Über die
  Prognosekraft von Verkäufen sagt diese Messung nichts.
- **Kein Betragsgewicht.** Ein 1.001-$-Kauf zählt wie ein 5-Mio-$-Kauf. `amount_range` liegt in
  den Details und wäre eine sinnvolle nächste Dimension.
- **Der Placebo-Test nutzt 297 der 2.032 Titel** (die mit ladbarer Kurshistorie) und 12 Stichtage
  je Titel. Er widerlegt den Median-Titel-Einwand, ist aber kein vollständiges Gegenstück.
- **Absolutrenditen ohne Risikoadjustierung.** Ein Titel mit doppeltem Beta müsste über 12 Monate
  mehr als SPY liefern; hier wird nur die Differenz gemessen, kein Alpha im CAPM-Sinn.
