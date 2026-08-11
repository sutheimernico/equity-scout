# Die ersten aufgelösten Entry-Vorhersagen (2026-08-11)

Der Selbst-Check aus dem v15-Wave-1-Plan, einen Tag vorgezogen: **löst der Predict-then-Resolve-Loop
tatsächlich auf, wenn die erste Kohorte fällig wird?** Er war der Grund, warum der Plan überhaupt
geschrieben wurde — am 05.08. standen 299 Vorhersagen im Ledger und 0 aufgelöste, und niemand konnte
sagen, ob das an der Wartezeit oder an einem Defekt lag.

## Ergebnis in drei Sätzen

1. **Der Loop funktioniert.** 30 von 30 fälligen Vorhersagen aufgelöst, 0 ohne volles
   Vorwärtsfenster. Der Verdacht „Resolve-Loop kaputt" ist damit entkräftet.
2. **Das Entry-Modell schlägt auf dieser Kohorte die Trivialstrategie nicht.** 67 % Treffer gegen
   eine Basisrate von 77 % — „immer ablehnen" wäre besser gewesen.
3. **Die Kohorte kann trotzdem nichts entscheiden.** Alle 30 Vorhersagen stammen aus **einem
   einzigen Tag** (2026-07-10) und derselben Marktphase; das sind keine 30 unabhängigen
   Beobachtungen, sondern eine.

## Wie der Check ausgeführt wurde

```
uv run python scripts/run_resolve_predictions.py
→ Aufgelöst: 30 von 30 fälligen Vorhersage(n) (0 ohne volles Vorwärtsfenster); noch offen: 449.
```

Der Lauf war **manuell und außerhalb der Kette** — und genau das erklärt, warum die Tageskette am
selben Tag noch 0 gemeldet hat: die Kohorte wurde am 10.07. um **18:52 UTC** erzeugt, ihr
`resolve_after` liegt also bei 18:52 UTC, und die Tageskette läuft um **16:13 UTC**. Sie lief 2,5
Stunden vor Fälligkeit. Kein Defekt, aber eine systematische Eigenschaft: eine abends erzeugte
Vorhersage wird von einer früher am Tag laufenden Kette erst am **Folgetag** aufgelöst. Bei einem
Horizont von 20 Handelstagen ist ein Tag Verzug ohne Belang — festgehalten, nicht behandelt.

## Die Zahlen

| Maß | Wert | Einordnung |
|---|---|---|
| Aufgelöst | 30 von 30 fälligen | 449 weiter offen (noch nicht fällig) |
| Ø Relativrendite vs. SPY | **−5,41 %** | Median −4,45 %, Spanne −39,2 % bis +17,5 % |
| Schlagen SPY | 7 von 30 = **23 %** | |
| Treffer des Modells (`correct`) | 20 von 30 = **67 %** | |
| Basisrate „immer ablehnen" | 23 von 30 = **77 %** | **Das Modell liegt darunter** |
| Spearman Score vs. Ergebnis | ρ = −0,159, p = 0,40 | nicht signifikant |
| Pearson Score vs. Ergebnis | r = −0,415, p = 0,023 | von zwei Ausreißern getragen, siehe unten |
| Ø Top-10 nach Score | −9,38 % | |
| Ø Bottom-10 nach Score | −4,05 % | |

Die fünf höchsten Scores waren die fünf schlechtesten Ergebnisse:

| Ticker | Score | Relativ zu SPY |
|---|---|---|
| WDC | 65 | −27,88 % |
| SNDK | 62 | −39,15 % |
| MU | 62 | −12,81 % |
| GEV | 61 | −11,70 % |
| VRT | 56 | −17,00 % |

## Warum das trotzdem kein Urteil ist

**Alle 30 Zeilen tragen dasselbe Datum.** Die scheinbaren 30 Beobachtungen sind eine Kohorte in
einem Zeitfenster, und ihre Titel sind untereinander stark korreliert — WDC, SNDK und MU sind
dieselbe Branche und derselbe Absturz. Ein p-Wert, der Unabhängigkeit voraussetzt, ist hier nicht
interpretierbar; die Pearson-Korrelation von −0,415 ist im Wesentlichen die Aussage „drei
Halbleitertitel standen oben in der Rangliste und fielen gemeinsam". Genau die Lehre aus W0
(2026-08-11): überlappende und korrelierte Beobachtungen als unabhängig zu behandeln bläht jede
Statistik auf.

Ebenso ist der niedrige Ø von −5,41 % kein Modellbefund allein — er enthält, dass die Auswahl
insgesamt in einer schwachen Phase für ihr Segment lag, während SPY stieg.

**Was die Kohorte belegt:** der Loop läuft, die Auflösung greift auf echte Vorwärtspreise zu, und
die Richtung des ersten Signals ist kein Grund zur Zuversicht.
**Was sie nicht belegt:** dass das Modell anti-prädiktiv ist. Dafür braucht es Kohorten aus
mehreren Marktphasen.

## Einordnung gegen das, was schon bekannt war

Die Zahl passt zum in-sample-Befund: **AUC 0,496** in der Kreuzvalidierung, unverändert mit 11 wie
mit 14 Merkmalen (v17c-Nullbefund zum Volumen). Beide Messungen zeigen in dieselbe Richtung — das
Problem sitzt nicht in den Merkmalen. Der offene Hebel bleibt **Zielvariable, Horizont und
Universum**, und der ist weiter ungetestet.

## Kein Automatismus handelt auf diesen 30 Zeilen

Vor dem Lauf geprüft, weil eine Auflösung nachgelagerte Schritte auslösen kann:

- `run_evidence_refresh.py` nutzt die Zahl der Auflösungen als **Trigger** für einen
  Retrain-Versuch (`new_resolutions >= min_new_resolutions`), nicht als Trainingsdaten. Der Trigger
  wird beim nächsten Kettenlauf feuern — das ist beabsichtigt: neue Marktinformation ist
  eingetroffen.
- Die **Promotionshürde** hängt an der OOS-AUC des Herausforderers gegen den Amtsinhaber
  (`MIN_AUC_DELTA`, mit `sqrt(n_candidates)` skaliert) und an `MIN_OOS_N` — nicht am Ledger. Das
  einseitige Gate greift weiter: ein anti-prädiktives Modell wird auch als erster Champion nie
  promoviert.
- `run_learning_snapshot.py` schreibt die Ledger-Kennzahlen in die Lernkurve — eine Anzeige, keine
  Entscheidung.

Ergebnis: kein Datenleck, keine Promotion auf 30 korrelierten Zeilen.

## Was als Nächstes messbar wird

Ab jetzt löst pro Tageslauf auf, was fällig geworden ist — die 449 offenen Zeilen verteilen sich
über mehrere Wochen und Marktphasen. **Die erste belastbare Aussage über das Entry-Modell entsteht
nicht durch einen weiteren Bau-Schritt, sondern durch mehrere Kohorten.** Bis dahin gilt für jede
Aussage über die Modellgüte der Vorbehalt aus dieser Doku.
