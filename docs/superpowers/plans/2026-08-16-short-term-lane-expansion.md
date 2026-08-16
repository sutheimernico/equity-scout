# Short-Term-Lanes ausbauen — Implementierungsplan

**Auftrag (Nico, 2026-08-16):** „Tracken können wir ja eigentlich alles — deswegen lieber zu
viel als zu wenig. Dann können wir über die Zeit schauen, was gut ist." Also: jede
Short-Term-Idee, die mit unseren freien Daten ehrlich messbar ist, bekommt ein eigenes
Papierbuch in der Arena.

**Recherche-Grundlage:** Die Kandidatenliste und ihre Evidenzlage stehen in der Session vom
2026-08-16 (Quellen: Quantpedia Short-Term-Reversal, Della Corte/Kosowski Overnight-Intraday,
Alpha Architect zu den Kosten des Overnight-Effekts, George/Hwang 52-Wochen-Hoch).

## Iron rules für diesen Plan

1. **Backtest VOR Lane.** Keine Lane geht live, bevor ihre Regel gegen die eigene Historie
   gerechnet wurde — mit Kosten (`costs.py`, Corwin-Schultz-Boden). Ein Backtest kostet einen
   Tag, eine Lane kostet Monate Messzeit.
2. **Ein Backtest, der die Regel vernichtet, beendet den Kandidaten.** Das Ergebnis wird
   dokumentiert und die Lane NICHT gebaut. Ein Nullbefund ist ein Ergebnis, kein Scheitern.
3. **Long-only.** Keine Lane, die Leerverkäufe braucht — Borrow-Kosten können wir nur schätzen,
   und eine geschätzte Zahl sieht echter aus als sie ist (deshalb fällt Pairs-Trading raus).
4. **Eigenes Buch, eigenes Ledger, gleiches Startkapital** (10.000 USD), damit die Arena
   vergleichbar bleibt.
5. **Gate pro Aufgabe:** `uv run pytest -q` grün + `uv run ruff check .` sauber. Nur grün
   committen, dann die Checkbox hier setzen.

## Der Lane-Bauplan (gilt für jede neue Lane)

Jede Lane durchläuft dieselben sechs Schritte — sie sind die Definition von „fertig":

1. Regel-Modul `src/equity_scout/st_<name>.py` mit reiner Entscheidungsfunktion (keine I/O),
   Parameter als Modul-Konstanten wie bei `st_swing.PROFIT_TARGET`.
2. Unit-Tests für Einstieg, Ausstieg, Randfälle (leeres Panel, fehlende Bars).
3. Backtest-Lauf gegen die Historie, Ergebnis nach `docs/research/2026-08-XX-<name>-backtest.md`.
4. Registrierung: `shortterm_storage.LANES` + `LANE_LABELS`, `run_shortterm.py --lane <name>`.
5. Anzeige: `frontend/src/lanes.ts` (Klartextname + `what`-Text), Karte erscheint automatisch.
6. Zeitplan: Cron-Zeile über `scripts/install_crontab.sh` (line-managing, nie von Hand).

## Reihenfolge — billig und schnell entscheidbar zuerst

Die Reihenfolge folgt der Zeit bis zum Urteil, nicht der Attraktivität der Idee. Eine Lane mit
wenigen, großen Trades ist schneller beurteilt als eine mit vielen kleinen — und kostet
unterwegs weniger Gebühren.

### Welle 1 — die günstigen Regeln (wenige Trades)

- [x] **T1: Turn-of-Month — geprüft, KEINE Lane.** Backtest über 31 Jahre SPY (349 Trades):
      Fenster-Tage 7,72 bp/Tag gegen 3,75 bp an allen anderen, Differenz **t = 1,39 → nicht
      belegbar**, und 72 % davon gehen an die Handelskosten. Der Code bleibt als
      reproduzierbare Antwort liegen (`st_turnofmonth.py`, 8 Tests), die Lane wird nicht
      gebaut. Befund: `docs/research/2026-08-16-turn-of-month-backtest.md`.
- [x] **T2: 52-Wochen-Hoch — geprüft, KEINE Lane.** Event-Study über 91 US-Titel, 300.279
      Fenster: nach dem Ausbruch +0,54 % auf 20 Tage gegen +0,72 % bei Titeln knapp UNTER dem
      Hoch — der Ausbruchstag ist der schlechteste Einstieg der oberen Kursregionen, bei der
      niedrigsten Trefferquote (52,6 % gegen 56,0 %). Konsistent über 5/20/60 Tage. Die
      auffällige Zahl bei „weit weg vom Hoch" (+1,97 %) ist Survivorship und taugt für keine
      Entscheidung. Befund: `docs/research/2026-08-16-52-week-high-backtest.md`.
      **Anschlussidee (nicht in diesem Plan):** die Nähe zum Hoch als Rangfolge-Merkmal testen
      statt als Auslöser — die Kennzahl liegt seit v8 in `signals.py`.
- [x] **T3: Volumen-Kapitulation — geprüft, KEINE Lane.** Auf überlappenden Fenstern sah es
      nach dem ersten echten Treffer aus (20T: +1,25 pp, t = 3,73; 60T: t = 6,21). Auf
      **nicht überlappenden** Fenstern bleibt t = 1,64 bzw. 0,34, und über sechs Startpunkte
      der Teilstichprobe schwankt t zwischen 0,09 und 1,64 — das Urteil hängt an einer
      willkürlichen Wahl. Dazu eine niedrigere Trefferquote als an gewöhnlichen Tagen (51,6 %
      gegen 53,2 %), der Mittelwert ist also ausreißergetragen. Befund:
      `docs/research/2026-08-16-capitulation-backtest.md`.
      **Erster Fall, in dem die Überlappungsregel aus LOOP.md eine Fehlentscheidung verhindert
      hat** — ohne sie wäre die Lane auf einem vierfach überhöhten t-Wert gebaut worden.

### Welle 2 — erst messen, dann entscheiden

- [x] **T4: Overnight-Drift — geprüft, KEINE eigene Lane, aber der stärkste Befund der Serie.**
      Der Effekt ist massiv und robust: SPY +10,62 %/Jahr über Nacht (t = 5,23) gegen +2,43 %
      tagsüber (t = 0,87); auf 91 Einzeltiteln 325.000 Beobachtungen, **93 % der Gesamtrendite
      entsteht über Nacht** (t = 18,08 gegen 1,01). Keine Lane, weil sie Buy-and-Hold nicht
      schlägt (10,62 % gegen 13,31 %) und bei ~2 bp je Seite kippt — genau der Bereich unserer
      gemessenen Slippage (67 echte Fills: Median +0,40 bp), und die stammt aus dem
      Intraday-Handel, nicht aus der teureren Eröffnungsauktion.
      **Konsequenz für den Bestand:** die Intraday-Session-Lane handelt ausschließlich im
      renditelosen Teil des Tages und ist per Konstruktion (immer flach zum Schluss) vom
      einzigen Zeitfenster mit Rückenwind ausgeschlossen. Gehört in ihre Beurteilung.
      Befund: `docs/research/2026-08-16-overnight-drift-backtest.md`.
- [x] **T5: Short-Term-Reversal — geprüft, KEINE Lane.** Vorsprung des Verlierer-Fünftels
      +0,29 pp auf 5 Tage (t = 2,68), aber vier unabhängige Gründe dagegen: in **keiner**
      Teilperiode signifikant (t = 0,18 bis 2,33, Bonferroni-Schwelle ~2,5) und getragen von
      der Stressphase 2020–2023; 40 % höhere Volatilität für den Vorsprung (10,63 % gegen
      7,58 %), risikoadjustiert also nichts; unveränderte Trefferquote (51,9 % gegen 51,1 %),
      der Mittelwert ist wieder ausreißergetragen; und Survivorship wirkt genau in Richtung
      des Befunds. **Die Zerlegung nach Tageszeit repliziert Della Corte/Kosowski:** Signal aus
      dem Intraday-Anteil t = 1,82, aus dem Overnight-Anteil **t = 0,03**.
      Befund: `docs/research/2026-08-16-short-term-reversal-backtest.md`.

### Welle 3 — wenn Welle 1 und 2 stehen

- [x] **T6: Earnings-Premium — geprüft, KEINE Lane.** 1.790 Termine, 80 Titel: vor der Meldung
      −0,08 pp (t = −0,52), durch die Meldung +0,13 pp (t = 0,47), nur die Reaktion +0,14 pp
      (t = 0,59). **Wichtiger als die Nullen ist die Nachweisgrenze:** bei 11,78 % Streuung je
      Ereignis müsste ein Effekt über **0,56 pp** liegen, um sichtbar zu werden — die Literatur
      nennt 0,2–0,3 %. Die Frage ist an unseren Daten also gar nicht entscheidbar, und eine
      Lane, deren Zielgröße unter der Auflösung des Messgeräts liegt, liefert keine Antwort.
      Befund: `docs/research/2026-08-16-earnings-premium-backtest.md`.
- [x] **T7: Gap-Fade — Backtest POSITIV, Lane wartet auf T8.** Der einzige Kandidat, der jeder
      Nachfrage standhält: monoton über sechs Lückenklassen (bei ≤ −5 % Lücke +228,68 bp
      Tagesverlauf, t = 12,36; bei −1…−3 % noch +28,96 bp, t = 15,69), in **jeder** Teilperiode
      signifikant (t = 4,61 bis 13,31), trägt Kosten bis 50 bp je Seite, und die Beobachtungen
      überlappen nicht. Befund: `docs/research/2026-08-16-gap-fade-backtest.md`.

- [x] **T8: Gap-Fade — Ausführbarkeit geprüft, KEINE Lane.** 283 Lücken über 42 Handelstage auf
      5-Minuten-Bars: Einstieg zum Eröffnungskurs +65,59 bp, nach 5 Min +29,97, **nach 15 Min
      −0,09**, nach 30 Min −34,68 — Rendite und Trefferquote fallen beide monoton. Der Effekt
      aus T7 existiert, aber er lebt in den ersten Minuten nach der Auktion und ist für
      jemanden, der das Signal aus dem Eröffnungskurs ableitet, per Konstruktion unerreichbar.
      Befund: `docs/research/2026-08-16-gap-fade-executability.md`.
      Verbleibender Weg (Pre-Market-Schätzung + Market-on-Open-Order) steht unten unter „Offene
      Punkte für Nico" — eigene Baustelle, eigene Risiken, seine Entscheidung.

## Nicos Entscheidungen vom 2026-08-16 (abends)

1. **Krypto-Lane läuft weiter** — bewusst, trotz entschiedenem Negativbefund. Nicht antasten.
2. **Gap-Fade: erst die Vorprüfung** (T9 unten), danach entscheidet er über die Lane.
3. **Parameter-Nachjustierung: automatische Übernahme erlaubt** (T10–T12 unten). Meine
   Bedenken stehen im Plan und bleiben stehen; die Umsetzung bekommt deshalb dieselben
   Schutzmechanismen, die für die Regel-Strategien seit v14 gelten — kein Mensch muss
   zustimmen, aber eine Hürde muss geschlagen werden.
4. **Push nach origin: erledigt** (2026-08-16, Secret-Scan über alle 44 Commits sauber,
   `autopilot/work` liegt auf GitHub).

## Neue Aufgaben aus diesen Entscheidungen

- [x] **T9: Vorbörsliche Vorhersage — gemessen, WARTET AUF NICO.** Der vorbörsliche Kurs sagt
      die Lücke gut vorher (Korrelation 0,882; bei ≤ −2 % trifft die Schwelle in 61 % der
      Fälle). Die handelbare Auswahl behält **zwei Drittel des Effekts**: +42,00 bp gegen
      +65,59 bp bei rückschauender Auswahl. **Aber:** t = 1,00, Trefferquote 46,3 %, und die
      Kosten einer Market-on-Open-Order in eine Auktion mit 2–3 % Abwärtslücke sind unbekannt.
      Die Stichprobe kann nicht wachsen — vorbörsliche Kurse reichen frei nur 60 Tage zurück.
      Befund: `docs/research/2026-08-16-premarket-gap-prediction.md`.
      **Entscheidung Nico: Lane bauen (misst weiter, wo der Backtest endet, und liefert die
      echten Auktionskosten) oder abhaken?**

- [x] **T10: Lane-Parametersuche — GEBAUT, erster Lauf sagt „nichts ändern".** 650 Ereignisse,
      36 Kombinationen, simuliert mit derselben `exits.exit_reason` wie die Lane. Bester
      Kandidat 5 %/5 %/14 Tage mit +1,19 % je Trade gegen +0,77 % heute (Rang 17 von 36) —
      aber die Differenz trägt nur **t = 1,01 bei 36 Trials**, also kein belegbarer Vorsprung.
      Bleibender Hinweis: **alle** sechs besten Kombinationen wollen einen weiteren Stop.
      Befund: `docs/research/2026-08-16-lane-parameter-search.md`.
      Gesucht wurde über `PROFIT_TARGET`, `STOP_LOSS` und `MAX_HOLDING_CALENDAR_DAYS`; die
      eigene Hürde und das eigene Ledger kommen mit T12, weil erst dort verglichen wird.
- [ ] **T11: Parameter aus der DB statt aus Konstanten.** Die Lane liest ihre Knöpfe aus einer
      persistierten Zeile; fehlt sie, gelten die heutigen Konstanten als Voreinstellung. Jede
      Änderung schreibt eine Historienzeile (wann, von was auf was, mit welcher Begründung),
      sonst ist ein Track im Nachhinein nicht mehr lesbar.
- [ ] **T12: Automatische Übernahme mit Hürde.** Ein Gewinner wird übernommen, wenn er (a) die
      eigene DSR-Hürde schlägt und (b) den Amtsinhaber auf **derselben Stichprobe** schlägt
      (`evaluate_fitted_model`-Muster aus der Nacht vom 11.08. — ein gespeicherter Wert darf nie
      gegen einen frischen verglichen werden). Übernahme setzt den Forward-Track der Lane
      zurück und stempelt den Bruch, weil die Lane danach eine andere Strategie ist.
      **Sperre:** höchstens eine Parameteränderung pro Lane und Kalendermonat.

## Bilanz der Welle

**Sieben Kandidaten geprüft, null Lanes gebaut.** Turn-of-Month, 52-Wochen-Hoch,
Volumen-Kapitulation, Overnight-Drift, Short-Term-Reversal, Earnings-Premium, Gap-Fade — jeder
mit Zahlen abgelehnt, keiner mit Bauchgefühl. Kosten: ein Tag Rechnen statt sieben Lanes über
Monate Messzeit.

Drei Erkenntnisse, die über die einzelnen Absagen hinausgehen:

1. **93 % der Marktrendite entsteht über Nacht** (T4). Die bestehende Intraday-Lane handelt
   ausschließlich im renditelosen Teil des Tages und ist per Konstruktion vom einzigen
   Zeitfenster mit Rückenwind ausgeschlossen. Das gehört in jede Beurteilung ihres Ergebnisses.
2. **Zwei Kandidaten starben an derselben Messfalle** (T3 Überlappung, T5 Survivorship), die im
   Projekt schon dokumentiert war. Die Regeln aus `LOOP.md` haben zum ersten Mal konkrete
   Fehlentscheidungen verhindert, statt nur Doku zu sein.
3. **Nicht jede Frage ist an unseren Daten entscheidbar** (T6): Das Earnings-Premium liegt mit
   0,2–0,3 % unter unserer Nachweisgrenze von 0,56 pp. Mehr Messzeit hilft dagegen nicht.

## Verworfen, mit Grund

- **Pairs-Trading / Cointegration:** braucht Leerverkäufe (Regel 3).
- **Index-Rebalancing:** die Aufnahme-Ankündigungen sind frei nicht verlässlich zu bekommen.
- **Short-Interest-Squeeze:** dieselbe Datenlücke.

## Was dieser Plan bewusst NICHT tut

**Keine Lane justiert ihre Parameter selbst nach.** `PROFIT_TARGET`, `STOP_LOSS`,
`ENTRY_LOOKBACK` bleiben Konstanten. Selbstjustierende Parameter sind der schnellste Weg, sich
an Rauschen anzupassen — und bei drei Lanes ohne Urteil gibt es noch nichts, woran man justieren
könnte. Das ist eine offene Frage an Nico, keine Aufgabe (siehe unten).

## Offene Punkte für Nico

1. **Soll die Krypto-Lane weiterlaufen?** Ihr Ergebnis ist statistisch entschieden (32 Trades,
   p = 0,0003, negativ). Sie handelt weiter und zahlt weiter Gebühren. Nach dem Ausgang dieser
   Welle gibt es auch keine neue Lane mehr, für die man Kapazität frei machen müsste — die
   Frage ist jetzt allein, ob eine erledigte Messung weiterlaufen soll.
2. **Gap-Fade über Pre-Market + Market-on-Open?** Der einzige Effekt, der die Prüfungen bestand
   (T7), ist nur zum Eröffnungskurs erreichbar — und den bekommt man nur mit einer Order, die
   VOR der Auktion liegt, also auf Basis des vorbörslichen Kurses statt der fertigen Lücke.
   Technisch möglich (Alpaca kann MOO, Pre-Market-Kurse gibt es frei), aber eine eigene
   Baustelle: Wie gut sagt der Pre-Market-Kurs die Lücke vorher, wie liquide ist er bei diesen
   Titeln, und eine MOO-Order ist eine Order ohne Preisgrenze in die volatilste Auktion des
   Tages. Nur auf ausdrückliches Go.
3. **Dürfen bewährte Lanes irgendwann ihre Parameter nachjustieren?** Heute verboten (siehe
   oben). Das ist eine Grundsatzentscheidung, keine technische. Der erste konkrete Anlass liegt
   inzwischen vor: Die nächtliche Lane-Auswertung zeigt, dass 59 % des Swing-Ergebnisses aus
   dem Ablauf der Haltefrist stammen und nicht aus dem Gewinnziel — ein Hinweis, dass Ziel oder
   Frist nicht zueinander passen.
4. **Push nach origin** steht weiterhin aus.

## Kontext, den ein frischer Agent braucht

- Der Autotrader gewichtet erst nach Güte, wenn ein Sleeve **60 eigene** Beobachtungen hat
  (seit dem Fix vom 2026-08-16 zählt jeder Sleeve für sich, vorher hielt der jüngste alle auf).
  Aktueller Stand: die sechs ältesten stehen bei 19, es fehlen 41 Handelstage — etwa der
  13.10.2026. **Neue Lanes verschieben dieses Datum nicht mehr.**
- Die Arena-Anzeige wurde am 2026-08-16 umgebaut: Gesamtzeile oben, Urteil je Karte aus dem
  Trade-Test (`significance.py`), nicht mehr aus dem Kalender. Eine neue Lane erscheint dort
  automatisch, sobald sie in `LANES` und `lanes.ts` steht.
