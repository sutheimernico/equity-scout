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

## Iron principles (never overridden)
- **Local & free only.** yfinance / SEC EDGAR (UA header) / public lists. No paid feeds, no
  real-money anything. A task needing a paid resource goes to "Needs Nico", never faked.
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
- [ ] P7 Backlog: Strategie-Parameter-Suche im Research-Loop (EIGENES Ledger + EIGENE DSR-Hürde,
      Multiple-Testing-Trennung; v5-P4)
- [ ] Backlog: DSR-Hürde zum Trial-Zeitpunkt im Research-Ledger mitspeichern (Ledger nutzt
      positionsbasierte INSERTs -> kleiner Schema-Umbau nötig; ohne das ist die rückwirkende
      "war der Champion damals über der Hürde"-Kurve nicht rekonstruierbar)
- [ ] Backlog: vorzeichenrichtige Ledger-Auflösung für bearish Voice-Calls (bis dahin: Anzeige +
      Alert, aber keine Statistik — dokumentiert in evidence/voices.py)

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
- [ ] Bug: Form-4-Collector wirft bei ~21 Watchlist-Tickern XML-Parse-Fehler ("tag mismatch:
      meta/head" = SEC liefert eine HTML-Seite statt XML — vermutlich Filing-Index-URL oder
      fehlender Accept-Header); log-and-continue hat gehalten, 9/30 Ticker sauber geprüft
      (live 2026-07-14 nach EDGAR-Freischaltung)

## Phase: Vision v7 — Ziel-Exits, Event-Engine, Lern-Loop (2026-07-15)
> Nico-Direktive: Long-Modell mit explizitem Zielwert/Exit, news-getriebenes Kurzfrist-Trading
> (ehrlich: Latenz messen statt Minuten-Trading behaupten), sichtbares tägliches Lernen.
> **Plan: `docs/superpowers/plans/2026-07-15-vision-v7-target-exits-events-learning.md`**
- [x] A1 fix(sizing): Positionsgröße vom aktuellen NAV statt initial_capital (portfolio, lanes)
- [x] A3 feat(ml): Triple-Barrier-Preset für entry-Familie (labeling.py wiederverwenden)
- [ ] B5 fix(evidence): voices-Ticker-Resolution härten + news_themes Titel-Dedupe
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
- [ ] Backlog (B5-Review-Fund, pre-existing): tail-lose Single-Token-Firmennamen in
      voices.resolve_ticker bleiben exponiert — konkrete Instanzen SHEL.L ("Shell"),
      TGT ("Target"), NXT.L ("Next"): generische kapitalisierte Wörter in Headlines lösen
      auf diese Ticker auf. Fix-Idee: Single-Token-Namenskanal ebenfalls gegen
      _GENERIC_FIRST_WORDS gaten und/oder Mehrwort-Firmennamen im Titel bevorzugen.
- [ ] Backlog (B5-Review-Fund): _GENERIC_FIRST_WORDS ist ein manueller Snapshot des Universe
      (2026-07-15) — bei Universe-Refresh können neue eindeutige generische First-Words entstehen.
      Idee: Scan-Skript unter scripts/ oder Drift-Check im Data-Quality-Report.

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
- [ ] A5 feat(receiver): 🔎-Details-Button pro Pitch (`detail:<pitch_id>` callback) — Receiver
      antwortet mit der langen erklärenden Pitch-Version als eigene Nachricht (HTML, Absätze)
- [ ] C1 feat(regime): `regime.py` — 4 Signale (SPY vs. 200d-MA, VIX-Band, Breadth = % Universum
      > 200d-MA aus Cache, Zinskurve ^TNX−^IRX) → Composite-Ampel 0–4 grün; pure Funktionen,
      Fake-Daten-Tests, ehrliche Degradierung wenn ein Signal keine Daten hat
- [ ] B1 feat(strategies): `SectorRotationStrategy` — 11 SPDR-Sektor-ETFs (XLK XLF XLV XLI XLE
      XLU XLB XLP XLY XLRE XLC), Top-3 nach 12M/6M-Momentum-Blend, monatlich, Absolut-Momentum-
      Cash-Fallback (BIL) wie GEM; in `default_strategies()` registrieren; Backtest läuft mit
- [ ] B3 feat(sectors): Sektor-Momentum-Snapshot — Ranking aller 11 Sektor-ETFs (1M/3M/6M/12M)
      als pure Funktion + `/api/sectors` + Dashboard-Karte "Sektoren"
- [ ] A6 feat(digest): Digest-Redesign — HTML-Sektionen mit fetten Überschriften + Absätzen;
      Kopfzeile = Markt-Ampel (C1) + Top-3-Sektoren (B3), beide degradieren ehrlich wenn Daten
      fehlen; bestehende Sektionen (Alerts/Chancen/Earnings/Pitches/Evidenz) bleiben inhaltlich
- [ ] B2 feat(forward): Sektor-Rotation als Forward-Paper-Konto aufnehmen + im Strategien-
      Dashboard sichtbar (build_reports nimmt Registry-Strategien auto auf — verifizieren)
- [ ] C2 feat(api): `/api/regime` + Dashboard-Ampel (Strategien- oder Übersichts-Kopf) — gleiche
      Ampel wie im Digest, ein Klick zeigt die 4 Einzelsignale mit Werten
- [ ] D1 feat(factors): 52-Week-High-Proximity als zweite Momentum-Metrik (Blend mit 6M-Return
      innerhalb der momentum-Familie, global gerankt) + `docs/factors.md` nachziehen
- [ ] D2 feat(quality): Piotroski F-Score via SEC EDGAR XBRL `companyfacts` (UA-Header; ohne
      `EDGAR_USER_AGENT` ehrlich "unconfigured" wie der 13F-Collector) als Quality-Trend-Metrik
      im Quality-Score-Blend; yfinance-Fallback NICHT bauen (bekannt löchrig)

## Needs Nico (loop cannot do these itself)
- autopilot/work → main merge/push decision (repo is public on GitHub since 2026-07-04; the v3/v4 work is local-only until you push).
- Any data source that would require a paid key (do NOT sign up — log here instead).
- `EDGAR_USER_AGENT="name (email)"` in `.env` so the 13F collector can run (stays politely
  `unconfigured` until then; never faked).
- **Run `./scripts/install_crontab.sh` once** (updated 2026-07-14): installs the daily copilot
  chain (18:00 Mon–Fri), receiver keepalive (5-min flock), the NEW 30-min intraday chain and the
  NEW nightly training chain (02:30 Tue–Sat). The autonomous
  session was not allowed to modify the crontab itself; the installer is idempotent and
  preserves the existing forward-paper line.
- Voices-Personenliste bestätigen/erweitern (`evidence/voices.py::PERSONS`, aktuell die 8
  Fonds-Manager hinter den 13F-Fonds) — Veto-Option, Session 2026-07-14.
- Visueller Abnahme-Pass des IA-Overhauls im Browser (kein Screenshot-Tooling in der Build-Umgebung).
