# Erste Lane-Parametersuche: der Gewinner ist nicht belegbar besser (2026-08-16)

T10 aus dem Plan, gebaut auf Nicos Entscheidung, automatische Nachjustierung zuzulassen. 650
Ereignisse (Quartalsmeldung mit Kursreaktion über +2 %), 36 Parameterkombinationen, simuliert
mit **derselben** `exits.exit_reason`, die die Lane live verwendet.

## Was die Suche findet

| Ziel | Stop | Tage | Ø je Trade | Trefferquote | häufigster Ausstieg |
|---|---|---|---|---|---|
| 5 % | **5 %** | **14** | **+1,19 %** | 56,3 % | Kursziel (300 von 650) |
| 8 % | 5 % | 14 | +1,17 % | 51,8 % | Stop-Loss (249) |
| 12 % | 5 % | 14 | +1,07 % | 49,1 % | Stop-Loss (260) |
| … | | | | | |
| 5 % | 3 % | 7 | +0,77 % | 49,2 % | **heutige Einstellung, Rang 17 von 36** |

Das Muster ist eindeutig: **Jede der besten Kombinationen hat einen weiteren Stop (5 % statt
3 %) und eine längere Haltefrist (14 statt 7 Tage).** Das passt exakt zum Befund der nächtlichen
Lane-Auswertung — der enge Stop wirft Positionen heraus, bevor sie sich entwickeln können.

## Warum trotzdem nichts geändert wird

| | Ø je Trade | t gegen null |
|---|---|---|
| bester Kandidat | +1,19 % | 3,83 |
| heutige Einstellung | +0,77 % | 2,78 |
| **Differenz** | **+0,42 pp** | **1,01** |

**t = 1,01 bei 36 getesteten Kombinationen.** Beide Einstellungen verdienen für sich genommen
Geld (t = 3,83 bzw. 2,78) — aber der Vorsprung des Gewinners ist von null nicht zu
unterscheiden. Wer 36 Kombinationen durchprobiert, findet immer eine, die im Rückblick besser
aussah; nach Bonferroni läge die Schwelle hier bei etwa t = 3.

**Das ist der erste echte Lauf der Mechanik, die Nico wollte — und ihr erstes Urteil lautet
„nichts ändern".** Genau dafür ist die Hürde da. Ohne sie hätte das System die Parameter
umgestellt und dabei Rauschen für Lernen gehalten.

## Was das über die Idee sagt, nicht nur über diesen Lauf

Der Befund, der bleibt, ist nicht der Gewinner, sondern das **Muster**: Alle sechs besten
Kombinationen wollen einen weiteren Stop. Ein einzelner Gewinner kann Zufall sein, eine
Richtung über die gesamte Rangliste ist schwerer als Zufall zu erklären. Das ist ein Hinweis,
den man weiterverfolgen kann — aber mit einer Prüfung außerhalb dieser Stichprobe, nicht mit
einer Übernahme innerhalb.

Vorsicht bleibt bei den Ereignissen selbst: Sie stammen aus derselben überlebensverzerrten
Titelauswahl wie alle Tests dieser Serie, und die Sortierung nach Kursreaktion ist nur ein Proxy
für die klassifizierte Überraschung, die die Lane real verwendet.
