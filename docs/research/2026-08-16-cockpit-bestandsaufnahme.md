# Handy-Cockpit — Bestandsaufnahme auf 390 px (2026-08-16)

Schritt 1 des offenen Task 9 aus `plans/2026-08-06-phone-cockpit-beginner-friendly.md`, aber
gegen die **heutige** IA statt gegen die acht Views von damals: der Mockup-v2-Umbau vom 08.08.
hat 13 Views auf vier Tabs plus ein "Mehr"-Blatt gefaltet, die alte Task-9-Liste zeigt auf
Ansichten, die es so nicht mehr gibt.

## Wie gemessen wurde

Screenshots zeigen, DASS etwas abgeschnitten ist, nie WAS es abschneidet. Deshalb zusätzlich
eine Messung über das DevTools-Protokoll: derselbe Chromium, `Emulation.setDeviceMetricsOverride`
auf 390×1400 (`--window-size` erreicht eine nach dem Start navigierte Seite NICHT — der erste
Durchlauf maß dadurch 500 px und hätte jeden Überlauf untertrieben), dann pro Element
`getBoundingClientRect().right - clientWidth` und `scrollWidth - clientWidth`.

Skript: `/tmp/.../scratchpad/measure_overflow.py` (nicht im Repo — es braucht `websockets`, das
hier nur transitiv installiert ist). Wenn weitere Cockpit-Runden folgen, lohnt die Aufnahme als
`scripts/measure_phone_overflow.py` mit deklarierter Abhängigkeit.

## Was gemessen kaputt war (behoben in dieser Runde)

| Ansicht | Element | Überlauf | Folge auf dem Handy |
|---|---|---|---|
| Heute | `dd.num` (Autopilot-Block) | 39 px | „im Schnitt über 3 Taktiken" endete nach „Taktike" |
| Labor | `div.buy-row` | 124 px | Der Eurobetrag stand außerhalb des Bildschirms |
| Depot | `table.history` | 82 px | Spalte „Sharpe (63T)" unerreichbar, kein Scrollen möglich |
| Labor | `table.history.compare` | 398 px | Fünf von sechs Sektor-Spalten unerreichbar |

Gemeinsame Ursache bei den Tabellen: die Mobile-Regel `table { overflow-x: auto }` (Spezifität
0,0,1) wurde von `table.history { overflow: hidden }` (0,1,1) überstimmt — dieselbe
Spezifitätsfalle, die im CSS zwei Blöcke weiter oben für `.num` bereits dokumentiert ist.
Bei `dd.num`: `.view .num { white-space: nowrap }` ist für Zahlen richtig, der Wert war aber ein
ganzer Satz. Die Zahl trägt jetzt die Klasse, der Erklärtext daneben nicht.

## Was gemessen kaputt bleibt (Entscheidung nötig)

- **Firmennamen werden gekappt** (`span.pitch-company`, `nowrap` + `ellipsis`): „Sea Limited
  American Depositary Shares, each representing one…" braucht 265 px mehr als vorhanden. Das
  Kappen ist gewollt (sonst sprengt der Name die Karte), aber bei NASDAQ-Langnamen bleibt vom
  Namen nichts Unterscheidbares übrig. Optionen: zweizeilig erlauben, oder den Namen serverseitig
  auf den Kern kürzen („Sea Limited"), oder so lassen. Betrifft „Entscheiden" und „Wer kauft?".

## Je Ansicht: welche Frage sie beantwortet, was stört

**Heute — „Was ist gerade los?"** Trägt. Zwei Beobachtungen: unter der Marktlage-Karte steht ein
etwa 60 px hoher leerer Kasten, und die Karte „Was passiert ist" beginnt mit ähnlich viel
Leerraum.

**Aktien — „Was schlägt der Scout vor?"** Trägt, wirkt aber leer: zwei Vorschläge, danach zwei
Drittel Leerfläche. Tippfehler in der Fußnote: „…berechnet.Wie die Auswahl entsteht →" (fehlendes
Leerzeichen).

**Entscheiden — „Was muss ich entscheiden?"** Der Leerzustand ist gut und ehrlich. Die Historie
darunter wiederholt pro Karte dieselben vier Blöcke; auf dem Handy ist das viel Scrollen für
wenig Neues.

**Depot — „Wie steht mein Geld?"** Inhaltlich die dichteste Ansicht. „Letzte Umschichtungen"
bleibt kryptisch: „12.08. auf DBC +2,1 % · 2.124" — die letzte Zahl ist unbeschriftet.

**Ergebnisse — „Funktioniert das?"** Die stärkste Ansicht: jede Karte stellt eine Alltagsfrage
und beantwortet sie in einem Satz. Genau das Muster, das die anderen brauchen. Kleinigkeit: die
ⓘ-Symbole rutschen manchmal allein in die nächste Zeile.

**Wer kauft? — „Wer kauft gerade was?"** Widerspruch zwischen Titel und Inhalt: die häufigste
Zeile ist „wird in der Presse erwähnt", also gerade kein Kauf. Dazu doppelte Ticker („HTZ HTZ",
„ARAI ARAI") überall dort, wo kein Firmenname hinterlegt ist.

**Wie funktioniert das? — „Was tut die App?"** Trägt unverändert.

**Labor — „Was steckt dahinter?"** Der schwächste Punkt der Navigation: neun Zeilen Tabs
übereinander (drei Ebenen Reiter, davon zwölf Strategie-Reiter), bevor der erste Inhalt kommt.
Auf 390 px ist das ein halber Bildschirm reine Navigation.

## Daraus abgeleitet, aber KEIN Layout-Thema

Beim Nachmessen der Depot-Tabelle fiel auf, dass sie „ML Long Bot +12,5 %" listet — einen Sleeve,
der seit dem Verlust seines Champions nichts mehr hält. Ursache war die Persistenz, nicht die
Anzeige: `save_sleeve_weights` machte ein reines Upsert, konnte also eine verschwundene Strategie
nicht entfernen. Die angezeigten Gewichte summierten sich auf 112,5 %. Gefixt mit Test; die
Altzeile verschwindet beim nächsten nächtlichen Lauf von selbst, ohne Eingriff in die Produktions-DB.
