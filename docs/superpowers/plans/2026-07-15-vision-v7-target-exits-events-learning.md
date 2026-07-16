# Vision v7 — Ziel-Exits, Event-Engine, Lern-Loop (2026-07-15)

> Nico-Direktive (Session 2026-07-15): Das Projekt zur Vision ausbauen — "möglichst gute Aktien
> finden und damit Geld verdienen". Konkret gewünscht: (1) ein ML-Modell für LONG-Trades mit
> explizitem Zielwert (wo verkauft wird), (2) ein kurzfristiges, news-getriebenes Trading
> ("News kommt → in Minuten reagieren"), (3) sichtbare dynamische Verbesserung Tag für Tag.
> Volle Autonomie erteilt, subagent-driven, Loop bis zur Vision.

## Ehrlichkeits-Rahmen (nicht verhandelbar, aus PROJECT/LOOP)

Paper-only, nur kostenlose Quellen, kein Alpha-Versprechen. **Minuten-Trading ist mit kostenlosen
Daten nicht ehrlich messbar** (RSS-Publikationsverzug + 15-min-Poll + yfinance ~15 min
Kursverzögerung ⇒ Best Case 30–45+ min Ereignis→Signal). Der ehrliche Weg zur News-Vision:
Events so früh wie kostenlos möglich erkennen (EDGAR 8-K, Earnings-Kalender vorab), Reaktion
paper-traden und die **Latenz mitloggen** — dann beweist oder widerlegt das System selbst, ob auf
unserem Zeithorizont etwas zu holen ist. Kein Fake, keine Behauptung.

## Review-Basis (3 Subagent-Reviews, 2026-07-15)

- **ML**: Entry-Modell rein preisbasiert, binäres Label (schlägt SPY in 20d/10d), kein Kursziel;
  Triple-Barrier-Labeling existiert fertig in `ml/labeling.py`, ist aber nur ans (nie handelnde)
  ETF-Meta-Modell angebunden. Kein geschlossener Lernkreislauf (Ledger-Outcomes fließen nicht
  zurück). Risiken: Survivorship-Bias im Backfill (heutige Watchlist ab 2007),
  8 Kandidaten/Nacht gegen fixes `MIN_AUC_DELTA=0.01` ohne Multiple-Testing-Schutz.
- **Trading**: ML-Bots haben **keine Exits** (nur Top-K-Rausfallen), `ExitRules` existieren nur in
  der Arena-Lane (`lanes.py`). Sizing-Bug: 5 % vom **Start**kapital statt NAV
  (`portfolio.py:101`, `lanes.py:139`). Score wird equal-weight statt konfidenzgewichtet genutzt
  (`ml_bot.py:118/162`). Einzelaktien-P&L ohne Dividenden. ATR berechnet (`entry.py`), ungenutzt.
- **News/Intraday**: 7 Evidence-Quellen, aber kein Earnings-Kalender, kein 8-K-Feed, kein
  Beat/Miss-Klassifikator. voices-Ticker-Resolution kollisionsanfällig, `news_themes` zählt
  Quellen ohne Artikel-Dedupe.

## Strang A — Trade-Lifecycle: Long-Bot mit Kursziel

- **A1 fix(sizing)**: Positionsgröße vom aktuellen Eigenkapital (NAV) statt `initial_capital`
  (`portfolio.py:101`, `lanes.py:139`) + Regressionstests.
- **A2 feat(exits)**: Echter Trade-Lifecycle für die Forward-Bots: Entry-Preise pro Position
  tracken, `ExitRules` (Profit-Target / Stop-Loss / Max-Haltedauer) vor jedem Rebalance anwenden,
  Exit-Grund persistieren; kein Sofort-Wiedereinstieg am selben Tag nach Exit.
- **A3 feat(ml)**: Triple-Barrier-Preset für die `entry`-Familie: `ml/labeling.py`
  wiederverwenden; Label = Profit-Barrier vor Stop-Barrier innerhalb Horizont;
  vol-/ATR-skalierte Barriers; nightly_train nimmt das Preset auf; Champion-Gating unverändert.
- **A4 feat(ml)**: Kursziel + Stop pro Pick als Modell-Output: aus der Barrier-Konfig des
  Champions abgeleitet (Ziel = Kurs × (1+pt), Stop = Kurs × (1−sl)); über API abrufbar.
- **A5 feat(bots)**: Konfidenzgewichtetes Sizing (score-proportional, normalisiert, Cap pro
  Position) statt equal-weight.
- **A6 feat(pitch)**: 🎯 Kursziel + 🛑 Stop in Telegram-Pitch, Inbox und Frontend-PickCard.

## Strang B — Event-Engine (ehrliches News-Trading)

- **B1 feat(events)**: Earnings-Kalender via yfinance (`earnings_dates`) für Watchlist- +
  Depot-Ticker; Persistenz; Digest-Sektion "📅 Earnings diese Woche"; Intraday-Kette kennt
  Earnings-Tage.
- **B2 feat(events)**: EDGAR 8-K-Collector (kostenloser Atom-Feed, near-realtime; Items
  2.02 Results / 7.01 / 8.01) als Evidence-Quelle über die bestehende EDGAR-Infrastruktur,
  begrenzt auf Watchlist-/Depot-Ticker.
- **B3 feat(events)**: Deterministischer Beat/Miss/Guidance-Klassifikator (Keyword-basiert,
  getestet) über News-Headlines + 8-K-Titel → `events`-Tabelle mit `published_at` und `seen_at`
  (⇒ ehrliche Latenzmessung).
- **B4 feat(events)**: Event-Reaktions-Lane (paper-only): klassifiziertes Event → Papier-Reaktion
  (beat→long, miss→avoid/short) mit geloggter Latenz; Auswertung Rendite nach 1h/1d/5d ab
  `seen_at` — misst ehrlich, ob auf unserer Latenz etwas zu holen ist.
- **B5 fix(evidence)**: voices-Ticker-Resolution härten (Kontext-Check statt bloßer
  Stopword-Liste) + Titel-Hash-Dedupe in `news_themes` vor der `min_sources`-Zählung.

## Strang C — Lern-Loop + Ehrlichkeit

- **C1 feat(learning)**: Tägliche Lernkurve als Zeitreihe: `n_train`, `n_resolved`, rollierende
  Trefferquote, Rank-IC pro Tag persistiert; `/api/model/history` erweitert; Frontend-Kurve —
  sichtbares tägliches Lernen statt seltener Champion-Events.
- **C2 feat(ml)**: Promotion-Gate gegen Multiple-Testing härten (8 Kandidaten/Nacht):
  einfachste solide Korrektur (Delta-Anhebung pro Kandidatenzahl oder Bootstrap-Signifikanz).
- **C3 fix(pnl)**: Dividenden für Einzelaktien-Lanes/Portfolio (TTM-Dividendenrendite anteilig
  pro Haltetag) — schließt die größte P&L-Realismus-Lücke bei Value/Quality-Titeln.
- **C4 docs+fix**: Rebalance-Kadenz-Mismatch Backtest (monatlich) vs. Forward (täglich) beheben
  oder ehrlich dokumentieren; Survivorship-Bias des Backfills sichtbar im Modell-Report
  kennzeichnen.

## Wellenplan (Datei-disjunkt, je 2–3 parallele Subagents)

1. A1 + A3 + B5
2. A2 + B1 + C3
3. A4/A5 + B2 + C1
4. A6 + B3 + C2
5. B4 + C4 + Outcome-Doku

## Gate

`uv run pytest -q` grün + `uv run ruff check .` sauber nach jeder Welle; Frontend-Änderungen
zusätzlich `npm run typecheck`/`build`. Commits: Conventional Commits, ein Task = ein Commit,
zentral nach Gate (Agents committen nicht selbst).

## Outcome (2026-07-16, subagent-driven)

**Alle 12 Tasks umgesetzt** in 4 Wellen (W2 A2·C3·B1 · W3 A4·A5·B2·C1 · W4 A6·B3·C2 · W5 B4·C4),
jeder Task Implementer→Spec/Quality-Review→zentraler Commit, Gate (pytest+ruff, FE zusätzlich
typecheck+build) nach jeder Welle grün. Commits `593f263..66d757d` auf `autopilot/work`, nicht
gepusht. Zwei echte Bugs im Review gefunden und gefixt (s.u.).

### Abweichungen von der Plan-Prosa (Kontext-Kartierung deckte veraltete Annahmen auf)
- **C3:** `advance()` hatte kein „letzter Lauf"-Konzept → `days_elapsed`-Skalar vom Caller; `load_valuations`
  liefert die ÄLTESTEN N → neue `latest_valuation_at`. Dividende via Cash-Gutschrift, kein Position-Schema-Change.
- **B1:** yfinance `.calendar` (nur kommende Termine) statt `.earnings_dates`; „Intraday kennt Earnings" bewusst
  nur log-only (Klassifikation/Reaktion gehört zu B3/B4).
- **A4:** Barrier-Konfig ist vol-skaliert (`k_pt`/`k_sl`/`vol_window`), nicht flache pt/sl; nutzt `trailing_daily_vol`
  wieder (kein Drift zum Label). Andockpunkt `/api/entry`, nicht LLM.
- **B2:** SEC `submissions`-API (trägt schon `items`+`acceptanceDateTime`) statt Atom-Feed; 8-K haben KEINE
  Freitext-Titel → nur Item-Code-Kategorie.
- **B3:** Richtungsklassifikation aus News-Headlines (8-K nur Kategorie). **Review-Bug gefixt:** `street`/`consensus`
  + „will not/unlikely to" lösten fälschlich `beat` aus → auf `unknown` korrigiert (konservativ).
- **C2:** real 12 Kandidaten/Nacht (nicht 8); Multiple-Testing pro Familie (4 Presets) → `MIN_AUC_DELTA*sqrt(n)`.
  Bootstrap verworfen (rohe OOS-Vorhersagen werden nicht persistiert).
- **B4:** Als ehrliche **Event-Study-Auswertung** gebaut, NICHT als handelnde Lane (Lanes sind long-only). 1h
  ehrlich als „mit kostenlosen Daten nicht messbar" markiert (keine Intraday-Bars). **Review-Bug gefixt:**
  Look-ahead im Anker (intraday-`seen_at` nahm den noch-nicht-feststehenden selben-Tag-Close) → marktschluss-bewusster
  Anker (16:00 ET, DST via zoneinfo).
- **C4:** Kadenz-Mismatch dokumentiert (nicht behoben — Verhaltensänderung wäre riskant/out-of-scope).
- **Integrations-Fix (finaler Review):** C4-Caveats erschienen nicht in der Lernkurven-Ansicht → `/api/model/history`
  + `LearningCurvePanel` zeigen jetzt dieselben `MODEL_CAVEATS`.

### Offene Punkte / Needs Nico
- **merge/push:** `autopilot/work` → `main` ist noch offen (öffentliches Repo, alles lokal). Nicos Entscheidung.
- **Vorbestehender Test-Flake (nicht v7):** `test_entry_model::test_calibrated_model_scores_through_the_calibrator`
  ist nicht-deterministisch (~1/5 isoliert rot, ungeseedete numpy-Arrays) — verstößt gegen die LOOP-Determinismus-Regel.
  Bewusst NICHT im v7-Scope gefixt; Fix-Vorschlag: Test/Fixture seeden.
- **A6 Rate-Limit-Beobachtung:** Sobald ein `entry_tb`-Champion existiert, löst die `--inbox-only`-15-min-Kette
  pro Pick einen 1y-Preis-Fetch aus (fürs Kursziel im Inbox-Text) — potenzielle yfinance-Last, die das Projekt
  sonst meidet. Ggf. target_stop im Intraday-Pfad cachen/überspringen.
- **Kleinere Backlog-Funde:** B1 single-date-Robustheit; B2 8-K/A-Ausschluss + roher-8-K-Ledger-hit_rate (bis B3
  gerichtet); `forward_storage.load_exits` bisher ohne Leser (Audit-Trail nur per DB); B3 Mehrwort-Hedge-Lücke.
- **Datenvoraussetzungen für den echten Effekt:** target_stop/Kursziel, Lernkurve und Event-Reaktions-Auswertung
  brauchen einen trainierten `entry_tb`-Champion bzw. aufgelaufene klassifizierte Events — sichtbar werden sie erst
  nach den nächtlichen Läufen.
