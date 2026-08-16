# Turn-of-Month: geprüft, nicht gebaut (2026-08-16)

Erster Kandidat aus `plans/2026-08-16-short-term-lane-expansion.md`. Regel: kaufen zum Schluss
des drittletzten Geschäftstags eines Monats, verkaufen zum Schluss des dritten Geschäftstags
des Folgemonats, sonst Kasse. Ein Instrument (SPY), long-only, ~12 Roundtrips im Jahr.

**Ergebnis: die Lane wird nicht gebaut.** Der Effekt existiert, ist aber gegenüber normalen
Handelstagen nicht belegbar, und drei Viertel des Unterschieds gehen an die Handelskosten.

## Die Zahlen

SPY, 1995-01-03 bis 2026-08-14, 7.957 Handelstage, 349 abgeschlossene Trades.

| Kosten je Seite | Strategie | Buy & Hold | Trefferquote |
|---|---|---|---|
| 0 bps | +4,66 %/Jahr | +11,28 %/Jahr | 60,7 % |
| 10 bps | +2,37 %/Jahr | +11,28 %/Jahr | 56,2 % |
| 20 bps | +0,14 %/Jahr | +11,28 %/Jahr | 51,6 % |

Die Strategie ist nur **26,2 % der Tage im Markt**, der Vergleich mit Buy & Hold ist also
unfair zu ihren Ungunsten. Deshalb der eigentliche Test — Fenster-Tage gegen alle anderen:

| | n | Ø pro Tag | annualisiert | t |
|---|---|---|---|---|
| Turn-of-Month-Tage | 2.435 | 7,72 bp | 21,5 % | 3,30 |
| alle anderen Tage | 5.521 | 3,75 bp | 9,9 % | 2,30 |
| **Differenz** | | **3,97 bp** | | **1,39** |

## Warum das ein Nein ist

1. **Die Differenz ist nicht signifikant.** t = 1,39 über 31 Jahre und fast 8.000 Handelstage.
   Das ist die beste Datenlage, die wir zu dieser Frage je bekommen werden — wenn der
   Unterschied hier nicht steht, wird er in ein paar Monaten Papierhandel nicht auftauchen.
2. **Die Kosten fressen ihn.** Ein Roundtrip kostet bei 10 bps je Seite 20 bp, verteilt auf die
   ~7 Handelstage im Fenster sind das 2,86 bp pro Tag — gegen 3,97 bp Differenz. Netto bleiben
   1,11 bp pro Tag, also **72 % des Effekts gehen an die Reibung**.
3. **Der Rest ist ein Risiko-Argument, kein Alpha-Argument.** Ja, die Regel erzielt 4,66 %/Jahr
   mit nur 26 % Marktzeit — pro Zeit im Markt schlägt sie Buy & Hold. Das ist aber die Aussage
   „weniger Risiko bringt weniger Rendite", nicht „diese Tage sind besonders". Und als Lane
   gegen SPY gemessen würde sie dauerhaft schlecht aussehen, obwohl sie nur ein Viertel des
   Risikos trägt — genau die irreführende Gegenüberstellung, die wir bei der Crypto-Lane
   schon einmal korrigiert haben.

## Was bleibt

Der Code bleibt liegen (`src/equity_scout/st_turnofmonth.py`, 8 Tests): reine
Entscheidungslogik plus ein Backtest, der Kosten je Seite verrechnet. Er kostet nichts, er
läuft nirgends, und wenn die Frage wiederkommt, ist die Antwort in einer Minute reproduzierbar
statt in einem Tag.

**Methodisch festhalten:** Der Einstiegstag kommt aus dem **Kalender**, nicht aus dem
Kursverlauf. „Drittletzter Handelstag" rückwärts durch die beobachteten Sessions zu zählen
setzt voraus, dass man weiß, dass keine weitere folgt — am Tag selbst weiß man das nicht. Diese
Art Look-ahead hätte den Backtest geschmeichelt, ohne dass es jemandem aufgefallen wäre.
