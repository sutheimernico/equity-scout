# Session 2026-08-09 21:38 → 2026-08-10 08:23 — Autotrader-Diagnose + v15 P3 Evidence-Learning

## Kontext & Ziel

Nico: „Schau dir den Autotrader an. Funktioniert der ja oder nein? … analysiere die Probleme
und fixxe die und mache alles viel krasser … gib alles." Dazu die Frage, ob der Daytrader
„sekündlich" werden muss, und die Vision reich zu werden. Drei Sessions arbeiteten parallel
im selben Tree (diese = P3-Strang; parallel: P2 Insider-Schattenlane, Cockpit-Refresh-Buttons)
— Koordination lief über SendMessage, Dateibesitz sauber getrennt, Commits nur mit expliziten
Pfaden.

## Ergebnis

**Diagnose (Task-Details im Task-Register dieser Session, Kernzahlen im Abschlussbericht):**
- Maschine funktioniert: Crons/Windows-Tasks aktiv, Session-Lane auf Alpaca-IEX-Echtzeit,
  Slippage 1–3 bps, Fill-Latenz ~5 s. Ökonomie noch nicht: Session −2,2 % (n=17, zu früh),
  Crypto −1,7 % (~70 % Kosten), Depot +0,9 % vs. SPY +3,3 % (strukturell, 0,60 Exposure).
- Antwort auf „sekündlich?": Nein — Engpass ist Edge+Kosten, nicht Geschwindigkeit.

**Gebaut (alles auf `autopilot/work`, Gate final 1860 py + ruff, Final-Review SHIP):**
- **v15 P3 komplett** via subagent-driven-development (je Task: Implementierer → Spec-Review →
  Opus-Quality-Review): `ml/evidence_features.py` (PIT-Insider-Index, 71308c9+6dd40e7),
  `score_row`-Guard (84359dd+dee2873), `entry_dataset` additiv (0405b4c+48374db),
  Evidence-Challenger-Training mit ehrlichem n_candidates (5a3bf78+24332ad+d0a4df3),
  Refresh-Runner (97fe62a+6d37a6d+f426416), Live-Verify + Outcome (017de62).
  **Live-Nullbefund:** Coverage 2,5 % (7/27 Ticker), v122 AUC 0,4713 vs. v123 0,4743 (+0,003),
  kein Champion. Vollständiges Outcome inkl. aller Abweichungen:
  `docs/superpowers/plans/2026-08-07-v15-p3-evidence-learning.md` (Abschnitt „Outcome").
- **Gate-Härtung außerhalb der Plan-Map** (88fe531): `_no_edge` einseitig — anti-prädiktives
  Modell (AUC ≤ 0,45) kann nicht mehr Erst-Champion werden.
- **Crypto-Lane: echte Kraken-Taker-Fee 80 bps/Seite** (e092fc4; vorher 0 bps — Quelle
  kraken.com/features/fee-schedule, geprüft 2026-08-09).
- **Sleeve-Isolation** (29bee9d): crashendes Sleeve → Tag in Cash, statt alle 8 Sleeves zu killen;
  gleiche Isolation in `run_forward_paper.py`.
- AUTOPILOT_LOG-Zeile (846cdb8), Memory aktualisiert (`equity-scout-project.md`).

## Entscheidungen

- **P2/P3 als freigegeben interpretiert:** Nicos „gib alles"-Direktive galt als Go für die
  vorbereiteten, warteten Pläne; P2 lief ohnehin schon in der Parallel-Session.
- **Kraken-Fee als Default 80 bps Taker (unterste Stufe):** Daten-Venue = Fee-Venue, konservative
  Seite; nur Forward-Messung, Historie unangetastet.
- **Gate verschärft statt dokumentiert** (einseitiges No-Edge-Band): Ein Fake-Erst-Champion wäre
  der wahrscheinlichste Schadensfall der verdoppelten Ziehungen gewesen; Hürde wurde erhöht, nie
  gesenkt — Call-Site-Survey vorab (überall auc/higher-is-better).
- **Kein Auto-Fix der Nicht-US-Null-Konfundierung:** Report-only (Print + Outcome), weil ein
  Regime-Feature dem Modell erst recht einen Jurisdiktions-Dummy gäbe und Zeilen-Drop den
  Same-Sample-Vergleich zerstörte. v2-Entscheidung liegt bei Nico.
- **Kein Worktree trotz drei Sessions:** Live-DBs liegen unversioniert im Repo-Root; Dateimengen
  disjunkt verifiziert, explizite Pfad-Commits reichten (0 Kollisionen).

## Offene Fragen

- Trägt der Insider-Edge live? Erste Ledger-Auflösungen fällig Di 11.08. 18:52 UTC, realistisch
  schreibt der Daily-Chain (16:00 UTC) erst Mi 12.08. — Wave-1-Plan hat den Selbst-Check
  („12.08. noch resolved=0 → Plan wieder öffnen").
- v2-Design Evidence-Learning: US-lastiges Trainingsuniversum (Store hat 7.053 US-Ticker) oder
  Regime-Spalte? Panel-as_of-Uhr statt Resolution-Proxy für den Refresh-Trigger?
- M2: Evidence-Varianten sind in /api/model/history + ModelPanel nicht unterscheidbar
  (api.py gehörte der Cockpit-Session; Folge-Verdrahtung offen).

## To-dos

### Nico
1. Alpaca-Konto „Training" (PA3AKCY23RCD): Die Glattstellungs-Order der Parallel-Session sollte
   heute (Mo) zur Eröffnung gefüllt haben — im Dashboard nachschauen.
2. Mittwoch kurz prüfen (oder prüfen lassen), ob die ersten Vorhersage-Auflösungen da sind.
3. v2-Entscheidung lesen + treffen: Abschnitt „Findings for Nico" im P3-Plan-Outcome
   (`docs/superpowers/plans/2026-08-07-v15-p3-evidence-learning.md`, ganz unten).
4. Weiter offen aus früheren Sessions: Windows-Energieeinstellungen (Rechner schlief über
   US-Börsenschluss), GPU-oder-API-Entscheidung für den Assistenten.

### Nächste Session (Agent)
- Mi 12.08.+: `uv run python scripts/run_evidence_refresh.py` (Dry-Run) — sobald ≥30 neue
  Auflösungen: mit `--apply` die Evidence-Challenger neu bewerten; Ergebnis ehrlich berichten.
- P2-Schattenlane-Befund querlesen (evidence_events hatte historisch nur 1 Insider-Event;
  erster Werktags-Lauf des Kollektors war Mo 10.08.).
- M2-Verdrahtung (Varianten-Kennzeichnung im ModelPanel/API) — vorher klären, ob die
  Cockpit-Session api.py noch besitzt.
- Falls Nico das US-Universum will: neuer Plan via writing-plans (bewusst NICHT ad hoc).

## Einstieg für die nächste Session

Branch `autopilot/work` (HEAD 846cdb8, alles committet, Tree sauber; main wurde von der
P2-Session auf 51d5f63 gepusht — neuere Commits sind noch nicht auf main). Erster Blick:
P3-Outcome im Plan-Doc + dieses Dokument. Erste Handlung je nach Wochentag: Resolve-Stand
prüfen (`SELECT COUNT(*), SUM(resolved_at IS NOT NULL) FROM entry_predictions` in
equity_scout.db). Keine Secrets in dieser Doku; Alpaca-Keys liegen in `.env`
(`ALPACA_*_KEY_ID`/`_SECRET_KEY`).
