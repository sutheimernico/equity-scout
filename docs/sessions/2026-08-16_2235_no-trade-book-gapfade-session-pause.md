# Session 2026-08-16 22:35 — Nicht-Trade-Buch, Gap-Fade-Lane, Session-Lane pausiert

## Kontext & Ziel

Direkte Fortsetzung der 21:22-Session. Nico gab Blanko-Go („Ich vertraue dir, bau das wie
du meinst, mach in einer Loop bis zum Ende alles; Entscheidungen im Sinne der Vision") für
die vier Lücken, die der Abgleich seiner Autotrader-Vision ergeben hatte: (1) das Review
der NICHT getradeten Gelegenheiten, (2) die Ereignis-Knappheit (15 statt 60), (3) die
finale Entscheidung über die widerlegte Session-Lane, (4) Gap-Fade als Messlane.

Plan mit allen Details und Outcome:
`docs/superpowers/plans/2026-08-16-no-trade-book-and-learning-loop.md`.
12 Tasks, 11 Commits auf `autopilot/work`, Gate durchgehend grün (2.145 py-Tests + ruff +
127 Frontend-Tests), gepusht.

## Ergebnis

**Nicht-Trade-Buch (`st_rejections` in shortterm.db).** Jede geprüfte, abgelehnte
Gelegenheit wird persistiert — swing: `not_bullish`/`too_old`/`cap_full`/`already_held`/
`no_quote` (Erfassung im Runner, `pick_entries_explained` bleibt pure); gapfade:
`below_threshold`/`stale_premarket`. Nachts löst `rejection_review` sie mit den LIVE
laufenden Exit-Regeln auf (swing) bzw. mit Open→Close des Ablehnungstags (gapfade), und
`lane_review` stellt sie den gehandelten Trades gegenüber. Überall steht BRUTTO dabei:
die Zahl beantwortet „war die Ablehnung richtig?", nie „hätten wir verdient?".

**Session-Lane pausiert (wirksam ab Mo 17.08.).** Der neue, persistierte Backtest
`scripts/research_orb_overnight.py` (Lektion aus T8: nie wieder Ad-hoc-Skripte) prüfte
Nicos „tagesübergreifend halten"-Idee auf der ORB-Einstiegsregel: 2.550 Signale, 89 Titel,
drei Arme — Zwangsflat −5,45 bp (t = −2,20), Overnight +3,63 bp über Benchmark (t = 0,62),
Swing-Exits 20 bp UNTER dem bedingungslosen 10:15-Einstieg (gepaart t = −11,4). Kein Arm
rettet die Regel; nicht das Halten war falsch, der Einstieg. Cron-Zeile entfernt,
`st_session_sweep` bleibt als Netz, Buch bleibt im Cockpit lesbar (lanes.ts erklärt es).
Befund: `docs/research/2026-08-17-orb-overnight-backtest.md`.

**Gap-Fade-Lane LIVE als Messinstrument.** `st_gapfade.py` (pure), OPG/CLS-Orders im
Alpaca-Wrapper (`auction_payload`/`place_auction_order`), Runner mit drei Phasen (Signale
9:00–9:28 ET einmal täglich fail-closed, Fills+MOC ab 9:31, Settle im Nightly), Cron
`*/5 14-16 * * 1-5` mit internem ET-Gate (trägt beide DST-Regime). Kernmessung: Signal- vs.
Auktions-Fill in `st_executions`; Schwellen-Kalibrierung über below_threshold-Zeilen im
Nicht-Trade-Buch. Abbruchkriterium: 60 Trades → Trade-Test, „negativ" beendet die Lane.
Ehrlichkeitszeile (Paper misst Verrutschen, nicht Auktionsimpact) steht im Frontend.

**Ereignis-Knappheit an zwei Wurzeln gefixt.** (1) News-Klassifikation läuft jetzt über
`tracked_tickers()` statt des rotierenden 30er-Watchlist-Snapshots — Symmetrie mit 8-K;
Nebenwirkung dokumentiert: auch Form 4 folgt jetzt der breiteren Menge. (2) Der echte
guidance_up-Killer war NICHT die Regex (die existierte), sondern die Dual-Match-Regel:
„beats estimates and raises guidance" fiel als Doppeltreffer auf `unknown`. Jetzt bleibt
nur GEGENSÄTZLICHE Richtung unknown; Guidance-Fenster 20→30 Zeichen. Vorher: 0 guidance_up
in 603 Headlines.

## Entscheidungen (in Nicos Namen, per Blanko-Go)

1. **Session-Lane pausieren** — nach Iron Rule 2, Backtest in allen drei Armen negativ.
   Reaktivierung = eine Cron-Zeile.
2. **Gap-Fade bauen als Messlane** — der einzige Kandidat mit positivem T7-Backtest;
   Paper kann messen, was der Backtest nicht kann. Mit hartem Abbruchkriterium.
3. **Kein News-Backfill** — frei nicht verfügbar, Proxys wären unehrlich.
4. **Krypto-Lane unangetastet** (Nicos stehende Entscheidung vom 16.08.).

## Offene Fragen

- Erster Gap-Fade-Lauf Mo ~15:00 lokal: füllt Alpaca Paper OPG-Orders realistisch zur
  Eröffnung? (Erst der echte Lauf zeigt es.)
- Wie schnell füllt sich das Nicht-Trade-Buch? Die swing-Rejections hängen an der
  News-Rate; der tracked_tickers-Scope sollte sie etwa verdreifachen.
- Reicht der neue Event-Zufluss, damit `run_lane_tuning` die 60er-Hürde in Wochen statt
  Monaten erreicht? (Q3-Earnings-Saison ab Oktober hilft zusätzlich.)

## To-dos

### Nico

1. **Rechner freitags 15:30–22:00 laufen lassen** — sonst handelt nichts (zweiter Ausfall).
2. **DASH_TOKEN + Telegram-Bot-Token rotieren** (liegen in alten Chat-Protokollen).
3. **Cockpit auf dem Handy durchklicken** (steht seit 08.08. aus).
4. Im Cockpit gelegentlich die neue Gap-Fade-Karte und die Session-Pausierung ansehen —
   beides erklärt sich dort selbst.

### Nächste Session (Agent)

- **Nach der Nacht Mo→Di 02:30 `train.log` prüfen:** Premiere der vollen Kette
  `st_gapfade_settle` → `rejection_review` → `lane_review` → `lane_tuning` in echt —
  alle vier Steps sind neu bzw. erweitert und noch nie zusammen gelaufen.
- **Mo abends `shortterm.log` prüfen:** erster Gap-Fade-Signallauf (~15:00–15:28 lokal),
  MOO-Fills, `st_executions`-Zeilen (expected vs. actual = die Kernmessung).
- Ereignis-Zufluss nach ein paar Tagen nachzählen (`classified_events` je event_type) —
  wirkt der tracked_tickers-Scope + der Dual-Match-Fix messbar?

## Einstieg für die nächste Session

Branch `autopilot/work`, sauber, gepusht. Der Plan
`docs/superpowers/plans/2026-08-16-no-trade-book-and-learning-loop.md` ist KOMPLETT
(Outcome-Abschnitt am Ende). Erster technischer Schritt ohne Rückfrage: die beiden
Log-Prüfungen oben. Der CronCreate-Wächter dieser Session ist session-only — bei Bedarf
neu armen.
