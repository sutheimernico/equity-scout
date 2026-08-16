# No-Trade Book & Learning Loop Completion — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this
> plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die abendliche Lern-Pipeline vervollständigen: verworfene Gelegenheiten werden
protokolliert und aufgelöst („hätte es funktioniert?"), die Ereignis-Knappheit wird an der
Wurzel angegangen, die widerlegte Session-Lane wird per Backtest final entschieden, und
Gap-Fade wird als Papier-Messlane gebaut.

**Architektur:** Neues `st_rejections`-Buch in `shortterm.db` nach dem Vorbild von `st_trades`
(Erfassung im Runner, Entscheidungsfunktionen bleiben pure). Nächtliche Auflösung simuliert
verworfene Kandidaten mit derselben Exit-Logik wie `lane_tuning.simulate_event`. Gap-Fade
bekommt OPG/CLS-Orders im bestehenden Alpaca-Wrapper und läuft auf dem Paper-Konto.

**Tech Stack:** Python 3 (uv, pytest, ruff), SQLite, Alpaca Paper API, yfinance (Research).

**Auftrag (Nico, 2026-08-16 nachts):** Blanko-Go — „Ich vertraue dir, bau das wie du meinst,
mach in einer Loop bis zum Ende alles. Entscheidungen im Sinne der Vision (autonomer Trader,
der positiv tradet und aus jedem Abend lernt)."

**Entscheidungen, die dieser Plan in Nicos Namen trifft (mit Begründung):**

1. **Session-Lane wird pausiert, falls der ORB+Overnight-Backtest (Task 7) die Regel nicht
   rettet.** Ihre Einstiegsregel ist an 1.684 Ausbrüchen widerlegt; eine widerlegte Regel
   weiterlaufen zu lassen dient der Vision nicht. Der Backtest prüft vorher ehrlich Nicos
   „tagesübergreifend halten"-Idee auf derselben Einstiegsregel.
2. **Gap-Fade-Lane wird gebaut — als Messinstrument, nicht als belegtes Edge** (T9-Befund vom
   16.08.: t = 1,00). Messziel: (a) Wie gut sagt der Pre-Market-Kurs die Lücke live vorher?
   (b) Wie weit verrutscht der Fill zwischen Signal und Eröffnungsauktion? Abbruchkriterium:
   Nach 60 abgeschlossenen Trades entscheidet `significance.assess_trades` — Verdict
   „negativ" beendet die Lane. Ehrlichkeitsgrenze: Paper-MOO misst das Verrutschen
   Signal→Open, NICHT den echten Auktionsimpact — steht so in der Lane-Doku und im Frontend.
3. **Ereignis-Scope: News-Klassifikation läuft künftig über `tracked_tickers()`** (wie 8-K
   schon heute) statt über den 30er-Watchlist-Snapshot — Symmetrie-Fix, kein neues Muster.
   Kein Proxy-Backfill: Historische News sind frei nicht verfügbar, und ein Kursreaktions-Proxy
   ist „nicht das, worauf die Lane handelt" (Befund T10 vom 2026-08-16).

**Iron Rules (aus LOOP.md, gelten unverändert):** Backtest vor Lane; vernichtender Backtest
beendet den Kandidaten; Gate = `uv run pytest -q` grün + `uv run ruff check .` sauber, nur
grün committen; Überlappungsregel (unabhängige n berichten); Paper ja, Live nie; Tests
deterministisch ohne Netz.

---

## Teil A — Nicht-Trade-Buch

### Task 1: `st_rejections`-Storage

**Files:**
- Modify: `src/equity_scout/shortterm_storage.py`
- Test: bestehende Storage-Testdatei erweitern (Datei per `grep -l shortterm_storage tests/`
  finden)

- [x] **Step 1: Failing Tests** — `record_rejections` schreibt idempotent (doppelter Aufruf
  = eine Zeile), `load_open_rejections` liefert nur unaufgelöste, `resolve_rejection` setzt
  `resolved_at`/`sim_return`/`sim_exit_reason`.
- [x] **Step 2: Schema + Funktionen** in `shortterm_storage.py`, exakt im Idiom von
  `st_trades` (CREATE TABLE IF NOT EXISTS in `init_shortterm_db`, INSERT OR IGNORE):

```sql
CREATE TABLE IF NOT EXISTS st_rejections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lane TEXT NOT NULL,
    ticker TEXT NOT NULL,
    seen_at TEXT NOT NULL,          -- Zeitpunkt der Ablehnung (UTC ISO)
    reason TEXT NOT NULL,           -- kategorial: too_old | cap_full | already_held |
                                    --   not_bullish | no_quote | below_threshold | stale_premarket
    ref_price REAL,                 -- Referenzpreis zum Ablehnungszeitpunkt, falls bekannt
    detail TEXT,                    -- Klartext (Event-Text, Gap-Größe, ...)
    resolved_at TEXT,               -- NULL = offen
    sim_return REAL,                -- simulierter Return der verworfenen Gelegenheit
    sim_exit_reason TEXT,           -- profit_target | stop_loss | max_days | open_to_close | no_data
    UNIQUE (lane, ticker, seen_at, reason)
);
```

Signaturen:

```python
def record_rejections(db_path, rejections: list[dict]) -> None: ...
def load_open_rejections(db_path, lane: str | None = None) -> list[dict]: ...
def resolve_rejections(db_path, resolutions: list[dict]) -> None:
    """resolutions: [{id, resolved_at, sim_return, sim_exit_reason}] — eine Transaktion."""
def load_resolved_rejections(db_path, lane: str, *, since: str | None = None) -> list[dict]: ...
```

- [x] **Step 3: Gate + Commit** — `feat(book): add st_rejections storage for the no-trade book`

### Task 2: Swing-Lane erfasst Ablehnungen

**Files:**
- Modify: `src/equity_scout/st_swing.py` (pure bleibt pure: Ablehnungen werden ZURÜCKGEGEBEN,
  kein I/O im Modul)
- Modify: `scripts/run_shortterm.py` (`run_swing`, persistiert die Rejections)
- Test: `tests/test_st_swing.py` (bzw. die bestehende Swing-Testdatei), Runner-Tests

- [x] **Step 1: Failing Tests** — `pick_entries_explained` liefert `(picks, rejections)`;
  Fälle: zu alt → `too_old`; schon im Buch → `already_held`; Cap erreicht während Iteration →
  `cap_full` für die restlichen bullischen Events; `unknown`/`miss`-Events → `not_bullish`.
  Nicht loggen: leerer Ticker, Duplikat im selben Lauf (Rauschen, keine Gelegenheit),
  `earnings_filed`/`other_8k` (per Design richtungslos).
- [x] **Step 2: Implementierung** — neue Funktion, `pick_entries` wird dünner Wrapper:

```python
def pick_entries_explained(events, book, *, now=None, max_positions=MAX_POSITIONS
                           ) -> tuple[list[dict], list[dict]]:
    """Wie pick_entries, plus zweiter Rückgabewert: warum die anderen NICHT dran sind.

    Eine Rejection ist {"ticker", "reason", "seen_at", "detail"} — reine Daten, kein I/O.
    """

def pick_entries(events, book, *, now=None, max_positions=MAX_POSITIONS) -> list[dict]:
    return pick_entries_explained(events, book, now=now, max_positions=max_positions)[0]
```

- [x] **Step 3: Runner-Hook** — in `run_swing` (scripts/run_shortterm.py): Rejections aus
  `pick_entries_explained` einsammeln, den Preis-Skip (`no_quote`, bisher Zeile ~174) als
  weitere Rejection erfassen, am Ende des Laufs via `record_rejections` schreiben
  (nach `persist_lane_step`; Idempotenz trägt die UNIQUE-Constraint).
- [x] **Step 4: Gate + Commit** — `feat(swing): record rejected opportunities in the no-trade book`

### Task 3: Nächtliche Auflösung der Rejections

**Files:**
- Create: `src/equity_scout/rejection_review.py`
- Create: `scripts/run_rejection_review.py`
- Modify: `scripts/nightly_train.sh` (neuer Step `rejection_review` direkt VOR `lane_review`)
- Test: `tests/test_rejection_review.py`

- [x] **Step 1: Failing Tests** — Swing-Rejection älter als `MAX_HOLDING_CALENDAR_DAYS`
  (7 Kalendertage) wird mit derselben Exit-Logik wie die Lane simuliert
  (`lane_tuning.simulate_event`-Muster über die Closes ab Ablehnungstag, Regeln aus
  `lane_params.load_params` mit den `st_swing`-Defaults); jüngere bleiben offen;
  Rejection ohne Kursdaten wird mit `sim_exit_reason="no_data"` geschlossen statt ewig
  offen zu bleiben. Reine Funktionen, Kursdaten werden hereingereicht.
- [x] **Step 2: Implementierung** — Kernfunktion:

```python
def resolve_swing_rejections(rejections: list[dict], closes_by_ticker: dict[str, pd.Series],
                             rules: ExitRules, *, now: datetime) -> list[dict]:
    """Gibt [{id, sim_return, sim_exit_reason, resolved_at}] für alles Fällige zurück."""
```

  Script lädt offene Rejections, holt Preise über den bestehenden `load_price_history`-Pfad,
  ruft die pure Funktion, schreibt via `resolve_rejections`. Ehrlichkeitszeile im Output:
  simulierte Returns sind BRUTTO (keine Kosten) — sie beantworten „war die Ablehnung richtig?",
  nicht „hätten wir Geld verdient?".
- [x] **Step 3: Nightly verdrahten** — `step rejection_review "$PY" scripts/run_rejection_review.py`
  vor dem `lane_review`-Step einfügen.
- [x] **Step 4: Gate + Commit** — `feat(book): resolve rejected opportunities nightly`

### Task 4: `lane_review` zeigt die Verworfenen

**Files:**
- Modify: `src/equity_scout/lane_review.py`, `scripts/run_lane_review.py`
- Test: `tests/test_lane_review.py` (bzw. bestehende Review-Testdatei)

- [x] **Step 1: Failing Tests** — `review_lane` akzeptiert `rejections: list[dict] | None`
  (aufgelöste der letzten 7 Tage); Review-Notes enthalten: Anzahl aufgelöst, Anteil mit
  positivem `sim_return`, mittlerer `sim_return`, und den direkten Satz „Verworfene hätten
  im Schnitt X gebracht, Gehandelte brachten Y" (brutto, steht dabei).
- [x] **Step 2: Implementierung** — `run_lane_review.py` lädt `load_resolved_rejections`
  je Lane und reicht sie durch; `render` druckt den Abschnitt nur, wenn Auflösungen da sind.
- [x] **Step 3: Gate + Commit** — `feat(review): nightly review covers the no-trade book`

## Teil B — Ereignis-Knappheit

### Task 5: News-Scope auf `tracked_tickers()`

**Files:**
- Modify: `scripts/run_evidence.py` (`_watchlist_news`)
- Test: bestehende run_evidence-Tests erweitern

- [x] **Step 1: Failing Test** — News-Sammlung fragt die `tracked_tickers()`-Menge ab
  (Watchlist ∪ Portfolio ∪ Arena-Lanes), nicht nur `load_latest_watchlist`.
- [x] **Step 2: Implementierung** — dieselbe Quelle, die `collect_8k` schon nutzt; Limit 5
  Headlines je Ticker bleibt (Rate-Hygiene).
- [x] **Step 3: Gate + Commit** — `fix(evidence): classify news for tracked tickers, not just the watchlist snapshot`

### Task 6: `guidance_up` kann matchen

**Files:**
- Modify: `src/equity_scout/evidence/event_classifier.py`
- Test: `tests/test_event_classifier.py` (bzw. bestehende Classifier-Testdatei)

- [x] **Step 1: Failing Tests** mit realen Headline-Mustern: „raises full-year guidance",
  „lifts FY26 outlook", „boosts revenue forecast" → `guidance_up`; Negationen („cuts
  guidance", „withdraws outlook", „does not raise guidance") → NICHT `guidance_up`.
  Honesty over recall: nur eindeutige Verben (raise/lift/boost/hike).
- [x] **Step 2: Implementierung** — Regex-Erweiterung im bestehenden Stil (Verb+Objekt-Paar,
  Negation killt den Treffer). Kontext: Live-Zählung hält 0 `guidance_up` von 603
  News-Zeilen — die Klasse existiert bisher nur auf dem Papier.
- [x] **Step 3: Gate + Commit** — `fix(evidence): guidance_up headlines are recognised`

## Teil C — Session-Lane final entscheiden

### Task 7: Backtest „ORB-Einstieg + Overnight halten"

**Files:**
- Create: `scripts/research_orb_overnight.py` (persistiert — Lektion aus T8 vom 16.08.:
  Ad-hoc-Skripte fehlen hinterher)
- Create: `docs/research/2026-08-17-orb-overnight-backtest.md`

- [x] **Step 1: Skript** — yfinance 15-Min-Bars (60 Tage, so weit frei verfügbar), gleiche
  ORB-Definition wie `st_session.opening_range` (2 Bars, Breakout über High). Drei Arme je
  Signal, ein Signal pro Ticker/Tag (keine Überlappung):
  (a) Zwangsflat zum Close (= heutige Lane, Kontrolle);
  (b) Halten bis zum nächsten Open (erbt den Overnight-Drift);
  (c) Halten mit Swing-Exits (5 %/3 %/7 Tage) auf der Tagesschluss-Serie.
  **Fairness-Benchmark:** derselbe Halte-Return OHNE ORB-Bedingung über alle Titel/Tage —
  wenn ein Arm nur den Drift einsammelt, den jeder bekommt, ist die Einstiegsregel weiterhin
  wertlos. t-Werte, Trefferquoten, unabhängige n berichten.
- [x] **Step 2: Lauf + Befund** nach `docs/research/2026-08-17-orb-overnight-backtest.md`.
- [x] **Step 3: Commit** — `research: ORB entry with overnight holding, tested against plain drift`

### Task 8: Entscheidung vollziehen (abhängig vom Task-7-Befund)

**Files (Pausier-Fall):**
- Modify: `scripts/install_crontab.sh` (SESSION_LINE entfernen; `st_session_sweep` im Nightly
  bleibt als Sicherheitsnetz), `frontend/src/lanes.ts` (what-Text um Pausier-Grund ergänzen),
  `PLAN.md`

- [x] **Step 1: Entscheidung nach Iron Rule** — rettet der Backtest die Einstiegsregel in
  keinem Arm gegen den Fairness-Benchmark, wird die Lane pausiert (Cron-Zeile raus,
  `install_crontab.sh` ausführen; Buch und Historie bleiben lesbar, Reaktivierung = eine
  Cron-Zeile). Rettet er sie, stattdessen einen Umbau-Task hier anfügen (neuer Backtest-Arm
  wird die Lane-Regel) und NICHT pausieren.
- [x] **Step 2: Frontend-Text + PLAN.md, Gate + Commit**

## Teil D — Gap-Fade-Papierlane

### Task 9: OPG/CLS-Orders im Alpaca-Wrapper

**Files:**
- Modify: `src/equity_scout/alpaca_broker.py`
- Test: `tests/test_alpaca_broker.py` (Fake-HTTP-Muster der bestehenden Tests)

- [x] **Step 1: Failing Tests** — `auction_payload(ticker, *, qty, side, auction)` →
  `{type: "market", time_in_force: "opg" | "cls", ...}`; `place_auction_order(...)` POSTet
  und liefert `BrokerOrder`; Mengen werden wie bei `bracket_payload` auf ganze Stücke
  abgerundet.
- [x] **Step 2: Implementierung + Gate + Commit** —
  `feat(broker): market-on-open and market-on-close orders`

### Task 10: `st_gapfade.py` — pure Entscheidungslogik

**Files:**
- Create: `src/equity_scout/st_gapfade.py`
- Test: `tests/test_st_gapfade.py`

- [x] **Step 1: Failing Tests** — Kandidat mit Pre-Market-Gap ≤ −2 % → Pick; Gap in
  (−2 %, −1 %] → Rejection `below_threshold` (mit Gap-Größe im detail — das ist der
  wertvollste Eintrag im Nicht-Trade-Buch: er kalibriert die Schwelle live); Pre-Market-Kurs
  älter als `MAX_QUOTE_AGE_MINUTES` → Rejection `stale_premarket`; Cap `MAX_POSITIONS=3`;
  bereits heute gehandelt → kein zweiter Einstieg.
- [x] **Step 2: Implementierung** — Konstanten im `st_swing`-Stil:

```python
GAP_THRESHOLD = -0.02        # T9: Schwelle trifft die echte Lücke in 61 % der Fälle
LOG_THRESHOLD = -0.01        # ab hier wird abgelehnt UND protokolliert
ENTRY_FRACTION = 0.15
MAX_POSITIONS = 3
MAX_QUOTE_AGE_MINUTES = 20   # IEX-Pre-Market ist dünn; alter Kurs = kein Signal

def pick_gap_entries(premarket, prev_closes, book, *, now
                     ) -> tuple[list[dict], list[dict]]:
    """(picks, rejections) — pure, keine I/O. premarket: {ticker: (price, quoted_at)}."""
```

- [x] **Step 3: Gate + Commit** — `feat(gapfade): pure decision logic for the gap-fade lane`

### Task 11: Runner, Registrierung, Cron

**Files:**
- Modify: `scripts/run_shortterm.py` (`run_gapfade`, `--lane gapfade`),
  `src/equity_scout/shortterm_storage.py` (LANES/LANE_LABELS),
  `src/equity_scout/alpaca_data.py` (Pre-Market-Letztkurse via latest-trade-Endpoint),
  `frontend/src/lanes.ts`, `scripts/install_crontab.sh` (GAPFADE_LINE)
- Test: Runner-Tests (Fake-Broker/Fake-Daten), Frontend-Tests

- [x] **Step 1: Failing Tests** — Runner platziert vor der Eröffnung MOO-Orders für Picks und
  eine CLS-Order je gefüllter Position; außerhalb des Fensters (interner ET-Check 9:00–9:28)
  tut er nichts; `st_state`-Tagesmarker verhindert Doppelplatzierung; Fills werden nach der
  Eröffnung zurückgelesen und als Trades gebucht (Signal-Kurs → `expected_price`,
  Auktions-Fill → `actual_price` in `st_executions` — DAS ist die Messgröße der Lane).
- [x] **Step 2: Implementierung** — Buch 10.000 USD wie alle Lanes; Rejections aus
  `pick_gap_entries` via `record_rejections`; Universum = `tracked_tickers()`;
  Cron `GAPFADE_LINE`: `*/5 14-16 * * 1-5` lokal, geflockt, internes ET-Gate trägt die
  Sommer-/Winterzeit. Frontend-Karte trägt die Ehrlichkeitszeile („Paper misst das
  Verrutschen Signal→Eröffnung, nicht den Auktionsimpact").
- [x] **Step 3: Gap-Rejections abends auflösen** — in `rejection_review.py`:
  `below_threshold`- und `stale_premarket`-Einträge mit Open→Close des Ablehnungstags
  auflösen (`sim_exit_reason="open_to_close"`), Tagesdaten über den bestehenden Preis-Pfad.
- [x] **Step 4: `install_crontab.sh` ausführen, Gate + Commit** —
  `feat(gapfade): paper lane measuring the opening auction`

## Teil E — Abschluss

### Task 12: Doku, Outcome, Push, Verify-Auftrag

- [x] **PLAN.md aktualisieren** (Arena-Abschnitt: Session-Entscheidung, gapfade neu,
  Nicht-Trade-Buch).
- [x] **Outcome-Abschnitt an diesen Plan** (was umgesetzt, Abweichungen, offene Punkte —
  erst NACH der Umsetzung schreiben, mit echten Zahlen).
- [x] **Session-Doku** nach `docs/sessions/`.
- [x] **Push nach origin** (Secret-Scan-Hook läuft beim Push).
- [x] **Verify-Auftrag für die Nacht Mo→Di** (Nightly läuft Di–Sa 02:30): `train.log` prüfen —
  Premiere von `rejection_review`, `lane_review`, `lane_tuning` in der echten Kette; erste
  Gap-Fade-Ausführung Mo ~15:20 lokal prüfen (`shortterm.log`). Übernimmt der Session-Wächter,
  sonst die nächste Session.

---

## Outcome (2026-08-16, ~21:45–22:35 — Session mit Nicos Blanko-Go)

**Alle 12 Tasks umgesetzt. Gate durchgehend grün: 2.145 py-Tests + ruff sauber + 127
Frontend-Tests. 11 Commits auf `autopilot/work`.** (Datumskonvention: Research-Doc und
Pausierung tragen den 17.08., weil sie ab dem Handelstag Montag wirken; gebaut wurde alles
am Abend des 16.08.)

**Der entscheidende Backtest (Task 7,** `docs/research/2026-08-17-orb-overnight-backtest.md`**):**
2.550 ORB-Signale, 89 Titel, 60 Handelstage. (a) Zwangsflat −5,45 bp (t = −2,20, repliziert
die Widerlegung unabhängig); (b) Overnight +0,25 bp, gegen den bedingungslosen Benchmark
+3,63 bp bei Welch-t = 0,62 — nichts; (c) Swing-Exits +32,33 bp, aber der Einstieg OHNE
Bedingung lieferte +52,66 bp — die ORB-Bedingung schadet (gepaart Cluster-t = −11,4).
→ Session-Lane pausiert (Task 8), Cron-Zeile entfernt und Entfernung vom line-managenden
Installer verwaltet.

**Abweichungen vom Plan:**
- `resolve_rejection` wurde als Batch-Funktion `resolve_rejections` gebaut (eine Transaktion
  für hunderte nächtliche Auflösungen).
- `sim_exit_reason` trägt die deutschen Kurztexte aus `exits.exit_reason` („Kursziel
  erreicht", „Stop-Loss ausgelöst", …) statt der im Plan skizzierten englischen Tokens —
  Konsistenz mit dem Exit-Mix von `lane_tuning` und dem Review-Text.
- Task 6 war anders als geplant KEINE Regex-Lücke allein: Die `guidance_up`-Patterns
  existierten bereits. Der Haupttäter war die Dual-Match-Regel — „beats estimates and
  raises guidance", die häufigste bullische Headline überhaupt, matchte zwei Kategorien
  und fiel auf `unknown`. Fix: Nur GEGENSÄTZLICHE Richtungen bleiben unknown; dazu das
  Guidance-Fenster 20→30 Zeichen („raises fiscal 2026 full-year guidance").
- Gap-Fade-Phasenreihenfolge: settle vor absorb, damit eine soeben platzierte Order nie im
  selben Lauf gepollt wird; MOC-Exits, die terminal sterben, werden neu platziert, damit
  keine Position hängen bleibt.
- Nachschärfung aus dem Self-Review: `_gapfade_settle_exits` captured die SPY-Benchmark
  beim ersten Settle — ohne das hätte jede Valuation-Zeile `benchmark_return=NULL` getragen.

**Was jetzt automatisch passiert:**
- Mo ~15:00–15:28 lokal: erster Gap-Fade-Signallauf (Cron `*/5 14-16`, ET-Gate im Runner).
- Nacht Mo→Di 02:30: Premiere der vollen Lernkette in echt — `st_gapfade_settle` →
  `rejection_review` → `lane_review` (jetzt mit Nicht-Trade-Vergleich) → `lane_tuning`.
  `train.log` danach prüfen (Verify-Auftrag, Session-Wächter bzw. nächste Session).

**Offen (Needs Nico):** Rechner freitags 15:30–22:00 laufen lassen; DASH_TOKEN- und
Telegram-Token-Rotation (aus früheren Sessions); Cockpit-Handy-Durchklick. Die
Krypto-Lane läuft unverändert weiter (Nicos Entscheidung vom 16.08.).
