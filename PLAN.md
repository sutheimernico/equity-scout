# equity-scout — Plan (AUTOPILOT-driven build backlog)

**Source of truth for design:** `docs/superpowers/specs/2026-06-24-equity-scout-design.md`
**v1 implementation log:** `docs/superpowers/plans/2026-06-24-vertical-slice-v1.md` (done — see Outcome).
Personal rules (`~/.claude/CLAUDE.md`) + global loop rules (`~/private/AUTOPILOT.md`) apply.

> **NEXT MAJOR DIRECTION (2026-06-24) — IN PROGRESS:** multi-strategy paper-trading (N strategies as
> N demo accounts, dashboard tabs) + a self-learning ML meta-model with a feedback loop.
> **Active plan + phase backlog: `docs/superpowers/plans/2026-06-24-multi-strategy-v2.md`**
> (Phases A–F). Research + resolved §9 decisions: `docs/research/2026-06-24-strategy-ml-data-research.md`.
> Vision: `docs/superpowers/specs/2026-06-24-multi-strategy-ml-vision.md`. The phases below
> (Phase 2–8 + redesign/transparency/paper/naming) are the prior, completed v1 work.
>
> Key research findings that changed the spec: (1) the TAA family (Faber GTAA, VAA, **DAA**, PAA,
> Accelerating DM) + Permanent/All-Weather benchmarks were the biggest gap — added to v1.
> (2) Intraday is a dead end on free data — dropped. (3) `mlfinlab` is no longer open-source — use
> `purgedcv`/`skfolio`/CatBoost. (4) Backtest history is the initial ML training material; forward
> paper is the feedback loop — backtest and forward share one engine.

This file is the binding backlog for the autonomous loop. Each iteration picks the SINGLE
highest-value open `- [ ]` task, does it on `autopilot/work`, runs the gate, commits only if green,
checks the box, and appends one line to `AUTOPILOT_LOG.md`.

## Von Nico angesetzt — nächste Session (notiert 2026-08-16, 03:00)
- [ ] **Das Handy-Cockpit fertig bauen.** Nicos Ansage in der Nacht auf den 16.08.: "morgen die
      App zu Ende bauen fürs Handy, das Dashboard". **Der Scope ist NICHT festgelegt — erster
      Schritt ist die Klärung mit Nico, was "zu Ende" für ihn heißt, nicht das Bauen.**
      Bekannte Kandidaten für diese Klärung:
      - **Task 9** aus `docs/superpowers/plans/2026-08-06-phone-cockpit-beginner-friendly.md`
        ("Mehr"-Ansichten einsteigerfreundlich, der große Durchgang über acht Panels). Durch den
        Mockup-v2-Umbau vom 08.08. (13 Views → 5 Tabs) teilweise überholt — vor dem Anfangen
        gegen die heutige IA neu bewerten, nicht blind abarbeiten. Task 8 desselben Plans gilt
        durch den Assistent-Uplift vom 07.08. als erledigt, die Haken fehlen nur.
      - `docs/superpowers/plans/2026-08-09-cockpit-refresh-buttons.md`: sieht im Code umgesetzt
        aus (die Guard-Wrapper tragen die Plan-Kommentare wörtlich), aber alle Checkboxen sind
        offen und ein Outcome-Abschnitt fehlt — verifizieren und den Plan schließen.
      - Nicos eigener Durchklick auf dem Handy steht seit dem 08.08. als Needs-Nico aus; ohne
        seine Funde ist "zu Ende" nicht bestimmbar.

## Phase: Allocator-Tilt auf Inverse-Vol statt Sharpe-Softmax (2026-08-17) — DONE
Task 4 aus `docs/superpowers/plans/2026-08-16-autotrader-review-upgrades.md`.

- **Warum:** eine Sharpe-Schätzung über 63 Tagesbeobachtungen hat einen Standardfehler von grob
  2 annualisierten Einheiten — der Softmax-Exponent rankte also Rauschen (DeMiguel/Garlappi/Uppal
  2009). Genau der Schätzfehler, gegen den der 50-%-Anker existiert, kam über den Tilt zurück.
  Volatilität IST auf 63 Beobachtungen schätzbar, und der W0-Befund sagt dasselbe von der
  Datenseite: Rendite ist hier nicht vorhersagbar, Risiko schon.
- **Was bleibt:** 50-%-Equal-Weight-Anker, Floor 5 % / Cap 40 %, seasoned/young-Trennung,
  monatliche Neuberechnung, Sharpes auf allen Oberflächen sichtbar — sie bestimmen nur keine
  Gewichte mehr. Modus heißt jetzt `tilt_invvol`; gespeicherte `tilt`-Zeilen (Altschema) werden
  nicht mehr durch den Monat getragen, sondern neu berechnet.
- **Live-Wirkung heute: null, nachgewiesen.** Das Depot läuft seit Juli durchgehend im
  `anchor`-Modus (11 Sleeves à 9,09 %); ein Tilt hat noch nie stattgefunden. Der Dry-Run nach dem
  Umbau liefert unverändert Anker mit 9,1 %, die gespeicherten Zeilen bleiben `anchor`. Deshalb
  war die Attributionsregel des Plans (Task 1 und 4 nicht in derselben Nacht) hier nicht
  einschlägig — die einzige Verhaltensänderung dieser Nacht ist der VIX-Multiplikator.
- **Wann er erstmals greift:** `MIN_OVERLAP_OBS = 60` gemeinsame Beobachtungen bei ≥ 2 Sleeves.
  Stand 2026-08-17 führen die ältesten sechs Sleeves mit **19** Beobachtungen — bei täglichem
  Forward-Lauf also grob **Mitte Oktober 2026**.

## Phase: Rebalance-Timing-Glück gemessen (2026-08-17) — STUDIE DONE, Bau wartet auf Nico
Task 5 aus `docs/superpowers/plans/2026-08-16-autotrader-review-upgrades.md`. Doku:
`docs/research/2026-08-17-rebalance-timing-luck.md`, reproduzierbar über
`scripts/run_timing_luck_study.py`. Keine Live-Änderung — reine Messung.

- **Material, aber gespalten:** signalgetriebene Sleeves streuen allein durch den Rebalance-Tag
  **1,6–5,9 pp CAGR** (Mean-Reversion 5,85 · DAA 4,15 · GEM 3,63 · Momentum 12-1 3,12 · Sektor
  2,46 · VolTarget 2,31 · Low-Vol 1,60); die Allokations-Sleeves ohne Signal-Stichtag sind immun
  (60/40 0,23 · DCA 0,25 · Permanent 0,27 · Risk Parity 0,48).
- **Glück, kein Kalendereffekt:** über alle Strategien gemittelt +8,77 / +8,32 / +9,19 / +8,27 %
  für Offset 0/5/10/15, und der Sieger wechselt pro Strategie. Es gibt keinen besseren Tag zu
  wählen, nur eine Streuung zu mitteln (passt zum widerlegten Turn-of-Month-Effekt, 2026-08-16).
- [ ] **Nico-Gate: Tranching für die 7 signalgetriebenen Sleeves bauen?** Vier Tranchen à 25 %
      (Offsets 0/5/10/15), Ergebnis gemittelt. Preis: jeder getrancht laufende Sleeve ist eine
      **neue Strategie-Identität mit frischem Forward-Track** — der bisherige Track endet. Die
      vier immunen Sleeves bleiben am Monatsende. Ohne Go bleibt der Punkt gemessen-und-erledigt,
      und die Streuung ist als bekannte Unsicherheit des Live-Tracks dokumentiert.

## Runde 2026-08-17 (Nicos Blanko-Go: Lernkreis vervollständigen) — DONE
Plan: `docs/superpowers/plans/2026-08-16-no-trade-book-and-learning-loop.md` (mit Outcome)
- **Nicht-Trade-Buch (`st_rejections`).** Jede geprüfte, nicht gehandelte Gelegenheit wird
  mit Grund persistiert (swing: not_bullish/too_old/cap_full/already_held/no_quote;
  gapfade: below_threshold/stale_premarket), nachts mit den Live-Exit-Regeln simuliert
  (`rejection_review.py`, Nightly-Step `rejection_review`) und im `lane_review` den
  gehandelten Trades gegenübergestellt — brutto, steht überall dabei.
- **Session-Lane PAUSIERT (2026-08-17).** Einstiegsregel intraday widerlegt (16.08., 1.684
  Ausbrüche) UND mit Overnight-Halten in allen drei Armen gegen den bedingungslosen
  Benchmark verloren (`docs/research/2026-08-17-orb-overnight-backtest.md`). Cron-Zeile
  entfernt (install_crontab.sh verwaltet das Fehlen), `st_session_sweep` bleibt im Nightly,
  Buch bleibt im Cockpit lesbar. Reaktivierung = SESSION_LINE wieder eintragen.
- **Gap-Fade-Papierlane LIVE als Messinstrument** (lane `gapfade`, Cron `*/5 14-16` lokal,
  ET-Gate im Runner): Pre-Market-Gap ≤ −2 % → Market-on-Open, Exit Market-on-Close (Settle
  im Nightly). Misst live, was der Backtest nicht kann: Pre-Market→Open-Verrutschen
  (`st_executions`) und die Schwellen-Kalibrierung über das Nicht-Trade-Buch. Abbruch:
  nach 60 Trades entscheidet der Trade-Test, Verdict „negativ" beendet die Lane.
- **Ereignis-Knappheit an der Wurzel:** News-Klassifikation läuft über `tracked_tickers()`
  statt des 30er-Watchlist-Snapshots (Symmetrie mit 8-K), und gleichgerichtete
  Doppel-Headlines („beats estimates and raises guidance") behalten ihre Richtung —
  vorher 0 guidance_up in 603 Headlines, weil der stärkste bullische Headline-Typ als
  Dual-Match auf unknown fiel.

## Iron principles (never overridden)
- **Local & free only.** yfinance / SEC EDGAR (UA header) / public lists. No paid feeds, no
  real-money anything. A task needing a paid resource goes to "Needs Nico", never faked.
  Order routing to a **paper** broker account is permitted since 2026-08-04 (Nico's decision,
  session lane / Alpaca Paper); live endpoints and funded accounts stay out of reach.
- **Honesty guardrails on every surface.** Disclaimer present; LLM theses are interpretation,
  never price forecasts; the data-completeness gate is mandatory — never rank thin-data noise.
- **Gate is objective:** `uv run pytest -q` green AND `uv run ruff check .` clean. Never commit red.
- **Small, reviewable diffs.** New logic ships with a test. Net/LLM behind seams, faked in tests.
- **One change per iteration.** No bundling. No speculative abstractions (YAGNI).

## Status
- **v1 Vertical Slice — DONE.** Funnel end-to-end (universe→data→gate→factors→buckets→LLM-seam→
  SQLite→API→dashboard), 21 tests + ruff green, live yfinance run over 42 global tickers verified.

## Phase 2 — Persistent cache + real global universe — DONE (2026-06-24)
- [x] Read-through SQLite quote cache (`data/cache.py`), freshness vs. injected run-date, wired into CLI.
- [x] Index-constituent sources behind a seam (`data/constituents.py`): hand-curated global CSV +
      S&P 500 from Wikipedia (polite UA), deduped → `data/universe_combined.csv` (531) + provenance.
- [x] Retry/backoff + bounded-parallel fetch (`data/fetch.py`), wired into pipeline + yfinance provider.
- [x] Per-run gate statistics (total, by reason, by region) persisted + surfaced in API + dashboard.
- [x] Follow-up: add STOXX Europe 600 + Nikkei 225 constituent sources (each needs an exchange→Yahoo
      suffix mapping; Nikkei is `code + .T`, STOXX is multi-exchange). v2.2 shipped S&P 500 only.
      DONE 2026-06-26: `WikipediaStoxx600Source` (country→suffix map, 459/600 live) +
      `WikipediaNikkei225Source` (tag-strip + `code+.T`, 223/225 live); pure parse fns unit-tested.
      FIXED 2026-07-02: Nikkei rows were hardcoded `sector="Unknown"` (the page groups sectors by
      heading, not a column) — sector-relative ranking silently pooled all 223 JP tickers into one
      meaningless bucket. Now derives sector from the nearest h3 industry heading (222/223 live; the
      1 remaining Unknown is an honest intro-prose dedup edge case, not a guess). Also found:
      `refresh_universe.py` was built for STOXX/Nikkei on 2026-06-26 but never actually re-run, so
      the committed `universe_combined.csv` was still the stale S&P-500-only snapshot (531: 503 US /
      28 non-US) despite this phase being marked DONE for "real global universe". Re-ran it live:
      **1191 rows (503 US, 452 EU, 223 JP, 13 other)** — verified via `load_universe`. 9 new tests.
- [x] Follow-up: historize the universe instead of CSV-overwrite-only, to avoid survivorship bias
      (a later backtest/ML use of history must not see today's constituent list for every past date).
      DONE 2026-07-02: `data/universe_storage.py` snapshots each refresh with an `as_of` date in
      SQLite (mirrors the `storage.py`/`forward_storage.py` pattern); re-running the same day replaces
      that day's row instead of duplicating it. CSV stays the "latest" export the live pipeline reads.
      5 new tests.
- [x] Follow-up: `data/fetch.py`/`data/yf_provider.py` swallowed every fetch exception with a bare
      `except Exception`, no logging or counting — a provider failing on most tickers looked like
      just a smaller universe. DONE 2026-07-02: retry attempts + give-ups are now logged; a
      thread-safe `FetchStats` counts attempted/info_failed/closes_failed; new `data_quality.py`
      builds a per-run report (fetch error rate, missing fundamentals per field, gate-filtered count)
      that `run_scout.py` prints and `/api/latest` + a dashboard KPI tile surface. 9 new tests.

## Phase 3 — Scheduler automation + run history — DONE (2026-06-24)
- [x] `scripts/scheduled_run.sh` + `docs/scheduling.md` (cron + systemd user-timer templates).
- [x] Run-history: `load_run_summaries`, `/api/history`, `pick_churn` helper, dashboard history section.
- [x] Budget-capped LLM theses: `attach_theses(max_per_bucket)` + CLI `--llm-top-n` (default 3).
- [x] Follow-up: `ClaudeCliAnalysis` shelled `claude -p` without checking its returncode, so a
      non-zero exit with stray stdout (e.g. an auth error printed to stdout) would have been
      silently adopted as the thesis. DONE 2026-07-02: every failure mode (non-zero exit, missing
      binary, timeout, empty stdout) now degrades to an explicit "These nicht verfügbar (<reason>)"
      message instead. 6 new contract tests mock `subprocess.run`.

## Phase 4 — Factor / bucket refinement — DONE (2026-06-24)
- [x] Sector-relative percentile ranking for value/quality/growth (momentum/low-vol stay global).
- [x] Low-volatility factor (stdev of daily returns), wired into bucket weights (defensive 0.25).
- [x] ~~Winsorize~~ → replaced by **cleaning invalid values** (non-positive P/E/P/B dropped).
      Rank-based scoring is ordinal, so winsorizing is a no-op; cleaning was the real fix.
- [x] `docs/factors.md` — families, directions, sector-relative + rank-based rationale, weights,
      honest limitations.

## Phase 5 — Dashboard polish (React) — DONE (2026-06-24)
- [x] Vite + React 19 + TS dashboard (`frontend/`): bucket tabs, score-breakdown bars, region
      filter, per-pick drilldown (factor bars + thesis). FastAPI serves the built `dist/`.
- [x] Gate stats (total + by region) + disclaimer surfaced; run-history section.
- [x] Follow-up: sector filter (region done) and a dedicated gated-out list view.
      DONE 2026-06-26: sector dropdown in FunnelView (chains with region); `GatedOutList` disclosure
      shows excluded tickers + reasons (filterable by reason) + per-region summary. Live-verified.

## Phase 6 — Frontend redesign — DONE (2026-06-24)
- [x] Dark design-token system (Geist/Linear-style: near-black surface stack, border-as-shadow,
      one accent, tabular-nums).
- [x] App shell: topbar + KPI stat-tiles + underline tabs + responsive card grid.
- [x] Redesigned pick cards, score bars, history as a clean hairline table; modular components
      with descriptive names (StatTile/PickCard/RunHistory/MethodologyNote, format.ts helpers).

## Phase 7 — Score transparency — DONE (2026-06-24)
- [x] API exposes `bucket_weights`; pick drilldown shows per-factor `percentile × weight =
      contribution`, composite = sum of contributions.
- [x] In-app methodology note explaining rank-based, sector-relative scoring + the data gate.

## Phase 8 — Paper-trading bot — DONE (2026-06-24)
- [x] Paper portfolio (100k demo): buy picks with composite ≥ threshold, equal-weight, buy-and-hold;
      mark-to-market vs cost + SPY benchmark, small fee; persisted (portfolio + valuation history).
- [x] `scripts/run_paper.py` to advance it + `/api/portfolio` + dashboard portfolio view. Paper-only.
- [x] Follow-up: sell/exit rules, costs/slippage realism, valuation sparkline chart.
      DONE 2026-06-26: hysteresis exit (sell < 0.55 / buy ≥ 0.70 or drop-out), per-leg slippage_bps
      on the fill + commission, valuation-vs-benchmark sparkline (reused EquityChart). 5 new tests.

## Code quality — DONE (2026-06-24)
- [x] Renamed cryptic variables (fam, _t closure trick, t/q/pct, s) to descriptive names in
      factors/gate/buckets; frontend uses descriptive names throughout. Behavior unchanged, tests green.

## Standing mandate (per AUTOPILOT, once per phase — not per iteration)
- [x] Research current best practice (factor investing, free data sources, screening pitfalls) and
      challenge this plan. If a materially better approach exists, write an ADR in `docs/adr/` and
      adjust the backlog. Re-examine settled decisions only with a concrete, sourced reason.
      DONE 2026-06-26 (ML phase): sourced challenge of the overfitting design (Bailey & LdP) →
      ADR 0002. Kept the design, made PBO first-class + sharpened framing; rejected N_eff-clustering
      as churn (needs return-series storage). Measured PBO refreshed 0.69→0.77 over the wider search.
      DONE 2026-07-02 (10/10-hardening session): challenged whether the ML loop's meta-labeling
      should extend to the factor screener, or the ML loop should split into its own repo → ADR 0003.
      Kept status quo for both (data gap: no free point-in-time fundamentals for the non-US majority
      of the universe; no concrete driver for a repo split yet); flagged Rank-IC tracking on
      run-history as the correctly-scoped, lower-cost future step instead of meta-labeling.

## Phase: Signal-Radar v3 — external evidence + full automation (2026-07-07) — DONE 2026-07-10
> Vision (Nico, in-session 2026-07-07): congress trades + famous-fund 13F moves + news themes
> as evidence on pitches and as separate alerts, fully unattended via cron, each source
> honesty-tracked in its own predict-then-resolve ledger. Evidence annotates — it NEVER
> changes the entry composite or selection rules.
> **Active plan + task backlog: `docs/superpowers/plans/2026-07-07-signal-radar-v3-external-evidence.md`**
- [x] Task 0 — baseline gate + branch hygiene (gate was red from clean checkout; fixed)
- [x] Task 1 — evidence storage + per-source ledger (foundation)
- [x] Task 2 — congress-trades collector (live smoke 2026-07-07: 5000 rows → 193 purchases
      in the 30d filing window, honest skip counters for ticker-less/stale/derivative rows)
- [x] Task 3 — EDGAR 13F collector (live smoke 2026-07-07: 7/8 funds diffed, 36 events,
      1 stale fund skipped; share-class dedup + staleness guard added after first live run)
- [x] Task 4 — news-theme radar (live smoke 2026-07-07: 130 headlines/3 feeds; LLM labelling
      dropped as YAGNI — deterministic bigrams are already readable; unigram bar doubled)
- [x] Task 5 — pitch evidence block + labelled evidence alerts (evidence annotates
      pitches between Kennzahlen and Analystensicht; off-watchlist clusters ≥2 buyers/funds
      alert without decision buttons, 14d cooldown, row-before-send)
- [x] Task 6 — ledger wiring + edge monitor (run_evidence/run_resolve_evidence CLIs,
      /api/evidence, digest per-source hit-rate section)
- [x] Task 7 — automation glue: daily_copilot.sh chain + receiver keepalive, live smoke
      2026-07-10 (18 Evidenz-Alarme real via Telegram); crontab install → Needs Nico
- [x] Task 8 — docs (README evidence/automation sections, .env.example, scheduling.md),
      outcome section in the plan doc, verification sweep 2026-07-10/11

## Phase: Person Track Record v4 (2026-07-10) — DONE 2026-07-10/11
> Nico's vision (in-session 2026-07-10): score the PERSONS behind evidence events by their
> measured historical call performance; strong records rank alerts higher. Plan + outcome:
> `docs/superpowers/plans/2026-07-10-person-track-record-v4.md`. X/Twitter finfluencer
> scraping re-verified as not freely feasible in 2026 (paid API, dead Nitter) — famous
> investors ride the 13F path instead (Burry = Scion).
- [x] person_track.py scoring core (T0 = filing date, abnormal return vs SPY 1M/3M,
      n≥5 gate, 540d recency decay) + person_scores storage + run_person_scores CLI
- [x] Surfaces: track-record lines on pitches/alerts, single-strong-buyer alert rule
      (≥ +2 % weighted @3M), /api/evidence person ranking, Monday cron wiring
- [x] Live 2026-07-10: 977 backfill calls / 13 filers → 5 scoreable persons; 2 alerts
      (KHC/Peters, COHR/Whitehouse) really delivered via Telegram

## Phase: Always-on Copilot v6 (2026-07-13) — DONE 2026-07-14
> Vision (Nico, in-session 2026-07-13): (1) auch tracken, was bekannte Investoren SAGEN
> (Burry-Beispiel), (2) ML soll fortlaufend lernen UND wirklich weitertraden — Long- und
> Short-Bots, sichtbare Lernkurve, kurzfristiger, (3) kompletter Konzept-/UX-Review
> (Navigation/Bezeichnungen unübersichtlich), (4) Always-on: ~30-min-Takt statt 1×/Tag.
> **Plan + Outcome: `docs/superpowers/plans/2026-07-13-always-on-copilot-v6.md`**
- [x] P1 Voices-Evidenzquelle (Google/Bing News RSS je Person, deterministische Call/Kontext-Grenze,
      bullish Calls -> Ledger + Person-Track, bearish nur Anzeige/Alert; live 184 Mentions)
- [x] P2 Entry-Modell v2 (OOS-Isotonic-Kalibrierung, catboost+ensemble Presets, alle Presets je
      Nacht, --horizon + SHORT_HORIZON_DAYS=10)
- [x] P3 ML-Bot-Familie (signed weights + side, Short-P&L/Borrow-Proxy/Margin-Floor, Registry-
      Familien entry/entry_short, MLLong/MLShort in run_forward_paper; Long-Bot handelt live)
- [x] P4 Sichtbare Lernkurve (champion_history, rollierende resolved-Fenster, echtes Drift-
      Snapshot, /api/model/history)
- [x] P5 Always-on (intraday_copilot.sh 30-min mit Marktfenster-Guard, nightly_train.sh,
      install_crontab.sh erweitert, run_evidence --fast, Kurs-Verzögerungshinweis auf Pitches)
- [x] P6 IA-Overhaul (sichtbare Nav-Gruppen, Heute-Startseite, Depots vereinheitlicht mit
      TimeContextBadge, Stimmen-/Lernkurven-Views, Signal-Stack pro Ticker, Entry-Modell/
      Signal-Filter-Umbenennung; /api/stack, ML-Score in /api/radar)
- [x] P7 Backlog: Strategie-Parameter-Suche im Research-Loop (EIGENES Ledger + EIGENE DSR-Hürde,
      Multiple-Testing-Trennung; v5-P4)
      DONE 2026-07-24 (Vision v14): eigene Tabellen `strategy_trials`/`strategy_loop_state`
      in research_ledger.db, endliches 43er-Grid über die Regel-Strategie-Knobs,
      Whole-History-After-Cost-Backtests mit eigener DSR-Hürde, /api/research-Block +
      Dashboard-Karte, Nightly-Step. Champions = Evidenz, nie Auto-Übernahme — siehe
      Phase Vision v14 unten.
- [x] Backlog: DSR-Hürde zum Trial-Zeitpunkt im Research-Ledger mitspeichern (Ledger nutzt
      positionsbasierte INSERTs -> kleiner Schema-Umbau nötig; ohne das ist die rückwirkende
      "war der Champion damals über der Hürde"-Kurve nicht rekonstruierbar)
      DONE 2026-07-24 (v13 Q2): `dsr_hurdle`-Spalte + idempotente Migration; record_trial
      speichert die Hürde, die VOR dem Trial galt; alte Rows lesen ehrlich None.
- [x] Vorzeichenrichtige Auswertung bearischer Voice-Calls — 2026-08-11 (Head-Modus). `Call` trägt
      jetzt `direction`, `score_persons` dreht bei `bearish` das Vorzeichen jeder gemessenen
      Rendite: ein bearischer Call, dem Unterperformance folgt, ist ein TREFFER statt eines
      Fehlschlags. Damit heißt „Trefferquote" für beide Arten dasselbe — „lag die Richtung
      richtig" — statt „ist der Kurs gestiegen". **Rein additiv:** Meldungen drücken nur Kaufen
      aus, also sind congress/13F/insider bitgleich (per Test gepinnt: explizit `bullish` ==
      Default). **Wirkung: die Voice-Stichprobe wächst von 15 auf 35 Calls (+133 %)** — 20
      bearische Calls waren gesammelt und dann aus jeder Statistik verworfen worden.
      **Bewusste Asymmetrie:** das predict-then-resolve-LEDGER bleibt long-only (seine Zeilen
      modellieren einen Long-Einstieg, ein Short-Bein existiert dort nicht) — ein bestehender Test
      pinnt genau das, damit die Trennung nicht versehentlich verschwindet.

## Phase: Universe v3 — "screen everything" (2026-07-14) — DONE
> Nico: "1191 sind mir zu wenig, ich möchte eigentlich alles dauerhaft gescreent bekommen —
> nur kostenlos." Quelle: NASDAQ Trader symbol directory (nasdaqlisted.txt + otherlisted.txt,
> frei, kein Key, nächtlich aktualisiert) — ALLE US-Listings inkl. ADRs (= globale Abdeckung
> über US-Listings); ETFs/Warrants/Units/Preferreds/Test-Issues deterministisch gefiltert.
- [x] NasdaqTraderSource + Parser (word-boundary Non-Common-Filter, $-Preferreds raus,
      BRK.B->BRK-B), in refresh_universe verdrahtet; live: **6592 Titel** (5904 US, 452 EU,
      223 JP, Rest) statt 1191
- [x] Sektor-Backfill im yfinance-Provider (Unknown-Sektor wird aus .info befüllt) — die
      Nikkei-Lektion: sector-relative Ranking darf nie tausende Namen in einen Unknown-Topf
      poolen
- [ ] Beobachten: yfinance-Fehlerquote + Laufzeit des ersten 6.6k-Scout-Laufs (FetchStats im
      Data-Quality-Report); ggf. Universum per Mindest-Preis/-Historie vorfiltern
      → Sichtbarkeit geschaffen 2026-07-24 (v13 Q5): run_scout druckt am Laufende eine
      Fetch-Statistik-Zeile (geholt/Fehler/Fehlerrate/Laufzeit); Beobachten bleibt offen.
- [x] Bug: Form-4-Collector wirft bei ~21 Watchlist-Tickern XML-Parse-Fehler ("tag mismatch:
      meta/head" = SEC liefert eine HTML-Seite statt XML — vermutlich Filing-Index-URL oder
      fehlender Accept-Header); log-and-continue hat gehalten, 9/30 Ticker sauber geprüft
      (live 2026-07-14 nach EDGAR-Freischaltung)
      DONE durch `e31436f` (2026-07-20): SEC-Throttle + Nicht-XML-Bodies werden mit sauberem
      Fehler abgewiesen; in der v13-Triage 2026-07-23 verifiziert.

## Phase: Vision v7 — Ziel-Exits, Event-Engine, Lern-Loop (2026-07-15)
> Nico-Direktive: Long-Modell mit explizitem Zielwert/Exit, news-getriebenes Kurzfrist-Trading
> (ehrlich: Latenz messen statt Minuten-Trading behaupten), sichtbares tägliches Lernen.
> **Plan: `docs/superpowers/plans/2026-07-15-vision-v7-target-exits-events-learning.md`**
- [x] A1 fix(sizing): Positionsgröße vom aktuellen NAV statt initial_capital (portfolio, lanes)
- [x] A3 feat(ml): Triple-Barrier-Preset für entry-Familie (labeling.py wiederverwenden)
- [x] B5 fix(evidence): voices-Ticker-Resolution härten + news_themes Titel-Dedupe — 2026-08-11,
      beide Teile nach einem Live-Audit umgesetzt. **voices:** von 296 gespeicherten Erwähnungen
      trugen **79 % einen Ticker, den die Schlagzeile nie nennt** — alle über die zwei
      Großschreibungs-Kanäle („Moving Past Buffett" → MITQ, „Major AI Stock" → SYBT, „Aussies
      Take Over" → TTWO, „Just Warned" → JUST.AS, „Who Foots the Bill" → BILL, „- Yahoo Finance
      Singapore" → FOA). `_GENERIC_FIRST_WORDS` war die richtige Idee mit zu kurzer Liste UND
      schützte nur den Mehrwort-Kanal, nie den Einzelwort-Kanal (daher JUST.AS/BILL). Die
      tragfähige Unterscheidung ist **Wortschatz, nicht Großschreibung**: `_COMMON_WORDS` sperrt
      gewöhnliche englische Wörter in BEIDEN Kanälen, der Outlet-Suffix wird vorher abgeschnitten.
      Gemessen an den 35 gerichteten Calls (die im Ledger landen): Fehlzuordnungen **22 → 13**,
      und **jeder echte Treffer bleibt** (DraftKings, Nebius, Zoetis, Micron, „Microsoft (MSFT)").
      Nebenwirkung: der MSN-Portal-Bug vom 15.07. ist behoben (MSN → MU). **Ein erster Ansatz über
      Title-Case-Erkennung wurde vor dem Commit verworfen** — er lehnte auch „Michael Burry Adds
      to DraftKings Stake" ab, tauschte also eine Fehlerklasse gegen eine andere; ein Test pinnt
      das. **news_themes:** eine Schlagzeile ergibt jetzt höchstens EIN Event pro Ticker. Vorher
      wurde derselbe Artikel unter mehreren Themen gebucht (`themes=['now', 'right now']`) —
      Pseudo-Replikation, dieselbe Inflation, für die W0 korrigieren musste. Ehrliche Wirkung:
      **26 von 251 Zeilen (10 %)**, nicht die 80, die eine erste Zählung ergab — die übrigen 54
      sind die GEWOLLTE Wochenrotation der Event-Keys.
- [ ] **Needs Nico: Altlast bereinigen.** Der Fix verhindert nur NEUE Fehlzuordnungen; **121 der
      296 gespeicherten voice-Events sind mit dem heutigen Resolver nicht reproduzierbar** und
      verschmutzen weiter Signal-Radar und Ledger (7 offene Vorhersagen hängen dran). Skript liegt
      bereit, Trockenlauf ist Default, `--apply` verlangt `--backup`:
      `uv run python scripts/fix_voice_misattributions_2026_08_11.py --apply --backup pre_fix.db`
      Gegen eine DB-Kopie voll verifiziert (296 → 175 Events, 15 → 8 Vorhersagen, aufgelöste
      Zeilen unberührt). **Bewusst nicht selbst ausgeführt**, obwohl Head-Mandat: es ist eine
      Löschung ohne Zeitdruck, und sie entfernt auch **echte, aber mehrdeutige** Erwähnungen
      („Alibaba, JD.Com, Baidu" nennt drei Firmen → Ambiguitätsregel greift). Die Verzerrung geht
      bewusst in Richtung „weniger Evidenz statt falscher" — das ist Nicos Abwägung, nicht meine.
- [x] Themen-Kalibrierung — 2026-08-11 als eigener Schritt nachgezogen. Audit der tatsächlich
      erzeugten Themen: **`buy` war mit 43 Treffern das zweithäufigste „Thema"**, dahinter `know`
      (12), `com` (7), `higher` (6), `now`/`need`/`action` (4 je) — Schlagzeilen-Füllwörter, die
      nichts darüber sagen, worum eine Nachrichtenwoche ging; `com` stammt aus Domains und
      gepunkteten Namen („JD.Com", „finance.yahoo.com"), die die Tokenisierung überleben.
      **8 Themen entfallen, 82 der 251 Zeilen (33 %) wären so nie entstanden.** Bewusst
      KONSERVATIV: `earnings`, `bank`, `oil`, `tech`, `demand`, `yields`, `growth`, `price` bleiben
      erlaubt — jedes davon kann eine Nachrichtenwoche echt dominieren, und sie zu sperren würde
      genau das Signal verstecken, für das der Kollektor existiert. Die neuen Wörter liegen in
      einem EIGENEN Literal, weil der bestehende Block per `split()` zerlegt wird: ein
      `#`-Kommentar darin wäre still zum Stoppwort geworden (mir beim Schreiben genau so passiert
      und vor dem Commit korrigiert) — ein Test pinnt, dass kein Kommentar-Müll in der Liste steht.
- [x] A2 feat(exits): Trade-Lifecycle für Forward-Bots (ExitRules, Exit-Grund persistiert)
- [x] B1 feat(events): Earnings-Kalender (yfinance) + Digest-Sektion + Intraday-Awareness
- [x] C3 fix(pnl): Dividenden für Einzelaktien-Lanes/Portfolio (TTM anteilig)
- [x] A4 feat(ml): Kursziel + Stop pro Pick aus Champion-Barrier-Konfig (API)
- [x] A5 feat(bots): konfidenzgewichtetes Sizing statt equal-weight
- [x] B2 feat(events): EDGAR 8-K near-realtime Collector als Evidence-Quelle
- [x] C1 feat(learning): tägliche Lernkurve (n_train/n_resolved/hit-rate/rank-IC als Zeitreihe)
- [x] A6 feat(pitch): 🎯 Kursziel + 🛑 Stop in Pitch/Inbox/Frontend
- [x] B3 feat(events): Beat/Miss/Guidance-Klassifikator + events-Tabelle (published_at/seen_at)
- [x] C2 feat(ml): Promotion-Gate gegen Multiple-Testing härten (8 Kandidaten/Nacht)
- [x] B4 feat(events): Event-Reaktions-Lane paper-only mit Latenz-Log + 1h/1d/5d-Auswertung
- [x] C4 docs+fix: Rebalance-Kadenz-Mismatch + Survivorship-Kennzeichnung im Modell-Report
- [x] Backlog (B5-Review-Fund, pre-existing): tail-lose Single-Token-Firmennamen in
      voices.resolve_ticker bleiben exponiert — konkrete Instanzen SHEL.L ("Shell"),
      TGT ("Target"), NXT.L ("Next"): generische kapitalisierte Wörter in Headlines lösen
      auf diese Ticker auf. Fix-Idee: Single-Token-Namenskanal ebenfalls gegen
      _GENERIC_FIRST_WORDS gaten und/oder Mehrwort-Firmennamen im Titel bevorzugen.
      DONE 2026-07-24 (v13 Q4): beides umgesetzt — Gate im Single-Token-Kanal (Caps-Ticker-
      Kanal bleibt offen) + chirurgische Mehrwort-Präferenz (nur wenn das Single-Token-Wort
      im Vollnamen-Match liegt; echte Zwei-Firmen-Headlines bleiben ehrlich None).
- [x] Backlog (B5-Review-Fund): _GENERIC_FIRST_WORDS ist ein manueller Snapshot des Universe
      (2026-07-15) — bei Universe-Refresh können neue eindeutige generische First-Words entstehen.
      Idee: Scan-Skript unter scripts/ oder Drift-Check im Data-Quality-Report.
      DONE 2026-07-24 (v13 Q4): `scripts/scan_generic_words.py` difft exponierte Wörter gegen
      den committeten Snapshot `data/voices_exposed_words.txt` (--update nach Review).

## Phase: Vision v8 — Klarheit auf einen Blick + Sektorrotation + Markt-Ampel (2026-07-16)
> Nico-Direktive: Notifications sind unübersichtlich/unverständlich/nicht zielgerichtet — Ziel:
> "auf den ersten Blick gute Aktie / schlechte Aktie", kein Müll, Absätze + Detailtiefe zum
> Nachlesen. Plus Sektorrotation und weitere recherchierte Strategien (Regime-Ampel, 52W-High,
> F-Score). **Spec: `docs/superpowers/specs/2026-07-16-vision-v8-clarity-sector-rotation.md`**
- [x] A1 feat(telegram): HTML `parse_mode` einführen — `escape_html()`-Helper, alle Sende-/Edit-
      Pfade (Text, Foto-Caption, Caption-Edit) auf HTML umstellen, defensiver Plain-Text-Retry
      bei 400-Fehler; alle dynamischen Inhalte escaped; Tests für Escaping + Fallback
- [x] A2 feat(pitch): deterministisches Ampel-Urteil 🟢/🟡/🔴 (`compute_verdict`: Score-Bänder ×
      Risikosignale, pure Funktion, getestet) + Ein-Satz-Warum; ehrlich gelabelt als
      "Einstiegs-Attraktivität laut Modell", in Caption + Langpitch + Inbox-API + Frontend
- [x] A3 feat(pitch): Layout-Redesign mit Absätzen — Caption: fetter Kopf (Ticker + Urteil),
      Leerzeilen zwischen Blöcken (Überblick / Fakten / Risiko); Langpitch: `<b>`-Abschnitts-
      überschriften + `<blockquote expandable>` für den Detailteil (Bot-API-Support in Captions
      prüfen; Fallback laut Spec)
      → Entscheidung: expandable-Quote NUR in Textnachrichten (A5-Details), Caption nutzt
      nur `<b>` + Absatz-Blöcke — kein Caption-Support-Risiko; Overflow degradiert zu plain
- [x] A4 feat(notify): Qualitäts-Gate statt Auffüllen — `--min-pitches`-Auffülllogik ersetzen
      durch Score-Schwelle (`--min-score`, Default aus bisheriger Threshold-Praxis); 0 Kandidaten
      ⇒ ehrliche Ein-Zeilen-Meldung statt Mittelmaß; Digest nennt Anzahl unter der Schwelle
      → umgesetzt via bestehendem `--threshold` als Qualitätsgrenze für Top-ups (kein neues
      Flag nötig); Leermeldung + Schwellen-Transparenz in run_notify; Digest-Zeile folgt in A6
- [x] A5 feat(receiver): 🔎-Details-Button pro Pitch (`detail:<pitch_id>` callback) — Receiver
      antwortet mit der langen erklärenden Pitch-Version als eigene Nachricht (HTML, Absätze)
      → HTML-Variante wird beim Pitch-Erzeugen persistiert (`pitch_html`, ein gecachter
      Ollama-Call für beide Varianten); Detail-Press ist keine Entscheidung, Pitch bleibt offen
- [x] C1 feat(regime): `regime.py` — 4 Signale (SPY vs. 200d-MA, VIX-Band, Breadth = % Universum
      > 200d-MA aus Cache, Zinskurve ^TNX−^IRX) → Composite-Ampel 0–4 grün; pure Funktionen,
      Fake-Daten-Tests, ehrliche Degradierung wenn ein Signal keine Daten hat
- [x] B1 feat(strategies): `SectorRotationStrategy` — 11 SPDR-Sektor-ETFs (XLK XLF XLV XLI XLE
      XLU XLB XLP XLY XLRE XLC), Top-3 nach 12M/6M-Momentum-Blend, monatlich, Absolut-Momentum-
      Cash-Fallback (BIL) wie GEM; in `default_strategies()` registrieren; Backtest läuft mit
      → per-Slot-Hurdle (Slot fällt auf IEF), junge Sektoren (XLC/XLRE) werden übersprungen,
      < 6 rankbare Sektoren ⇒ voll defensiv; bewusst NICHT im Ensemble-Blend (C4-Lektion)
- [x] B3 feat(sectors): Sektor-Momentum-Snapshot — Ranking aller 11 Sektor-ETFs (1M/3M/6M/12M)
      als pure Funktion + `/api/sectors` + Dashboard-Karte "Sektoren"
      → `sectors.py` nutzt dieselbe MarketView-Arithmetik wie die Rotation (Anzeige kann der
      Strategie nie widersprechen); `top_sector_line` liegt bereit für den A6-Digest-Kopf
- [x] A6 feat(digest): Digest-Redesign — HTML-Sektionen mit fetten Überschriften + Absätzen;
      Kopfzeile = Markt-Ampel (C1) + Top-3-Sektoren (B3), beide degradieren ehrlich wenn Daten
      fehlen; bestehende Sektionen (Alerts/Chancen/Earnings/Pitches/Evidenz) bleiben inhaltlich
      → Regime im Digest aus Trend/VIX/Zinskurve (Breadth-Wiring folgt mit C2); SMTP/stdout
      bleiben plain, Telegram bekommt die HTML-Variante; A4-Schwellen-Transparenz-Zeile drin
- [x] B2 feat(forward): Sektor-Rotation als Forward-Paper-Konto aufnehmen + im Strategien-
      Dashboard sichtbar (build_reports nimmt Registry-Strategien auto auf — verifizieren)
      → verifiziert: run_forward_paper iteriert default_strategies() ⇒ Konto entsteht beim
      nächsten Lauf automatisch; alter Panel-Snapshot ohne Sektor-Ticker ⇒ Konto sitzt ehrlich
      in Bonds bis zum nächsten `--refresh` (Integrationstests)
- [x] C2 feat(api): `/api/regime` + Dashboard-Ampel (Strategien- oder Übersichts-Kopf) — gleiche
      Ampel wie im Digest, ein Klick zeigt die 4 Einzelsignale mit Werten
      → Breadth = Sektor-ETF-Approximation aus dem lokalen Panel (ehrlich als "Sektoren"
      gelabelt, volle Universums-Historie existiert nicht lokal); Tages-Cache in der API;
      Ampel auf der "Heute"-Seite als Disclosure; Digest-Regime jetzt ebenfalls 4/4-fähig
- [x] D1 feat(factors): 52-Week-High-Proximity als zweite Momentum-Metrik (Blend mit 6M-Return
      innerhalb der momentum-Familie, global gerankt) + `docs/factors.md` nachziehen
      → Quelle: `fiftyTwoWeekHigh` aus dem info-Call (kein zusätzlicher Fetch, History bleibt
      6mo); alte Cache-Rows degradieren aufs 6M-Bein bis zum nächsten Refresh
- [x] D2 feat(quality): Piotroski F-Score via SEC EDGAR XBRL `companyfacts` (UA-Header; ohne
      `EDGAR_USER_AGENT` ehrlich "unconfigured" wie der 13F-Collector) als Quality-Trend-Metrik
      im Quality-Score-Blend; yfinance-Fallback NICHT bauen (bekannt löchrig)
      → ABWEICHUNG: NICHT im Quality-Blend — companyfacts nur für Watchlist-Ticker machbar
      (Universum-Sweep wäre GB-groß) und eine Metrik, die nur 30 von 6.6k Titeln haben, darf
      nicht ins Universums-Perzentil. Stattdessen eigenständige, klar gelabelte Bilanz-Trend-
      Zeile auf Pitch/Caption ("ohne Einfluss auf den Score"), 30-Tage-Cache (`f_scores`),
      Kriterium einzeln None wenn Daten fehlen, Score nur ab 5 bewertbaren Kriterien

## Phase: Vision v10 — Autotrader "Auto-Depot" (2026-07-20) — DONE 2026-07-20
Spec/Plan: `docs/superpowers/{specs,plans}/2026-07-20-vision-v10-autotrader.md`. Ein
automatisch gehandeltes Paper-Meta-Depot über alle Sleeves: Meta-Allokation (EW-Anker +
Sharpe-Softmax-Tilt, 63d-Fenster, Floor/Cap, monatlich; Anker-Phase ehrlich gelabelt bei
< 60 überlappenden Forward-Beobachtungen), Look-Through-Aggregation mit Ticker-Netting,
komponierbarer Risk-Layer (ConcentrationCap 10 %, RegimeGate rot→½, VolTarget 12 %,
DrawdownBreaker 10 %/20 % mit Hysterese+Cooldown), Close-Fill-Konvention wie forward_paper,
Trades/Valuations/Risk-Events als eigene Tabellen (`autotrader.db`), EUR-Spot je Valuation.
Nightly-Step nach forward_paper (18:00 wäre Intraday-Stand); Digest-Block, `/api/autodepot`,
Dashboard-Tab "Auto-Depot". Broker-Seam = Trade-Rows + README-Fakten (Alpaca/T212/IBKR),
bewusst KEIN Adapter-Code — Echtgeld-Routing bleibt per LOOP.md verboten.
- [x] Backlog: Next-Open-Fills (braucht OHLC-Panel-Welt; Close-Fill + konservative 10 bps
      decken den Realismus-Gap bei täglicher Kadenz)
      DONE 2026-07-24 (v13 Wave O): OHLC-Panel-Welt + pending_orders-Fills am nächsten Open
      + Corwin-Schultz-Kostenboden — siehe Phase Vision v13.
- [ ] Backlog: (Fractional-)Kelly-Sizing erst ab ~50 realisierten Depot-Trades (vorher
      Schätz-Rauschen)
- [x] v10.1 Always-on (2026-07-20, same session): `run_nightly_guarded.sh` (flock +
      Tages-Marker, KEIN Wochenend-Skip — Sonntag-Catch-up eines verpassten Samstag-Slots
      bucht den Freitags-Close), persistenter systemd-Timer `equity-scout-nightly.timer`
      02:35 Tue–Sat (installiert + aktiv), Crontab-Nightly-Zeile auf den Wrapper umgestellt
      (Installer ausgeführt), Windows-Task-XML `equity-scout-nightly` bereitgestellt
      (Registrierung → Needs Nico). 3 Wrapper-Tests (pytest/subprocess).

## Phase: Vision v11 — Kurzfrist-Arena (2026-07-20) — DONE 2026-07-20
Spec/Plan: `docs/superpowers/{specs,plans}/2026-07-20-vision-v11-shortterm-arena.md`. Drei
Kurzfrist-Paper-Lanes à 10.000 USD im ehrlichen Wettrennen (Nico: "alles umsetzen, tracken,
schauen was sich rentiert"): `swing` (Event-Swing 1–5 Tage auf classified_events, nightly),
`session` (ORB-Daytrader auf ~15-min-VERZÖGERTEN Bars mit Settled-Bar-Gate + Fill am
nächsten settled Open, nie über Nacht, */15 im Marktfenster), `crypto` (Donchian 20/10 auf
Kraken-ECHTZEIT-Bars, 24/7-Cron, Benchmark BTC buy-and-hold). Gemeinsames Book mit
realisiertem P&L/Win-Rate/Kosten als First-Class-Werten (`shortterm.db`), long-only v1.
Surfaces: Dashboard-Tab "Kurzfrist-Arena", /api/shortterm, Digest-Block "⚡". Framing
unverändert ehrlich: Erwartung nach Kosten negativ — die Arena misst, sie verspricht nichts.
- [ ] Backlog: Shorts in den Lanes erst mit Borrow/Margin-Realismus
- [x] Backlog: Session-Lane auf Alpaca-IEX-Echtzeit (kostenloser Key) umstellbar — würde das
      Delay-Modell überflüssig machen; Needs Nico (Account)
      DONE 2026-08-06: Lane läuft live auf Alpaca Paper, das Delay-Modell ist raus.

## Phase: Vision v12 — "One Autotrader" (2026-07-20) — DONE 2026-07-21
Spec/Plan: `docs/superpowers/{specs,plans}/2026-07-20-vision-v12-one-autotrader.md`. Nico-Direktive
2026-07-20: Autotrader komplett reviewen + aufarbeiten, Short/Mid/Long als EIN System, Telegram
aufs Handy, Dashboard als Handy-App (Laptop = Server), Beweis-Evidenz "kann das funktionieren?".
Drei-Spur-Review (Kern/Arena/Notify) 2026-07-20 abgeschlossen; Findings im Plan-Doc verankert.
Harte Grenzen unverändert: paper-only, kein Order-Routing, local & free, DISCLAIMER überall.
- [x] R1 (P0) Session-Lane: stale Positionen (opened_at != heute) vor decide() zwangsflatten
- [x] R2 (P1) Zentrale SQLite-Konventionen (db.py: WAL + busy_timeout) für autotrader/shortterm
- [x] R3 (P1) Atomarer Autotrader-Persist (eine Transaktion, Account-Blob zuletzt)
- [x] R4 (P1) Atomarer Shortterm-Persist (eine Transaktion pro Lane-Step)
- [x] R5 (P1) Depot-Exits über Sleeve-Bücher (ML-Sleeves spiegeln POST-Exit-Buch, Docstring-Fix)
- [x] R6 (P1) Digest: bei TelegramError persistieren + beim nächsten Chain-Lauf nachsenden
- [x] R7 (P1) Digest-Freshness-Guards (⚠️ bei as_of älter als 2 Handelstage)
- [x] R8 (P1) Intraday-Bars: tz-Assertion + lauter Fehlerpfad
- [x] R9 (P2) Allocator: Kalenderlücken-Returns aus dem Sharpe-Fenster filtern
- [x] R10 (P2) Marktfenster aus America/New_York berechnen (DST-Übergang)
- [x] R11 (P2) Robustheits-Sweep (/api/entry-Guard, Receiver-answerCallbackQuery, Swing-Event-Alter)
- [x] W1 Chain-Heartbeats + Dead-Man-Watchdog mit Telegram-Alarm (Cooldown 24h)
- [x] W2 Auto-Depot-Event-Push (Trades/Risk-Events gebündelt, silent, env-gated)
- [x] I1 /api/overview: Gesamtvermögen + Horizont-Subtotale (short/mid/long)
- [x] I2 promotion.py: Beweis-Gate (≥30 Trades, ≥60 Tage, Netto-P&L>0, PF≥1.1)
- [x] I3 Promotion-Wiring: eligible Lane wird Auto-Depot-Sleeve, Demotion bei Verfall
- [x] I4 Integrations-Surfaces (Digest-Prüfstand-Zeile, FE Gesamt-Tab + Promotion-Checkliste)
- [x] M1 --host-Flag + Token-Auth-Middleware (DASH_TOKEN, localhost exempt, Fail-closed)
- [x] M2 PWA-Shell (manifest + icons + theme-color, kein Service Worker in v1)
- [x] M3 Dashboard-Server als systemd user service (Port 8420, Restart=always)
- [x] M4 Handy-Onboarding (Digest-Footer mit DASH_URL wöchentlich, README, Tailscale=Needs Nico)
- [x] P1 proof.py: ehrliche Kennzahlen pro Buch (Sharpe/MaxDD/WinRate/Kostenanteil + Labels)
- [x] P2 Proof-Surfaces (/api/proof + FE "Beweis"-View mit Überzeugungs-Schwellen)
- [x] P3 Monatlicher Telegram-Proof-Report (state-gated, 1. des Monats)
- [x] P4 Docs-Abschluss (README "Kann das funktionieren?", Outcome-Sektion)

## Phase: Vision v13 — "Trust & Honest Fills" (2026-07-23) — DONE 2026-07-24
Spec/Plan: `docs/superpowers/{specs,plans}/2026-07-23-vision-v13-trust-and-honest-fills.md`.
Nico-Direktive: "alles dranlegen, dass der Autotrader krass wird — Review, alles."
Drei Wellen, alle abgeschlossen (Outcome-Details im Plan-Doc):
- **Wave R (Härtung, 7 Tasks):** beide P0s (Arena-P&L-Verlust via persistente Bewertungs-
  Marks; gap-toleranter Panel-Load — der Trim steckte AUCH in run_forward_papers Snapshot)
  + P1/P2 (stale-Position-Zwangsexit, ehrlicher Kostenanteil-Nenner, Promotion-Gate liest
  alle Trades, Swing exits-before-entries + pick_entries-Off-by-one gefunden/gefixt).
- **Wave Q (ML-Unblock + Qualität, 5 Tasks):** Mindest-Historie-Vorfilter fürs Entry-Panel
  (entblockt entry_tb-Walk-Forward), dsr_hurdle-Spalte im Research-Ledger (Migration),
  WFE-Metrik (soft, Excess-AUC-Ratio), voices-Single-Token-Gate + Drift-Scanner
  (`scripts/scan_generic_words.py` + Snapshot), FetchStats-Laufzeile.
- **Wave O (ehrliche Ausführung, Depot-only, 3 Tasks):** OHLC-Panel-Welt (`data/ohlc_panel.py`),
  Next-Open-Fills über persistierte pending_orders (Kosten am Fill, Intraday-Attribution,
  ehrliche fill-Labels, Legacy-Migration), Corwin-Schultz-Kostenboden max(10 bps, CS/2) als
  dokumentierte UNTERGRENZE (`costs.py`); Sleeves bleiben bewusst Signal-Layer (Close-Fill,
  flat 10 bps). README-Konventions- und P0-Absatz, ProofView-Label "Kostenanteil (mind.)".
- [x] Verify: erste Live-Nightly unter Next-Open beäugt (2026-07-24). Befund: Übergangsnacht
      korrekt (Legacy-Blob ohne Pending → kein Fill, neue Pending erzeugt), ABER die
      02:34-Nightly lief gegen eine Tokio-gestempelte 24.07.-Panelzeile (laufende Session,
      US-Spalten = ffill-Kopien) → Depot + ML Long Bot standen auf `last_as_of=2026-07-24`;
      der Samstag-Lauf hätte den echten Freitags-Close idempotent ÜBERSPRUNGEN und die
      Pending-Orders wären nur je am Close-Fallback gefüllt worden (Next-Open faktisch tot).
      Fix: `last_completed_us_session` + `trim_to_completed_sessions` in BEIDEN Loader-Pfaden
      (deckt auch manuelle Tages-Läufe ab, die Intraday-Kurse als Close buchen — Vorfall
      2026-07-23 15:57); Einmal-State-Reparatur `scripts/fix_future_asof_2026_07_24.py`
      (Backup in `data/backup-2026-07-24-pre-asof-fix/`). Bekannter, akzeptierter Rest:
      der 15:57-Lauf hat Intraday-als-Close gebucht — einmalige Bewertungsunschärfe im
      Depot-Track-Record, nicht rekonstruierbar. Dry-Run-Smoke grün (Trim + Idempotenz).

## Phase: Vision v14 — Strategie-Parameter-Suche (2026-07-24) — DONE 2026-07-24
Spec/Plan: `docs/superpowers/{specs,plans}/2026-07-24-vision-v14-strategy-param-search.md`.
P7/v5-P4 umgesetzt: zweite Suchdimension im Research-Loop über die Knobs der Regel-Strategien
(Vol-Target 4×4, GEM 4, DAA 3, Sektor-Rotation 4×4, 60/40 4 = 43 Configs; bewusst ohne
Leverage/Permanent/DCA — Begründung im Modul-Docstring). EIGENE Buchführung: Tabellen
`strategy_trials` + `strategy_loop_state` in research_ledger.db mit EIGENER
expected-max-Sharpe-Hürde — ML-Suche und Strategie-Suche teilen sich nie ein
Multiple-Testing-Budget (Trennungs-Test). Trial = Whole-History-After-Cost-Backtest
(`engine.run_backtest`, ME, 10 bps) → PSR-Statistiken; Cursor wrappt modulo Raumgröße
(ausgeschöpftes Grid re-evaluiert per Upsert gegen die wachsende Historie — Zählung bleibt
unique, Metriken bleiben frisch). Surfaces: `/api/research`-Block `strategy_search`
(Champion/Leaderboard/Beste-pro-Strategie), Dashboard-Karte in der Forschung-View mit
In-Sample-Label, Nightly-Step `strategy_research --trials 25`, CLI
`run_strategy_research.py`. Ehrlichkeitsgrenze: Champions sind Evidenz, NIE Auto-Übernahme —
geänderte Parameter wären eine neue Strategie-Identität und würden Forward-Track-Records
verfälschen (v15-Kandidat: Übernahme als neue Sleeve-Identität mit frischem Track).
Live-Smoke 2026-07-24: 5 Trials gegen das echte Panel (Hürde 0.000→0.005), Dash-Service
neu gestartet, `/api/research` liefert den Block live.

## Phase: Session-Lane auf Alpaca Paper, minütlicher Takt (2026-08-04/06) — DONE 2026-08-06
Spec/Plan: `docs/superpowers/{specs,plans}/2026-08-04-session-lane-*`. Die Lane handelt jetzt
über ein PAPER-Broker-Konto (`PA3SIKMAPF0N`) statt simuliert: Opening Range aus 15-Min-,
Trigger aus 1-Min-IEX-Bars, Entries als Bracket-Orders (Stop/Target liegen im Markt und
triggern auch bei totem Rechner — die 21.07.-Ausfallmechanik), Reconciliation gegen den Broker,
erste MESSBARE Slippage in `st_executions`. Takt `*/15` → **jede Minute Mo–Fr** aus eigenem
Script/Lock/Log (`scripts/session_lane.sh`, `session.log`); stille No-Op-Läufe sind Pflicht,
sonst wäre das Log bei 390 Läufen/Tag unlesbar. Windows-Task `equity-scout-session` weckt die
Maschine vor der Eröffnung (der Minuten-Cron in WSL kann sonst gar nicht feuern) und heilt den
Fall „WSL läuft, cron tot" im 10-Minuten-Notbetrieb.
**Ehrlichkeitsgrenze:** der Track VOR dem 06.08. entstand auf verzögerten Bars mit simulierten
Fills und ist strukturell zu gut — `execution_regime` markiert den Bruch auf Desktop UND Handy,
die beiden Zeiträume sind keine Serie. Fünf Defekte fand erst der Live-Betrieb (alle mit
Regressionstest gefixt): Exit für nie eröffnete Position; `pending_new` ist die EINZIGE
Order-Antwort (der „filled"-Zweig war unerreichbar, 4 Orders liefen ungebucht); Menge nach dem
Fill neu abgeleitet statt gebucht; jeder Exit wäre an `held_for_orders` gescheitert; Teilfüllung
spaltete Buch und Broker. Verify erledigt: 07.08. lief eine volle Session (324 Cron-Ticks,
~5 s Entry-Latenz auf dem einen echten Cron-Fill), und der „Session-Ende (flat)"-Exit ist seit
07.08. 15:45 ET live belegt (NFLX +6.08, TSLA −9.30 über den eigenen Flatten-Pfad).

## Phase: Bracket-Leg-Fills zurücklesen (2026-08-09) — DONE 2026-08-09
Sechster Live-Defekt derselben Familie, gefunden beim Nachlesen des 07.08.-Logs. Die
Bracket-Legs liegen im Markt und feuern ohne uns (genau ihr Zweck, 21.07.-Ausfallmechanik) —
aber das Buch las diese Fills NIE zurück: es führte die Position weiter, bis die eigenen Bars
ein Exit-Signal erzeugten, dann lief `_close_position` in ein 404 und buchte den SIGNALPREIS.
Messung am Live-Konto: **alle sechs Stop-Exits des 07.08.** so gebucht, jeder besser als der
Markt gab (+1.26 USD auf 10k = 1.3 bps/Tag, systematisch einseitig), und keiner davon in
`st_executions` — die Slippage-Statistik sah nur die selbst platzierten Orders.
`session_reconcile.resolve_book_only` löst jetzt eine `book_only`-Abweichung über die
Fill-Historie auf und bucht den echten Exit (Preis, Zeit, Menge) plus Execution-Zeile gegen
den Preis, den das Leg wollte — erste Messung der Stop-Slippage überhaupt (META wollte 592.08,
bekam 591.965 = −1.9 bps). Läuft vor Stale-Flatten, vor `decide()` UND vor dem Nachlauf-Sweep,
der denselben Defekt durch die eigene Tür hatte. Grenze bleibt: `broker_only` und
`qty_mismatch` werden nie geheilt, ein Fill vor der Positionseröffnung oder einer, der die
Menge nicht deckt, löst zu nichts auf — Melden schlägt Raten. Zeitstempel werden als Instant
verglichen (Buch stempelt New York, Alpaca antwortet UTC; als String sortiert ein 18:00Z-Fill
hinter einen 15:45-04:00-Entry, den er in Wahrheit um vier Stunden unterschreitet).
Replay gegen die echte Order-Historie: alle 6 Abweichungen lösen korrekt auf.
- [ ] Nicht rückwirkend korrigiert: die 6 Trades vom 07.08. bleiben zum Signalpreis gebucht
      (1.26 USD Bewertungsunschärfe, Präzedenz v13 15:57-Lauf). Rekonstruierbar wäre es —
      die Kaskade über Cash/Valuations/Proof-Metriken ist das Risiko nicht wert. Falls doch:
      die 6 fehlenden `st_executions`-Zeilen wären additiv nachtragbar.

## Phase: v15 P2 — Insider-Cluster-Schattenlane (2026-08-09) — DONE 2026-08-09
Spec/Plan: `docs/superpowers/plans/2026-08-07-v15-p2-insider-shadow-lane.md` (Outcome dort).
Die EINZIGE Evidenzklasse, die die P2a-Studie überlebt hat, bekommt eine vorab registrierte
Vorwärtsspur — ohne Kapital: Detection (≥3 verschiedene Insider, `evidence/insider_shadow.py`),
Runner (`scripts/run_insider_shadow.py`), Status-JSON, eigener Cron 18:45 Mo–Fr. Eine offene
Vorhersage pro Ticker, EIN Horizont (63 Handelstage), Prior trägt die Out-of-Sample-Schwäche
(+0,77 % ± 0,79pp) auf jeder Oberfläche mit. **Die Kongress-Lane ist auf den Zahlen tot** und
bleibt reine Annotation. Zwei geerbte Wave-1-Defekte im Evidenz-Ledger mitgefixt: Kalender-
statt Handelstag-Stempel (Zeilen wurden ~30 Tage zu früh „fällig") und ein Resolver, der ein
VERSCHOBENES Fenster maß und als Ergebnis buchte (Test bewies `resolved: 1` vor dem Fix).
1833 Tests, 25 neu.
- [ ] Beobachten: die Lane hat 0 Zeilen registriert, weil `evidence_events` in der GESAMTEN
      Historie nur 1 Insider-Ereignis hält (congress zum Vergleich: 671 in 30 Tagen). Ursachen
      gemessen: Form-4-Kollektor war bis 08.08. defekt und lief seitdem durch keinen
      Werktags-Lauf (erster: Mo 10.08. 18:00); nur 17 der 30 Watchlist-Titel sind überhaupt
      Form-4-fähig (13 sind nicht-US), und die 17 sind Small Caps/Closed-End-Fonds. Ab Montag
      prüfen, ob Filings ankommen — bleibt es leer, ist die Sichtfeld-Grenze das Thema,
      nicht die Lane.

## Phase: Wartungsrunde 2026-08-10 (Watchdog, Kapitalbasis, Crypto-Kosten, M2) — DONE
Nach der Bestandsaufnahme „Was macht der Autotrader, funktioniert das?" abgearbeitet. Plan für
den Crypto-Teil: `docs/superpowers/plans/2026-08-10-crypto-lane-cost-honest-holding-period.md`.
- **Watchdog-Fehlalarm behoben** (`164ebc9`): die SLA war flach 26 h für alle Ketten, die
  nightly läuft aber Di–Sa. Sonntag und Montag war ihr Heartbeat planmäßig 48–72 h alt →
  garantierter Wochenend-Fehlalarm, live gemessen als „nightly überfällig seit 64 h", während
  die Kette exakt im Plan lag. Kadenz-Ketten werden jetzt gegen den letzten FÄLLIGEN Slot in
  der Zeitzone des Crontabs geprüft, mit dem frühesten Trigger als Slot (der Heartbeat wird am
  Ende der Kette gestempelt und kann dem systemd-Slot vorausgehen). Der Alarm nennt den
  verpassten Slot, damit er gegen den Crontab falsifizierbar ist. Gleicher Fix deckt den
  daily-Fehlalarm am Wochenende ab.
- **Session-Lane: Broker-Equity wird mitgeschrieben** (`4fe435b`): das Buch rechnet auf 10.000,
  das Papierkonto hält 100.000 — dieselben Trades lasen sich als −2,41 % (Buch) und −0,10 %
  (Konto). Additiv gelöst: `equity`/`total_return` bleiben das Strategie-Ledger, die neue
  Spalte trägt, was die Börse selbst meldet (`fetch_account`), NULL für simulierte Lanes und
  alle Altzeilen. Ein Backfill aus dem Buch hätte genau die Zahl erfunden, die die Spalte
  verhindern soll. Cockpit zeigt beide plus die Kapitalauslastung.
- **Crypto-Lane auf Tagesbars** (`c446017`): von 451,60 USD Verlust waren ~460 USD Gebühren —
  vor Kosten ±0, nach Kosten Totalverlust. Donchian 20/10 jetzt auf Tagesbars, Hard-Stop
  2 % → 15 %. Die Taker-Fee wurde bewusst NICHT auf den Maker-Satz gesenkt (die Lane routet
  nichts, und ein Limit am Ausbruchsniveau ist genau die Order, die beim Ausbruch nicht füllt).
  Übergangsdefekt vom Live-Lauf gefunden: die Bar-Watermarks der 15-Minuten-Ära sind neuer als
  der neueste vollständige Tagesbar und blockierten jede Entscheidung.
- **v15 M2 verdrahtet** (`6d42963`): Evidence-Challenger teilen Familie UND model_kind mit
  ihrer Basis, waren auf der Lernkurve also nicht unterscheidbar. `evidence_features` und
  `evidence_coverage_91d` gehen jetzt durch die API, die Kurve zeichnet Evidenz-Versionen als
  Ringe, und die Bildunterschrift sagt, dass 2,5 % Abdeckung noch kein Befund ist.
- **Windows-Tasks wecken jetzt** (`ea224f1`): `WakeToRun` war bei daily und nightly false (nur
  session hatte es) — beide Slots hingen davon ab, dass die Maschine schon wach war. Live
  gesetzt und im gestageten XML verankert, damit der Installer es nicht zurückdreht.
- **Chat-Latenz: stabiles Präfix statt kurzer Prompts** (`b1c772b`, Plan
  `docs/superpowers/plans/2026-08-10-chat-latency-prompt-cache.md`). Nicos Randbedingung „nur
  den Laptop": Intel Iris Xe ist für Ollama praktisch nutzlos (keine offizielle Unterstützung,
  und eine iGPU teilt den Speicherbus mit der CPU — genau die limitierende Ressource). Also
  am Prompt gearbeitet. Kernmessung: **Ollama cached das Prompt-Präfix zwischen Anfragen —
  gleiches Präfix 1,8 s Prefill, anderes 108,6 s.** Damit kippt die Richtung: stabil schlägt
  kurz, und das bisherige Topic-Trimming des Glossars baute pro Themenkombination ein anderes
  Präfix. Glossar jetzt konstant und vorn, ADVICE_BRIEF dahinter, Keyword-Routing am
  Wortanfang verankert (`hältst`/`offensichtlich`/`Sammlung` feuerten als Substrings),
  Überblick-Fallback unterdrückt sobald die Frage einen Anker hat. Der Live-Check fand einen
  echten Antwort-Defekt: Hausbegriff-Fragen trafen kein Keyword, bekamen über den Fallback das
  ganze Dashboard und wurden mit „steht nicht im Datenkontext" beantwortet, obwohl die
  Definition im Glossar darüber stand — neues Topic `begriffe`, **121 s und falsch → 8 s und
  richtig**. Grenze: alle Sekundenwerte unter Fremdlast gemessen, der 1.5b-Modellvergleich
  war dadurch ungültig und bleibt offen.
- **Schritt-Timeout in den Ketten** (`c1a906d`) — gefunden vom neuen Watchdog, zwei Stunden
  nachdem es passierte, am selben Abend, an dem er gebaut wurde. Die Daily-Kette vom 10.08.
  lief nie fertig: `insights` (12 Titel × 2 LLM-Aufrufe, normal 2–3 Min) kroch unter schwerer
  CPU-Last, der Windows Task Scheduler beendete die Kette an ihrem 1-Stunden-Limit
  (`LastTaskResult` 0xC000013A), und **alles danach fiel aus — `evidence`, `fscore`, die
  Resolver und die Telegram-Zustellung**. Ohne Log-Zeile, ohne Tages-Marker. Die Ketten
  degradierten pro Schritt nur, wenn der Schritt ZURÜCKKAM; ein hängender war unbegrenzt.
  Jetzt läuft jeder Schritt unter `timeout` (daily 12 min, nightly 25 min, per
  `EQUITY_SCOUT_STEP_TIMEOUT` überschreibbar), und Exit 124 wird als `TIMEOUT` statt `FAILED`
  geloggt — „zu langsam" und „kaputt" brauchen verschiedene Reaktionen. Der Tageslauf wurde
  danach manuell nachgeholt. Die zwei übrigen Ketten (`intraday_copilot.sh`,
  `run_full_refresh.sh`) haben denselben unbegrenzten `step()` — siehe Backlog.
- Gate der Runde: 1883 Tests grün, ruff clean, `tsc --noEmit` clean.
- [x] Schritt-Timeouts der Intraday-Ketten — 2026-08-11, gemessen statt geschätzt (genau die
      Sorge, die den Punkt zurückgestellt hatte). Über **226 protokollierte Läufe**: radar median
      7 s / p95 10 s, aber **EIN Lauf bei 995 s (16,6 min)**; evidence median 25 s / max 65 s;
      notify median 1 s / max 60 s. Der 995-s-Ausreißer überlief die 15-Minuten-Kadenz, also
      übersprang `flock -n` den Folgeslot — der Hänger kostete zwei Runden, und **nichts im Log
      sagte warum**. Cap jetzt 5 min (~9× der langsamste normale Schritt, weit innerhalb der
      Kadenz), TIMEOUT vs. FAILED getrennt geloggt wie in der Tageskette.
- [x] **Neuer Fund derselben Runde, gravierender als der Backlog-Punkt: die minütliche
      Session-Lane konnte still offline gehen.** `flock -n` verhindert Stapeln, aber **derselbe
      Lock macht einen HÄNGER schlimmer als einen Absturz**: solange ein Lauf ihn hält, wird jede
      folgende Minute übersprungen — ein einziger steckengebliebener Netzwerkaufruf hätte die Lane
      so lange lahmgelegt, wie der Prozess lebt, ohne eine einzige Logzeile. Cap 55 s, also unter
      der Kadenz: der schlimmste Fall kostet eine Minute statt einer Sitzung.
- [x] `run_full_refresh.sh` bewusst OHNE Cap — begründet abgelehnt statt mitgezogen: seine
      Schritte SIND die geschützten Ketten (daily 12 min, nightly 25 min je Schritt), ein Cap dort
      müsste Stunden abdecken und würde nichts retten. Ein Test pinnt die Entscheidung, damit
      niemand sie als Versäumnis „behebt".
- [x] **Folgebefund `insights` passt nicht mehr in sein Budget** — gemessen und behoben
      2026-08-11, siehe eigene Phase unten.
- [ ] **Crypto-Lane Kill-Kriterium (vorab registriert 2026-08-17):** Urteil ausschließlich auf
      Daily-Ära-Trades (`lane_review.MEASUREMENT_EPOCHS`, Epoche 2026-08-10). Nach ≥ 30
      geschlossenen Daily-Ära-Trades entscheidet `significance.assess_trades`: Verdict „negativ"
      ⇒ Cron-Zeile entfernen (Lane-Ende, Buch bleibt lesbar — Session-Lane-Präzedenz);
      „positiv" ⇒ Promotion-Gate wie jede Lane. Bei 20/10-Donchian über 4 Paare sind das
      grob 12–24 Monate — wer früher urteilen will, braucht ein anderes Kriterium, nicht
      dieselben Daten nochmal. Stand beim Einbau: 4 Daily-Ära-Abschlüsse, −129,72 USD, Verdict
      „zu wenige Trades" (vorher las die Lane regime-gemischt „negativ, entschieden" über 32
      Trades / −451,60 USD — eine Zahl über eine Regel, die es nicht mehr gibt).

## Phase: v16 „Alpha-Fabrik" Welle 1 — vier neue Strategiefamilien (2026-08-10) — DONE
Plan + alle Zahlen: `docs/superpowers/plans/2026-08-10-v16-alpha-factory.md`. Autonom
umgesetzt auf Nicos Auftrag „bring die Applikation auf 10/10, mach das in einer Loop zuende".
Bewertung vorab: Maschine 8/10, Geldverdienen 2/10 (jedes Buch hinter Benchmark), gesamt 5/10.
Die Lücke war der zu enge Suchraum — alle 12 Strategien kamen aus EINER Familie.
- **Vier Familien mit verschiedenen Entscheidungsgründen** (`1aacab3`, 22 Tests): Low-Vol
  (wählt nach Risiko allein), Cross-Sectional Momentum (12-1 mit Skip-Month), Mean-Reversion
  (kauft, was die anderen verkaufen; z-normiert + Regime-Gate), Risk Parity (keine Auswahl).
  Jede verweigert einen stale Feed statt einen wiederholten Preis als risikolos zu ranken.
- **Backtest echtes ETF-Panel:** Cross-Sectional Momentum matcht SPY (15,3 % CAGR) bei
  −25,4 % statt −33,7 % Drawdown, Sharpe 1,00 — zweitbeste im Feld von 13. Risk Parity
  brauchbar (0,78), Low-Vol schwach (0,61), Mean-Reversion gescheitert (0,31 bei 16× Turnover).
- **Alle vier haben ihren ersten Forward-Advance gemacht** — ab jetzt echter Track.
- **Suchraum 43 → 82** (`7aaa968`), damit der Nightly meine Literatur-Startwerte nachprüft.
  Befund gegen die Literatur: `skip_months=0` gewinnt auf Index-ETFs (Kurzfrist-Umkehr ist ein
  Einzeltitel-Effekt). Produktions-Defaults bewusst NICHT auf die In-Sample-Gewinner gesetzt.
- [ ] Beobachten: der Forward-Track der vier Familien. Cross-Sectional Momentum ist der
      Promotions-Kandidat, muss aber ≥30 Trades/≥60 Tage/Netto>0/PF≥1,1 nehmen wie jede Lane.

## Phase: v16 Welle 2 — Kapitaleffizienz des Auto-Depots (2026-08-10) — DONE
Zwei Defekte, der zweite gefährlicher als der erste (`f685a0b`).
- **Der Concentration-Cap parkte 24 % des Depots in Cash.** Die Sleeves wollten 83,9 % Brutto,
  SPY aggregierte per Look-Through auf 29,1 % und VEU auf 14,6 % (sieben Sleeves teilen EINEN
  ETF-Kern), der Cap kappte beide auf 10 % und ließ die Differenz zu Cash verfallen → 60,2 %
  Brutto gegen SPY +3,3 %. **23,7 Prozentpunkte lagen brach, die keine Risikoregel verlangt
  hat.** Der Cap begrenzt, wie viel in EINEM Titel steckt — er soll kein Cash halten. Jetzt
  wird der gekappte Anteil auf die Titel unter dem Cap verteilt (proportional, nie über den
  Cap); die Schranke bleibt gleich streng, und die Schichten dahinter skalieren weiter das
  volle Buch (Test: gestresstes Brutto = exakt 25 % des ruhigen). Track-Bruch als
  `protection_regime` gestempelt.
- **Beim Verifizieren gefunden:** `active_sleeves()` gab JEDE Registry-Strategie zurück — die
  vier neuen Familien hätten in der Nacht je 1/12 Depot-Kapital bekommen, mit null
  Out-of-Sample-Historie, darunter Mean-Reversion (Sharpe 0,31, 16× Turnover). Das Gate der
  ML-Bots gilt jetzt für alle Sleeves: ≥5 Forward-Sitzungen, zurückgehaltene werden gedruckt.
  Live verifiziert. **Lehre:** eine Strategie in die Registry zu legen war nie nur eine
  Registry-Änderung — sie floss direkt ins Depot.
- Gate: 1915 Tests grün, ruff clean.
- [x] **Depot-Brutto verifiziert: 84 %** (2026-08-11 nachts, Trockenlauf gegen DB-Kopien statt
      Warten auf die Nightly). Erwartet war ~84 % statt 60 % — trifft zu, die Cap-Umverteilung aus
      Welle 2 wirkt. Im selben Lauf gegenverifiziert, dass der Vol-Target-Layer nicht überschießt
      (Drawdown 0,0 %).
- [ ] Rest von Welle 2: die Session-Lane nutzt 10 % ihres Broker-Kapitals.
- [x] **Kosten-Netting über Lanes — nachgelesen 2026-08-11, kein Defekt gefunden, nicht gebaut.**
      Zwei Ebenen, beide bereits konservativ: (a) über die Depot-**Sleeves** nettet es schon — die
      Kosten laufen auf dem AGGREGIERTEN Delta je Ticker (`delta = fill_targets − weights` in
      `autotrader_engine`), nachdem die Sleeve-Gewichte zusammengeführt sind; gegenläufige Sleeves
      erzeugen also keine doppelte Gebühr. (b) Über die **Lanes** wäre Netting sogar falsch: sie
      sind getrennte Bücher mit getrennten Tracks, und ihnen Synergien zuzurechnen, die nur bei
      gemeinsamer Ausführung entstehen, würde jede Lane besser darstellen als sie einzeln ist.
      Geprüft und verworfen: das Depot zahlt 10 bps, wenn es Kapital in eine Lane verschiebt,
      obwohl das real eine Ein-/Auszahlung wäre — das ist eine ÜBER-, keine Unterzeichnung der
      Kosten. Ohne einen konkreten Defekt wird hier nichts umgebaut.

## Phase: v16 Welle 3 — Selektionsgeschwindigkeit (2026-08-10) — DONE
Beide Teile gebaut (`a8a50e7`, Verlustanatomie im Folgecommit). Zweck: schneller erkennen,
was funktioniert und was nicht — tote Strategien liefen sonst monatelang weiter.
- **`significance.py`: „ist das schon ein Urteil, und wenn nein, wie weit fehlt es?"**
  Zwei-seitiger t-Test auf den Ø-Trade plus die Trade-Zahl für 80 % Power beim beobachteten
  Effekt. In der API Bonferroni-korrigiert, weil alle Lanes in EINER Antwort gezeigt werden.
  **Live-Befund:** crypto `negativ, p=0,000` (belegt den heutigen Umbau nachträglich mit
  einer Zahl) · session `noch nicht aussagekräftig`, p=0,169, **~210 Trades fehlen** — die
  −2,4 % sind KEIN Urteil über die Strategie · swing `zu wenige Trades` (n=2).
  Ehrlichkeitsgrenzen im Docstring UND in der gerenderten Notiz: Trade-P&Ls sind schief und
  fat-tailed, der t-Test ist also optimistisch (echte Signifikanz braucht MEHR Trades); ein
  Effekt nahe Null gibt `None` statt einer siebenstelligen Trade-Zahl.
- **Verlustanatomie im Produkt** (`shortterm_book.loss_anatomy`, API + Arena-Panel): Summe,
  Anzahl, Ø und Ergebnisanteil je Exit-Grund, größter Beitrag zuerst. Live an der
  Session-Lane: **74,2 % des Verlusts sind fünf „Altbestand (zwangsflat)"-Trades** — ein
  Einmal-Aufräumen, nicht die Strategie. Genau die Aussage, für die es heute Mittag eine
  Handauswertung brauchte.
- Gate: 1933 Tests grün, ruff clean, tsc clean.
- **Flaky Test verfolgt und die Ursache gefixt** (statt den Test zu entschärfen): Ein
  Gesamtlauf ließ `test_calibrated_model_scores_through_the_calibrator` fallen, isoliert war er
  grün. Ursache war nicht der Test, sondern **`LogisticRegression(solver="saga")` ohne
  `random_state`** — saga ist ein STOCHASTISCHER Solver und zog aus dem globalen numpy-Zustand,
  den meine neuen Testdateien verschoben hatten. Tragweite über den Test hinaus: das Registry
  vergleicht AUCs auf drei Dezimalen und kürt Champions auf diesen Abständen, ein nicht
  reproduzierbarer Fit heißt also **ein Champion, der aus seinen eigenen Eingaben nicht
  wiederherstellbar ist**. Random Forest und CatBoost hatten ihren Seed von Anfang an; nur
  elastic_net fehlte er. Mit Reproduzierbarkeits-Test, der den globalen Zufallszustand
  absichtlich stört. Gate zweimal hintereinander grün (1934).

## Phase: Faktencheck Auflösungen + `insights`-Budget (2026-08-11) — DONE
Zwei Dinge, die keinen Bau brauchten, sondern eine Messung.

- **Der Predict-then-Resolve-Loop funktioniert.** Der für Mi 12.08. geplante Selbst-Check
  einen Tag vorgezogen, weil die erste Kohorte um 18:52 UTC fällig wurde: **30 von 30
  aufgelöst**, 0 ohne Vorwärtsfenster. Der Verdacht „Loop kaputt" (Grund für den v15-Wave-1-
  Plan) ist erledigt. **Warum die Tageskette am selben Tag noch 0 meldete:** sie läuft um
  16:13 UTC, also 2,5 h vor Fälligkeit — abends erzeugte Vorhersagen löst sie erst am Folgetag
  auf. Bei 20-Handelstage-Horizonten belanglos, notiert statt behandelt.
- **Erste Out-of-Sample-Zahlen, und sie sind unerfreulich:** 67 % Treffer gegen eine Basisrate
  von 77 % — **„immer ablehnen" wäre besser gewesen**. Ø −5,41 % gegen SPY, 7 von 30 schlagen
  den Index, und die fünf höchsten Scores waren die fünf schlechtesten Ergebnisse (WDC −27,9 %,
  SNDK −39,2 %). **Kein Urteil:** alle 30 Zeilen stammen aus EINEM Tag (10.07.) mit stark
  korrelierten Titeln (drei Halbleiter) — eine Kohorte, keine 30 Beobachtungen. Passt zur
  in-sample-AUC 0,496. Auswertung: `docs/research/2026-08-11-first-resolved-entry-predictions.md`.
- **Vor dem Auflösen geprüft, ob ein Automatismus darauf handelt:** nein. Die Zahl der
  Auflösungen ist ein Retrain-**Trigger** in `run_evidence_refresh.py`, keine Trainingsdaten;
  die Promotionshürde hängt an der OOS-AUC, und das einseitige Gate verhindert weiter einen
  anti-prädiktiven Erst-Champion. Der Trigger feuert beim nächsten Kettenlauf — beabsichtigt.
- **`insights` gemessen — der alte Befund war in beiden Zahlen falsch** (`--limit 12` +
  „2 LLM calls"): `--limit` begrenzt **nur den Watchlist-Kopf**, jeder Screener-Pick wird
  **unbegrenzt** angehängt (heute 18) → **30 Titel**, und jeder kostet **bis zu drei**
  LLM-Aufrufe (Business, News, Schlagzeilen-Übersetzung). Real **~90 s pro Titel** ⇒ ~45 min
  für einen vollen Lauf. Die Zahl stand die ganze Zeit im Log („Erzeuge Steckbrief-Texte für
  30 Titel"); der alte Befund glaubte dem Kommentar statt dem Log.
- **Der Präfix-Cache-Trick ist hier schon ausgeschöpft** — nichts zu bauen: `ask_ollama` legt
  den Kontext in die System-Rolle **vor** die Frage, und Aufruf 2 und 3 teilen denselben
  `news_context` → der dritte ist bereits ein Cache-Treffer.
- **Zwei Fixes, beide klein:** (1) `insights` läuft **als letzter** Kettenschritt mit eigenem
  Cap (`EQUITY_SCOUT_INSIGHTS_TIMEOUT`, 35 min) statt als zweiter mit 12 min — nichts in der
  Kette liest seine Ausgabe, nur `/api/briefs`, also kostet ein Cap dort keine Lieferung mehr;
  vorher warteten zehn Schritte täglich 12 Minuten auf einen Anzeige-Cache. (2) Verarbeitung
  **älteste zuerst** (`order_by_staleness`), stabil sortiert, damit innerhalb einer
  Erneuerungs-Generation der Rang Tiebreaker bleibt.
- **Der Schaden, den (2) behebt, in Zahlen:** die Reihenfolge war der Rang, also gewannen
  täglich dieselben 8 Titel. Am echten Datenstand verifiziert — vorher hätten die ersten vier
  Titel ihren Text **zum zweiten Mal am selben Tag** bekommen, während 8 Titel seit dem 09.08.
  warteten; jetzt kommen genau die 8 zuerst. Kein Titel war je ohne Text (`save_insight`
  upsert), der Schaden war **veraltete Nachrichten auf 11 von 30 Karten**.
- Gate: **1990 Tests grün** (7 neue), ruff clean.
- [ ] Beobachten: ob die Kette morgen ohne `TIMEOUT insights` durchläuft und wie viele der 30
      Titel in 35 Minuten erneuert werden (erwartet ~23). Montags ist es knapper, weil `scout`
      und `person_scores` vorher laufen — die Stunde des Windows-Tasks ist die harte Grenze.
- [ ] Offen, bewusst nicht mitgefixt: die Screener-Pick-Zahl ist **unbegrenzt**, die Laufzeit
      des Schritts also grundsätzlich unvorhersehbar (heute 18 Picks, morgen können es 40 sein).
      Ein eigenes Limit dafür wäre der nächste Schritt, kappt aber Karten, die Nico am 07.08.
      ausdrücklich mit Texten wollte — Entscheidung gehört ihm.
- [x] Geprüft, keine Lücke: **die Karte zeigt das Datum schon** — `InsightBlock.tsx` rendert
      „KI-Zusammenfassung (qwen2.5:7b) vom 09.08. — keine Empfehlung." Ein zwei Tage alter Text ist
      also als solcher erkennbar. Kein Code nötig.

## Phase: Achse 2 — Zielgröße/Horizont/Universum (2026-08-11) — Befund statt Bau
Nicos Go: „Deine Empfehlung, mach einfach" → Achse 2. Beim Lesen des Universums fiel ein Defekt
auf, der den Hebel erübrigt. Volle Auswertung:
`docs/research/2026-08-11-champion-was-a-measurement-artifact.md`.

- **Der live scorende `entry`-Champion hat keinen nachweisbaren Vorteil.** Behauptet AUC 0,6195 aus
  **220** OOS-Zeilen; auf dem heutigen Sample mit **3281** Zeilen: **0,5152**, Rank-IC **0,0035**
  statt 0,1523. Die Neubewertung **bevorteilt** ihn (teils in-sample) — er verliert trotzdem gegen
  v124 (0,5348), den er blockierte.
- **Ursache: AUCs aus verschiedenen Samples wurden auf drei Dezimalen verglichen.** Das
  Trainingsuniversum ist die AKTUELLE Watchlist, also wechselt die Stichprobe fast jede Nacht —
  `n_train` schwankt zwischen 80 und 4806, von gestern auf heute von 4779 auf 3026. Dazu ist das
  Universum endogen (Screen auf heutige Daten, Training ab 2007) und klein (19 von 30 Titeln
  überleben den Historien-Filter).
- **v1 ist ein Ausreißer:** Median über 29 Modelle 0,5162, genau eines erreicht ≥ 0,6195 — es
  selbst. Sein 95-%-KI [0,546; 0,693] **überlappt** mit v126s [0,520; 0,566]; es war nie belegt,
  dass er besser ist. Der Selektionseffekt (Bester aus mehreren Presets im ersten Lauf) wird von
  `_min_auc_delta`s √N-Korrektur nur bei Herausforderern erfasst, nie rückwirkend beim Erst-Champion.
- **Der zweite, wichtigere Befund:** Der Fix allein promoviert NICHTS. `NO_EDGE_BAND` verlangt
  AUC ≥ 0,55, die ehrlichen Werte liegen bei 0,50–0,54. **Kein Modell dieser Familie hat auf einer
  belastbaren Stichprobe je die eigene Mindestschwelle erreicht** — und der Amtsinhaber erfüllt sie
  heute selbst nicht. Damit ist Achse 2 negativ beantwortet, ohne eine neue Zielvariable: das
  Problem ist nicht die Definition der Zielgröße.
- **Gebaut:** `evaluate_fitted_model` (Amtsinhaber auf den Folds des Herausforderers, wohlwollend,
  `KeyError` bei fremdem Feature-Block statt stiller NaN-Spalte) + `promote_if_better(...,
  incumbent_metric=...)` + nächtliche Meldung, live gegen eine DB-Kopie verifiziert. Ohne den
  Parameter bleibt das alte Verhalten; ein nicht bewertbarer Amtsinhaber fällt bewusst auf den
  gespeicherten Wert zurück (Vergleich gegen nichts würde auf keiner Evidenz promovieren).
- Gate: **2000 Tests grün** (10 neue), ruff clean.
- [x] **Automatische Entthronung — im Head-Modus entschieden und gebaut** (2026-08-11 nachts, Nicos
      „Du bist Head"). Begründung: das Prinzip steht wörtlich im Modul-Docstring („eine leere Arena
      hat keinen Champion statt einen falschen"), es galt aber nur für die Promotion — ein einmal
      gewonnener Titel wurde nie wieder geprüft. `demote_if_no_edge` schließt die Lücke
      **symmetrisch**: `_no_edge` ist dieselbe Schranke, die einen Neuling blockiert; wer heute als
      Herausforderer abgelehnt würde, hat heute keinen Anspruch auf den Titel. Läuft VOR den
      Promotionsversuchen, damit die Arena ehrlich leer ist, während die Herausforderer dieser
      Nacht beurteilt werden. Ein nicht messbarer Amtsinhaber (None/NaN/inf) wird NIE entthront —
      eine kaputte Messung darf die Arena nicht leeren. **Live-Folge, ab dem Nightly heute Nacht:
      der ML-Long-Bot handelt nicht mehr** („kein Edge, kein Trade" — die Oberfläche sagt das schon
      korrekt, wie beim Short-Bot seit Wochen); das Depot läuft dann mit 7 statt 8 Sleeves, die
      Gewichtung ist dynamisch. Paper-Geld, vollständig reversibel. Am echten Fall gegen eine
      DB-Kopie verifiziert: v1 fällt (0,5140), der beste Herausforderer (0,5069) wird NICHT
      Nachfolger — die Arena bleibt leer, was der korrekte Zustand ist.
- [x] **Nachverifiziert vor dem ersten echten Lauf: das Depot verkraftet den fehlenden Sleeve.**
      Trockenlauf des Autotraders gegen die entthronte DB-Kopie: **7 Sleeves statt 8, Gewichte
      korrekt auf 14,3 % (1/7) normalisiert**, kein Absturz an `sleeve_weights`, Brutto 84 %.
      Das war eine echte Lücke — ich hatte die Entthronung gebaut, ohne zu prüfen, ob der
      Verbraucher ihres Ergebnisses damit umgehen kann.
- [ ] **Erwartete Nebenwirkung, beobachten:** mit 7 statt 8 Sleeves steigt die Konzentration in
      den Kern-ETFs, also greift der Einzeltitel-Cap breiter — im Trockenlauf bei **vier** Titeln
      (BIL, IEF, SPY, VEU) statt zwei, mit **32,2 %** Umverteilung statt 23,7 %. Das ist die
      Welle-2-Mechanik bei der Arbeit, kein Defekt, aber der erste Lauf nach der Entthronung
      schichtet einmalig groß um (im Trockenlauf 11 Trades, Deltas bis 8,8 %, ~40 USD Kosten).
- [x] Universum als Wurzel-Hebel — **ausgeführt, siehe eigene Phase unten.**

## Phase: Festes Trainingsuniversum → Achse 2 endgültig negativ (2026-08-11) — DONE
Head-Modus (Nicos „arbeite in einer loop immer weiter … Du bist Head"). Der Vorbefund empfahl, beim
Universum anzufangen. Das ist passiert, und es beantwortet die Frage abschließend.
Doku: `docs/research/2026-08-11-fixed-universe-and-the-final-null-result.md`.

- **Das Trainingsuniversum ist jetzt fest und ex ante** (`ml/entry_universe.py`): 503 US-Titel aus
  dem datierten Index-Snapshot `2026-07-02` statt der täglich wechselnden Watchlist. Snapshot-Datum
  und Region sind **angenagelte Konstanten** — ein „neuester Snapshot"-Zugriff würde genau die
  Drift zurückholen, die hier verschwindet. Liste alphabetisch sortiert und dedupliziert, damit sie
  zwischen zwei Nächten byte-identisch ist (per Test gepinnt).
- **Stichprobe: 3.931 → 68.085 Trainingszeilen, 2.431 → 54.735 OOS-Zeilen** (445 Titel nach dem
  Historien-Filter, 94 s Panel-Download für 504 Ticker).
- **DAS ERGEBNIS: der Vorteil verschwindet mit der Stichprobe, statt sich zu bestätigen.**
  AUC **0,5069** (random_forest) und **0,5041** (elastic_net) — NIEDRIGER als die 0,5348, die
  dasselbe Verfahren auf dem 22× kleineren Watchlist-Sample zeigte. Amtsinhaber v1 hier: 0,5140.
- **Der Rank-IC fällt von 0,05–0,07 auf 0,0142.** Damit ist auch die letzte Hoffnung des
  Vorbefunds widerlegt — es gab keine „schwache monotone Beziehung, wo die binäre Trennkraft
  fehlt", das war dieselbe Kleinstichproben-Illusion. **Diese frühere Notiz ist damit korrigiert.**
- **Voller Durchlauf, alle drei Familien × vier Presets: Spanne 0,4755–0,5069. NULL von elf
  erreichen die Schwelle 0,55, acht von elf haben einen NEGATIVEN Rank-IC.** Die kürzeren bzw.
  barrierenbasierten Zielgrößen (`entry_short` 10 Tage, `entry_tb` vol-skalierte Barrieren)
  schneiden **schlechter** ab als die 20-Tage-Relativrendite — auch das war auf den kleinen
  Samples nicht sichtbar.
- Laufzeit gemessen und in `nightly_train.sh` dokumentiert: ~94 s Download + ~65 s je Preset × 12
  = **~15 min** gegen den 25-min-Step-Cap (vorher ~60 s). Nicht mehr vernachlässigbar — die Zeile
  steht dort, wo die nächste Person sie braucht, bevor sie Presets ergänzt.
- Bei n = 54.735 ist der Standardfehler der AUC ~0,002: die 0,5069 sind **statistisch von 0,5
  unterscheidbar und wirtschaftlich bedeutungslos** — weit unter der eigenen Schwelle 0,55.
- **Jede Registry-Zeile stempelt jetzt `metrics["universe"]`** (`n_tickers`, `n_scored`). Das
  Fehlen dieser Information ist der Grund, warum der Champion-Defekt fünf Wochen unsichtbar blieb.
- **Achse 2 ist damit vollständig und negativ:** Features (3 Nullbefunde), Zielgröße/Horizont
  (3 Familien im Münzwurfbereich), Universum (22× mehr Daten → kleinerer Vorteil). Ehrliche
  Aussage: **an freien Tagesschlusskursen und preisabgeleiteten Features ist die
  Querschnitts-Relativrendite über 20 Handelstage mit diesem Setup nicht vorhersagbar.** Passt zum
  W0-Befund des Vortags (Rendite an diesen Daten nicht entscheidbar, Risiko schon).
- Grenzen ehrlich: Survivorship-Bias bleibt (Snapshot hält die Mitglieder SEINES Datums; delistete
  Titel liefern bei yfinance keine Historie) — entscheidend ist, dass der Restbias **kein
  Rendite-Screen** ist und nicht mehr nachtweise variiert. Gilt für dieses Zielmaß, nicht für
  längere Horizonte oder Fundamentaldaten.
- [x] Nebeneffekt „Trainings- und Anwendungsdomäne fallen auseinander" — **durch die Entthronung
      gegenstandslos geworden** (siehe unten). Der `MLLongStrategy`-Sleeve wurde in
      `run_autotrader.py` mit `long_universe = watch_tickers` gebaut, also mit der globalen
      Watchlist, während auf 445 US-Large-Caps trainiert wird. Ohne Champion baut sich der Sleeve
      gar nicht (`ready` = False), es wird also nichts auf der fremden Domäne gescort. **Wird
      wieder relevant, sobald je ein Modell die Grundqualität erreicht** — dann muss das
      Live-Universum mit dem Trainingsuniversum zusammengeführt werden (oder die Schnittmenge).
      Hier festgehalten, damit das bei einer künftigen Promotion nicht übersehen wird.

## Phase: Risiko-Schiene — VolTarget nutzt den schwächeren Schätzer (2026-08-12) — STUDIE DONE
Nicos Go („mach mal dein Ding") auf meine Empfehlung, Risiko VOR Fundamentaldaten anzugehen —
Begründung war der W0-Befund: Rendite ist an diesen Daten nicht entscheidbar, Risiko schon, und das
Depot nutzt es noch nicht. Doku: `docs/research/2026-08-12-voltarget-uses-the-weaker-estimator.md`,
reproduzierbar über `scripts/run_vol_forecast_study.py`.

- **`VolTarget` drosselt anhand der TRAILING 20-Tage-Vola, also erst NACHDEM die Vola gestiegen
  ist.** Der VIX sagt dieselben 20 Tage besser voraus: **rho 0,642 gegen 0,539** auf 233 nicht
  überlappenden Fenstern über 19 Jahre.
- **Inkrementell noch klarer:** VIX ohne trailing trägt **0,390**, trailing ohne VIX nur **0,099**.
  Der VIX enthält fast alles, was die trailing Vola weiß, plus deutlich mehr.
- **Out of sample bestätigt:** Divisor der Varianzrisikoprämie auf 2007–2016 gefittet (1,341), auf
  2017–2026 beurteilt → dort **rho 0,678 gegen 0,565**, Kalibrierung 1,07. Der Parameter hält.
- **Die Falle, die die Studie sichtbar macht:** roher VIX rankt am besten (0,642) und wäre trotzdem
  falsch — er liest **36 % zu hoch** (implizite Vola trägt die Varianzrisikoprämie), und
  `VolTarget` skaliert mit `ziel/schätzer`, würde also JEDEN Tag 36 % zu stark drosseln. Deshalb
  werden Rangfolge und Kalibrierung getrennt gemessen.
- **Erster positiver Befund dieser Serie** — Evidenz, Volumen, Zielgröße und Universum waren alle
  Nullbefunde.
- Gate: 2039 Tests grün (6 neue auf synthetischen Regimewechseln), ruff clean.
- [x] **Einbau — bewusst NICHT in derselben Nacht.** Er greift in eine live laufende Risikoschicht
      ein, und heute Nacht wirkt zum ersten Mal die Entthronung (Sleeve fällt weg, einmalige
      Umschichtung ~32 %). Zwei Eingriffe in einer Nacht würden die Ursachenzuordnung zerstören.
      Nächster Schritt nach der Nightly-Verifikation.
- [x] Beim Einbau zwingend: **dimensionsloser Multiplikator** (`VIX-Prognose / SPY-trailing`) auf
      die EIGENE trailing Depot-Vola, nie das SPY-Niveau direkt — das Depot ist Multi-Asset und
      hat niedrigere Vola, ein SPY-Niveau würde die Drosselung dauerhaft verschärfen. Und:
      **fällt der VIX aus, Rückfall auf die trailing Vola, nicht Schutz aus** — eine Datenlücke
      darf nie als „kein Risiko" gelesen werden.
- **Outcome (2026-08-17, Task 1 aus `plans/2026-08-16-autotrader-review-upgrades.md`):** eingebaut
  als `src/equity_scout/vol_forecast.py` + `RiskContext.vol_multiplier`; Konstanten Divisor 1,341,
  Fenster 20 Tage, Clamp 0,5–3,0 (asymmetrisch: implausibel NIEDRIG ⇒ misstrauen und trailing
  nutzen, weil ein Fehldruck den Schutz sonst abschaltet; extrem HOCH ⇒ auf 3,0 kappen, da mehr
  Drosselung die sichere Richtung ist). Jedes `RiskEvent` nennt seinen Schätzer als
  `(VIX-Prognose)` bzw. `(trailing)`. Messwert beim Einbau: VIX 14,25 / SPY-trailing 13,4 % ⇒
  Multiplikator **0,795**, das Depot drosselt aktuell also SCHWÄCHER als vorher — die Prognose
  sieht die kommenden 20 Tage ruhiger als die vergangenen 20. Live ab Nightly Di 18.08. 02:30.

## Phase: Fundamentaldaten-Schiene — Machbarkeit geprüft, Baustein gebaut (2026-08-12)
Zweite Schiene meiner Empfehlung (nach Risiko). Bewusst parallel begonnen, weil sie das Depot NICHT
berührt: es geht um Trainingsdaten, nicht um eine Live-Schicht — also kein Attributionskonflikt mit
der Entthronung, die heute Nacht erstmals wirkt.

- **Warum überhaupt:** alle 11 Modell-Features sind preis-abgeleitet. Fundamentaldaten sind die
  einzige große ungetestete Dimension, und das Projekt berechnet täglich F-Scores, die nie ins
  Modell fließen.
- **Machbarkeit belegt:** EDGAR `companyfacts` liefert pro Eintrag ein **`filed`**-Feld
  (`['accn','end','filed','form','fp','fy','start','val']`) — Point-in-Time ist also möglich.
  Kosten gemessen: **3,8 MB pro Ticker** (bei 445 Titeln ~1,7 GB, einmalig).
- **Zwei stille Fallen, beide an echten AAPL-Daten gefunden:**
  1. **`fy` ist das Fiskaljahr des FILINGS, nicht der Daten.** Das FY2024-Filing trägt Einträge mit
     `end` 2022-09-24, 2023-09-30 UND 2024-09-28 — alle als `fy: 2024`, weil ein 10-K Vorjahre als
     Vergleichszahlen wiederholt. Wer `fy` als Datenjahr liest, labelt Vergleichszahlen als
     aktuelle Werte. `fscore.py` macht das zu Recht (es will nur das jüngste Jahr), für eine
     Zeitreihe wäre es falsch.
  2. **Restatements teilen ein `end`.** Dieselbe Periode erscheint mehrfach mit verschiedenen
     Werten; die ehrliche Antwort an einem Stichtag ist das **damals jüngste** Filing, nie das
     heute jüngste.
- **Gebaut: `pit_fundamentals.py`** — `visible_annual_series(payload, tags, as_of=...)` gibt
  `{Periodenende: Wert}` für alles, was **bis** `as_of` eingereicht war; keyed auf `end`, `filed`
  nur als Sichtbarkeitsgate. Reine Logik, Netzwerk bleibt beim Aufrufer — weil ein
  Look-Ahead-Fehler nicht abstürzt, sondern still einen guten Backtest erzeugt.
- **Gegen echte Daten verifiziert:** am 2024-10-01 ist die jüngste sichtbare Periode FY2023, am
  2024-11-01 (Einreichungstag) springt sie auf FY2024. Genau das gewünschte Verhalten.
- **Eigener Fehler dabei gefunden und korrigiert:** meine Diagnosefunktion `filing_lag_days`
  suggerierte einen Median-Verzug von 396 Tagen — der ist von den Vergleichszahlen dominiert
  (bis 769 Tage). Aussagekräftig ist das **Minimum: 30–34 Tage**. Docstring korrigiert, Test
  ergänzt, der genau diese Verwechslung pinnt.
- Gate: 2050 Tests grün (11 neue), ruff clean.
- **Zielgröße vorab registriert (2026-08-17, Task 7 aus `plans/2026-08-16-autotrader-review-upgrades.md`):**
  `entry_eval.FUND_HORIZON_DAYS = 126` (~6 Monate), Familie `entry_fund`. Begründung: die
  10/20/60-Tage-Familien sind bei Münzwurf-AUC ausgereizt (Achse 2, 2026-08-11), und
  Fundamentaldaten wirken über Quartale. Gegen dieselben kurzen Horizonte zu testen hieße, einen
  erledigten Nullbefund nochmal zu produzieren. Festgelegt VOR dem Kollektor, damit die Zielgröße
  nicht nachträglich zum Ergebnis passend gewählt werden kann.
- [ ] Nächster Schritt: Backfill-Kollektor über das feste Trainingsuniversum (445 Titel), der pro
      monatlichem Stichtag die dann sichtbaren zwei Fiskaljahre zieht. Kosten und Fallen sind jetzt
      bekannt; EDGAR-Etikette (ein Abruf pro Sekunde) macht daraus ~8 Minuten Laufzeit. Label:
      `FUND_HORIZON_DAYS = 126` pro monatlichem Stichtag.
- [ ] Erst danach: die F-Score-Kriterien als Feature-Block additiv ins Entry-Modell, mit demselben
      Nachweis wie bei Evidenz und Volumen — `volume_index=None`-Muster, damit der Vergleich die
      FEATURES misst und nicht ein geändertes Sample, ausgewertet auf dem 126-Tage-Ziel.

## Needs Nico (loop cannot do these itself)
- **v12 Handy-Cockpit scharf schalten**: `DASH_TOKEN` in `.env` setzen (`openssl rand -hex 16`),
  `./scripts/install_dash_service.sh` erneut ausführen (Unit ist gestaged, aktiviert sich nur mit
  Token), optional `DASH_URL` für den wöchentlichen Digest-Hinweis. Von unterwegs: Tailscale
  (free tier, dein Account) — bewusst nicht automatisiert.
- autopilot/work → main merge/push decision (repo is public on GitHub since 2026-07-04; the v3/v4 work is local-only until you push).
- Any data source that would require a paid key (do NOT sign up — log here instead).
- `EDGAR_USER_AGENT="name (email)"` in `.env` so the 13F collector can run (stays politely
  `unconfigured` until then; never faked).
- ~~Run `./scripts/install_crontab.sh` once~~ — DONE 2026-07-20 (v10.1 session ran the
  idempotent installer under the project's local-autonomy grant; nightly line now points at
  `run_nightly_guarded.sh`, forward-paper line preserved).
- **Optional: register the Windows nightly task** — `./scripts/install_windows_task.sh` now
  installs BOTH tasks (daily 18:00 + nightly 02:40, starts WSL if down). Without it the
  nightly chain still runs via cron/systemd whenever WSL is up, and the persistent systemd
  timer catches up missed slots at the next WSL start; the Windows task is the only layer
  that can WAKE the box. — REGISTRIERT, und seit 2026-08-10 mit `WakeToRun` (vorher konnten
  daily/nightly die Maschine nicht wecken). Grenze bleibt: Windows erlaubt Wake-Timer nur am
  Netzstrom, am Akku sind sie per Policy aus — im Akkubetrieb über Nacht fällt der Slot aus.
- ~~Windows-Energieeinstellungen prüfen (Rechner schlief über US-Börsenschluss)~~ — 2026-08-10
  untersucht und die eine findbare Ursache gefixt (`WakeToRun`, siehe oben). Standby am
  Netzstrom steht bereits auf „nie", Wake-Timer am Netzstrom sind aktiv. Falls es WIEDER
  passiert: `powercfg /waketimers` als Admin laufen lassen (braucht erhöhte Rechte, deshalb
  hier nicht gemessen) und im Ereignisprotokoll nach Kernel-Power-Ereignissen sehen.
- Voices-Personenliste bestätigen/erweitern (`evidence/voices.py::PERSONS`, aktuell die 8
  Fonds-Manager hinter den 13F-Fonds) — Veto-Option, Session 2026-07-14.
- Visueller Abnahme-Pass des IA-Overhauls im Browser (kein Screenshot-Tooling in der Build-Umgebung).
