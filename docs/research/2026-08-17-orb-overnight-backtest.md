# ORB-Einstieg mit Overnight-Halten: rettet die Nacht die Session-Lane? (2026-08-17)

**Frage (aus Nicos Vision):** Der Short-Term-Trader soll auch 30 Minuten, Stunden oder
tagesübergreifend halten dürfen. Die Einstiegsregel der Session-Lane ist intraday widerlegt
(−8,94 bp nach 30 Min, t = −2,68, 1.684 Ausbrüche) — aber 93 % der Marktrendite entsteht über
Nacht (T4). Erbt ein ORB-Einstieg mit Overnight-Halten also den Drift und wird gut? Oder
sammelt er nur ein, was jeder bekommt?

**Antwort: Die Einstiegsregel ist in allen drei Halte-Varianten wertlos. Sie wird pausiert.**

## Aufbau

`scripts/research_orb_overnight.py` (persistiert — Lektion aus T8: Ad-hoc-Skripte fehlen
hinterher). 89 liquide US-Titel (explizite Liste im Skript), yfinance 15-Min-Bars über 60
Handelstage (freies Fenster) + Tagesdaten. Gleiche ORB-Definition wie `st_session.py`
(erste 2 Bars = Spanne, erster 15-Min-Close über dem Hoch, Fill am Open des Folgebars),
ein Signal pro Ticker/Tag. **Fairness-Benchmark:** dieselben Haltefenster, Einstieg 10:15
ohne jede Bedingung — der einzige Unterschied ist die ORB-Bedingung selbst.

## Ergebnis (brutto, 2.550 Signale über 60 Tage)

| Arm | Signale Ø | t | Benchmark Ø | Differenz | Welch-t |
|---|---|---|---|---|---|
| (a) Zwangsflat zum Close (heutige Lane) | −5,45 bp | −2,20 | −2,62 bp | −2,84 bp | −0,88 |
| (b) Halten bis zum nächsten Open | +0,25 bp | 0,05 | −3,38 bp | +3,63 bp | 0,62 |
| (c) Swing-Exits 5 %/3 %/7 T | +32,33 bp | 3,13 | **+52,66 bp** | **−20,33 bp** | −1,60 |

Trefferquoten der Signale: 48,0 % / 49,2 % / 48,7 % — in keinem Arm über der Münze.

## Die drei Lesarten, einzeln erledigt

1. **(a) repliziert die Widerlegung** von gestern unabhängig (anderes Skript, anderes
   Universum, gleiche Richtung): Der Intraday-Teil des Ausbruchs ist ein Verlust.
2. **(b) Overnight rettet nichts.** +0,25 bp brutto ist ökonomisch null (Netto bei
   10 bp/Seite: −19,75 bp), und der Vorsprung gegen bedingungsloses Halten (+3,63 bp)
   trägt t = 0,62. Der Drift gehört allen — der Ausbruch fügt ihm nichts hinzu.
3. **(c) sieht absolut gut aus und ist die eigentliche Falle.** +32 bp mit t = 3,13 wäre
   als Einzelzahl eine Lane. Aber der Einstieg um 10:15 OHNE Bedingung lieferte im selben
   Fenster +52,66 bp — der Absolutwert ist der Markt-Drift des Sommerfensters, nicht die
   Regel. Der gepaarte Tagesvergleich (gleicher Ticker, gleicher Tag, gleicher Exit)
   misst den Wert der Breakout-Bestätigung gegen ihren Preis: **Cluster-t = −11,4 über
   60 Tage** — man kauft nach dem Ausbruch systematisch teurer und verdient den Aufpreis
   nie zurück. (Die t = 3,13 der Signale ist zudem durch überlappende 7-Tage-Fenster
   aufgebläht — Überlappungsregel aus LOOP.md; für die Entscheidung irrelevant, weil der
   Arm schon am Benchmark scheitert.)

## Grenzen

- 60 Tage sind das freie Intraday-Fenster; das Regime (Aufwärtssommer) steckt in allen
  Absolutwerten. Die ENTSCHEIDUNG hängt aber an den Differenzen zum Benchmark, und die
  sind regime-neutral gepaart.
- Kosten als flache Sensitivität (10 bp/Seite = costs.py-Boden), nicht je Titel gerechnet.
  Kein Arm hängt an dieser Feinheit: (a)/(b) sind schon brutto tot, (c) am Benchmark.

## Konsequenz

Nach Iron Rule 2 des Plans (`2026-08-16-no-trade-book-and-learning-loop.md`): Die
Session-Lane wird **pausiert** (Cron-Zeile entfernt, Buch und Historie bleiben lesbar,
`st_session_sweep` bleibt als Sicherheitsnetz im Nightly). Nicos „tagesübergreifend
halten"-Idee ist damit nicht erledigt — sie ist beantwortet für DIESEN Einstieg: Nicht das
Halten war falsch, der Einstieg war es. Ein Einstieg, der etwas über die Nacht hinaus
wissen will, muss etwas anderes wissen als „der Kurs hat gerade ein 30-Minuten-Hoch
überschritten".
