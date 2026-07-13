# Always-on Copilot v6 — Voices, ML-Bot-Familie, Dauerbetrieb, IA-Overhaul (2026-07-13)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (inline, single-threaded —
> Pakete haben Abhängigkeiten). Checkboxen (`- [ ]`) sind der Fortschritts-Tracker.

**Goal:** Der Copilot läuft als Hintergrund-Anwendung (30-min-Takt), trackt zusätzlich was bekannte
Investoren öffentlich SAGEN, lässt erstmals ML-Modelle wirklich forward traden (Long- UND Short-Bot,
paper-only) mit sichtbarer Lernkurve, und bekommt eine Navigation, in der man immer weiß, wo man ist.

**Architecture:** Alles baut auf vorhandene Seams: Voices als fünfter Evidence-Collector nach dem
`CollectorResult`-Muster; die Bots als `Strategy`-Implementierungen über `ForwardAccount`;
Lernkurve aus Registry-/Ledger-Daten, die schon existieren, aber nicht aufbereitet sind; Dauerbetrieb
als zweite Cron-Kette neben `daily_copilot.sh`. Kein neues Framework, keine neuen Pflicht-Deps.

**Tech Stack:** Python 3 + httpx/yfinance/scikit-learn (+ optional catboost, bereits gepinnt),
SQLite, FastAPI, Vite + React 19 TS, cron + flock.

**Trigger (Nico, 2026-07-13, wörtlich zusammengefasst):** (1) „nicht nur was Kongressmitglieder
kaufen, sondern auch was andere Leute sagen — heute wieder was von Michael Burry gesehen";
(2) „ML soll fortlaufend lernen und weitertraden, ich will SEHEN dass es besser wird; Long- und
Short-Bots; auch kurzfristiger"; (3) „unübersichtlich, wo ich wann bin, Bezeichnungen — Konzept
komplett reviewen"; (4) „Pipeline nicht nur 1× täglich — gefühlt jede halbe Stunde, App im
Hintergrund, regelmäßig Vorschläge". Autonome Umsetzung bis zur Vision beauftragt (kein Go-Gate;
Nico ist nicht live dabei). Ehrliches Framing bleibt nicht verhandelbar.

**Review-Basis:** drei parallele Review-Pässe 2026-07-13 (UX/IA, ML-Architektur, Voices-Feasibility).

## Review-Kernbefunde (kondensiert)

- **ML handelt nirgends.** Der Entry-Score wird geloggt + resolved (`/api/model`), aber kein
  `ForwardAccount` und keine Lane kauft danach — die Arena-„Autopilot"-Lane nutzt den REGELBASIERTEN
  Composite aus `signals.py`. `run_train_entry.py` behauptet im Docstring, gecront zu sein — ist es
  nicht; `run_research.py` läuft nur manuell via nohup. `/api/model.drift` ist ein None-Platzhalter,
  obwohl `prediction_ledger.drift_snapshot()` existiert.
- **UX:** drei Paper-Depots unter drei Namen an drei Orten (Arena `/api/arena`, „Demo-Depot" im
  Screener `/api/portfolio`, „Live (Forward)" unter Strategien `/api/forward`); Namenskollision
  „Modell" (Nav) vs „Meta-Modell" (Tab); „Live (Forward)" klingt nach Echtzeit-Handel; Nav-Gruppen
  existieren nur als unsichtbare Hairline (`App.tsx:12-25`); keine Übersichts-Startseite;
  Deutsch/Englisch-Mischmasch.
- **Voices:** Google News RSS (`news.google.com/rss/search?q=%22<Person>%22&hl=en-US&gl=US&ceid=US:en`)
  und Bing News RSS (`bing.com/news/search?q=...&format=RSS&mkt=en-US`) live verifiziert (Titel +
  pubDate + Quelle, kein Rate-Limit-Problem bei moderater Nutzung). ABER: das ist ein
  **Mentions-Feed, kein Statements-Feed** — die Mehrheit der Treffer sind Erwähnungen/Listicles.
  Konsequenz: deterministische Call-Klassifikation mit ehrlicher Grenze (unten).
- **Short-Seite:** `TargetWeight.weight` ist hart `[0,1]` — kein Short-Seam; nirgends
  Borrow-Kosten; Short-Universe braucht die as_of-historisierten Universe-Snapshots gegen
  Survivorship; eigenes Short-Modell nötig (invertierter Long-Score hat andere Fehlerverteilung).

## Eiserne Regeln (unverändert aus LOOP.md/PLAN.md)

Local & free only · paper-only, nie Order-Routing · Disclaimer auf jeder Surface · LLM interpretiert,
prognostiziert nie · Look-ahead-Schutz (gehärteter `purged_walk_forward` wird IMPORTIERT, nie
kopiert) · Gate objektiv: `uv run pytest -q` grün + `uv run ruff check .` clean (+ FE
typecheck/build bei Frontend-Paketen) · kleine Diffs, neue Logik mit Test, Netz/LLM hinter Seams,
in Tests gefakt · Conventional Commits · eine `AUTOPILOT_LOG.md`-Zeile pro Paket.

---

## P1 — Voices: personen-attribuierte öffentliche Aussagen als fünfte Evidenzquelle

**Files:** Create `src/equity_scout/evidence/voices.py`, `tests/test_evidence_voices.py` ·
Modify `evidence/base.py` (`SOURCE_VOICE = "voice"`), `scripts/run_evidence.py` (Collector),
`evidence/aggregate.py` (`_voice_line()`; `_person_of()` um `details.get("speaker")`),
`evidence/person_track.py::calls_from_events` (speaker), `scripts/run_person_scores.py::collect_calls`,
`notify.py` (Voice-Call-Alert, bestehender 14d-Cooldown), `.env.example`/`README.md` (Abschnitt).

**Design (gelockt):**
- `PERSONS: dict[str, list[str]]` — Manager der 8 getrackten Fonds aus `edgar.py` (Scion → Michael
  Burry usw.) + Aliase; Modul-Konstante nach dem `TRACKED_FUNDS`-Vorbild. Erweiterung/Veto → Needs Nico.
- Fetch: Google News RSS primär, Bing News RSS (`&mkt=en-US`) sekundär, über den bestehenden
  `http_get`-Seam; Parse-Logik nach `news_themes.py`-Vorbild. Status-Vokabular
  `ok/fetch_failed/parse_failed` wie gehabt, nie stumm degradieren.
- Dedupe über normalisierten Titel-Hash (NICHT feed-guid); `event_key` mit Wochen-Rotation wie
  news_themes.
- `classify_call(headline, matcher) -> Call | Context`: **messbarer Call NUR wenn** (1) eindeutiger
  Ticker-/Firmennamen-Match gegen die Universe (Wiederverwendung `edgar.build_name_matcher`,
  nur-eindeutige-Treffer-Regel) UND (2) Richtungs-Verb aus geschlossener Liste
  (`buys/bought/adds/short(s)/bearish on/bullish on/sees upside/dumps/sells/exits` …) direkt im
  Titel. Alles andere = Kontext-Annotation: wird am Pitch angezeigt, geht NIE ins Ledger, erzeugt
  NIE einen Person-Track-Call. Kein LLM in der Klassifikation.
- Ledger: nur messbare Calls via `log_evidence()` (predict-then-resolve, 60d-Horizont, resolved vs
  SPY — Infrastruktur ist quellenagnostisch vorhanden). Person-Scores laufen über den bestehenden
  `(person, source)`-Schlüssel — Voices vermischen sich nie mit 13F/Congress-Scores.
- Alert: messbarer Call einer getrackten Person → gelabelter Telegram-Alert („Stimme: …", ohne
  Entscheidungs-Buttons), bestehender Cooldown.

**Tests:** Fixture-XML für beide Feeds (parse), Titel-Hash-Dedupe über Feeds hinweg, classify_call
Positiv-/Negativ-Fälle (Ticker ohne Verb → Kontext; Verb ohne eindeutigen Ticker → Kontext;
beides → Call, Richtung korrekt), Collector mit fake `http_get` (ok/fetch_failed), Ledger-Idempotenz,
`_person_of`/`calls_from_events` mit speaker-Events.

- [x] P1 umgesetzt, Gate grün, committed (`feat(evidence): track what famous investors say as fifth evidence source`)

## P2 — Entry-Modell v2 (übernimmt v5-P3) + kurzer Horizont

**Files:** Modify `ml/entry_model.py` (Presets `catboost`, `ensemble`; OOS-Isotonic-Kalibrierung),
`ml/entry_eval.py` (`HORIZON_DAYS` → Parameter des Datasets/Evals statt Konstante; zusätzliches
Kurz-Horizont-Preset 10 Handelstage für die Bots), `scripts/run_train_entry.py` (trainiert ALLE
Presets, das gehärtete Registry-Gate entscheidet; Docstring-Lüge „Phase 5 crons it" fixen — Cron
kommt real in P5), `ml/model_registry.py` (Preset+Horizont in Metadaten). Tests erweitern
(`test_entry_model.py`, `test_catboost.py`, `test_entry_eval.py`).

**Design:** Kalibrierung strikt OOS (isotonic auf Walk-Forward-OOS-Scores, nie in-sample);
catboost optional-import mit Skip, wenn nicht installiert (Muster aus `test_catboost.py` prüfen);
Ensemble = Mittel der kalibrierten Einzel-Scores. Promotion bleibt allein Sache des gehärteten
`promote_if_better` (MIN_AUC_DELTA/MIN_OOS_N/NO_EDGE_BAND — KEINE Lockerung).

- [x] P2 umgesetzt, Gate grün, committed (`feat(ml): entry model v2 with calibration, presets and short horizon`)

## P3 — ML-Bot-Familie: Long-Bot + Short-Bot als Forward-Paper-Konten

**Files:** Create `src/equity_scout/strategies/ml_long.py`, `strategies/ml_short.py`,
`tests/test_ml_bots.py` · Modify `strategies/base.py` (`TargetWeight.side: "long"|"short"`,
Default long, Validierung angepasst), `forward_paper.py` (Short-P&L `-weight*return`,
`borrow_bps_per_day`-Proxy explizit gelabelt, Margin-Floor: Equity ≤ 0 → Zwangsglattstellung,
geloggt als „simuliert"), `engine.py` (gleiche Short-Mathematik im Backtest-Pfad),
`ml/entry_model.py`/`entry_dataset.py` (Short-Label: underperformt SPY; `model_kind="entry_short"`
eigene Registry-Partition + EIGENE Gate-Konstanten-Instanz), `scripts/run_forward_paper.py`
(zwei neue Accounts „ML Long Bot"/„ML Short Bot", nur wenn ein Champion der jeweiligen Partition
existiert — sonst ehrlich skippen + loggen), `scripts/run_train_entry.py` (trainiert auch
entry_short).

**Design (gelockt):**
- Long-Bot: Champion lädt via Registry, scort das Universum, Top-K über Schwelle, equal-weight,
  Rebalance wöchentlich, Horizont = Kurz-Preset aus P2.
- Short-Bot: EIGENES Modell (Label „underperformt SPY um X über Horizont"), Universum = liquide
  Large Caps aus dem as_of-historisierten Universe-Snapshot (`universe_storage.py`) — Filter:
  Mindest-Marktkapitalisierung + Preis, als gelabelte Vereinfachung dokumentiert (keine
  Borrow-Verfügbarkeits-Daten frei verfügbar).
- Ehrlichkeit: Borrow-Proxy + Fill-Annahmen (Spot, keine Bid/Ask) auf der Depot-Surface als
  Vereinfachung ausgewiesen; Margin-Floor-Events sichtbar; DISCLAIMER wie überall.
- Beide Bots erscheinen automatisch in `/api/forward` → Frontend-Anbindung in P6.

**Tests:** Short-P&L-Mathematik (Gewinn bei fallendem Kurs, Verlust bei steigendem), Borrow-Kosten
über N Tage, Margin-Floor-Zwangsglattstellung, `decide()` beider Bots mit Fake-Champion
(deterministische Scores), Skip-ohne-Champion-Pfad, Registry-Partition-Trennung.

- [x] P3 umgesetzt, Gate grün, committed (`feat(strategies): ML long and short bots trade forward on paper`)

## P4 — Sichtbare Lernkurve

**Files:** Modify `ml/model_registry.py` (Tabelle `champion_history(model_kind, version,
promoted_at, prior_version, auc, oos_n)`, geschrieben bei jedem erfolgreichen `promote_if_better`),
`ml/ledger.py` (geltende DSR-Hürde zum Trial-Zeitpunkt mitspeichern), `ml/prediction_ledger.py`
(`resolved_stats_windowed(db_path, window_days)` rollierend), `strategy_service.py`/`api.py`
(`/api/model` bekommt echtes `drift` aus `drift_snapshot()`; NEU `/api/model/history`: AUC/Brier
je Registry-Version + Champion-Timeline + rollierende Trefferquote/Kalibrierung, je model_kind).
Tests: `test_model_registry.py`, `test_prediction_ledger.py`, `test_api.py` erweitern.

**Ehrlichkeit:** Die Kurve zeigt was IST — auch wenn sie fällt. Keine Glättung, die Verschlechterung
versteckt; n je Fenster wird mit angezeigt (kleine n ≠ Signal).

- [x] P4 umgesetzt, Gate grün, committed (`feat(ml): learning-curve history API from registry and ledgers`)

## P5 — Always-on-Betrieb: 30-min-Takt + nächtliches Training

**Files:** Create `scripts/intraday_copilot.sh` · Modify `scripts/install_crontab.sh` (idempotent
erweitern), `scripts/run_research.py` (`--trials N` Batch-Modus zusätzlich zum Endlos-Modus),
`docs/scheduling.md`, `README.md`, `notify.py`/Pitch-Rendering (Hinweis „Kurse ~15 min verzögert"
auf intraday erzeugten Vorschlägen).

**Design (gelockt):**
- `intraday_copilot.sh` (alle 30 min, Mo–Fr, 15:00–22:30 Europe/Berlin ≈ US-Handelszeit; Zeitfenster-
  Guard im Script, flock, log-and-continue wie `daily_copilot.sh`): Radar-Check gegen aktuelle
  (verzögerte) Kurse → schnelle Evidence-Collector (congress, news_themes, voices — 13F/Form4
  bleiben täglich, ändern sich intraday nicht) → Pitches + Evidenz-Alerts. Bestehende Cooldowns
  verhindern Spam; Idempotenz über die vorhandenen event_key-/row-before-send-Mechanismen.
- Nachts (1× täglich): `run_train_entry.py` (alle Presets, beide model_kinds; Gate entscheidet) +
  `run_research.py --trials 25` + `run_resolve_predictions`/`run_resolve_evidence`. Wochentags-
  Splits wie gehabt (Scout Mo, Person-Scores Mo).
- Crontab-INSTALLATION bleibt Needs Nico (`./scripts/install_crontab.sh`, idempotent, erhält
  bestehende Zeilen).

**Tests:** Zeitfenster-Guard als pure Funktion (`within_market_window(now)`) unit-getestet;
`--trials`-Batch-Modus; Rest ist Shell-Glue nach bestehendem, live-verifiziertem Muster.

- [x] P5 umgesetzt, Gate grün, committed (`feat(automation): 30-minute intraday copilot chain and nightly training`)

## P6 — IA/UX-Overhaul + Signal-Stack (übernimmt v5-P5)

**Files:** Modify `frontend/src/App.tsx` (Nav-Gruppen MIT sichtbaren Labels, neue View-Union),
`frontend/src/api.ts` (neue Fetcher) · Create `frontend/src/components/TodayView.tsx`,
`DepotsView.tsx` (+ `ui/TimeContextBadge.tsx`), `VoicesPanel.tsx`, `LearningCurvePanel.tsx`,
`SignalStackDrilldown.tsx` · Rename/Umbau: `ModelPanel.tsx`→„Entry-Modell", `MLSection.tsx`-Tab
„Meta-Modell"→„Signal-Filter", `ForwardPanel`/`Portfolio`/`ArenaPanel` ziehen unter `DepotsView` ·
Backend: `api.py` (`/api/stack/{ticker}`, `/api/evidence` um Voices-Ansichtsdaten, ML-Score in
`/api/radar` joinen), `strategy_service.py`/`radar.py` nach Bedarf. Tests: `test_api.py` +
FE typecheck/build.

**Ziel-IA (gelockt, deutsche Labels, Gruppen sichtbar):**
```
Heute            — Systemstatus: offene Pitches, Depot-Stände, letzte Alerts, letzte Läufe
Signale          — Screener · Radar · Stimmen
Entscheiden      — Inbox · Depots (Paper): Arena | Screener-Depot | Strategie-Forward | ML-Bots
Forschung        — Strategien · Entry-Modell · Signal-Filter · Auto-Research · Lernkurven
Assistent        — lokaler Chat
```
- Jede Oberfläche trägt eine Einzeiler-Beschreibung (`section-sub`-Muster aus `RadarPanel.tsx`).
- `TimeContextBadge` auf JEDEM Depot-Tab: „Backtest" | „Forward-Paper seit TT.MM." | „Paper seit
  TT.MM." — beendet die „Live"-Mehrdeutigkeit; Label „Live (Forward)" verschwindet.
- Signal-Stack: Klick auf Ticker (Radar/Screener) → Drilldown mit Faktor-Score, Entry-Composite,
  ML-Score, Evidenz-Events, Personen-Track-Records — v5-P5-Umfang.
- UI-Texte deutsch (Projekt-Konvention), Fachbegriffe (AUC, DSR) bleiben original + Tooltip.

- [x] P6 umgesetzt, Gate grün (inkl. `npm run typecheck`+`build --prefix frontend`), committed
  (`feat(frontend): information architecture overhaul with today view, unified depots and signal stack`)

## P7 (Backlog, nur wenn Session-Zeit übrig) — Strategie-Parameter-Suche (v5-P4)

Zweite Suchdimension im Research-Loop über Strategie-Hyperparameter, EIGENES Ledger + EIGENE
DSR-Hürde (Multiple-Testing-Trennung), Surface in `/api/research`.

- [x] P7 explizit als Backlog dokumentiert (PLAN.md, 2026-07-14) — nicht umgesetzt

---

## Reihenfolge & Abhängigkeiten

P1 (unabhängig) → P2 (Basis für P3) → P3 (braucht P2-Horizont) → P4 (liest P2/P3-Artefakte) →
P5 (cront P1–P4-CLIs) → P6 (zeigt alles an) → P7 Backlog. Single-threaded inline (Orchestrator),
ein Commit pro Paket minimum, `AUTOPILOT_LOG.md`-Zeile pro Paket, Outcome-Abschnitt am Ende.

## Needs Nico (läuft auf, nie geraten)

- PERSONS-Startliste (Fonds-Manager + Burry) per Veto/Erweiterung bestätigen.
- `./scripts/install_crontab.sh` einmal ausführen (Session darf Crontab nicht ändern) — enthält
  danach auch die neue Intraday-Kette; `EDGAR_USER_AGENT` in `.env` weiterhin offen.
- Merge-/Push-Entscheidung `autopilot/work` → `main` (Repo ist public).

## Outcome (2026-07-14)

**P1–P6 komplett umgesetzt** auf `autopilot/work`, Gate pro Paket grün (pytest + ruff, P6 zusätzlich
FE typecheck + build), ein Feature-Commit + Log-Zeile pro Paket (8483d80, ad5b666, e0684be, 2759a05,
75749e1, 766b546). Live-Verifikation: Voices-Collector gegen echte Feeds (184 Mentions → 1 Bearish-
Call korrekt, Burry/NVDA-Short ehrlich als Kontext), Forward-Paper-Lauf (Long-Bot handelt mit dem
existierenden Champion, Short-Bot ehrlich übersprungen), Server-Smoke aller Endpoints inkl.
`/api/stack/{ticker}` und `/api/model/history` (200, echte Daten).

**Abweichungen vom Plan:** (1) Bots in EINEM Modul `strategies/ml_bot.py` statt `ml_long.py` +
`ml_short.py` — sie teilen die komplette Scoring-Logik. (2) Long-Bot-Modell bleibt auf dem
20-Tage-Horizont (bestehende /api/model-Semantik); der kürzere Horizont (10 Handelstage) gehört dem
Short-Modell, die kurzfristige Kadenz kommt über tägliche Advances. (3) „DSR-Hürde pro Trial
speichern" (P4-Teilpunkt) ins Backlog verschoben — das Research-Ledger nutzt positionsbasierte
INSERTs, der Umbau lohnt separat. (4) run_research hatte `--trials` bereits.

**P7 (Strategie-Parameter-Suche) bleibt Backlog** (siehe PLAN.md).

**Needs Nico:** `./scripts/install_crontab.sh` neu ausführen (jetzt inkl. Intraday- + Nightly-Kette),
PERSONS-Startliste in `evidence/voices.py` bestätigen/erweitern, visueller FE-Abnahme-Pass,
Merge-/Push-Entscheidung.
