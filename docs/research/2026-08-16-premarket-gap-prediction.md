# Sagt der vorbörsliche Kurs die Lücke vorher? (T9, 2026-08-16)

Die Vorbedingung für einen handelbaren Gap-Fade: Um zum Eröffnungskurs zu kaufen, muss die
Order vor der Auktion liegen — also auf Basis des vorbörslichen Kurses statt der fertigen
Lücke. Frage: Wie gut geht das?

3.558 Handelstage mit vorbörslichen Kursen, 69 Titel, 16.06.–14.08.2026. Als vorbörslicher
Kurs gilt der letzte Bar **vor 09:25 ET** — Market-on-Open-Orders müssen vor etwa 09:28 liegen.

## Die Vorhersage funktioniert

| | |
|---|---|
| Korrelation vorbörsliche ↔ echte Lücke | **0,882** |
| Vorzeichen stimmt | 68,0 % aller Tage |
| Vorbörslich ≤ −2 % → echte Lücke auch ≤ −2 % | 61 % |
| Vorbörslich ≤ −3 % → echte Lücke auch ≤ −3 % | 53 % |

Der vorbörsliche Kurs ist also ein brauchbarer, aber unscharfer Schätzer: Die Richtung stimmt
fast immer, die Größe rutscht in gut einem Drittel der Fälle über die Schwelle.

## Was die handelbare Auswahl bringt

Entscheidend ist nicht die Korrelation, sondern was mit den Titeln passiert, die man auf dieser
Grundlage tatsächlich gekauft hätte:

| Auswahl | n | Rendite Eröffnung → Schluss | t | Trefferquote |
|---|---|---|---|---|
| vorbörslich ≤ −2 % (handelbar) | 283 | +42,00 bp | 1,00 | 46,3 % |
| vorbörslich ≤ −3 % (handelbar) | 159 | +52,53 bp | 0,78 | 46,5 % |
| *zum Vergleich: echte Lücke ≤ −2 %, rückschauend* | *283* | *+65,59 bp* | *1,64* | *50,2 % |

**Die vorbörsliche Auswahl behält etwa zwei Drittel des Effekts** (42 von 66 bp). Das ist mehr,
als nach dem Zerfallsbefund aus T8 zu erwarten war — dort war der Effekt 15 Minuten nach
Eröffnung vollständig weg, hier bleibt er erhalten, weil die Order vor der Auktion liegt und
den Eröffnungskurs bekommt.

## Warum das trotzdem keine Entscheidung von mir ist

**1. Nichts davon ist in dieser Stichprobe signifikant.** t = 1,00 bei 283 Ereignissen aus
42 Handelstagen. Zur Einordnung: Die rückschauende Auswahl erreicht in derselben Periode auch
nur t = 1,64, während sie über 14 Jahre t = 15,69 zeigt. Die Stichprobe ist zu kurz für ein
Urteil — und **länger geht nicht**, weil vorbörsliche Kurse frei nur 60 Tage zurückreichen.

**2. Die Trefferquote liegt unter 50 %** (46,3 %). Der positive Mittelwert wird wieder von
wenigen großen Bewegungen getragen, nicht von der Breite.

**3. Die Ausführungskosten sind unbekannt.** Unsere gemessene Slippage (Median +0,40 bp aus 67
Fills) stammt aus dem laufenden Handel. Eine Market-on-Open-Order ist eine Order **ohne
Preisgrenze in die volatilste Auktion des Tages**, bei Titeln, die gerade 2–3 % im Minus
eröffnen. Bleiben davon 20 bp hängen, ist die Hälfte des Effekts weg.

## Die Vorlage für die Entscheidung

Der Effekt selbst ist über 14 Jahre belegt (T7, t = 15,69). Die Umsetzbarkeit lässt sich nur
über 42 Tage prüfen, und dort reicht es für kein Urteil. Damit steht die Frage so:

- **Für eine Lane:** Genau diese Unentscheidbarkeit ist der Fall, in dem ein Papierbuch das
  richtige Werkzeug ist — es misst weiter, wo der Backtest an der Datengrenze endet, und
  liefert nebenbei die echten Auktionskosten, die niemand schätzen kann.
- **Gegen eine Lane:** Trefferquote unter 50 %, unbekannte Auktionskosten, und die Lane wäre
  der nächste Nachbar der Session-Lane, die selbst noch 161 Trades von einem Urteil entfernt
  ist.
