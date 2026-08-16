# Der Ausbruch hat einen Impuls — er dauert eine Minute (2026-08-16)

Nicos Einwand zum ORB-Befund: „Bei Ausbrüchen musst Du direkt mit auf den Zug springen, später
ist das nur volatiler." Der vorige Test lief auf Fünf-Minuten-Bars, der Einstieg lag damit im
Schnitt 2,5 Minuten nach dem eigentlichen Ausbruch. Also derselbe Test auf **Minutenbars**, mit
Einstieg im Ausbruchsmoment.

91 Ausbrüche über die 30-Minuten-Eröffnungsspanne, 40 Titel, 7 Handelstage (mehr gibt yfinance
bei Minutenauflösung nicht her).

## Das Ergebnis

| gehalten bis | Ø | t | Trefferquote |
|---|---|---|---|
| **+1 Minute** | **+4,63 bp** | 0,94 | 44,0 % |
| +5 Minuten | −12,53 bp | −2,17 | 41,8 % |
| +15 Minuten | −13,36 bp | −1,34 | 39,6 % |
| +30 Minuten | −18,65 bp | −1,33 | 41,8 % |

**Nico hat recht mit der Zeitstruktur:** Es gibt einen Impuls direkt nach dem Ausbruch, und er
ist positiv. Der Wert fällt danach monoton — je später der Einstieg, desto schlechter, genau wie
vermutet. Der Fünf-Minuten-Test hatte den Impuls schlicht verpasst, weil sein Einstieg zu spät
lag.

## Warum das trotzdem nicht handelbar ist

**Der Impuls beträgt 4,63 Basispunkte und hält eine Minute.** Ein Roundtrip kostet bei
liquiden Titeln 4 bp, realistischer 10. Damit bleibt zwischen +0,6 bp und −5,4 bp — und das
bei t = 0,94, also von null nicht zu unterscheiden.

Dazu die Trefferquote: **44 % schon nach einer Minute.** Mehr als die Hälfte der Trades ist
sofort im Minus; der positive Mittelwert kommt von wenigen großen Bewegungen.

## Zum Hebel, weil die Frage direkt daran hängt

Mit 4 bp Kosten bleibt +0,6 bp je Trade. Ein Hebel von 10 macht daraus +6 bp — das klingt nach
einem Weg. Er ist keiner, und zwar aus einem Grund, der nichts mit Vorsicht zu tun hat: **t =
0,94 heißt, dass wir nicht wissen, ob die 0,6 bp überhaupt existieren.** Ein Hebel vervielfacht
eine Zahl, die wir nicht von null unterscheiden können — und mit ihr die Streuung, die hier bei
44 % Trefferquote erheblich ist.

Der Hebel ist die richtige Antwort auf einen **gesicherten** positiven Erwartungswert. Der Weg
dahin führt über eine Stichprobe, die groß genug ist — und die hier bei 91 Ereignissen aus
sieben Tagen liegt, weil Minutendaten frei nicht weiter zurückreichen.

## Was daraus folgt

Für die Session-Lane ändert sich nichts: Sie steigt nicht in der ersten Minute ein, sondern auf
dem nächsten abgeschlossenen Bar — und dort ist der Impuls bereits negativ (−12,53 bp nach fünf
Minuten, t = −2,17). Der Befund verschärft die Diagnose eher, als sie zu entschärfen: Die Lane
kauft nicht nur eine Bewegung, die zurückkommt, sie kauft sie auch noch nach dem einzigen
Moment, in dem der Ausbruch etwas wert war.
