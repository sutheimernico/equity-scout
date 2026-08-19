# Plan: Katalysator-Radar + Ignition-Lane (v16)

**Datum:** 2026-08-19
**Auftrag (Nico, wörtlich):** „ich will sowas einfach künftig vorab sehen oder wenn es passiert mit auf
den Zug springen können, dafür soll das system sorgen, dafür soll es news ziehen, dafür soll es aktien
sekündlich/minütlich beobachten und die Sprünge sehen und mit auf den Zug springen … oder halt vorab
das schon antizipieren aus gerüchten oder sonstiges … geht aber nicht nur um die Moderna branche
sondern in allen."

**Anlass:** Moderna +127 % am 2026-08-19 (Phase-3-Krebsvakzin mit Merck + FDA-Zulassung mFLUSIVA).
Das System hat es nicht gesehen: kein Trade, kein Alarm, kein Event. MRNA lag im Scout auf Rang
1852/2038 und war in keiner der drei Scope-Mengen (Watchlist 30 Titel, Event-Scope 62 Titel,
Session-Universum 12 Titel).

---

## Diagnose: vier unabhängige Blindheiten

| # | Blindheit | Belegter Zustand |
|---|---|---|
| B1 | **Kein marktweiter Blick.** | Intraday wurden nur 12 hardcodierte Megacaps beobachtet (`intraday_bars.SESSION_UNIVERSE`). |
| B2 | **News-Scope an Watchlist gekoppelt.** | `tracked_tickers()` = Watchlist ∪ Depot ∪ Lanes = 30–70 Titel. Alpacas News-Endpunkt liefert marktweit, war aber nur in `data/news_history.py` für eine Einmal-Forschungsfrage verdrahtet. |
| B3 | **Kein Vorab-Kalender.** | Nur `earnings_dates` (yfinance, 56 Titel). Null Treffer im Repo für FDA/PDUFA/ClinicalTrials. |
| B4 | **Kein Spike-Signal.** | `volume_signals.py` ist EOD und auf ein 7-ETF-Sleeve begrenzt; `st_highbreak.py` ist toter Code auf Tagesschlüssen. |

## Verifizierte Datenlage (live gegen die API geprüft, 2026-08-19)

| Quelle | Status | Befund |
|---|---|---|
| `/v1beta1/screener/stocks/movers?top=50` | **200, 0.4 s** | 50 Gainer + 50 Loser **marktweit**, auf **SIP**-Basis — obwohl unser Bar-Feed nur IEX ist. MRNA stand mit +127 % drin. Ein Call ersetzt jeden Universums-Sweep. |
| `/v1beta1/screener/stocks/most-actives?top=50` | **200, 0.4 s** | Volumen-Ranking marktweit (MRNA: 120,9 Mio Stück). |
| `/v2/stocks/snapshots?symbols=…` | **200, 0.4 s** | Batch: `dailyBar` + `prevDailyBar` + `minuteBar` je Titel. Volumen ist IEX-dünn, das **Verhältnis** heute/Vortag bleibt aber valide (MRNA 17,6×). |
| `/v1beta1/news` **ohne** Symbol-Filter | **200, 0.4 s** | Marktweiter Benzinga-Wire, sekundengenau, Paginierung per Token. Löst B2 vollständig. |
| `/v2/assets` | **200, 1,6 s** | 14 248 Assets, 13 384 handelbar, 7 551 teilbar; Warrants und 2×-ETFs sind formal „tradable". |
| `/v2/stocks/quotes/latest` | **200** | **Spreads bei echten Spike-Titeln: MRNA 400 bp, MRNY 326 bp, ZSTK 2584 bp** — gegen AAPL 1 bp. |
| Paper-Konto | equity 99 879 $ | `multiplier = 4`, `shorting_enabled = true`. Hebel technisch verfügbar. |

### Zwei Befunde, die das Design bestimmen

1. **Der Movers-Endpunkt ist nicht vertrauenswürdig.** `FIXX` wurde mit **+1378 %** gemeldet; die
   echten Bars sagen +7 % (`dailyBar` 0,965 gegen `prevDailyBar` 0,8978), und die letzte Minutenbar
   des Titels stammt vom **25.03.2024**. Der Screener rechnet gegen veraltete Schlusskurse. Ein
   Scanner, der Movers ungeprüft glaubt, kauft Datenmüll. → **Zwei-Quellen-Bestätigung ist Pflicht:
   ein Kandidat gilt erst, wenn Snapshot-Bars den Sprung unabhängig bestätigen.**
2. **Der Spread ist der bindende Engpass, nicht die Latenz.** Bei 2584 bp Spread ist ein Titel
   unhandelbar, egal wie schön der Sprung aussieht — der Roundtrip kostet mehr als der erhoffte
   Gewinn. → **Spread-Obergrenze als hartes Eintrittskriterium, und Entry ausschließlich per
   Limit-Order.** Market-Orders sind in diesem Segment strukturell falsch.

---

## Architektur: fünf Schichten, ein gemeinsames Signalbuch

```
Schicht 1  IGNITION-SCAN (minütlich, Marktfenster)     "es passiert JETZT"
           movers + most-actives  ->  Cross-Check gegen Snapshots  ->  Filter  ->  Signal
Schicht 2  NEWS-SWEEP (minütlich, rund um die Uhr)     "es wird gerade bekannt"
           globaler Wire ohne Ticker-Filter  ->  Katalysator-Klassifikation  ->  Signal
Schicht 3  KATALYSATOR-KALENDER (täglich)              "es steht bevor"
           ClinicalTrials.gov + Earnings  ->  Termin-Vorwarnung  ->  Signal
                                   |
                                   v
                      catalyst_signals  (eine Tabelle, ein Schema)
                                   |
                 +-----------------+------------------+
                 v                                    v
Schicht 4  IGNITION-LANE (Paper, Limit-Entry)   Schicht 5  ALARM + COCKPIT
           aufspringen mit Stop/Trail                    Telegram + /api/catalysts
```

**Trennung wie im Rest des Projekts:** reine Entscheidungslogik in Modulen ohne I/O, alles I/O im
Runner. Schicht 1–3 sind *Erkennung* (kein Geldrisiko, sofort produktiv). Schicht 4 ist *Ausführung*
(Paper, mit Stop-Kriterium). Die Trennung ist bewusst: Nico soll **sehen**, auch wo wir bewusst
nicht handeln.

---

## Aufgaben

### A — Signalbuch (Fundament)
- [x] A1 `catalyst_storage.py`: Tabelle `catalyst_signals` (source, ticker, kind, score, detail,
      seen_at, ref_price, verified, traded) + Idempotenz-Schlüssel, damit ein Minuten-Rerun nichts
      doppelt schreibt. Eigene DB-Datei `catalysts.db` (kein Schema-Konflikt mit laufenden Strängen).
- [x] A2 Tests: Idempotenz, Dedup pro Tag, Abfragen nach Zeitfenster.

### B — Schicht 1: Ignition-Scanner
- [x] B1 `catalyst_scan.py` (pure): `pick_ignitions(movers, most_actives, snapshots, assets, quotes)`
      → (Signale, Ablehnungen mit Grund). Filterkette: Handelbarkeit → Instrumententyp
      (keine Warrants/Rights/Units/gehebelten ETFs) → Mindestpreis → Mindest-Dollarvolumen →
      **Snapshot-Cross-Check** (Movers-Behauptung vs. echte Bars, Toleranz) → Sprungschwelle →
      Volumenbestätigung (heute/Vortag) → **Spread-Obergrenze**.
- [x] B2 `alpaca_screener.py`: `fetch_movers`, `fetch_most_actives`, `fetch_snapshots`,
      `fetch_quotes`, `fetch_tradable_assets` (mit Cache) + 429-Backoff.
- [x] B3 Runner `scripts/run_catalyst_scan.py` + Cron minütlich im Marktfenster.
- [x] B4 Tests: jede Filterstufe einzeln, inklusive des FIXX-Falls (Movers behauptet +1378 %,
      Bars sagen +7 % → muss abgelehnt werden) und des ZSTK-Falls (2584 bp Spread → abgelehnt).

### C — Schicht 2: marktweiter News-Sweep
- [x] C1 `catalyst_news.py` (pure): `classify_catalyst(headline)` → Katalysator-Typ + Stärke.
      Typen, die Sprünge machen: FDA-Zulassung/-Ablehnung, Studienergebnis, Übernahme/Fusion,
      Guidance, Großauftrag, Insolvenz, Aktienrückkauf, Analysten-Ruck, Index-Aufnahme.
      Branchenneutral — Keywords decken Pharma, Tech, Industrie, Rohstoff, Finanz ab.
- [x] C2 `news_sweep.py`: inkrementelles Ziehen des globalen Wire per Zeitstempel-Cursor,
      kein Ticker-Filter. Cursor persistent, damit nach Ausfall nachgeholt wird.
- [x] C3 Runner `scripts/run_news_sweep.py` + Cron minütlich.
- [x] C4 Tests: Klassifikation je Typ, Cursor-Fortschritt, Mehrfach-Symbol-News.

### D — Schicht 3: Katalysator-Kalender (vorab)  → **delegiert**
- [x] D1 `catalyst_calendar.py`: ClinicalTrials.gov v2 API — Studien in Phase 2/3 mit
      Primary-Completion-Date in den nächsten N Tagen, Sponsor → Ticker-Zuordnung.
- [x] D2 Integration in das Signalbuch als `kind='upcoming'` mit Vorlaufzeit.
- [x] D3 Runner + täglicher Cron. Tests ohne Netz (Fixtures).

### E — Schicht 4: Ignition-Lane (aufspringen)
- [x] E1 `st_ignition.py` (pure): `pick_entries(signals, book, …)` → Limit-Preis (Bid + Anteil des
      Spreads), Positionsgröße, Chase-Schutz (kein Einstieg nach zu weit gelaufenem Move),
      Sektor-/Titel-Cap, Tages-Cap. `pick_exits`: Trailing-Stop, Zeit-Stop, Katalysator-Verfall.
- [x] E2 Limit-Order-Pfad in `alpaca_broker.py` (`place_limit`, `place_limit_bracket`) — fehlte.
- [x] E3 Lane in `run_shortterm.py` als `--lane ignition` + Stop-Kriterium über
      `significance.assess_trades` nach 60 geschlossenen Trades.
- [x] E4 Tests: Limit-Preis-Rechnung, Chase-Schutz, Caps, Exits.

### F — Schicht 5: Sichtbarkeit
- [x] F1 Telegram-Alarm bei jedem verifizierten Signal über Alarmschwelle (mit Cooldown).
- [~] F2 `/api/catalysts` steht und liefert; die **Cockpit-Kachel im Frontend fehlt noch**
      (bewusst offen gelassen — `frontend/` gehört einem anderen Strang).
- [x] F3 Watchdog-Eintrag: schlägt Alarm, wenn der Scanner im Marktfenster stillsteht.

### G — Abschluss
- [x] G1 Gate: `uv run pytest -q` grün + `uv run ruff check .` clean.
- [x] G2 Doku: README-Abschnitt, PLAN.md, AUTOPILOT_LOG.md, Outcome hier.
- [x] G3 Live-Rauchtest gegen die echte API (Scanner + News-Sweep im Trockenmodus).

---

## Ehrlichkeitsgrenzen (gelten und werden angezeigt)

1. **Der Sprung selbst ist nicht fangbar, wenn die News über Nacht kommt.** Moderna eröffnete
   gegappt; wer nicht vorher drin war, kauft nach dem Move. Was diese Lane messbar adressiert, ist
   die **Fortsetzung** nach dem Sprung, nicht der Sprung.
2. **IEX sieht 2–3 % des Volumens.** Die Sprung-*Erkennung* läuft über SIP-basierte Screener und ist
   davon unberührt; die Bar-*Bestätigung* ist IEX-dünn — deshalb wird nur das Verhältnis zum Vortag
   im selben Feed bewertet, nie ein absolutes Volumen.
3. **Paper-Fills messen nicht Marktwirkung.** Bei einem Titel, der eben +100 % gemacht hat, ist der
   Unterschied zwischen Paper-Limit-Fill und echter Ausführung größer als sonst. Die Lane
   protokolliert Signalpreis vs. Fillpreis, damit diese Lücke messbar wird statt behauptet.
4. **Hebel bleibt bei 1× bis Trades vorliegen.** Das Konto erlaubt 4×. Hebel auf eine ungetestete
   Einstiegsregel multipliziert einen unbekannten Erwartungswert — der Parameter existiert und ist
   eine Zeile, aber er wird erst nach dem Stop-Kriterium-Urteil gestellt.
5. **„Gerüchte vorab" ist ehrlich benannt Termin-Vorwarnung.** Wir bauen keinen Social-Media-Scraper
   (bewusst verworfen, siehe Matrix-Plan). Was wir bauen: bekannte Termine vorher kennen und
   ungewöhnliches Verhalten vor der Meldung sichtbar machen.

---

## Outcome (2026-08-19, abends)

**Gate: 2368 Tests grün, `ruff check .` clean.** 22 der 23 Aufgaben umgesetzt, eine
teilweise (F2). Alles unten steht live und ist per Cron verdrahtet.

### Was jetzt läuft

| Kadenz | Was | Cron |
|---|---|---|
| jede Minute im Marktfenster | Ignition-Scan + Ignition-Lane | `* 15-23 * * 1-5 catalyst_radar.sh` |
| jede Minute rund um die Uhr | marktweiter News-Sweep | `* * * * * news_sweep.sh` |
| täglich 12:30 | Katalysator-Kalender | `30 12 * * * catalyst_calendar.sh` |

### Erste echte Läufe (nicht Fixtures)

- Scan: 100 marktweite Kandidaten → **1 Signal** (MRNA +140 %, Güte 0,93), 99 abgelehnt.
  Telegram-Alarm zugestellt.
- News-Sweep über 6 h: 171 Meldungen → **13 Signale**, darunter das echte Moderna/Merck-
  Studienergebnis, eine FDA-Zulassung (FEMY) und sechs Übernahmen.
- Kalender: **186 Vorab-Termine** (145 Studienabschlüsse + 41 Earnings), idempotent.
- Ignition-Lane: **kein Einstieg** — MRNA per Chase-Schutz abgelehnt und protokolliert
  („Bewegung +140 % schon zu weit gelaufen"). Genau das gewünschte Verhalten.

### Fünf Fehler, die echte Daten aufgedeckt haben (alle als Test gepinnt)

1. **Movers lügt.** FIXX mit +1378 % gemeldet, Bars sagten +7 % — der Endpunkt rechnete
   gegen einen Schlusskurs, dessen Minutenbar von 2024 stammte. → Bar-Gegenprüfung Pflicht.
2. **Derivate auf den springenden Titel.** MRNY (YieldMax-Optionsprämien-ETF auf MRNA) kam
   im ersten Live-Lauf durch. → gepoolte Vehikel raus, per Wortgrenzen-Regex.
3. **Substring-Matching.** `" trust"` verwarf „Trustmark Corporation", eine normale Bank.
4. **CRO-Beauftragung als Studienergebnis.** Ein nacktes „Phase 2/3" traf eine
   Dienstleister-Meldung. → Ergebniswörter sind Pflicht.
5. **Analystenreaktion als Quartalszahlen.** Die häufigste „Earnings"-Schlagzeile am Wire
   ist „These Analysts Revise Their Forecasts After Q2" — da ist die Bewegung längst vorbei.
   → eigene, schwache Klasse, unter der Alarmschwelle.

Punkt 2 und 5 hätten den Alarm zugemüllt, und ein zugemüllter Alarm wird stummgeschaltet.

### Offene Punkte

- **Cockpit-Kachel** im Frontend (Endpunkt `/api/catalysts` liefert bereits).
- **Ein bekannter Fehltreffer im Sponsor-Matching:** „Polaris Group" (Taiwan-Biotech) → PII
  (Polaris Inc., Motorräder). Braucht eine Ausnahmeliste.
- **Ablehnungen des Kalenders deduplizieren nicht tagesgenau** (3 Zeilen/Tag Rauschen), weil
  `catalyst_rejections.seen_at` dort den Laufzeitstempel trägt.
- **Kein FDA-/PDUFA-Kalender** — es existiert keine freie Termindatenbank. Die Vorab-Deckung
  ist damit Pharma-Studien + 56-Titel-Earnings, nicht branchenweit. Der einzige echte
  Cross-Sector-Hebel wäre eine breitere Earnings-Terminquelle.
- **Alarmschwellen sind ungemessen** (Güte 0,45, Cooldown 6 h). Die Ablehnungsbücher sammeln
  ab jetzt die Daten, um sie zu begründen.
