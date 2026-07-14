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

## Outcome

_(wird nach Abschluss gefüllt)_
