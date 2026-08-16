# Gap-Fade: der erste Kandidat, der hält — mit einer harten offenen Frage (2026-08-16)

Siebter und letzter Kandidat aus `plans/2026-08-16-short-term-lane-expansion.md`: gegen die
Eröffnungslücke handeln. 91 US-Titel, 324.931 Handelstage 2012–2026.

**Ergebnis: der einzige Befund dieser Serie, der jeder Nachfrage standhält — und der einzige,
bei dem die Umsetzbarkeit noch nicht geklärt ist.** Deshalb noch keine Lane, sondern eine
konkrete Vorbedingung.

## Der Befund ist monoton und stark

Kursverlauf vom Eröffnungskurs bis zum Schluss desselben Tages, nach Größe der Lücke:

| Eröffnungslücke | n | Tagesverlauf | t | Trefferquote |
|---|---|---|---|---|
| ≤ −5 % | 2.976 | **+228,68 bp** | 12,36 | 56,6 % |
| −5 … −3 % | 4.939 | +101,17 bp | 14,20 | 57,5 % |
| −3 … −1 % | 32.537 | +28,96 bp | 15,69 | 52,0 % |
| ±1 % | 239.212 | −0,56 bp | −1,22 | 46,0 % |
| +1 … +3 % | 35.668 | −19,01 bp | −10,89 | 42,8 % |
| > +3 % | 9.599 | −118,87 bp | −16,50 | 33,2 % |

Perfekt monoton über sechs Klassen, in beide Richtungen. Die Aufwärtslücken wären das noch
stärkere Signal — für uns nicht handelbar, weil sie Leerverkäufe bräuchten.

## Er hält, was die anderen sechs nicht gehalten haben

**Über die Zeit** (Lücke ≤ −3 %): 2012–2016 +274,84 bp (t = 13,31) · 2016–2020 +142,08 (t = 8,89)
· 2020–2023 +69,23 (t = 4,61) · 2023–2027 +139,19 (t = 9,45). Schwächer werdend, aber in
**jeder** Teilperiode signifikant — anders als bei Reversal, wo eine Periode exakt null war.

**Nach Kosten** (Lücke ≤ −3 %): bei 10 bp je Seite +129,11 bp (t = 15,58), bei 25 bp +99,11
(t = 11,96), bei 50 bp +49,11 (t = 5,93). Erst bei 100 bp je Seite kippt es ins Minus. Die
anderen Kandidaten starben bei 2 bis 20 bp.

**Keine Überlappung.** Jeder Handelstag ist eine eigene Beobachtung — der Fehler, der die
Kapitulation aufgeblasen hat, kann hier nicht auftreten.

## Die offene Frage, die alles entscheidet

**Das Signal ist der Eröffnungskurs — und der ist erst bekannt, wenn die Eröffnung vorbei ist.**
Um zum offiziellen Open zu kaufen, müsste die Order VOR der Auktion liegen; dann kennt man die
Lücke aber noch nicht. Der Backtest kauft also zu einem Preis, den ein Marktteilnehmer in dem
Moment, in dem er das Signal sieht, nicht mehr bekommt.

Das ist kein Detail: Eine Lücke schließt sich am schnellsten in den ersten Minuten. Wie viel des
Effekts nach fünf, fünfzehn oder dreißig Minuten noch übrig ist, entscheidet über die ganze
Idee — und es ist messbar, denn für die Session-Lane liegen Alpaca-Minutenbars bereits vor.

**Vorbedingung für eine Lane:** derselbe Test noch einmal, mit Einstieg zum ersten Kurs nach
+5/+15/+30 Minuten statt zum Eröffnungskurs. Bleibt nach 15 Minuten mehr als die Kosten übrig,
ist die Lane gerechtfertigt. Bleibt nichts, war der Effekt nie unserer.

## Was außerdem im Auge zu behalten ist

**Survivorship.** Titel, die mit −5 % eröffnen und danach verschwinden, fehlen in der
Stichprobe — die verzerrt genau die auffälligste Klasse nach oben. Beruhigend ist, dass der
Effekt auch bei milden Lücken (−1 bis −3 %, n = 32.537) klar da ist, wo diese Verzerrung
deutlich schwächer wirkt. Die Richtung ist damit belastbarer als die Größe.
