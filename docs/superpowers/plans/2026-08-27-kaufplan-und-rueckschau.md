# 2026-08-27 — Kaufplan-Ansicht + Vorschlags-Rückschau (Nachtschicht)

**Auftrag (Nico, 01:45, „ich geh pennen, arbeite das selber in einer Loop"):** Autotrader/App
weiterbringen; Vorschläge aktualisieren; **Score, ob die bisherigen Vorschläge gute Einstiege
gewesen wären**; eine Ansicht mit Kaufplan pro Aktie (kurz/lang, Kauflimit, Score, Verkaufsziel,
Tranchen, Geschäftsmodell, Warum, News, wer hat gekauft); Link per Telegram fürs Handy.

## Ausgangsbefund (gemessen, nicht geschätzt)
- Watchlist-Snapshot 2026-08-26 20:45: **30 Titel, davon 0 `in_zone`.** Die App-Ansicht
  „Kaufbereit" ist damit leer — genau in der Nacht, in der Nico kaufen will.
- Spitzenreiter ITC.NS (Score 69) steht **13 % UNTER** seiner Einstiegszone
  („Support gebrochen"), ist also ausdrücklich kein Kauf. Der Rest: Score 41 abwärts.
- 31 Pitches seit Juni, 16 distinct Ticker; die letzten 12 tragen fast durchgehend
  `verdict=red` und `status=expired`.
- **Es gibt keine Messung, ob die Vorschläge je etwas gebracht haben.** `/api/proof` misst die
  Paper-BÜCHER (Auto-Depot, Arena-Lanes), nicht die Vorschlagsliste. Das ist die Lücke.

## Tasks
- [ ] T1 `suggestion_review.py`: reine Messfunktionen für „hätte der Vorschlag getragen?"
      (Vorschlag → Rendite über Horizont → minus regionaler Benchmark → Aggregat mit
      unabhängigem n). Ehrlichkeitsregeln aus LOOP.md gelten: Stichprobenidentität stempeln,
      überlappende Fenster nicht als unabhängig zählen.
- [ ] T2 `scripts/run_suggestion_review.py`: Kurse holen (yfinance, hinter Naht), messen,
      Ergebnis in Tabelle `suggestion_reviews` schreiben.
- [ ] T3 `/api/rueckschau` + Panel: die Zahl, die Nico verlangt hat — mit Aussagekraft daneben.
- [ ] T4 `/api/kaufplan`: pro Titel EIN Kaufplan-Objekt (Horizont, Score, Limit/Zone, Tranchen,
      Ziel, Stop, Positionsgröße, Geschäft, Warum, News, wer kauft, Verkaufsregeln).
- [ ] T5 Kaufplan-Ansicht im Cockpit (Handy-first, 390 px).
- [ ] T6 Voll-Scout + Insights frisch (läuft seit 01:50 im Hintergrund).
- [ ] T7 Telegram: Link + Kurzfassung der Befunde.

## Harte Grenzen (unverändert)
Kein Echtgeld-Routing, keine bezahlten Feeds, keine neuen Konten. Jede Oberfläche trägt den
DISCLAIMER. Die Rückschau misst Vergangenheit — sie ist keine Prognose und wird nirgends als
eine dargestellt.

---

## Outcome (2026-08-27, 03:20)

Alle sieben Tasks umgesetzt. Gate: **2 638 Backend-Tests grün, 1 vorgefundener Fehler**
(davon **105 neu** in `test_suggestion_review.py` / `test_suggestion_storage.py` /
`test_buy_plan.py`) und **166 Frontend-Tests** grün, `ruff` sauber, `tsc --noEmit` sauber.
Zum einen Fehler siehe „Vorgefundener roter Test" unten.

### T1–T3 — Die Antwort auf „wäre das erfolgreich gewesen?"
`suggestion_review.py` + `suggestion_storage.py` + `scripts/run_suggestion_review.py`.
196 Vorschläge (31 Pitches, 165 Ranglisten-Plätze) über 37 Titel, 189 Messungen, Kursabdeckung
100 %. Ergebnis, Stand 2026-08-27:

| Quelle | Horizont | unabh. n | Ø Exzess | Trefferquote | p |
|---|---|---|---|---|---|
| Pitches | 5 Tage | 22 | **+2,7 pp** | 64 % | 0,016 |
| Pitches | 20 Tage | 15 | +2,2 pp | 67 % | 0,32 |
| Rangliste | 5 Tage | 45 | **+0,9 pp** | 58 % | 0,021 |
| Rangliste | 20 Tage | 15 | +0,1 pp | 60 % | 0,94 |

**Kein Befund — und das ist die wichtige Zeile.** Zwei Quellen mal drei Horizonte sind sechs
Tests; das korrigierte Niveau ist 0,0083, und beide „signifikanten" p-Werte liegen darüber.
Dazu: der 60-Tage-Horizont hat noch kein einziges abgeschlossenes Fenster, und **Kosten sind
nirgends abgezogen** — bei fünf Handelstagen Haltedauer und überwiegend ausländischen Titeln
frisst der Spread eine Überrendite dieser Größe plausibel ganz auf.

### T4–T5 — Der Kaufplan
`buy_plan.py` + `/api/kaufplan` + `KaufplanView.tsx`. Eine Karte pro Titel: Haltung, Kauflimit,
Tranchen, Kursziel/Stop, Halten-Band, Positionsgröße, Geschäftsmodell, Faktor-Gründe,
Handelbarkeit, gemeldete Käufe, Schlagzeilen. 390-px-Verify mit Playwright gegen den laufenden
Dienst: **1 911 px zugeklappt für 12 Karten (2,3 Bildschirme), 87 px pro Karte, kein
horizontaler Überlauf**; aufgeklappt 996 px.

Drei Defekte, die dieser Verify gefunden hat und die beim ersten Entwurf drin waren:
1. **Limit und Tranchenleiter widersprachen sich.** Die Karte zeigte für EHLD „Limit 7,56" und
   „Tranche 1: jetzt bei 9,89". `tranche_basis` hängt die Leiter jetzt an die Zahl, die auch in
   die Order geht; unter einer gebrochenen Zone gibt es gar keine Leiter mehr.
2. **„Jetzt" hieß nicht jetzt.** Dieselbe Sache in Worten — `relabel_tranches` macht daraus
   „bei Limit", sobald die Leiter am Limit hängt.
3. **Die Bilanz-Box sagte alles doppelt.** Gemessen, nicht geschätzt: die kompakte und die volle
   Fassung standen untereinander. Nur noch die volle (sie trägt die Einordnung mit).

### Zwei Befunde, die über den Auftrag hinausgehen
- **Die lokale Übersetzung erfindet Schlagzeilen.** Aus „Euroholdings Ltd. (NASDAQ: EHLD) Stock
  Price, News & Analysis" wurde „EHLD profitiert von starker Nachfrage nach Elektrifizierung —
  laut Analysten-Konsens" (eine Reederei; Nachfrage, Thema und Quelle frei erfunden). Zweiter
  Fall: „Flat on the Stockholm stock market at midday" → „S&P 500 ist stabil …". Maschinell
  nicht zuverlässig zu erkennen — eine Heuristik auf Wortüberlappung markiert 23 % der Paare
  und trifft dabei vor allem die korrekten. Gegenmaßnahme deshalb nicht Filtern, sondern
  Beilegen: `news_items` führt das Original IMMER mit, die Karte zeigt es unter der Übersetzung.
  **Offen für später:** die Übersetzung selbst absichern oder abschalten.
- **Der Screen findet überwiegend Titel, die Nico gar nicht kaufen kann.** Von den Top 12
  standen 4 auf Börsen, die ein deutsches Standard-Depot kaum bedient (Indien, Hongkong).
  `tradability` weist das jetzt pro Karte aus, und der Filter „Erreichbar" blendet sie aus
  (12 → 8). Das ist eine Einschätzung nach Handelsplatz, ausdrücklich keine Depot-Abfrage.

### T6 — Aktualisieren
Der erzwungene Voll-Scout um 01:50 **lief in eine Yahoo-Drosselung** (821 Rate-Limit-Fehler in
16 Minuten gegen 126 im gesamten 2¼-Stunden-Lauf vom 24.08.) und wurde um 02:06 gestoppt; der
Wochen-Marker blieb dabei korrekt ungesetzt. Ursache ist die Parallelität: mit
`--max-workers 2` statt 6 liefen die ersten 45 Sekunden mit **null** Rate-Limits durch. Der
Lauf wurde so neu gestartet (`scout_nightshift.log`).
**Empfehlung für die Cron-Kette:** `scripts/scheduled_run.sh` von `--max-workers 6` auf 2–3
senken. Nicht ungefragt geändert — es betrifft den regulären Montagslauf.

Nebenbefund: die Drosselung ließ einen Rückschau-Lauf mit **null** Kursreihen einen gültigen
Bericht überschreiben. `MIN_COVERAGE` (70 %) verhindert das jetzt; die leere Zeile wurde
gelöscht, der gültige Bericht steht.

### T7 — Telegram
`scripts/notify_nightshift.py`, stumm gesendet (message_id 282) — er schläft, die Nachricht soll
morgens da sein, nicht klingeln. Befund vor dem Link, Link mit `DASH_TOKEN` (dieselbe bewusste
Abwägung wie im Copilot-Digest).

## Vorgefundener roter Test — NICHT von dieser Runde
`tests/test_watchdog.py::test_run_watchdog_cli_sends_once_then_respects_cooldown` ist rot. Er
war es vor dieser Runde schon: `git diff --name-only 0afad67..HEAD` zeigt, dass diese Nacht
keine Datei der Watchdog- oder Lane-Kette angefasst hat.

**Ursache, nachgestellt:** `run_watchdog.py` alarmiert seit dem 26.08. zusätzlich auf
`position_divergence(args.shortterm_db)`, und `--shortterm-db` hat den **Produktions**-Default.
Der Test setzt nur `--db` — er liest also die echte `shortterm.db`, findet dort eine reale
Divergenz (WSHP: Buch 169 vs. Konto 338) und bekommt zwei Nachrichten statt einer. Der Test
wurde damit nicht durch eine Codeänderung rot, sondern durch einen Produktionszustand.
Das sind **zwei** Punkte für Nico:
1. Der Test isoliert nicht — `--shortterm-db` gehört im Test auf eine tmp-Datei.
2. Die Divergenz WSHP ist echt und offen: das Konto hält 338 Stück, das Buch 169.

**Ebenfalls vorgefunden:** Der Watchdog alarmiert seit 59 h täglich für `gapfade`. Dessen
Cron-Zeile wurde am 24.08. bewusst entfernt (`5cc67b3`), der Eintrag in
`watchdog.CHAIN_SCHEDULES` blieb stehen. Fehlalarm, ein Zeilenlöschen — und ein Test, der
`CHAIN_SCHEDULES` gegen `scripts/install_crontab.sh` prüft, würde die nächste Entkopplung
fangen. Nicht ungefragt gefixt.
