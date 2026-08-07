# Plan: Phone-Cockpit-Umbau auf Mockup v2

**Go:** Nico, 2026-08-07 im Chat — "freie Macht", ohne weitere Rückfragen bauen. Er fand
Mockup v2 "fein". Dieser Plan macht eine frische Session ohne Chat-Kontext arbeitsfähig.

**Backup (vor Arbeitsbeginn verifizieren):** `git tag pre-cockpit-rebuild-2026-08-07` +
`~/backups/equity-scout-pre-cockpit-rebuild-2026-08-07.bundle` (alle Branches/Tags).
Fehlt es, zuerst neu ziehen.

**Referenz:** `docs/design/2026-08-07-phone-cockpit-mockup-v2.html` — klickbares Mockup
(im Browser öffnen; Regie-Notizen rechts erklären jede Entscheidung). Das Mockup ist die
Design-Wahrheit für Struktur, Wording und Informationstiefe. Demo-Daten dort sind erfunden;
die echten Werte kommen aus den unten genannten Endpoints.

## Ziel-Persona
"Alex, 31": ETF-Sparplan, kauft selten Aktien, kennt KGV grob — Sharpe/ATR/AUC nie im
Sichtfeld. Täglicher 3-Minuten-Blick: Lage? Was Interessantes? Muss ich entscheiden?
Läuft der Autopilot?

## Neue IA (13 Views → 5 Tabs + Mehr)
Bottom-Bar: **Heute · Aktien · Entscheiden · Depot · Mehr**

| Neu | Ersetzt/Enthält |
|---|---|
| Heute | TodayView + Autopilot-Status-Dreizeiler (Lang/Kurz/Du) + "Zu entscheiden"-Teaser + "Was passiert ist" (Evidenz in Alltagssprache) |
| Aktien | FunnelView + RadarPanel + Heute-StockList → EINE Liste; Segmente "Kaufbereit (in Zone) / Fast / Alle"; Stil-Chips Defensiv/Ausgewogen/Aggressiv |
| Aktienprofil (NEU, eigene View/Route pro Ticker) | vereint PickCard-/BriefRow-/RadarEntry-Drilldowns + "Wer kauft" (Evidence) + News + Kursziele; erreichbar aus JEDER Liste; Kaufen/Beobachten-Aktionen |
| Entscheiden | InboxPanel (Kern unverändert), Pitches verlinken ins Profil |
| Depot | DepotsView: 7 Desktop-Tabs → 3 Sichten Langfrist/Kurzfrist/Du, je mit "Funktioniert es?"-Kopf (Messtag N/60) |
| Mehr → Ergebnisse | ProofView (aus der Bottom-Bar raus — Nicos expliziter Wunsch) |
| Mehr → Wer kauft? | PeoplePanel + VoicesPanel fusioniert |
| Mehr → Labor | StrategyDashboard + ModelPanel + MLSection + LearningCurvePanel (Monitoring-Tiefe BEHALTEN) |
| Mehr → Wie funktioniert das? | NEU: 5 Fragen inkl. Trichter-Grafik 7.500→30 und "Welche Modelle arbeiten im Hintergrund?" |
| Assistent | FAB unten rechts auf jedem Screen (ChatPanel als Overlay), zusätzlich Eintrag im Mehr-Sheet |

## Harte Regeln
1. **Nichts löschen, nur einsortieren.** Jede heutige Information bleibt erreichbar —
   Rausschmiss nur mit sehr guter Begründung im Commit/Outcome.
2. Risikoprofil (Defensiv/Ausgewogen/Aggressiv) als Chip auf JEDER Aktienkarte + Zeile im
   Profil, eigene Farbe (violett, kollidiert nicht mit Ampel), Klartext ("High Risk, High
   Reward" für aggressiv).
3. Score-Übersetzung im Profil: drei Balken **Qualität / Kurs-Timing / KI-Zweitmeinung**
   mit je einem Klartext-Satz; volle Tiefe als "Im Detail"-Disclosures darunter:
   5 Faktor-Perzentile (breakdown), 3 Timing-Signale (dip/gap/momentum aus /api/radar),
   Modell-Erklärung mit Trefferquote (/api/model). Einstiegsplan-Level (SMA200, Fibonacci,
   Böden, ATR, Tranchen) als Disclosure (/api/entry.plan).
4. Kursziele doppelt + ehrlich: Analysten-Ziel (analyst_target/count) UND Scout-Ziel
   (/api/entry.target_stop mit source-Label "trainiertes Modell" vs. "konservative
   Faustformel"); Stop als "Absicherung"; Earnings-Termin (/api/company.next_earnings).
5. Bilanz-Check: F-Score aus /api/company als "N von 9 Punkten" + Kriterien im Disclosure.
6. "Wer kauft gerade" im Profil: Kongress/Insider/13F/Stimmen des Tickers aus /api/evidence
   bzw. /api/stack.evidence_events, mit Meldeverzug; Link auf "Wer kauft?"-Seite.
7. News im Profil: KI-Zusammenfassung (insight) + Original-Quellen verlinkt (Pick.news —
   Rendering existiert seit 9bd5197 in InsightBlock).
8. Deutsch, Alltagssprache; Fachbegriffe nur in Klammern/Disclosures (MethodNote-Muster).
9. Mock-/Demo-Daten gibt es nach dem Umbau NICHT — alles aus echten Endpoints; leere
   Zustände ehrlich benennen (bestehendes Muster).

## Backend-Reste (klein)
- `brief.model_target` (briefs.py, nightly) auf `entry.resolve_target_stop` umstellen +
  Provenance-Feld; StockList-Label anpassen ("Scout-Ziel" statt "Modell-Kursziel", mit
  Faustformel-Hinweis analog EntryPlanBlock 99005af).
- Profil-Datenbedarf prüfen: /api/stack/{ticker} + /api/company/{ticker} + /api/entry/
  {ticker} decken fast alles; fehlende Felder additiv in company_api.py ergänzen (api.py
  nur für include nötig — Modul-Begründung siehe company_api.py-Docstring).
- Bekannter toter Zweig: /api/stack liest `pick_dict.get("factors")`, Feld heißt
  `breakdown` → beim Anfassen fixen (liefert heute immer None).

## Arbeitsweise
- Branch autopilot/work, kleine atomare Commits (Conventional Commits, englisch).
- Koordination: vor Edits an api.py/frontend git status prüfen — falls ein Parallelstrang
  Dateien uncommitted hält, dessen Dateien meiden; Commits immer mit expliziten Pfaden.
- Gates: `uv run ruff check` + `uv run pytest` (Backend), `npx tsc --noEmit` +
  `npx vitest run` + `npm run build` (frontend/). Neue Logik mit Tests.
- Abschluss: dist gebaut, Dash-Service neu starten (Prozess auf :8420, scripts/run_api.py
  --host 0.0.0.0 --port 8420), /api/health + Stichproben-Views über Tailscale-URL (DASH_URL
  + ?token=DASH_TOKEN aus .env) verifizieren, Nico per Telegram Link + Änderungsliste
  schicken (equity_scout.telegram_client.send_message, COPILOT_TG_BOT_TOKEN/CHAT_ID).
- Danach: Outcome-Abschnitt hier ergänzen (was gebaut, Abweichungen, offene Punkte) und
  `Outcome: DONE` als eigene Zeile setzen (schaltet den SessionStart-Hook stumm).

## Outcome
(offen — nach Umsetzung ausfüllen; DONE-Zeile nicht vergessen)
