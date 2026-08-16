# Volumen-Kapitulation: geprüft, nicht gebaut (2026-08-16)

Dritter Kandidat aus `plans/2026-08-16-short-term-lane-expansion.md`. Regel: kaufen nach einem
Tag mit außergewöhnlichem Volumen und deutlichem Kursrückgang, Stop unter dem Panik-Tief.
Definition übernommen aus `volume_signals.read_volume` (Volumen gegen den eigenen
20-Tage-Median, Rückgang ≥ 3 %), nicht neu erfunden.

**Ergebnis: die Lane wird nicht gebaut.** Der Effekt verschwindet, sobald man ihn korrekt misst.

## Der Befund, der nach einem Treffer aussah

91 US-Titel, 2012–2026. Vorwärtsrendite nach einem Kapitulationstag gegen alle anderen Tage,
auf **überlappenden** Fenstern:

| Horizont | Kapitulation | sonst | Differenz | t |
|---|---|---|---|---|
| 5 T | +0,56 % | +0,33 % | +0,22 pp | 1,37 |
| 20 T | +2,51 % | +1,26 % | +1,25 pp | **3,73** |
| 60 T | +7,00 % | +3,60 % | +3,40 pp | **6,21** |

Ein t von 6,21 liest sich wie ein sicherer Fund. Er ist ein Artefakt der Messung.

## Derselbe Befund, korrekt gemessen

Ein 20-Tage-Vorwärtsfenster teilt 19 seiner 20 Tage mit dem Fenster vom Vortag. Solche
Beobachtungen sind nicht unabhängig, und jede Statistik darüber ist um etwa √h aufgebläht —
die Regel steht seit dem 11.08. in `LOOP.md`, das Werkzeug dazu ist
`behaviour_study.independent_subsample`. Auf **nicht überlappenden** Fenstern:

| Horizont | n Ereignisse | Kapitulation | sonst | Differenz | t |
|---|---|---|---|---|---|
| 20 T | 322 | +4,66 % | +1,26 % | +3,41 pp | **1,64** |
| 60 T | 154 | +5,17 % | +4,06 % | +1,11 pp | **0,34** |

Und die Probe auf die Willkür — dieselbe Rechnung mit anderem Startpunkt der Teilstichprobe:

| Offset | 0 | 4 | 8 | 12 | 16 | 20 |
|---|---|---|---|---|---|---|
| Differenz | +3,41 pp | +0,75 | +2,18 | +0,19 | +1,02 | +0,12 |
| t | 1,64 | 0,56 | 1,10 | 0,16 | 0,81 | 0,09 |

**Das Urteil hängt vollständig an einer beliebigen Wahl.** Es gibt keinen Startpunkt, bei dem
der Effekt signifikant wird, und die Spanne von t = 0,09 bis 1,64 zeigt, wie wenig Substanz
hinter dem 6,21 der ersten Rechnung steckt.

## Der zweite Grund, unabhängig vom ersten

Die Trefferquote nach Kapitulation ist **niedriger** als an gewöhnlichen Tagen (51,6 % gegen
53,2 % auf 20 Tage). Ein positiver Mittelwert bei schlechterer Trefferquote heißt: der Effekt
wird von wenigen großen Ausreißern getragen, nicht von der Breite. Dasselbe Muster wie bei den
Insider-Clustern — und dieselbe Konsequenz: eine Lane, die davon leben soll, braucht die
Ausreißer und bekommt sie nicht zuverlässig.

Die strengere Schwelle (3× statt 2× Normalvolumen) macht es nicht besser, sondern schlechter
(t = 2,58 statt 3,73 auf überlappenden Fenstern) — weniger Ereignisse, kein klareres Signal.

## Was bleibt

`src/equity_scout/st_capitulation.py` mit 7 Tests. Einer davon ist wichtiger als die Regel
selbst: `test_event_study_matches_read_volume_day_for_day` prüft die schnelle, vektorisierte
Definition Tag für Tag gegen die, die das Cockpit anzeigt. Zwei Definitionen desselben Begriffs
in einer Codebasis driften auseinander, und die in der Handelsregel ist die, auf die niemand
schaut.

**Methodisch festhalten:** Ohne die Korrektur für überlappende Fenster wäre hier eine Lane
gebaut worden, die auf einem vierfach überhöhten t-Wert beruht. Das ist der erste Fall in
diesem Projekt, in dem die Regel aus der Nacht vom 11.08. eine konkrete Fehlentscheidung
verhindert hat.
