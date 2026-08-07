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

Outcome: DONE

**Umgesetzt 2026-08-08 (9 Commits, c130f88..e65f495), deployt auf :8420, live per
Playwright-Smoke auf dem Phone-Viewport verifiziert (Screenshots aller Kern-Views).**

- **Backend-Reste:** `/api/stack` liefert das echte `breakdown`-Feld (der `factors`-Read
  war seit v6 P6 immer None) + jetzt auch `news` (Original-Quellen) im Screener-Block.
  `/api/briefs` trägt `bucket` (= Risikoprofil) und ein provenance-getaggtes Scout-Ziel
  (`model_target`/`model_stop`/`target_source`) via `resolve_target_stop` über die
  nächtlich gecachte Kursreihe — null zusätzliche Netz-Calls; neuer `?ticker=`-Param für
  den Profil-Deep-Link. `/api/company` additiv um Kennzahlen aus dem Quote-Cache
  (`metrics` + `metrics_fetched_on`). `pitch_market_context` trägt `bucket`.
- **Neue IA (v7):** 5 Tabs Heute · Aktien · Entscheiden · Depot · Mehr; Aktienprofil als
  eigene Route (`?view=profil&ticker=X`); Mehr-Sheet mit Icon+Beschreibung (Ergebnisse /
  Wer kauft? / Wie funktioniert das? / Labor / Assistent); Assistent-FAB auf jedem Screen,
  Chat als Vollbild-Overlay (`?chat=1`, Back-Geste schließt). Legacy-Deep-Link-Map: jeder
  alte `?view=`-Key (Telegram!) landet am neuen Ort.
- **Aktien:** EINE Liste (Briefs) mit Segmenten Kaufbereit/Fast/Alle (near = bis 5 % über
  Zonen-Oberkante; unter der Zone nie „fast") + Stil-Chips; Risiko-Chip (violett für
  aggressiv) auf jeder Karte inkl. Pitch-Karten.
- **Profil (Herzstück):** Kopf + Risikozeile, Jahres-Chart + Zonen-Balken, Analysten- vs.
  Scout-Ziel (Provenance-Label), Stop als Absicherung, Earnings-Termin, 3 Klartext-Balken
  (Qualität/Kurs-Timing/KI-Zweitmeinung) mit Im-Detail-Disclosures (5 Faktor-Perzentile,
  3 Timing-Signale mit Begründung, Modell-Erklärung mit Live-Trefferquote),
  EntryPlanBlock-Disclosure, Wer-kauft (30-Tage-Events + Meldeverzug), News (KI-Summary +
  Original-Quellen), Zahlen im Klartext (KGV/Wachstum/Marge/ROE/KBV + Piotroski
  „N von 9" mit Kriterien-Disclosure).
- **Heute:** 3-Minuten-Briefing in Mockup-Reihenfolge (Marktlage-Klartext, Top-3-Karten →
  Profil, Zu-entscheiden-Teaser, Autopilot-Dreizeiler aus /api/proof + Arena, Was
  passiert ist).
- **Depot:** 7 Tabs → 3 Sichten mit „Funktioniert es?"-Kopf (Messtag N/60 + Verdict aus
  /api/proof); Forschungs-Depots → Labor; Gesamt-Überblick als Disclosure.
- **Mehr:** Labor bündelt Strategien/Entry-Modell/Signal-Filter/Lernkurven + Screener-
  und Radar-Rohsichten + Forschungs-Depots (volle Monitoring-Tiefe). Wer kauft? =
  Personen + Stimmen gestapelt. Wie funktioniert das? NEU mit Trichter aus ECHTEN
  Zahlen des letzten Laufs (7.499 → 6.105 → 30).

**Abweichungen vom Mockup (begründet):**
- Keine Kaufen/Beobachten-Actionbar im Profil: es existiert kein Endpoint für freie
  Käufe (nur `decidePitch` für Inbox-Pitches), und Mock-Aktionen sind verboten (Regel 9).
  Stattdessen Teaser-Karte → Entscheiden, wenn ein offener Pitch existiert — deckt sich
  mit der Mockup-Rationale („Kaufen/Später/Ablehnen bleibt die einzige Stelle mit
  Pflicht-Charakter").
- Kein Tagesdelta (+1,8 %) auf Karten/Profil: kein Endpoint liefert eine Tagesänderung —
  weggelassen statt erfunden.
- „Alle 30": /api/briefs cappt den Fundamentals-Fan-out bei 20; die Liste nennt ehrlich
  ihre echte Anzahl.
- `brief.model_target` nicht im Nightly berechnet, sondern request-seitig aus der
  nightly gecachten Serie (gleiches Ergebnis, kein neuer Nightly-Schritt; Titel ohne
  gecachte Serie bleiben ehrlich null).

**Zusatzbefund gefixt:** `zone_gap` lieferte auf BEIDEN Seiten der Zone positive Werte,
`entry_note`s Below-Zone-Zweig (`gap_pct < 0`) feuerte nie — Support-gebrochen-Titel
lasen sich als „über dem letzten Support". Vorzeichen trägt jetzt die Richtung
(Regressionstest; kein anderer Konsument liest das Vorzeichen).

**Gates:** ruff sauber, 1739 Backend-Tests, tsc, 110 Frontend-Tests, vite build.

**Offen / Needs Nico:**
- Insider-Events (Form 4) weiterhin nicht in der DB (SEC-Rate-Limit vom 07.08.) — der
  Nightly sollte nachholen; morgen prüfen.
- DASH_TOKEN ist während des Playwright-Smoke im Session-Transcript gelandet
  (Tailscale-only erreichbar, trotzdem Rotation empfohlen).
- Desktop-Sidebar nutzt die neue IA (8 Einträge + Assistent) — Desktop-Feinschliff war
  nicht Teil des Mockups und blieb bewusst minimal.
