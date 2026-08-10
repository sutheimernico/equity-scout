# W0 — Die Verhaltensindikatoren gegen die eigene Historie geprüft (2026-08-11)

Nicos Anweisung vom 2026-08-10: **jeder Verhaltensindikator wird gegen die Historie geprüft,
bevor er eingebaut wird.** Das ist hiermit passiert. Reproduzierbar über
`uv run python scripts/run_behaviour_study.py`, Rohzahlen in `data/behaviour_study.json`.

## Ergebnis in drei Sätzen

1. **Kein einziger Kandidat sagt die Marktrendite voraus** — 7 Signale × 3 Renditehorizonte über
   bis zu 19 Jahre, kein Treffer, in keiner Variante.
2. Was trägt, sagt ausschließlich **Risiko** voraus (Folgevolatilität und Drawdown) — und **jeder
   dieser Treffer stammt aus einem Signal, das die Ampel schon führt.**
3. **Der geplante nächste Schritt W1 (VIX-Terminstruktur) wäre umsonst gewesen:** roh sieht er
   stark aus, aber nach Abzug dessen, was VIX-Level und Marktbreite bereits sagen, bleibt nichts
   übrig (p = 0,027 gegen ein korrigiertes Niveau von 0,0006, Rank-IC fällt von 0,51 auf 0,08).

**Empfehlung: aus der Landkarte wird nichts gebaut.** Weder W1 noch W2–W6 in der bisherigen Form.
Die Begründung und was stattdessen sinnvoll ist, steht unten.

## Was geprüft wurde

| Signal | Historie | Quelle |
|---|---|---|
| VIX-Level | 2005-01 – 2026-08 (5435 Tage) | ^VIX (Kontrolle — sitzt schon in der Ampel) |
| VIX-Terminstruktur VIX/VIX3M | 2006-07 – 2026-08 (5033) | ^VIX, ^VIX3M — **der W1-Kandidat** |
| VIX kurz/mittel VIX9D/VIX | 2011-01 – 2026-08 (3908) | ^VIX9D, ^VIX |
| SPY-Volumenratio | 2007-01 – 2026-08 (4921) | Produktions-`read_volume` |
| SPY-OBV-Trend | 2007-01 – 2026-08 (4921) | Produktions-`read_volume` |
| Sleeve-Spike-Anteil (7 Anlageklassen) | 2007-01 – 2026-08 (4921) | Produktions-`read_volume` |
| Marktbreite % über 200d | 2007-10 – 2026-08 (4917) | 63 Titel des Bots-Panels (Kontrolle) |

Ziele: SPY-Forward-**Rendite** (5/21/63 Handelstage), Forward-**Volatilität** und
Forward-**Drawdown** (21/63). Risiko ist ein eigenständiges Ziel, weil der geplante Einbauort die
Exposure-Drosselung ist — ein Signal, das nur Risiko trifft, wäre dort trotzdem etwas wert.

Insgesamt 84 Tests (49 roh + 35 inkrementell), Bonferroni-korrigiertes Niveau **α = 0,0006**.

## Die Befunde

**Runde 1 — sagt das Signal überhaupt etwas voraus?** 6 von 49 Tests tragen:

| Signal | Ziel | Spread | p | Rank-IC | Startpunkt-robust |
|---|---|---|---|---|---|
| VIX-Level | Vola 21T | +11,70 % | <0,0001 | +0,65 | 100 % |
| VIX-Level | Drawdown 21T | −2,51 % | 0,0004 | −0,39 | 91 % |
| VIX-Terminstruktur | Vola 21T | +11,02 % | <0,0001 | +0,51 | 100 % |
| VIX-Terminstruktur | Drawdown 21T | −2,52 % | 0,0001 | −0,32 | 86 % |
| Marktbreite | Vola 21T | −11,50 % | <0,0001 | −0,48 | 100 % |
| Marktbreite | Drawdown 21T | +2,94 % | <0,0001 | +0,29 | 100 % |

**Alle sechs sind Risikovorhersagen. Bei den Renditen: null Treffer, über alle Signale und
Horizonte.**

**Runde 2 — bleibt nach Abzug der Ampel-Bestandssignale etwas übrig? Null von 35.**

| Kandidat | bestes Restergebnis | Rank-IC roh → inkrementell |
|---|---|---|
| VIX-Terminstruktur | Vola 21T, p = 0,027 | 0,51 → **0,08** |
| VIX9D/VIX | Vola 21T, p = 0,31 | — |
| SPY-Volumenratio | Vola 21T, p = 0,011 | 0,14 → 0,15 |
| SPY-OBV-Trend | Rendite 21T, p = 0,034 | −0,27 → −0,12 |
| Sleeve-Spike-Anteil | Vola 21T, p = 0,28 | — |

Kein Rest überlebt das korrigierte Niveau. Übersetzt: Diese Signale sagen dasselbe wie VIX-Level
und Marktbreite — nur schlechter.

## Zwei Befunde, die erst durch die Methodik sichtbar wurden

**Der OBV-Treffer war ein Artefakt.** Der OBV-Trend trug zunächst deutlich (Vola 21T: p = 0,0003,
Drawdown: p = 0,0005) — bis der Startpunkt-Test lief. Die Stichprobe nicht überlappender Fenster
kann an 22 gleichwertigen Stellen beginnen; der Befund hielt bei **9 % bzw. 5 %** davon. Er war
eine Eigenschaft der willkürlichen Wahl „fang bei Zeile 0 an", nicht des Marktes. VIX und
Marktbreite halten dagegen bei 86–100 %. Der Test steckt jetzt fest im Verdict, damit dieselbe
Falle nicht beim nächsten Kandidaten zuschnappt.

**Das Volumen-Panel war ohne Not elf Jahre zu kurz.** Es begann 2018-01, obwohl yfinance ab 2007
liefert — das drittelte die Aussagekraft jedes Volumentests (n = 31 statt 76 unabhängige Fenster
bei 63 Tagen). Neu gezogen ab 2007-01; die vorhandenen Zeilen kamen bit-identisch zurück, 2770
Zeilen sind dazugekommen. Erst dadurch war der OBV-Befund überhaupt sichtbar — und erst dadurch
auch widerlegbar.

## Grenzen — was dieser Test NICHT zeigt

**Der Nullbefund bei den Renditen ist keine Abwesenheit eines Effekts.** Der kleinste Unterschied,
den dieses Sample bei 80 % Testmacht noch von Zufall trennen könnte:

| Ziel | erkennbar ab (korrigiert) | (unkorrigiert) |
|---|---|---|
| Rendite 5T | 0,87 % | 0,57 % |
| Rendite 21T | **3,47 %** | 2,27 % |
| Rendite 63T | 9,91 % | 6,49 % |
| Vola 21T | 7,84 % | 5,14 % |
| Drawdown 21T | 2,78 % | 1,82 % |

Baker & Wurgler berichten für Hoch-Sentiment-Phasen **−0,9 % im Folgemonat**. Das liegt weit
unterhalb der 3,47 %, die hier auflösbar sind — **ein Effekt dieser Größe wäre in unseren Daten
grundsätzlich unsichtbar.** Um ihn zu messen, bräuchte es rund (3,47/0,9)² × 224 ≈ 3300
unabhängige Monatsfenster, also etwa **275 Jahre Historie**. Das ist mit täglichen Kursen nicht
zu heilen; es ist eine harte Grenze der Fragestellung, keine Schwäche der Umsetzung.

**Konsequenz, und sie ist die eigentliche Erkenntnis dieser Runde:** Die Rendite-Frage
(„sagt Stimmung die Marktrichtung voraus?") ist an unseren Daten **nicht entscheidbar**. Die
Risiko-Frage ist es — dort sind die Effekte groß genug (Spread 11,7 % gegen 7,84 % Auflösung).
Ein Verhaltenssignal kann sich hier also nur über die Risiko-Schiene rechtfertigen, nie über eine
behauptete Renditevorhersage. Wer die Renditeschiene trotzdem verfolgt, arbeitet an etwas, das
sich mit unseren Mitteln weder bestätigen noch widerlegen lässt.

**Weitere Einschränkungen, ehrlich benannt:**

- **Der VIX-Vola-Zusammenhang ist fast tautologisch.** VIX *ist* die implizite 30-Tage-Volatilität;
  dass er die realisierte 21-Tage-Volatilität vorhersagt, ist kaum eine Entdeckung. Der ehrlichere
  Teil des Befunds ist die Marktbreite, die keine Volatilitätsgröße ist und trotzdem trägt.
- **Volatilität ist ein leichtes Ziel.** Sie clustert stark, deshalb ist sie viel besser
  vorhersagbar als Renditen — ein Treffer dort wiegt deutlich weniger, als die p-Werte suggerieren.
- **Die Marktbreite ist survivorship-verzerrt.** Das Panel enthält die heute verfolgten Titel;
  delistete Namen fehlen, das Niveau ist nach oben verzerrt. Die Rangfolge über die Zeit — das
  Einzige, was der Test nutzt — ist davon weniger betroffen, aber nicht unberührt.
- Getestet wurde gegen **SPY**. Ein Signal, das für Einzeltitel oder das eigene Universum trägt,
  aber nicht für den Index, wäre hier nicht sichtbar.

## Was das für die Baker-Wurgler-Asymmetrie heißt

Die Landkarte leitete ab: *„drosseln bei Überhitzung, nicht aufdrehen bei Pessimismus."* Die
Messung stützt das **nicht** — sie zeigt das Gegenteil der erwarteten Seite:

- Marktbreite → Vola: das **untere** Extrem wirkt (schwache Breite → +13,19 Prozentpunkte Vola,
  p < 0,0001), das obere nicht (p = 0,37).
- Marktbreite → Drawdown: unteres Extrem −3,30 % (p = 0,0013), oberes +0,15 % (p = 0,72).

Die wirksame Seite ist die **Panik**-Seite, nicht die Euphorie-Seite. Wichtige Einordnung: Baker
und Wurgler sprechen über *Renditen*, hier gemessen ist *Risiko* — in der Renditedimension war
nichts messbar (siehe oben). Die Aussage lautet also präzise: **Die Baker-Wurgler-Asymmetrie ließ
sich an unseren Daten nicht bestätigen; die Asymmetrie, die wir sehen, sitzt auf der anderen Seite
und in einer anderen Größe.** Ein einseitiges Gate nach dem Landkarten-Muster hätte auf einer
Annahme aufgesetzt, die unsere Historie nicht trägt.

## Konsequenzen für den Wochenplan

- **W1 VIX-Terminstruktur — gestrichen.** Sie trägt nichts über den VIX-Level hinaus, der bereits
  in der Ampel steht. Eine zweite Datenquelle für dieselbe Aussage ist reine Wartungslast.
- **W2 Marktbreite ausbauen — herabgestuft.** Die Breite ist der *beste* Nicht-Volatilitäts-
  Prädiktor im Test und sie ist bereits verbaut. A/D-Linie und Neue-Hochs-minus-Tiefs sind
  Varianten derselben Beobachtung; bevor daran gebaut wird, müssten sie inkrementell gegen die
  vorhandene Breite antreten — dieselbe Runde 2 wie hier.
- **W3 Sentiment-Gate — Grundlage entfallen.** Es sollte einseitig nach Baker-Wurgler wirken; die
  Asymmetrie ließ sich nicht bestätigen. Falls ein Gate kommt, dann auf der gemessenen Seite
  (Panik/schwache Breite) und mit Risiko-, nicht mit Renditebegründung.
- **W4 Put/Call, W5 Short Interest, W6 AAII — Reihenfolge kippt.** Diese drei sind die einzigen
  Kandidaten, die eine **wirklich unabhängige Beobachtung** mitbringen (Optionsmarkt,
  Leerverkaufspositionen, Umfrage) statt einer weiteren Transformation von Kurs und Volatilität.
  Genau deshalb sind sie die einzigen, die überhaupt eine Chance haben, Runde 2 zu bestehen.
  Sie bleiben aber demselben Gate unterworfen — und W6 (AAII, wöchentlich) hat bei ~1000
  Wochenwerten ein n-Problem, das vor dem Abruf zu klären ist.

**Das Gate hat gehalten und sich bezahlt gemacht:** W1 stand als nächster Schritt fest, sah in der
Literatur und im Erreichbarkeitstest gut aus — und wäre eine Datenquelle, ein Ampelfeld und eine
laufende Wartung für null Informationsgewinn gewesen.

## Werkzeug

`src/equity_scout/behaviour_study.py` (26 Tests). Die vier Entscheidungen, die die Ergebnisse
tragen: Forward-Fenster ab **t+1** (nicht t), **nicht überlappende** Stichprobe als einzige
Grundlage für Signifikanz, **Startpunkt-Sweep** gegen Artefakte, **Residualisierung** gegen die
Bestandssignale als Bau-Entscheidungskriterium. Jede davon hat in diesem Lauf mindestens ein
Ergebnis gekippt, das ohne sie als Treffer durchgegangen wäre.
