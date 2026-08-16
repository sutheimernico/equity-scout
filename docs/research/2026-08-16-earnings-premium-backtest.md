# Earnings-Premium: geprüft, keine Lane — und die Grenze der Frage benannt (2026-08-16)

Sechster Kandidat aus `plans/2026-08-16-short-term-lane-expansion.md`: vor dem Berichtstermin
kaufen statt danach — das Gegenstück zur bestehenden Swing-Lane. 80 US-Titel, 1.790 Termine
2012–2026 (Termine über yfinance, ~21 Quartale je Titel).

**Ergebnis: keine Lane.** Alle drei Varianten liefern nichts — und der Test kann einen Effekt
in der Größe, die die Literatur nennt, gar nicht auflösen. Beides gehört zum Befund.

## Die Messung

Vergleichsmaßstab ist jeweils ein gleich langes Fenster irgendwo sonst im selben Titel.

| Variante | n | Ereignis | Basis | Differenz | t |
|---|---|---|---|---|---|
| vor der Meldung (T−5 → T−1) | 1.790 | +0,23 % | +0,31 % | −0,08 pp | −0,52 |
| durch die Meldung (T−5 → T+1) | 1.789 | +0,55 % | +0,42 % | +0,13 pp | 0,47 |
| nur die Reaktion (T−1 → T+1) | 1.789 | +0,28 % | +0,15 % | +0,14 pp | 0,59 |

Kein Vorzeichen ist belastbar, und die Variante, die Nicos Idee am nächsten kommt — vor dem
Termin rein, vor der Meldung raus — ist die einzige mit negativem Vorzeichen.

## Was der Test NICHT beantworten kann

Die Streuung je Ereignis beträgt 11,78 %. Bei 1.789 Ereignissen ergibt das einen Standardfehler
von 0,278 pp — **ein Effekt müsste über 0,56 pp liegen, um überhaupt sichtbar zu werden.**

Das ist die eigentliche Grenze: Savor/Wilson beziffern das Announcement-Premium auf eine
Größenordnung von 0,2–0,3 % pro Ankündigungszeitraum. **Das liegt unter unserer
Nachweisgrenze.** Um 0,10 pp aufzulösen, bräuchte man rund 55.000 Ereignisse — bei vier
Terminen pro Titel und Jahr wären das 700 Titel über zwanzig Jahre.

Der ehrliche Satz lautet deshalb nicht „es gibt kein Earnings-Premium", sondern: **wenn es
eines gibt, ist es kleiner als das, was wir mit unseren Daten unterscheiden können — und damit
auch kleiner als das, was eine Lane über Monate hinweg zeigen könnte.** Eine Lane zu bauen,
deren Zielgröße unter der Auflösung des Messgeräts liegt, produziert Beschäftigung, keine
Antwort. Dasselbe Argument, das die W0-Runde am 11.08. schon für die Verhaltenssignale
gezogen hat.

## Datengrenze, die zu nennen ist

Die Termine stammen aus yfinance und reichen etwa sechs Jahre zurück; neun der 91 Titel liefern
gar keine (delistete Ticker). Die Termine sind zudem der HEUTE bekannte Stand — nachträgliche
Korrekturen an Terminangaben sind darin nicht sichtbar. Für die Frage „ist der Effekt groß
genug, um ihn zu handeln" spielt das keine Rolle, weil die Antwort schon an der Streuung
scheitert.
