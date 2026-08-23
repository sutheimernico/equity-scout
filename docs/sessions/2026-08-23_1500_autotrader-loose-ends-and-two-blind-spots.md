# Session 2026-08-23 ~13:50 – 15:0x — Autotrader: liegengebliebene Arbeit + zwei Blindstellen

## Kontext & Ziel

Einstieg von Nico, ein Satz: „sind bei dem autotrader to dos offen, dann mach jetzt alles
fertig." Also erst Bestandsaufnahme (Repo, PLAN.md, Session-Docs, laufende Ketten), dann
alles abarbeiten, was ohne ihn geht — und beim Rest sagen, warum nicht.

**Eine Fehlspur gleich zu Beginn, damit sie nicht nochmal jemand läuft:** die Aktien-Ketten
(intraday, daily, gapfade) hatten seit Freitag nichts geschrieben, was zunächst wie ein
Ausfall aussah. Heute ist **Sonntag**; letzter Handelstag war Freitag der 21.08. Die Stille
war korrekt. Erst der Wochentags-Check hat die Diagnose gerettet — Logs allein hätten hier
einen Tag Arbeit in die falsche Richtung gekostet.

## Ergebnis

Sieben Commits auf `autopilot/work`, **Gate 2507 grün** (vorher 2483, +24 Tests), ruff clean.

| Commit | Inhalt |
|---|---|
| `d103d09` | `fix(alpaca)`: abgelehnte Batch ohne das genannte Symbol wiederholen |
| `3a114a4` | `feat(ml)`: Volume-Block, den die CLI seit v17c ignoriert hat, verdrahten |
| (docs) | Session-Nachtrag WSL-Verify · News-Latenz-Ergebnis committet |
| `0a6d7d7` | `feat(watchdog)`: Ausfall des Schedulers selbst erkennen, in Handelsminuten bepreist |
| `d6a4f2a` | `feat(gapfade)`: melden, wie viele Ticker die Lane überhaupt beurteilen konnte |
| (docs) | AUTOPILOT_LOG, PLAN.md, README, Cockpit-Plan geschlossen |

### 1. Alpaca-Batch überlebt ein totes Symbol (offene Frage der Vorsession)

`us_symbols` nimmt Auslandsnotierungen raus, aber ein **US**-Ticker, der seit dem täglichen
Watchlist-Neubau delistet wurde, tötete die Batch weiterhin mit 400. Alpaca **nennt** den
Schuldigen — also raus damit und wiederholen. Laut bleibt alles andere: ein 400 auf ein
Symbol, das wir nie gesendet haben (sonst würde ein unbekannter Fehler zum still
schrumpfenden Universum), jedes Nicht-400 (403/429 sind Bedingungen der Anfrage, nicht des
Symbols), ein leerer Rest, ein Überschreiten des Deckels.

Eigene **Verdrahtungstests**, weil dieses Repo denselben Fehler zweimal gemacht hat: einen
Block bauen, den nichts durchreicht.

### 2. Volume-Block: verdrahtet, gelaufen, NULLBEFUND

Exakt jener Fehler, Fall zwei: `build_backfill_dataset` akzeptiert seit v17c einen
`volume_index`, und **kein trainiertes Modell hatte ihn je gesehen**, weil die CLI ihn nie
übergab. Jetzt `--with-volume` / `--with-all-features`, beides in die Registry gestempelt.

**Konsument gelaufen, nicht nur getestet** (gegen eine DB-**Kopie**, damit nichts live
promotet wird): v245 entry/random_forest, 67.932 Zeilen, `vol_ratio_20d`/`vol_ratio_5d`/
`vol_obv_20d` im Feature-Set bei **Abdeckung 1,00** → **AUC 0,5079** auf 54.612 OOS-Zeilen,
kein Champion. Anders als bei den Katalysatoren (5,9 % Abdeckung) liegt es hier **nicht**
an dünnen Daten: der Block trägt nichts bei. Als Merkmalsquelle abgehakt.

### 3. BLINDSTELLE: der Wächter konnte seinen eigenen Ausfall nicht sehen

Er reitet im selben Cron-Kommando wie die Crypto-Lane und läuft **nach** ihr. Beim ersten
Lauf nach dem Aufwachen ist also jeder Herzschlag, den er liest, Sekunden alt — ein
Rechner, der einen ganzen Nachmittag verschlafen hat, sieht aus wie ein gesunder.

Real passiert: **22.08. 19:01 → 23.08. 03:54 und erneut 03:56 → 13:48 kein einziger
Cron-Lauf** (aus `/var/log/syslog` belegt), und nichts hat gemeldet.

`scheduler_gap` vergleicht jetzt gegen den Vorgängerlauf, **bevor** der Herzschlag
überschrieben wird, und `market_hours.session_minutes_between` bepreist die Lücke in der
einzigen Einheit, die entscheidet: 8,5 Wochenendstunden kosten nichts, 90 Dienstagsminuten
kosten jeden Ausstieg, den die Lanes genommen hätten.

**Live verifiziert am echten 14:00-Cron:** 19,0 h gefunden, 0 Handelsminuten — und der
alte Check druckte in der Zeile **darunter** unverändert „alle Ketten am Leben". Gegenprobe
gemacht: Reihenfolge umgedreht → Test rot.

### 4. BEFUND: die Gap-Fade-Lane hat am 21.08. faktisch nichts beurteilt

Ihre **einzige** protokollierte Zeile trug einen Kurs vom **19.08.** — zwei Tage alt
(`stale_premarket`, CHMG). Und „0 MOO platziert, 1 verworfen" liest sich identisch,
egal ob 24 Ticker bepreist waren und keiner gappte, oder ob 23 gar keinen Pre-Market-Print
hatten. IEX trägt nur einen kleinen Teil des US-Volumens (Größenordnung wenige Prozent — Allgemeinwissen, hier **nicht** nachgemessen), die Watchlist ist überwiegend Small Caps. Entscheiden wird es die neue Abdeckungszahl, nicht diese Schätzung.

Die Lane druckt und persistiert jetzt `asked/quoted/fresh/judgeable`. Damit wird auch ihr
Abbruchkriterium falsifizierbar: eine Lane, die zwei Titel am Tag beurteilt, erreicht ihre
60 Trades nie.

## Depot-Stand (Referenz für den nächsten Vergleich)

| Buch | Stand | Benchmark |
|---|---|---|
| Auto-Depot | +2,15 % (21.08.) | SPY +2,28 % |
| swing | +0,99 % (21.08.) | SPY +3,17 % |
| crypto | +7,24 % (23.08.) | BTC +18,42 % |
| ignition | +3,46 % (21.08.) | — |
| session | −2,61 %, **pausiert** seit 13.08. | SPY +4,69 % |

**Kein Trader schlägt seine Benchmark** — unverändert gegenüber dem 21.08.

## Entscheidungen

- **Wochentag vor Logdiagnose.** Siehe Fehlspur oben. Gehört in jede künftige „Kette tot?"-
  Prüfung als erster Schritt.
- **`--with-all-features` verweigert den Default-`--start` 2007, statt ihn zu kürzen.** Der
  Hilfetext versprach ein implizites 2016; der Code setzte es nie. Ein Flag, das das
  Trainingsfenster hinter dem Rücken des Aufrufers ändert, ändert die **Identität der
  Stichprobe** — genau die Fehlerklasse vom 11.08. Also laut statt still.
- **Kein Trainingslauf gegen die Produktions-DB.** Der Konsumenten-Beweis lief gegen eine
  Kopie; ein promoteter Champion aus einem Ad-hoc-Lauf wäre eine Live-Änderung, die niemand
  beauftragt hat.
- **Lückenmeldung ohne Cooldown.** Sie wird per Konstruktion nur einmal ausgelöst: beim
  nächsten Lauf ist der Vorgänger frisch.
- **Feiertage weiterhin nicht modelliert** (Linie des ganzen `market_hours`-Moduls) — die
  Handelsminuten sind damit eine **Obergrenze**, was in der Docstring steht.
- **Matrix-Hold-out nicht angefasst.** Einmalschuss, gehört Nico. Unverändert seit dem 21.08.

## Offene Fragen

- **Warum schläft der Rechner überhaupt?** Standby am Netzstrom steht laut PLAN.md auf
  „nie", Wake-Timer sind aktiv, `WakeToRun` ist seit dem 10.08. gesetzt — und trotzdem
  waren es gestern/heute zweimal mehrere Stunden. Der dokumentierte nächste Schritt
  (`powercfg /waketimers` als Admin, Ereignisprotokoll nach Kernel-Power) braucht erhöhte
  Rechte und ist deshalb Nicos. Immerhin **sieht** man es ab jetzt.
- **Reicht IEX-Pre-Market für die Gap-Fade-Lane?** Ab Montag liefert die Abdeckungszeile die
  Serie. Entscheidungsregel steht vorab in PLAN.md registriert, damit sie nicht nachträglich
  gebogen wird.

## To-dos

### Nico

1. **Windows-Energie**: `powercfg /waketimers` als Admin + Ereignisprotokoll (Kernel-Power).
   Zweimal mehrere Stunden Schlaf innerhalb von 24 h, trotz aller bisherigen Fixes.
2. **Telegram-Bot-Token rotieren** — steht seit Wochen, liegt im Klartext in einem alten Log.
3. **Matrix-Hold-out 2023–2025 freigeben oder nicht.** Unverändert der nächste große Schritt;
   ohne Go passiert nichts.
4. **Handy-Cockpit: was heißt „zu Ende"?** Der Refresh-Plan ist jetzt geschlossen, damit ist
   der Scope wieder offen und braucht deinen Durchklick.
5. ~~Rechner muss an Handelstagen 15:30–22:00 laufen~~ — **diese Angabe war falsch**, siehe Review-Teil unten: das Gap-Fade-Signalfenster ist **15:00–15:28** Berlin.

### Nächste Session (Agent)

- **Ab Mo 24.08. die Gap-Fade-Abdeckung mitschreiben.** `gapfade_coverage` in `st_state`
  der `shortterm.db`; Entscheidungsregel steht in PLAN.md.
- Erste echte Meldung des Lückendetektors an einem **Handelstag** abwarten — dann steht dort
  eine Zahl > 0 Handelsminuten, und die Meldung wird zum ersten Mal teuer.
- Der Watchdog fängt weiterhin **nicht** die Kette, die noch nie geschlagen hat (Design seit
  v12 W1, eigener Test). Das bleibt die bekannte Restlücke.

## Einstieg für die nächste Session

Branch `autopilot/work`, Gate 2507 grün, keine angefangene Arbeit. Alles, was ohne Nico ging, ist
zu; was offen bleibt, steht oben unter „Nico" und ist ausnahmslos eine Entscheidung oder ein
Zugriff, den der Loop nicht hat.

---

# Teil 2 (~19:30–20:0x) — Handy-Cockpit fertig

Nicos Nachfrage: „Ist das Handycockpit fertig? Sonst mach damit bitte jetzt weiter und
finishe das Ding."

## Wie der offene Scope aufgelöst wurde

Der PLAN.md-Eintrag stand seit dem 16.08. mit dem Vermerk „Der Scope ist NICHT festgelegt —
erster Schritt ist die Klärung mit Nico". Statt zu raten oder zu blockieren: **messen.**
Playwright gegen den laufenden Dienst, Viewport 390 × 844 px, `scrollHeight` je Ansicht.
Damit war „unübersichtlich" keine Geschmacksfrage mehr.

| Ansicht | vorher | Bildschirme | nachher |
|---|---:|---:|---:|
| **Wer kauft?** | **68 005 px** | **80,6** | 8 252 px (**−88 %**) |
| **Entscheiden** | **10 158 px** | **12,0** | 2 855 px (**−72 %**) |
| Labor: Tab-Leiste | 193 px | 3 Zeilen | **49 px** |

## Die Ursache war immer dieselbe

**Ungedeckelte Listen.** `VoicesPanel` rendert alle 262 Stimmen-Ereignisse als volle Karten,
`PeoplePanel` alle 23 Personenkarten, der Entscheiden-Schirm alle 28 verfallenen von 30
Pitches.

Dazu ein inhaltlicher Fehlgriff, den erst die Datenzählung sichtbar machte: **205 der 262
Stimmen-Ereignisse sind reine Presse-Erwähnungen.** Die Ansicht, die verspricht zu zeigen,
wer *kauft*, bestand zu vier Fünfteln aus Karten mit dem wörtlich identischen Satz „keine
erkennbare Kauf- oder Verkaufsrichtung". Und in den Personenkarten waren die sechs
sichtbaren Zeilen Erwähnungen, während Michael Burrys gemeldete Käufe hinter „+89 weitere
anzeigen" lagen — bei einer Ansicht mit der Überschrift „Wer kauft gerade was".

## Was geändert wurde

- **Stimmen:** gerichtete Aussagen sind die Standardansicht (57 von 262), reine Erwähnungen
  hinter einem Tab, Liste bei 15 gedeckelt. Der immer gleiche Erklärsatz steht einmal oben
  statt ~200-mal in den Karten.
- **Personen:** Meldungen und gerichtete Calls sortieren *innerhalb* einer Karte über bloße
  Erwähnungen; Karten bei 10 gedeckelt.
- **Entscheiden:** nur der entschiedene Schwanz wird gedeckelt — **offene Pitches nie**,
  dafür ist der Schirm da.
- **Tab-Leisten** mit vielen Einträgen scrollen auf dem Handy seitwärts statt umzubrechen.
- **`.content`** räumt 140 statt 64 px Fußfreiraum: der Chat-FAB reicht 128 px hoch und saß
  auf der letzten Listenzeile jeder langen Ansicht.

## Entscheidungen

- **`ergebnisse` bewusst NICHT angefasst.** Sie erfüllt das Muster, das der Plan für alle
  anderen fordert, bereits vollständig — Leitfrage als Überschrift („Kann das
  funktionieren?"), eine Zahl je Karte mit ihrer Vergleichsgröße, ehrliche Leerzustände
  („Noch nicht messbar (braucht abgeschlossene Trades mit Gewinn)"). Sie ist die Vorlage,
  nicht das Problem.
- **`labor` bleibt bei 5,2 Bildschirmen.** Zwölf Strategien mit Kennzahlenblöcken sind
  Inhalt, kein Rauschen; ein Deckel wäre dort Verlust.
- **Kartenreihenfolge bleibt echte Aktualität**, obwohl innerhalb der Karte anders sortiert
  wird — sonst überholte ein Monate alter Beleg jemanden, der heute aktiv war. Eigener Test.
- **Task 9 gegen die heutige IA neu bewertet**, nicht blind abgearbeitet: die acht im Task
  genannten Panel-Namen stammen aus der Zeit vor dem Rebuild vom 08.08.

## To-dos

### Nico

6. **Durchklick auf dem echten Handy** — steht seit dem 08.08. aus und ist der einzige Test,
   den ich nicht ersetzen kann.
7. **Chat-FAB entscheiden:** er verdeckt weiterhin Text *mitten* auf der Seite (das
   Seitenende ist freigeräumt). Verschieben, verkleinern oder nur auf manchen Ansichten
   zeigen — je ein anderer Kompromiss, kein Defekt.

### Nächste Session (Agent)

- Screenshot-Messung ist reproduzierbar: Playwright gegen `127.0.0.1:8420` bei 390 px,
  `scrollHeight` als Maß. Für jede künftige UI-Runde der billigste Realitätstest.


---

# Teil 3 (~20:20–21:0x) — Review aller Zahlen und Empfehlungen

Nicos Auftrag: „Review bitte alles, stimmen alle Zahlen? Sind die Empfehlungen up to date?"

## Zahlen: vier Korrekturen, der Rest hält

**Bestätigt, unverändert:** Gate 2507 (= 2483 + exakt 24 neue Tests, aus dem Diff gezählt) ·
vitest 142 = 127 + 15 · Volume-Lauf v245 / 67 932 Zeilen / AUC 0,5079 / 54 612 OOS /
Coverage 1,00 / kein Champion · Watchdog-Lücke 18,9995 h und 0 Handelsminuten · **alle fünf
Depot-Zahlen auf zwei Nachkommastellen** · 43 getrackte → 24 US-Ticker · CHMG mit Quote vom
19.08. · 30 Pitches / 28 verfallen · 68 005 → 8 252 px und 10 158 → 2 855 px.

Der Vorher/Nachher-Vergleich ist sauber: zwischen beiden Messungen war die Datenbasis
identisch (589 Evidenz-Ereignisse, 30 Pitches), obwohl der News-Sweep minütlich läuft.

**Korrigiert:**

| behauptet | richtig | Ursache |
|---|---|---|
| „475 der 589 Evidenz-Ereignisse sind Erwähnungen" | **205 der 262 Stimmen-Ereignisse** | Zählskript nutzte `details.get('kind','context')` — Quellen ohne `kind` zählten still als „context" |
| Labor-Tab-Leiste „~350 px" | **193 px** | aus einem Screenshot mit `deviceScaleFactor: 2` abgelesen, Bildpixel nicht halbiert |
| Strategien-Leiste „~800 px" | **553 px** | dieselbe Ursache |
| Host-Schlaf bis „03:30" | **03:54** | 03:30 war die syslog-Rotation, nicht der erste Cron-Lauf |

Die Schlussfolgerung „vier Fünftel der Karten sagen, dass keine Richtung erkennbar ist"
bleibt richtig (205/262 = 78 %) — sie gilt für die Stimmen-Ereignisse, nicht für die
Evidenz insgesamt. Keine Maßnahme ändert sich dadurch.

## Der Bug, den das Nachzählen fand

Beim Aufschlüsseln der Quellen fiel auf: die API sendet `source: "thirteen_f"`
(`SOURCE_13F` in `evidence/base.py`), `people.ts` verglich an **drei** Stellen gegen
`"13f"`. Alle drei Zweige waren tot.

> **80 Fonds-Meldungen von sechs Fonds** — Berkshire Hathaway, Baupost, Appaloosa,
> Duquesne, Himalaya Capital, Third Point — fielen in den Presse-Zweig und standen als
> „Investor / Stimme" mit „**wird in der Presse erwähnt**" da. In der Ansicht „Wer kauft
> gerade was". Ein 13F über 541 600 Amazon-Aktien, etikettiert als Geschwätz.

Der Fehler stammt aus `f52d59f`; **ich habe ihn gestern in `isAction()` repliziert**, indem
ich das Literal aus den Zeilen darüber übernahm, statt es gegen die Daten zu prüfen. Die
Quellen sind jetzt eine benannte Konstante `SOURCE`, aus `evidence/base.py` gespiegelt.
Die alten Tests konnten ihn nicht fangen — **sie haben nie ein Fonds-Ereignis gefüttert**.
Gegenprobe gemacht (Konstante zurück auf `"13f"` → 4 Tests rot). Live verifiziert:
„Duquesne Family Office · **Fonds** · Amazon — **Position aufgestockt**".

## Empfehlungen: eine war schädlich, vier waren erledigt

**Schädlich:** „Rechner an Handelstagen 15:30–22:00". Die Angabe stammt aus dem Fenster der
**Session-Lane**, die seit dem 17.08. **pausiert** ist, und wurde seither in jeder
Session-Doku weitergereicht — auch von mir heute, mit dem Zusatz „(unverändert)", ohne sie
zu prüfen. Das Gap-Fade-Signalfenster ist `GAPFADE_SIGNAL_START/END` = **09:00–09:28 ET =
15:00–15:28 Berlin**. Wer sich an „ab 15:30" hält, verpasst es vollständig; die Lane
platziert dann nie eine Order — und genau diese Lane soll gerade gemessen werden. Die
korrekte Fenstertabelle steht jetzt in PLAN.md unter „Needs Nico".

**Erledigt, standen aber noch offen** (alle vier live gegengeprüft): `DASH_TOKEN` gesetzt ·
`DASH_URL` gesetzt · `equity-scout-dash.service` `enabled` + `active` · `EDGAR_USER_AGENT`
gesetzt.

**Weiterhin gültig:** `powercfg /waketimers` (der Rechner schlief heute zweimal; seit 13:48
läuft er durch) · Telegram-Token-Rotation, **jetzt dringlicher**, weil heute zusätzlich der
`DASH_TOKEN` per Telegram-Link verschickt wurde · Matrix-Hold-out-Go · Chat-FAB-Entscheidung
· Durchklick am Handy.

---

# Teil 4 (~21:0x–21:3x) — die Fehlerklasse zu Ende geprüft

Nach dem 13F-Fund wäre es fahrlässig gewesen, es beim Einzelfix zu belassen: derselbe
Fehler kann überall stecken, wo das Frontend gegen einen String vergleicht, den das Backend
setzt.

## Vorgehen

Alle Stringvergleiche des Frontends gesammelt
(`source|status|kind|change|reason|verdict|lane|mode|family === "…"`) und gegen die Werte
gehalten, die **15 API-Endpunkte tatsächlich senden**.

| Vergleich | API sendet | Urteil |
|---|---|---|
| `source === "voice"` | voice | ok |
| `status === "open"/"expired"` | open, expired, buy | ok |
| `kind === "context"` | context, call, call_bearish | ok |
| `change === "new"` | new, increased | ok |
| `mode === "anchor"` | anchor | ok |
| `lane === "nico"` | nico (+5 weitere) | ok |
| `target_stop.source === "model"` | heuristic_v1 heute, „model" sobald ein Champion steht | ok |
| `source === "13f"` | **thirteen_f** | **war tot — gefixt** |
| `kind === "backtest"/"forward"/"anchor"`, `reason === "all"` | — | Frontend-eigene Props, keine API-Felder |

## Was dabei zusätzlich auffiel

`lanes.ts::verdictLine` rendert das Lane-Urteil **binär** — „verdient Geld" / „verliert
Geld" —, während `significance.assess_trades` **fünf** Verdicts kennt: positiv, negativ,
kein messbarer Effekt, noch nicht aussagekräftig, zu wenige Trades.

**Heute ist das korrekt**, weil der Binärzweig hinter `is_significant` liegt und `p < alpha`
nur bei den beiden gerichteten Verdicts wahr werden kann (die anderen drei setzen
`p_value=None` oder liegen über alpha). **Nichts hat diese Invariante erzwungen.** Ein
später ergänzter Äquivalenztest („signifikant KEIN Effekt") hätte das Cockpit still
behaupten lassen, eine Lane *verliere Geld*, wo der Befund „kein Unterschied" lautet — in
einem Projekt, dessen erste Regel ist, dass ein Nullergebnis ein valides Ergebnis ist.

Jetzt festgenagelt durch `test_a_significant_result_is_always_positive_or_negative`: fünf
Datenlagen, die Implikation geprüft — **und** geprüft, dass die Fälle beide Richtungen
überhaupt erzeugen, sonst bewiese die Zusicherung nichts. Der Frontend-Kommentar nennt den
Test beim Namen.

## Die Lehren stehen jetzt in LOOP.md

Nicht in einer Session-Doku, wo sie versanden, sondern dort, wo der nächste Agent sie liest
— als eigener Abschnitt neben den Messregeln vom 11./12.08.:

1. Ein aus einem Bild abgelesener Wert ist keine Messung (`deviceScaleFactor: 2`).
2. Ein Default in einem Zähler erfindet Daten (`get("kind", "context")`).
3. Geteilte Konstanten spiegeln und testen, nie abtippen.
4. Ein Test, der nur die behandelten Fälle füttert, beweist nichts.
5. Eine binäre Darstellung eines mehrwertigen Feldes braucht ihre Invariante als Test.
6. **Empfehlungen verrotten still** — „(unverändert)" ist eine Behauptung, kein
   Haftungsausschluss.
7. Wochentag prüfen, bevor man eine tote Kette diagnostiziert.
