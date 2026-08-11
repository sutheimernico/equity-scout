# Das feste Trainingsuniversum — und der endgültige Nullbefund (2026-08-11)

Der Vorbefund desselben Tages
(`2026-08-11-champion-was-a-measurement-artifact.md`) endete mit einer Empfehlung: wer Achse 2
weitertreiben will, muss beim **Universum** anfangen, nicht bei der Zielgröße. Das ist hiermit
passiert — und es beantwortet die Frage endgültig.

## Ergebnis in drei Sätzen

1. **Das Trainingsuniversum ist jetzt fest und ex ante**: 503 US-Titel aus einem datierten
   Index-Snapshot statt der täglich wechselnden Watchlist. Die Trainingsmenge wächst von **3.931
   auf 68.085 Zeilen**, die OOS-Menge von 2.431 auf **54.735**.
2. **Der Vorteil verschwindet mit der Stichprobe, statt sich zu bestätigen.** AUC **0,5069**
   (random_forest) und **0,5041** (elastic_net) — niedriger als die 0,5348, die dasselbe Verfahren
   auf dem 22-mal kleineren Watchlist-Sample zeigte.
3. **Der Rank-IC fällt von 0,05–0,07 auf 0,0142.** Damit ist auch die letzte Hoffnung des
   Vorbefunds widerlegt: es gab keine „schwache monotone Beziehung, wo die binäre Trennkraft
   fehlt" — das war dieselbe Kleinstichproben-Illusion.

**Die Preis-Features dieses Modells sagen die 20-Tage-Relativrendite nicht vorher.** Das ist jetzt
mit 54.735 Beobachtungen belegt statt mit 220 bestritten.

## Was gebaut wurde

`ml/entry_universe.py` — eine reine Funktion und zwei angenagelte Konstanten:

- `TRAINING_UNIVERSE_AS_OF = "2026-07-02"`: der kuratierte Index-Snapshot (S&P 500 + STOXX 600 +
  Nikkei 225 + kuratierte globale Liste). **Fest verankert**, weil ein „neuester Snapshot"-Zugriff
  genau die Drift zurückholen würde, die hier verschwindet. Die späteren Snapshots (6592/7499
  Titel) sind das „screen everything"-Universum, dessen Schwanz aus illiquiden Titeln ohne
  brauchbare Historie besteht.
- `TRAINING_REGION = "US"`: Der Benchmark ist SPY und die Markt-Kontext-Features (Breite,
  VIX-Regime, Drawdown) sind US-abgeleitet — ein Tokioter Titel würde gegen einen Markt bewertet,
  an dem er nicht handelt. Das deckt sich mit dem v15-P3-Befund, dass nicht-US-Titel eine
  Regime-Lücke kodieren statt eines Signals.
- Die Liste ist **alphabetisch sortiert und dedupliziert**, damit sie zwischen zwei Nächten
  byte-identisch ist. Das ist der ganze Zweck des Moduls, und ein Test pinnt es.

`_resolve_tickers` nimmt jetzt dieses Universum; die Watchlist bleibt **Fallback** für eine
Datenbank ohne Snapshot — mit gedruckter Warnung, weil ein stilles Zurückfallen auf das driftende
Universum genau der Fehler wäre, der hier behoben wird.

Zusätzlich stempelt jede Registry-Zeile jetzt `metrics["universe"]` (`n_tickers`, `n_scored`).
**Das Fehlen dieser Information ist der Grund, warum der Champion-Defekt fünf Wochen unsichtbar
blieb**: die Zeile hielt `n_train` fest, aber nicht die Identität der Stichprobe — zwei AUCs aus
verschiedenen Universen sahen dadurch vergleichbar aus.

## Die Messungen

| | Watchlist (vorher) | Festes Universum |
|---|---|---|
| Titel angefragt | 30 | 503 |
| Titel nach Historien-Filter | 19 | **445** |
| Panel-Download | — | **94 s** |
| Trainingszeilen | 3.931 | **68.085** |
| OOS-Zeilen | 2.431 | **54.735** |
| AUC random_forest | 0,5348 | **0,5069** |
| AUC elastic_net | 0,5172 | **0,5041** |
| Rank-IC | 0,05–0,07 | **0,0142** |
| Amtsinhaber v1, hier gemessen | 0,5152 | **0,5140** |

Bei n = 54.735 liegt der Standardfehler der AUC bei ~0,002. Die 0,5069 sind damit **statistisch von
0,5 unterscheidbar und wirtschaftlich bedeutungslos** — und weit unter der Grundqualitätsschwelle
von 0,55, die das Projekt selbst setzt.

### Der schärfste Einzelbeleg: catboost

Alle vier Presets der `entry`-Familie auf dem festen Universum:

| Preset | AUC (54.735 Zeilen) | Rank-IC | AUC vorher (2.431 Zeilen) |
|---|---|---|---|
| random_forest | 0,5069 | +0,0142 | 0,5348 |
| ensemble | 0,5049 | +0,0116 | 0,5315 |
| elastic_net | 0,5041 | +0,0102 | 0,5172 |
| **catboost** | **0,4977** | **−0,0049** | **0,5433** |

**catboost war auf der Watchlist der beste Herausforderer** — das Modell, das dem Champion mit
0,5433 am nächsten kam und dem der Vorbefund zugutehielt, es sei „messbar besser" als der
Amtsinhaber. Auf 22× mehr Zeilen liegt es **unter** dem Münzwurf und sein Rank-IC ist negativ.
Deutlicher lässt sich nicht zeigen, dass die Rangfolge der Presets auf dem kleinen Sample Rauschen
war und keine Modellqualität.

Der Panel-Download kostet 94 Sekunden für 504 Ticker; 58 Titel fallen am Historien-Filter
(30-%-Spannenregel), darunter jüngere Index-Mitglieder wie `UBER`, `TTD`, `VST`, `ZTS`.

### Alle drei Familien, alle vier Modellklassen

Der volle nächtliche Trainingsdurchlauf auf dem festen Universum, jede Zeile auf 54.735 OOS-Zeilen:

| Familie | Preset | AUC | Rank-IC |
|---|---|---|---|
| entry | random_forest | 0,5069 | +0,0142 |
| entry | ensemble | 0,5049 | +0,0116 |
| entry | elastic_net | 0,5041 | +0,0102 |
| entry | catboost | 0,4977 | −0,0049 |
| entry_short | catboost | 0,5006 | −0,0003 |
| entry_short | random_forest | 0,4895 | −0,0252 |
| entry_short | ensemble | 0,4882 | −0,0286 |
| entry_short | elastic_net | 0,4873 | −0,0304 |
| entry_tb | random_forest | 0,4916 | −0,0479 |
| entry_tb | catboost | 0,4784 | −0,0461 |
| entry_tb | elastic_net | 0,4755 | −0,0220 |

**Spanne 0,4755 bis 0,5069. Null von elf erreichen die Promotionsschwelle von 0,55, und acht von
elf haben einen negativen Rank-IC.** Die beiden kürzeren bzw. barrierenbasierten Zielgrößen
(`entry_short` mit 10 Tagen, `entry_tb` mit vol-skalierten Barrieren) schneiden dabei **schlechter**
ab als die 20-Tage-Relativrendite — auch das war auf den kleinen Samples nicht zu sehen.

## Was das für das Projekt bedeutet

**Achse 2 ist vollständig abgearbeitet und negativ.** Alle drei Teile:

- *Features* — drei Runden Nullbefund (Evidenz +0,003, Volumen −0,001, elf gegen vierzehn Spalten).
- *Zielgröße/Horizont* — drei Familien (`entry` 20 Tage, `entry_short` 10 Tage, `entry_tb`
  Triple-Barrier) liegen alle im Münzwurfbereich.
- *Universum* — hier gemessen: 22× mehr Daten machen den Vorteil kleiner, nicht größer.

Damit ist die ehrliche Aussage: **an freien Tagesschlusskursen und preisabgeleiteten Features ist
die Querschnitts-Relativrendite über 20 Handelstage mit diesem Setup nicht vorhersagbar.** Das ist
kein Misserfolg der Umsetzung, sondern ein Ergebnis — und es steht in einer Reihe mit dem
W0-Befund vom Vortag, dass an denselben Daten Renditeeffekte erst ab 3,47 %/Monat auflösbar sind,
während die Risikoschiene messbar ist.

## Ein Nebeneffekt, den diese Änderung selbst erzeugt

**Trainings- und Anwendungsdomäne fallen jetzt auseinander.** Der `MLLongStrategy`-Sleeve wird in
`run_autotrader.py` mit `long_universe = watch_tickers` gebaut — also mit der Watchlist, die global
ist und Titel wie `ITC.NS`, `9064.T` oder `PETR4.SA` enthält. Trainiert wird ab jetzt auf 445
US-Large-Caps.

Vorher war beides dieselbe (driftende) Liste; jetzt ist das Training stabil, aber das Modell wird
auf eine Domäne angewendet, die es nicht gesehen hat. Praktisch ist der Schaden null, solange kein
Modell einen Vorteil zeigt (AUC 0,507) — methodisch ist es trotzdem eine Lücke, und sie wird hier
benannt statt stillschweigend eingeführt.

**Nicht selbst entschieden**, weil beide Auswege das Handelsverhalten des Depots ändern: entweder
der Bot handelt künftig das feste Universum (dann nicht mehr die Titel, die Nico im Cockpit sieht),
oder nur die Schnittmenge aus Watchlist und Trainingsuniversum. Das ist dieselbe Klasse von
Entscheidung wie die offene Entthronungsfrage — und sie erledigt sich von selbst, falls entthront
wird: ohne Champion handelt der Bot gar nicht.

## Ehrliche Grenzen dieses Befunds

- **Survivorship-Bias bleibt.** Der Snapshot hält die Index-Mitglieder seines Datums; Titel, die
  vorher aus dem Index fielen oder delisteten, fehlen. Freie yfinance-Daten können das nicht
  heilen — ein delisteter Ticker liefert keine Historie. Entscheidend ist, dass der verbleibende
  Bias **kein Rendite-Screen** ist und nicht mehr von Nacht zu Nacht variiert.
- **Der Befund gilt für dieses Zielmaß.** Er sagt nichts über längere Horizonte, über absolute
  statt relative Renditen oder über Fundamentaldaten, die hier nicht im Feature-Block sind.
- **445 Titel sind nicht der ganze Markt.** Das Universum ist US-Large-Cap; Small Caps und
  Nicht-US-Märkte sind bewusst ausgeschlossen, mit der oben genannten Begründung.
