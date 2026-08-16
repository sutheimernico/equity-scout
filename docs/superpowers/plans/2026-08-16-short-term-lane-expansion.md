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

- [ ] **T4: Overnight-Drift, nur Backtest.** Kaufen zum Schluss, verkaufen zur Eröffnung.
      Brutto spektakulär (717 % vs. 12 %, 1993–2020), aber die Literatur ist eindeutig: die
      Handelskosten löschen den Effekt. Wir haben OHLC und einen Kostenboden — der Backtest
      beantwortet, ob unter Alpaca-Paper-Bedingungen etwas übrig bleibt. **Lane nur bei
      positivem Nettobefund.**
- [ ] **T5: Short-Term-Reversal, nur Backtest.** Kauft die Wochenverlierer. Neuere Arbeiten
      zeigen: der Effekt sitzt in der Intraday-Bewegung, nicht in der Overnight-Bewegung — der
      Backtest muss beide trennen, sonst misst er Rauschen. **Lane nur bei positivem
      Nettobefund.**

### Welle 3 — wenn Welle 1 und 2 stehen

- [ ] **T6: Earnings-Announcement-Premium.** Kauft wenige Tage VOR dem Termin, verkauft direkt
      danach — das Gegenstück zur bestehenden Swing-Lane, die nach der Meldung kauft. Der
      Earnings-Kalender existiert seit v7.
- [ ] **T7: Gap-Fade.** Handelt gegen die Eröffnungslücke. Intraday-Bars über Alpaca vorhanden.
      Nachbar der bestehenden Intraday-Lane, deshalb bewusst zuletzt — geringste Unabhängigkeit
      vom Bestand.

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
   p = 0,0003, negativ). Sie handelt weiter und zahlt weiter Gebühren. Stilllegen würde
   Messkapazität für die neuen Lanes frei machen.
2. **Dürfen bewährte Lanes irgendwann ihre Parameter nachjustieren?** Heute verboten (siehe
   oben). Das ist eine Grundsatzentscheidung, keine technische.
3. **Push nach origin** steht weiterhin aus — sieben Commits auf `autopilot/work`.

## Kontext, den ein frischer Agent braucht

- Der Autotrader gewichtet erst nach Güte, wenn ein Sleeve **60 eigene** Beobachtungen hat
  (seit dem Fix vom 2026-08-16 zählt jeder Sleeve für sich, vorher hielt der jüngste alle auf).
  Aktueller Stand: die sechs ältesten stehen bei 19, es fehlen 41 Handelstage — etwa der
  13.10.2026. **Neue Lanes verschieben dieses Datum nicht mehr.**
- Die Arena-Anzeige wurde am 2026-08-16 umgebaut: Gesamtzeile oben, Urteil je Karte aus dem
  Trade-Test (`significance.py`), nicht mehr aus dem Kalender. Eine neue Lane erscheint dort
  automatisch, sobald sie in `LANES` und `lanes.ts` steht.
