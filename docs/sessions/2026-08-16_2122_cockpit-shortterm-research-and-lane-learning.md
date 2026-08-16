# Session 2026-08-16 21:22 — Cockpit-Umbau, Short-Term-Recherche, Lane-Lernkreis

## Kontext & Ziel

Sonntag. Einstieg war Nicos Frage „lief der Autotrader, funktioniert alles?" — der Rechner war
von Fr 14.08. 13:15 bis So 02:30 aus. Daraus wurden vier zusammenhängende Stränge:

1. Autotrader-Nachholung prüfen und die Ursachen der Lücke benennen.
2. Handy-Cockpit fertig bauen (Nicos Auftrag „morgen die App zu Ende bauen").
3. Short-Term-Arena ausbauen („lieber zu viel tracken als zu wenig").
4. Automatisches Lernen der Handelsregeln (Nicos eigentliches Ziel: „dass die Software
   automatisch lernt und wir ein Modell hinkriegen, das positiv tradet").

20 Commits auf `autopilot/work`, alle gepusht (`d2f6b83` ist der letzte). Gate durchgehend
grün, zuletzt 2115 py-Tests + ruff + Frontend 127 Tests.

## Ergebnis

**Autotrader (Strang 1).** Der Nachhol-Lauf lief in dieser Session an: 8/8 Schritte OK, Depot
auf Fr 14.08. vorgerückt (101.534 USD, +1,5 % vs SPY +3,7 %). Zustandswechsel: 7 → 11 Sleeves,
weil die vier v16-Familien die 5-Sitzungen-Hürde genommen haben. Zwei echte Defekte gefunden
und behoben:
- `save_sleeve_weights` machte ein reines Upsert → der ML Long Bot hielt nach dem
  Champion-Verlust weiter 12,5 %, die angezeigten Gewichte summierten auf 112,5 % (`40394e9`).
- Der Sleeve-Tilt verlangte 60 Beobachtungen über ALLE Sleeves gemeinsam → jede Neuaufnahme
  setzte die Lernuhr für alle zurück (5 statt 19). Damit schlossen sich „mehr Strategien
  tracken" und „aus ihnen lernen" gegenseitig aus (`1442e4c`). Erster Tilt jetzt ~13.10.

**Cockpit (Strang 2).** Per CDP auf 390 px vermessen statt geraten — Werkzeug im Scratchpad,
nicht im Repo (braucht `websockets`, nur transitiv installiert). Behoben: Tabellen mit
`overflow: hidden` (Spezifitätsfalle, dieselbe die im CSS schon dokumentiert war), Buy-List
124 px zu breit, Autopilot-Zeile abgeschnitten (`64c769c`). Short-Term-Ansicht komplett
umgebaut (`84a3cea`): Gesamtzeile wie bei Long Term, „Funktioniert es?"-Block entfernt (er
zählte dieselben drei Lanes ein zweites Mal unter technischen Namen), Urteil je Karte aus dem
Trade-Test statt aus dem Kalender — das korrigierte eine falsche Aussage, weil Krypto längst
statistisch entschieden war. Reiter jetzt Long Term / Short Term. Rendite als Pille mit Pfeil
(`b85862a`). Bestandsaufnahme: `docs/research/2026-08-16-cockpit-bestandsaufnahme.md`.

**Short-Term-Recherche (Strang 3).** Plan
`docs/superpowers/plans/2026-08-16-short-term-lane-expansion.md`, vollständig abgearbeitet:
**sieben Kandidaten geprüft, null Lanes gebaut**, jeder mit eigenem Befund unter
`docs/research/2026-08-16-*`. Die drei Erkenntnisse, die über die Einzelabsagen hinausgehen,
stehen im Plan unter „Bilanz der Welle". Der wichtigste Einzelbefund: **93 % der Marktrendite
entsteht über Nacht** (t = 18,08 gegen 1,01 tagsüber).

**Session-Lane widerlegt.** Aus dem Minutenskala-Befund (Autokorrelation −0,0644, t = −32)
folgt direkt: Die Lane kauft Ausbrüche, die zurückkommen. An 1.684 Ausbrüchen gemessen
−8,94 bp nach 30 Minuten (t = −2,68), Trefferquote 45,8 % (`3dc46a4`). Nicos Einwand, man
müsse sofort einsteigen, war berechtigt — auf Minutenbars gibt es einen Impuls von +4,63 bp,
der genau eine Minute hält und den ein Roundtrip auffrisst (`1a30a25`).

**Lernkreis (Strang 4).** Vier Bausteine, alle in `nightly_train.sh` verdrahtet:
- `lane_review.py` — nächtliche Auswertung je Lane: Ergebnis, Zerlegung nach Ausstiegsgrund,
  Signifikanz, Veränderung seit gestern (`9511911`).
- `lane_tuning.py` — Parametersuche über dieselbe `exits.exit_reason`, die live läuft
  (`ff3a703`).
- `lane_params.py` — Regeln aus der DB statt aus Konstanten, mit Änderungshistorie und
  Monatsbremse (`ffb1244`).
- `lane_adoption.py` + `run_lane_tuning.py` — gepaarter Vergleich, Hürde steigt mit der Zahl
  der geprüften Kombinationen, automatische Übernahme (`d2f6b83`).

## Entscheidungen

- **Nico: Krypto-Lane läuft weiter**, obwohl ihr Ergebnis statistisch entschieden negativ ist —
  bewusst, nicht antasten.
- **Nico: automatische Parameter-Übernahme erlaubt.** Meine Bedenken stehen im Plan; die
  Umsetzung bekam deshalb dieselben Schutzmechanismen wie die Regel-Strategien seit v14.
- **Nico: Push nach origin erledigt**, Secret-Scan über alle 44 Commits sauber.
- **Backtest vor Lane** als Plan-Regel: Ein vernichtender Backtest beendet den Kandidaten. Hat
  siebenmal gegriffen und je einen Tag statt zwei Monate gekostet.
- **Keine Short-Lane**, obwohl Nico danach fragte: Nach schlechten Nachrichten steigen die
  Titel um 0,82 %, ein Short verlöre also vor Leihkosten (`623ae30`).
- **Lane nicht abgeschaltet**, obwohl die Session-Lane-Regel widerlegt ist — dieselbe
  Zuständigkeit wie bei Krypto liegt bei Nico.

## Offene Fragen

- Die Ereignis-DB hält nur **15 bullische Ereignisse** (`event_type = "beat"`). Die
  Parametersuche verlangt 60 und überspringt sich deshalb. Meine Suche lief auf 650
  Proxy-Ereignissen aus yfinance-Terminen — das ist nicht, worauf die Lane handelt. Ohne mehr
  klassifizierte Ereignisse kann der Lernkreis nichts lernen. Ursache prüfen: liefert der
  Klassifikator zu wenig, oder ist die Watchlist zu klein?
- Gap-Fade über Pre-Market + Market-on-Open: Der Effekt behält zwei Drittel (+42 bp), aber
  t = 1,00 auf 42 Handelstagen, und die Stichprobe kann nicht wachsen (Pre-Market-Daten reichen
  frei 60 Tage zurück). Die Auktionskosten sind unbekannt.
- Die Tilt-Uhr des Autotraders läuft jetzt, aber alle Lanes bleiben ohne belegten Vorteil. Der
  Hebel liegt eher im Overnight-Befund als in besseren Parametern.

## To-dos

### Nico

1. **Rechner freitags laufen lassen** (15:30–22:00). Das war der zweite Ausfall dieser Art; die
   Session-Lane hat den kompletten Freitagshandel verpasst, und das lässt sich nicht nachholen.
2. **Entscheiden: Session-Lane abschalten oder weiterlaufen lassen?** Ihre Einstiegsregel ist an
   1.684 Ausbrüchen widerlegt. Sie kostet keine echten Gebühren, aber sie belegt Messkapazität.
3. **Entscheiden: Gap-Fade-Lane bauen?** Es ist die einzige Idee, bei der ein Papierbuch noch
   etwas herausfinden könnte, das der Backtest nicht kann — nämlich die echten Auktionskosten.
4. **Cockpit auf dem Handy durchklicken** und Funde schicken. Zwei offene Design-Fragen liegen
   dort: lange Firmennamen werden gekappt („Sea Limited American Depositary Shares…"), und
   „Wer kauft?" zeigt überwiegend „wird in der Presse erwähnt", also gerade keinen Kauf.
5. **DASH_TOKEN und Telegram-Bot-Token rotieren** — beide liegen in alten Chat-Protokollen.

### Nächste Session (Agent)

- Ursache für die 15 klassifizierten Ereignisse suchen: `evidence/event_storage.py`,
  `classified_events`, Abdeckung der Watchlist. Ohne das läuft `run_lane_tuning.py` dauerhaft
  ins „übersprungen".
- Nach der ersten Nacht mit `lane_review` + `lane_tuning` prüfen, was in `train.log` steht —
  beide Schritte sind neu und noch nie in der echten Kette gelaufen.
- Offene Anschlussidee aus T2: die Nähe zum 52-Wochen-Hoch als **Rangfolge-Merkmal** testen
  statt als Auslöser; die Kennzahl liegt seit v8 in `signals.py`.
- `docs/sessions/` ist in diesem Repo **nicht** gitignored (drei ältere Docs sind committet) —
  die Konvention wurde beibehalten, aber sie ist eine Entscheidung, keine Selbstverständlichkeit.

## Einstieg für die nächste Session

Branch `autopilot/work`, sauber und gepusht. Der Plan
`docs/superpowers/plans/2026-08-16-short-term-lane-expansion.md` hat **keine offenen Aufgaben**
mehr — was dort steht, sind Entscheidungen für Nico (Abschnitt „Offene Punkte für Nico",
Punkte 1, 2 und 5). Erster technischer Schritt ohne Rückfrage: die Ereignis-Knappheit
untersuchen (siehe Offene Fragen), weil daran der ganze Lernkreis hängt. Der CronCreate-Wächter
dieser Session ist session-only und mit ihr beendet — bei Bedarf neu armen.
