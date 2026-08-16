# Short-Term-Reversal: geprüft, keine Lane (2026-08-16)

Fünfter Kandidat aus `plans/2026-08-16-short-term-lane-expansion.md`, als reiner Backtest
angesetzt: die Verlierer der letzten Woche kaufen. 91 US-Titel, 2012–2026, Signal- und
Haltefenster je 5 Handelstage, **nicht überlappend** ausgewertet (Lektion aus T3).

**Ergebnis: keine Lane.** Vier unabhängige Gründe, von denen jeder für sich reicht.

## Der Ausgangsbefund sah brauchbar aus

| | Vorwärtsrendite 5 T |
|---|---|
| Verlierer-Fünftel | +0,61 % |
| alle Titel (Basis) | +0,32 % |
| **Vorsprung** | **+0,29 pp**, t = 2,68 |

## Grund 1: In keiner Teilperiode signifikant

| Zeitraum | Vorsprung | t |
|---|---|---|
| 2012–2016 | +0,18 pp | 1,13 |
| 2016–2020 | +0,03 pp | 0,18 |
| 2020–2023 | +0,61 pp | 2,33 |
| 2023–2027 | +0,41 pp | 1,58 |

Der Gesamtbefund lebt von 2020–2023 — der Stressphase mit der höchsten Volatilität. Das passt
zur Standarderklärung (Reversal ist die Entlohnung dafür, in einer Panik die Gegenseite zu
nehmen), taugt aber nicht als verlässliche Regel: In der ruhigen Phase 2016–2020 ist der Effekt
exakt null. Bei vier Teilperioden liegt die Bonferroni-korrigierte Schwelle bei etwa t = 2,5 —
keine erreicht sie.

## Grund 2: Der Vorsprung ist Risiko, nicht Können

Das Verlierer-Fünftel schwankt mit **10,63 %** gegen 7,58 % im Gesamtdurchschnitt — 40 % mehr
Volatilität für 0,29 Prozentpunkte. Risikoadjustiert bleibt nichts übrig. Genau das sagt die
Literatur auch: Kurzfrist-Reversal ist überwiegend Kompensation für Liquiditätsbereitstellung.

## Grund 3: Die Trefferquote ist unverändert

51,9 % gegen 51,1 %. Der positive Mittelwert kommt also nicht daher, dass die Regel öfter
richtig liegt, sondern von wenigen großen Bewegungen — dasselbe Muster wie bei den
Insider-Clustern und bei der Kapitulation.

## Grund 4: Survivorship wirkt genau in Richtung des Befunds

Die Stichprobe sind heutige Universum-Mitglieder. Das Verlierer-Fünftel besteht per Definition
aus gerade gefallenen Titeln — und von denen sind nur die in den Daten, die sich erholt haben.
Die 17,67 %/Jahr, die hier als „Basis" herauskommen, sind allein schon ein Beleg dafür, wie
stark die Stichprobe nach oben verzerrt ist (der reale Markt liefert etwa 11 %).

## Was die Rechnung zusätzlich bestätigt hat

Die Zerlegung nach Tageszeit repliziert Della Corte/Kosowski sauber:

| Signal aus … | Spread Verlierer − Gewinner | t |
|---|---|---|
| Gesamtrendite | +0,40 pp | 2,98 |
| nur Intraday-Anteil | +0,25 pp | 1,82 |
| **nur Overnight-Anteil** | **+0,00 pp** | **0,03** |

Wer sich über Nacht bewegt hat, sagt über die nächste Woche **nichts** — die Umkehr steckt
ausschließlich in der Bewegung während der Handelszeit. Zusammen mit T4 (93 % der Rendite
entsteht über Nacht) ergibt das ein konsistentes Bild: Über Nacht kommt die Rendite, tagsüber
kommt das Rauschen, das sich anschließend zurückdreht.

## Bilanz der Welle

Fünf Kandidaten geprüft, fünf abgelehnt — Turn-of-Month, 52-Wochen-Hoch, Volumen-Kapitulation,
Overnight-Drift, Short-Term-Reversal. Das ist kein Zufall und kein Pech: Es ist genau die
Erwartung, die auf jeder Oberfläche dieses Projekts steht („Kurzfrist-Trading verliert im
Retail-Rahmen nach Kosten meistens"), zum ersten Mal an eigenen Zahlen durchbuchstabiert.
Der Wert liegt darin, dass es fünf Backtests gekostet hat statt fünf Lanes über Monate.
