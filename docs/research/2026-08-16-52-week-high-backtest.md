# 52-Wochen-Hoch: geprüft, nicht gebaut (2026-08-16)

Zweiter Kandidat aus `plans/2026-08-16-short-term-lane-expansion.md`. Regel: kaufen an dem Tag,
an dem ein Titel über dem höchsten Schluss der letzten 252 Sitzungen schließt; Ausstieg über
Trailing-Stop oder Haltefrist.

**Ergebnis: die Lane wird nicht gebaut.** Der Ausbruchstag ist in unseren Daten der schlechteste
Einstiegszeitpunkt der oberen Kursregionen — nicht der beste.

## Stichprobe

91 US-Titel aus `universe_combined.csv` (Zufallsstichprobe, fester Seed 11), 2012-01-03 bis
2026-08-14, 3.675 Handelstage, 300.279 auswertbare Vorwärtsfenster.

## Vorwärtsrendite nach 20 Handelstagen, nach Abstand zum eigenen 52-Wochen-Hoch

| Zustand am Signaltag | n | Ø 20T | Standardfehler | Trefferquote |
|---|---|---|---|---|
| **Ausbruch (> 100 %)** | 13.647 | **+0,54 %** | ±0,09 | 52,6 % |
| nah dran (95–100 %) | 65.283 | +0,72 % | ±0,03 | 56,0 % |
| mittel (80–95 %) | 107.747 | +0,94 % | ±0,03 | 54,0 % |
| weit weg (< 80 %) | 113.602 | +1,97 % | ±0,07 | 51,1 % |

Über alle drei geprüften Horizonte dasselbe Bild — 5 Tage: +0,12 % nach Ausbruch gegen +0,34 %
sonst; 20 Tage: +0,54 % gegen +1,30 %; 60 Tage: +2,29 % gegen +3,72 %.

## Was davon belastbar ist — und was nicht

**Belastbar: Ausbruch schlägt „nah dran" nicht.** Beide Gruppen bestehen aus denselben
überlebenden Titeln in einem gesunden Kurszustand, der Vergleich ist also fair. Der Ausbruchstag
liefert weniger Rendite (+0,54 % gegen +0,72 %) UND die schlechteste Trefferquote der oberen
Gruppen (52,6 % gegen 56,0 %). Für eine Lane, die genau an diesem Tag kauft, ist das das
Gegenteil einer Grundlage.

**Nicht belastbar: die starke Zahl bei „weit weg".** +1,97 % sieht nach dem besten Signal des
ganzen Panels aus und ist ein Artefakt: Die Stichprobe besteht aus **heutigen**
Universum-Mitgliedern. Ein Titel, der 30 % unter seinem Hoch stand und danach verschwand, ist
nicht in den Daten. Genau diese Gruppe trifft der Survivorship-Bias am härtesten — wir sehen
dort nur die Erholer. Die Zahl ist eine Obergrenze ohne bekannten Abstand zur Wahrheit und
taugt für keine Entscheidung.

## Verhältnis zur Literatur

George/Hwang zeigen, dass die **Nähe** zum 52-Wochen-Hoch die Folgemonate prognostiziert. Das
ist nicht dieselbe Aussage wie „der Ausbruchstag ist ein guter Kauf" — und unsere Daten trennen
genau das: Die Nähe-Gruppe ist tatsächlich die mit der höchsten Trefferquote (56,0 %), der
Ausbruch selbst fällt dahinter zurück. Wer die Idee weiterverfolgen will, müsste sie als
**Rangfolge-Merkmal** testen (wie nah ist ein Titel an seinem Hoch), nicht als Auslöser — und
dafür gibt es die Kennzahl im Scout bereits, seit v8.

## Was bleibt

`src/equity_scout/st_highbreak.py` mit 7 Tests: Ausbruchserkennung, Trailing-Stop und eine
leckfreie Event-Study. Ein Test pinnt den Fehler, der diese Sorte Backtest sonst verdirbt — das
Signalfenster darf den Signaltag nicht enthalten, sonst ist jeder Tag sein eigenes Maximum und
die Regel feuert ständig.
