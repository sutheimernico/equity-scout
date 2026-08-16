# Traden auf Minutenskala: der Effekt existiert, er ist nur kleiner als die Reibung (2026-08-16)

Nicos Einwand war berechtigt: Alle bisherigen Messungen liefen auf Tages- bis Wochenskala,
während er von Trades spricht, die fünf oder zehn Minuten offen sind — gern auch short und mit
Hebel. Also dieselbe Frage auf seiner Zeitskala. 248.461 Fünf-Minuten-Renditen, 69 US-Titel,
42 Handelstage, nur regulärer Handel.

## Es gibt Vorhersagbarkeit auf dieser Skala — und sie ist hochsignifikant

**Autokorrelation der Fünf-Minuten-Renditen: −0,0644 (t = −32,1).** Was gerade gestiegen ist,
fällt im nächsten Fenster leicht zurück und umgekehrt. Das ist keine Zufallszahl: Bei 248.000
Beobachtungen liegt der Standardfehler bei 0,0020.

Auf Tagesskala haben wir bisher nichts gefunden, was auch nur annähernd so klar war. Insofern
liegt Nico richtig: **Auf der kurzen Skala steckt tatsächlich Struktur.**

## Was davon übrig bleibt

Strategie: gegen die letzte Fünf-Minuten-Bewegung handeln, fünf Minuten halten.

| | Rohgewinn je Trade | nach 4 bp | nach 10 bp | nach 20 bp |
|---|---|---|---|---|
| alle Bewegungen | +1,69 bp | −2,31 | −8,31 | −18,31 |
| stärkstes Fünftel | +5,86 bp | **+1,86** | −4,14 | −14,14 |

Die typische Zehn-Minuten-Bewegung beträgt 34 bp. Ein Roundtrip von 10 bp frisst also 29 % der
gesamten Bewegung — und der **vorhersagbare** Teil davon sind 1,7 bis 5,9 bp.

**In der ganzen Tabelle gibt es genau eine positive Zelle**, und sie verlangt eine Ausführung zu
2 Basispunkten je Seite bei den volatilsten Titeln des Tages. Unsere gemessene Slippage liegt
im Median bei 0,4 bp — aber gemessen an ruhigen Titeln im laufenden Handel, nicht an den
Ausreißern, um die es hier geht.

## Zum Hebel, weil das der Kern des Missverständnisses ist

| Hebel | Ergebnis je Trade (stärkste Bewegungen, 10 bp Roundtrip) |
|---|---|
| 1× | −4,1 bp |
| 5× | −20,7 bp |
| 10× | −41,4 bp |
| 20× | −82,8 bp |

**Hebel ist ein Multiplikator, kein Vorzeichenwechsler.** Er vergrößert einen positiven
Erwartungswert und vergrößert einen negativen genauso. Bei einer Strategie, die nach Kosten bei
−4 bp steht, macht Hebel 10 daraus −41 bp je Trade — und dazu ein Risiko, bei dem eine normale
Tagesbewegung das Konto auslöschen kann.

## Warum das ökonomisch auch Sinn ergibt

Der Reversal auf Minutenskala ist in der Literatur kein Geheimnis, sondern die **Entlohnung für
Liquiditätsbereitstellung**: Wer in dem Moment die Gegenseite nimmt, in dem jemand dringend
verkaufen muss, bekommt dafür einen kleinen Aufschlag. Diesen Aufschlag verdient man, indem man
mit Limit-Orders im Buch **steht** — nicht, indem man mit Market-Orders zugreift. Wer zugreift,
**zahlt** ihn.

Genau daran ist die Crypto-Lane gescheitert: 460 von 451 USD Verlust waren Gebühren, vor Kosten
war sie etwa bei null. Und der Weg über Limit-Orders wurde dort schon geprüft und begründet
verworfen — eine Limit-Order am Ausbruchsniveau ist genau die Order, die nicht füllt, wenn das
Niveau tatsächlich bricht.

## Fazit

Auf der Minutenskala existiert ein echtes, statistisch klares Muster. Es gehört ökonomisch
demjenigen, der Liquidität bereitstellt, und ist für einen Teilnehmer, der über
Market-Orders zugreift, kleiner als die Reibung. Hebel ändert daran nichts außer der
Verlustgeschwindigkeit.
