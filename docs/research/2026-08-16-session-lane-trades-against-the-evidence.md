# Die Session-Lane kauft genau das, was zurückkommt (2026-08-16)

Folgerung aus dem Minutenskala-Befund, die ich selbst hätte ziehen müssen, statt sie mir von
Nico ansagen zu lassen: Wenn Fünf-Minuten-Bewegungen mit t = −32 zur Umkehr neigen, dann ist
eine Regel, die **Ausbrüche kauft**, strukturell auf der falschen Seite.

Direkt gemessen, nicht abgeleitet: 1.684 Ausbrüche über die Eröffnungsspanne — genau die Regel,
die die Session-Lane live handelt (`st_session.py`, erste 30 Minuten als Spanne).

## Das Ergebnis

| Nach dem Ausbruch nach OBEN kaufen (heutige Regel) | Ø | t | Trefferquote |
|---|---|---|---|
| nach 30 Minuten | **−8,94 bp** | **−2,68** | 45,8 % |
| nach 60 Minuten | −4,02 bp | −0,44 | 45,0 % |
| bis Handelsschluss | +0,56 bp | 0,08 | 46,4 % |

Der Einstieg ist in der halben Stunde danach im Mittel ein **Verlust**, signifikant, mit einer
Trefferquote von 45,8 %. Die Lane kauft messbar den ungünstigsten Moment.

## Die Umkehrung ist keine Lösung

| Nach dem Ausbruch nach UNTEN kaufen (long-only möglich) | Ø | t | Trefferquote |
|---|---|---|---|
| nach 30 Minuten | −2,23 bp | −0,75 | 50,5 % |
| nach 60 Minuten | +3,55 bp | 1,00 | 51,2 % |
| bis Handelsschluss | +6,77 bp | 1,06 | 49,5 % |

Nicht mehr negativ, aber auch nicht belegbar positiv — und +6,77 bp werden von einem Roundtrip
von 10 bis 20 bp aufgezehrt. Die naheliegende „dann eben andersherum"-Lösung trägt nicht.

## Was das für die laufende Lane heißt

Drei strukturelle Gegenwinde, alle heute gemessen:

1. **Sie handelt tagsüber**, und tagsüber gibt es keinen messbaren Drift (T4: 93 % der Rendite
   entsteht über Nacht, die Handelszeit trägt t = 0,87 bei).
2. **Sie kauft Ausbrüche**, die in der folgenden halben Stunde im Mittel zurückkommen (dieser
   Test, t = −2,68).
3. **Sie greift mit Market-Orders zu** und zahlt damit genau den Aufschlag, der den
   Minuten-Reversal ökonomisch erklärt.

Die Lane steht bei −2,6 %. Ihre eigene Messreihe verlangt noch 161 Trades bis zu einem Urteil —
aber dieser Test hat **1.684 unabhängige Ausbrüche** ausgewertet, also die 26-fache Stichprobe.
Die Frage „ist ihre Einstiegsregel gut" ist damit außerhalb ihres eigenen Buches beantwortet,
und die Antwort ist nein.

**Nicht getan:** die Lane abgeschaltet. Nico hat bei der Krypto-Lane entschieden, eine
widerlegte Lane weiterlaufen zu lassen; dieselbe Entscheidung gehört auch hier ihm und nicht
dem Plan. Der Befund gehört aber in die nächtliche Auswertung, damit er nicht in einer
Forschungsdatei verstaubt.
