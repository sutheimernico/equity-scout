# Vision v17: Vier Trader

**Datum:** 2026-08-19
**Status:** Spec — von Nico in dieser Session diktiert, Umsetzung begonnen (Schritt 1 steht)

## Warum dieses Dokument existiert

Weil v15 genau hier gescheitert ist. Nicos Vision war am 2026-08-05 als Spec vorhanden, sein
Nachtrag vom 06.08. lautete wörtlich „catch the Trump/Intel-type event, **leveraged**" — und am
2026-08-19 hat er dasselbe erneut verlangt, weil es nie gebaut wurde. Dazwischen lag die
Markt-Matrix-Vision vom 17.08., ebenfalls dokumentiert, ebenfalls nicht handelnd.

Der Fehler war nicht fehlende Dokumentation, sondern dass niemand die Vision gegen den
Ist-Zustand geprüft hat. Dieses Dokument ist deshalb kein Konzeptpapier, sondern eine
**Prüfliste**: jeder Trader hat einen Zustand, ein Gate und einen Blocker.

## Nicos Ansage (wörtlich, 2026-08-19)

> „Du machst Matrix Trader als zusätzlichen Trader, also neben dem aktuellen Short Term und Long
> Term als 3. und ich will noch ein 4. ML was fortlaufend tradet was auf basis der Datengrundlage
> lernt und lernt zu traden"

> „das Machine Learning Modell soll natürlich auch alle Art Informationen bekommen, die die
> anderen haben und darauf Zugriff kriegen"

> „soll nachher auch 'n Dashboard fürs Handy eingebaut werden alles, was wir jetzt hier machen"

Und aus der Matrix-Vision vom 2026-08-17, weiterhin gültig:

> „Einen Autotrader, der nicht an einem Parameter oder einer Zeitscheibe tradet, sondern allen —
> und das jeweils basierend auf gelerntem Wissen, was nachweislich erfolgreich war, und dann mit
> Risikoabschätzung entsprechende Hebel verwenden zum Einkaufen."

> „Es geht nicht darum, die Gewinnerzelle zu finden, sondern eine Auswahl an Gewinnerzellen."

## Die vier Trader

| # | Trader | Handelt nach | Zustand am 2026-08-19 |
|---|---|---|---|
| 1 | **Long-Term** | 11 regelbasierte ETF-Sleeves, gleichgewichtet | **LÄUFT.** 101.401 $ gegen SPY 102.510 $ — hinter dem Markt. Nie an einen Broker geroutet (`README.md:288`: „remains unrouted"), entgegen v15-P1. |
| 2 | **Short-Term** | Arena-Lanes: swing (Earnings), crypto (Donchian), gapfade (MOO/MOC), ignition (Katalysator-Sprünge) | **LÄUFT.** session pausiert seit 17.08. (ORB widerlegt). ignition seit heute live, 2 Positionen. |
| 3 | **Matrix** | die „Auswahl an Gewinnerzellen" über alle Parameter × Zeitscheiben, mit Risikoabschätzung | **NEU.** Messwerkzeug existiert, handelt nicht. Zwei Blocker, siehe unten. |
| 4 | **ML** | fortlaufend gelernte Funktion über **alle** Datenquellen des Systems | **HALB DA.** 207 Modellversionen trainiert (letzte 2026-08-19 00:31), `champion_history` **leer** — keine hat die Hürde genommen. |

Ausdrücklich: #3 ist **nicht** auf Kurzfrist beschränkt. Zeitscheibe ist eine Achse der Matrix,
kein Merkmal des Traders.

## Blocker, konkret

### #3 Matrix — Blocker A: die Teststatistik war falsch (BEHOBEN 2026-08-19)

`grid.pool_cells` rechnete `sum(t_i·√n_i)/√(sum n_i)` und behauptete im Docstring, das unterstelle
*keine* Unabhängigkeit der Ticker. Das Gegenteil ist wahr — die Formel IST die
Unabhängigkeitsannahme, und ~70 Ticker teilen Marktbewegungen.

**Gemessen an echten Minutenbars** (15 Mega-Caps, 2016–2022, Signal „Tagesverlust > 2 %",
Halten 3 Tage, 10 bp Kosten): altes t = **+3,04**, Bootstrap-t = **+1,63**, Aufblähung
**Faktor 1,9**; das 95-%-Intervall [−4,6; +73,1] bp schließt die Null ein. Ein „solider Befund"
war ein Grenzfall.

Fix: `matrix/bootstrap.py` — Kalenderblock-Bootstrap (Künsch 1989). Ganze Monate werden mit
Zurücklegen gezogen, wodurch Querschnitts- **und** Zeitabhängigkeit erhalten bleiben, statt
wegannahmiert zu werden. Dazu `grid.trade_returns_with_times`, weil der Bootstrap die
Zeitstempel braucht, die `trade_returns` verwirft. 13 Tests.

### #3 Matrix — Blocker B: die Leitung zum Handel (BEHOBEN 2026-08-19)

`find_plateaus` lieferte Plateaus, aber kein `Strategy`-Objekt las sie. Jetzt gebaut:

- [x] `matrix/registry.py`: Register mit vier geordneten Gates und vollem Herkunftsnachweis
      (Signal, Schwellen, Slices, Holds, Kosten, Bootstrap-Zahlen, Hold-out-Ergebnis). Auch
      Ablehnungen bleiben stehen — der Friedhof ist Evidenz.
- [x] `strategies/matrix_strategy.py`: handelt das Register und bewertet die Evidenz zur
      Handelszeit ausdrücklich NICHT neu (zweimal suchen ist der Fehler, der fünf Wochen kostete).
- [x] Positionsgröße aus der Bootstrap-Unsicherheit: t = 8 volles Gewicht, t = 2 ein Viertel.
      Bruttoexposure hart auf 1× — die Schutzkette setzt das voraus.
- [x] Short über die `side=`-Naht: ein Plateau mit konsistent negativen Folgereturns geht short.
      In `grid.cell_from_returns` korrekt gerechnet (`-gross - cost`, nicht `-(gross - cost)` —
      sonst würde jeder verlierende Long als gewinnender Short erscheinen).
- [x] `scripts/run_matrix_qualify.py`: die Kette Zelle → Plateau → Bootstrap → Robustheit →
      Hold-out, streamend über die 61 GB Checkpoints.
- [x] Als Sleeve registriert; `ready=False` solange nichts qualifiziert ist — verifiziert: das
      Depot listet weiter genau seine 11 ETF-Sleeves.
- [ ] Eigenes Buch + eigene Bewertungsreihe (offen — läuft bis dahin über die Sleeve-Mechanik).

### #3 Matrix — Blocker C: das Hold-out ist ein Einmalschuss (DISZIPLIN)

2023–2025 darf **einmal** geöffnet werden. Vorher nötig: Bootstrap auf allen Plateau-Kandidaten,
Entry-Robustheitsvariante `open[i+1]`, zustandsabhängige Kosten (Corwin-Schultz), und ein
Hold-out-Register (wer öffnet wann mit welcher Hypothese). Quelle:
`docs/research/2026-08-18-external-review-and-upgrade-plan.md`.

### #4 ML — Blocker: die Datengrundlage war zu dünn

Features der 207 Versionen: `mkt_vol, mkt_trend, mkt_breadth, mkt_drawdown, mkt_mom_3m, mom_1m,
mom_3m, mom_6m, dist_sma200, drawdown_1y, vol_3m` — ausschließlich Preis und Momentum. Keine
News, keine Events, keine Katalysatoren, keine Fundamentaldaten. Das Modell sollte Rendite aus
Chartform vorhersagen; der W0-Befund vom 11.08. sagt, dass das an unseren Daten nicht geht.

Nicos Vorgabe „alle Art Informationen, die die anderen haben" ist damit der eigentliche Hebel:

- [ ] Katalysator-Features: verifizierter Sprung, Volumenverhältnis, Spanne, News-Klasse,
      Katalysator-Alter, Termin-Vorlauf (alles ab heute in `catalysts.db`).
- [ ] Event-Features: Insider-Cluster, 8-K-Typen, Kongress-Käufe (`evidence_events`).
- [ ] Matrix-Features: in welcher Plateau-Region liegt der Titel gerade.
- [ ] Universum: 6241 handelbare Einzelaktien statt einer 30er-Watchlist (Tagesbars ab 2019
      werden gerade geholt, splitbereinigt).
- [ ] Fortlaufendes Lernen bleibt wie gebaut (nächtliches Retraining, Champion-Registry mit
      symmetrischer Demotion) — nur die Eingaben werden reicher.

## Gemeinsame Regeln für #3 und #4

1. **Paper, immer.** Kein Trader dieser Spec bekommt echtes Geld.
2. **Eigenes Buch und eigener Benchmark je Trader**, sonst ist kein Vergleich möglich.
3. **Promotion nur über die bestehenden Gates.** Der Weg ist gebaut und automatisch: ≥30
   realisierte Trades, ≥60 Kalendertage, Netto-P&L > 0, Profit-Faktor ≥ 1,1 → `resolve_promotions()`
   nimmt die Lane nachts selbst auf. Keine Abkürzung.
4. **Hebel ist eine gemessene Größe, kein Wunsch.** Verfügbar sind faktisch 4× innertags / 2×
   über Nacht (`multiplier = 4`); x100 existiert bei US-Aktien nicht. Der Optionsweg ist
   freigeschaltet (Level 3), aber die Kette trägt ihn nicht (bei MRNA ein Verfallstag, Strikes bis
   120 bei Kurs 143, keine Greeks). Positionsgröße folgt der Bootstrap-Streuung.
5. **Sichtbarkeit ist Teil der Aufgabe, nicht Zubehör.** Alle vier Trader gehören ins
   Handy-Dashboard — das schließt Nicos offenen Auftrag vom 16.08. ein („die App zu Ende bauen
   fürs Handy, das Dashboard"), dessen Scope noch mit ihm zu klären ist.

## Reihenfolge

1. ✅ Kalenderblock-Bootstrap (Blocker A) — 16 Tests, an echten Daten verifiziert (Faktor 1,9).
2. ⏳ Katalysator-Signale als Matrix-Achse — Code geliefert (`matrix/catalyst_axis.py`,
   neue Einträge in `signals.py`/`contexts.py`), Gate grün, **mein Review steht noch aus**.
3. ✅ Plateau → Register → Strategie → Sleeve (Blocker B) — die Leitung steht.
4. ✅ Hold-out-Register + Robustheits-Nachmessung gebaut (Blocker C). Das Öffnen selbst ist
   bewusst ein separater, manueller Aufruf: `--open-holdout --hypothesis "…"`, einmalig.
5. ⏳ ML-Featureblöcke aus Katalysator- und Ereignisdaten (#4) — Code geliefert
   (`ml/catalyst_features.py`), Gate grün, **Review und die Verdrahtung in `entry_dataset.py`
   stehen noch aus**. Ohne diese Verdrahtung trainiert das Modell weiter ohne die neuen Merkmale.
6. ✅ `/api/traders`: vier Trader in einer Ansicht, jeder mit Zustand und Blocker.

**Offen:** OHLCV-Panel für alle Strategien (heute nur die Matrix-Sleeve), eigenes Buch je
Trader, Frontend-Kachel für `/api/traders`, und der erste vollständige Qualifikationslauf über
die 61 GB Checkpoints (Stunden, eigener Lauf).

## Ehrliche Erwartung

Der Bootstrap kann Zellen entwerten, die nur durch das aufgeblähte t gut aussahen — bei der
Stichprobenmessung ist genau das passiert (t 3,04 → 1,63). Es ist ein reales Ergebnis, wenn nach
Schritt 4 nichts übrig bleibt. Dann ist die Antwort nicht „das Werkzeug ist kaputt", sondern
„dieser Signalraum trägt an unseren Daten keinen Handel" — und die Suche geht in einen anderen
Raum, nicht in eine schwächere Statistik.
