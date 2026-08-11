# Der Champion war ein Messartefakt (2026-08-11)

Nicos Auftrag war Achse 2 der Richtungsentscheidung: **Zielgröße, Horizont und Universum des
Entry-Modells** — der letzte ungetestete Hebel, nachdem drei Feature-Runden hintereinander
Nullbefunde waren. Beim Lesen des Universums fiel etwas auf, das den Hebel erübrigt.

## Ergebnis in drei Sätzen

1. **Der live scorende `entry`-Champion hat keinen nachweisbaren Vorteil.** Er behauptet AUC
   0,6195 aus **220** Out-of-Sample-Zeilen; auf dem heutigen Sample mit **3281** Zeilen liefert er
   **0,5152** und einen Rank-IC von **0,0035** statt 0,1523.
2. **Er hat fünf Wochen lang messbar bessere Herausforderer blockiert**, weil die Promotionsregel
   seine gespeicherte Zahl gegen frische Zahlen aus einem anderen, 15× größeren Sample verglich.
3. **Der Hebel „Zielgröße/Horizont" ist damit nicht der Engpass.** Kein einziges ehrlich gemessenes
   Modell erreicht je die Grundqualitätsschwelle des Projekts (AUC ≥ 0,55) — 29 Versuche, Median
   0,5162, Maximum 0,5433 ohne den Artefakt-Champion.

## Wie der Befund entstand

Das Trainingsuniversum ist **die aktuelle Watchlist** (`_resolve_tickers` → `load_latest_watchlist`).
Daraus folgt dreierlei, und der dritte Punkt ist der Defekt:

- Das Universum ist **endogen**: es ist das Ergebnis eines Screens auf HEUTIGE Daten, wird aber mit
  Historie ab 2007 trainiert. 2010 hätte niemand diese 30 Titel gehalten.
- Es ist **klein und lückenhaft**: von 30 Titeln überleben 19 den Historien-Filter, weil viele
  internationale Titel (`BBSE3.SA`, `INSW`, `LPG`, `SNDK`) das Panel zu stark beschneiden würden.
- Es **wechselt fast jede Nacht** — und damit wechselt die Stichprobe. `n_train` schwankt in der
  `entry`-Familie zwischen **80 und 4806**, von gestern auf heute von 4779 auf 3026.

Damit sind AUC-Werte aus verschiedenen Läufen **nicht vergleichbar**. Die Promotionsregel verglich
sie trotzdem, auf drei Dezimalen, mit einer Hürde von 0,01.

## Die Zahlen

Der Amtsinhaber gegen sein eigenes Versprechen, gemessen auf denselben Walk-Forward-Folds, auf
denen die heutigen Herausforderer gemessen wurden:

| | AUC | Rank-IC | n_oos |
|---|---|---|---|
| v1, **gespeicherte Behauptung** (05.07.) | 0,6195 | 0,1523 | 220 |
| v1, **heute neu gemessen** | **0,5152** | **0,0035** | **3281** |
| v124, Herausforderer gleicher Modellklasse | 0,5348 | — | 2431 |
| v126, bester Herausforderer heute (catboost) | 0,5433 | — | 2431 |

**Die Neubewertung bevorteilt v1**: es wurde auf 520 Zeilen gefittet, die teilweise in diesen 3281
Zeilen liegen, ein Teil der Messung ist also in-sample für ihn. Selbst mit diesem Vorteil verliert
er gegen die Herausforderer, die er blockierte.

### v1 ist ein Ausreißer, kein Ausnahmemodell

Über alle 29 je in der `entry`-Familie trainierten Modelle:

- Median AUC **0,5162**, Spannweite 0,4951–0,6195.
- **Genau ein** Modell erreicht ≥ 0,6195 — v1 selbst.
- v1s 95-%-Konfidenzintervall (Hanley-McNeil, n=220) ist **[0,546; 0,693]** und **überlappt** mit
  dem von v126 **[0,520; 0,566]**. Es war nie belegt, dass v1 besser ist.

Dazu kommt ein Selektionseffekt, für den die Regel nicht korrigiert: v1 war der Beste aus mehreren
gleichzeitig getesteten Presets im allerersten Lauf. Genau dagegen existiert `_min_auc_delta`s
√N-Skalierung — sie greift aber nur für Herausforderer, nie rückwirkend für den Erst-Champion.

## Der zweite, wichtigere Befund

Beim Testschreiben fiel auf, dass der Fix allein **nichts promoviert**: die Grundqualitätshürde
(`NO_EDGE_BAND = 0,05`) verlangt **AUC ≥ 0,55**, und die ehrlich gemessenen Werte liegen bei
0,50–0,54. Also:

> **Kein Modell dieser Familie hat auf einer belastbaren Stichprobe je die eigene Mindestschwelle
> des Projekts erreicht. Der Amtsinhaber erfüllt sie heute selbst nicht mehr — er würde als
> Neuling abgelehnt.**

Das ist die eigentliche Antwort auf Achse 2, und sie kam ohne eine einzige neue Zielvariable: das
Problem ist nicht, wie die Zielgröße definiert ist. An diesem Universum, mit diesen Features, gibt
es keinen Vorteil, der die eigene Schwelle erreicht. Der Rank-IC bleibt bei 0,05–0,07 leicht
positiv (eine schwache Rangfolge existiert), aber die binäre Trennkraft ist Münzwurf — konsistent
mit dem v17c-Nullbefund.

## Was gebaut wurde

Der Vergleich findet jetzt auf **einem** Sample statt:

- `entry_model.evaluate_fitted_model` bewertet ein bereits gefittetes Modell auf denselben
  Walk-Forward-Folds wie den Herausforderer. Wohlwollend gegenüber dem Amtsinhaber, per Test
  gepinnt, und ein fehlender Feature-Block ist ein `KeyError` statt einer stillen NaN-Spalte.
- `model_registry.promote_if_better(..., incumbent_metric=...)` nutzt diesen frischen Wert anstelle
  des gespeicherten. Ohne den Parameter bleibt das alte Verhalten — Aufrufer, die den Amtsinhaber
  nicht bewerten können (anderer Feature-Block, unladbares Artefakt), fallen bewusst auf die
  gespeicherte Zahl zurück, weil ein Vergleich gegen nichts auf keiner Evidenz promovieren würde.
- Der nächtliche Lauf **meldet** es, live verifiziert gegen eine DB-Kopie:

```
Amtsinhaber v1 auf DIESEM Sample: AUC 0,5152 (n_oos=3281) — gespeichert war 0,6195 (n_oos=220).
Der frische Wert ist die Vergleichsbasis.
  ⚠ Der Amtsinhaber liegt damit in der No-Edge-Bande (Promotion verlangt AUC ≥ 0,55) — er würde
  heute NICHT promoten und regiert auf einer Zahl, die sein eigenes Gate nicht mehr besteht.
```

Gate: 2000 Tests grün, ruff clean.

## Was bewusst NICHT gebaut wurde

**Die automatische Entthronung.** Sie wäre die logische Fortsetzung des bestehenden Prinzips („eine
leere Arena hat keinen Champion statt einen falschen"), aber sie hat eine Live-Folge: ohne
`entry`-Champion handelt der **ML-Long-Bot** nicht mehr, und der ist ein Depot-Sleeve mit 12,5 %
Gewicht. Das ist Nicos Entscheidung, nicht die des Loops. Bis dahin ist der Zustand jede Nacht im
Log sichtbar statt still.

## Konsequenz für die Richtungsfrage

Achse 2 ist beantwortet, bevor sie gebaut wurde — und zwar negativ für das aktuelle Setup. Wer sie
trotzdem angehen will, muss beim **Universum** anfangen, nicht bei der Zielgröße: ein festes,
ex-ante definiertes Trainingsuniversum (z. B. die S&P-500-Mitglieder eines Stichtags) statt der
heutigen Watchlist. Das behebt drei Dinge gleichzeitig — Selektions-Bias, Vergleichbarkeit zwischen
Nächten und Testmacht. Ohne das misst jede weitere Achse auf wechselndem Boden.
