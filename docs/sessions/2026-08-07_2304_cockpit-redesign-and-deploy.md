# Session 2026-08-07 23:04 — Cockpit-Redesign-Loop, Deploy & stehender Umbau-Auftrag

## Kontext & Ziel
Nico will das Handy-Cockpit radikal auf einen einfachen User ohne Aktien-Expertise
zuschneiden: App analysieren, Persona definieren, klickbares Mockup als Claude-Artifact,
in einer Feedback-Loop iterieren. Im Verlauf: Go für alles ("freie Macht"), Deploy mit
frischen Daten aufs Handy, am Ende stehender Auftrag für den Umbau in nächsten Sessions.

## Ergebnis
- **Mockup v1+v2** (Artifact, gleiche URL beide Runden):
  https://claude.ai/code/artifact/f2270350-d102-446a-a0cd-844eee725218 — Kopie im Repo:
  `docs/design/2026-08-07-phone-cockpit-mockup-v2.html`. v2 = Nicos Feedback: Risikoprofil-
  Chips (violett) überall, volle Score-Tiefe als "Im Detail"-Drilldowns, Einstiegsplan-Level,
  Earnings-Termin, Assistent-FAB unten rechts. Persona "Alex, 31"; IA 13 Views → 5 Tabs +
  Mehr; Details im Plan (s.u.), Analyse-Kernbefunde: 4 konkurrierende Aktienlisten,
  4 Score-/Kursziel-Konzepte, keine kanonische Detailseite.
- **App-Grundlagen gebaut+deployt** (autopilot/work, Gates: 1478 Backend- + 90 Frontend-
  Tests, tsc, vite build):
  - `c445675` resolve_target_stop: Scout-Ziel nie mehr null — Champion (source="model")
    oder konservative Faustformel (source="heuristic_v1", 2σ/1,5σ/20d)
  - `9e8722f` + `576caeb` GET /api/company/{ticker} (F-Score + next_earnings; eigenes
    Modul company_api.py, weil api.py parallel heiß war) + Mount + /api/entry-Umstellung
  - `9bd5197` News-Original-Quellen verlinkt (InsightBlock/PickCard)
  - `716ac92` Zurück-Geste blättert Tabs (pushState+popstate, Token-Leck verhindert)
  - `99005af` Provenance-Label am Kursziel ("trainiertes Modell" vs. "Faustformel")
- **Deploy + Daten-Refresh:** dist neu gebaut (Dash-Prozess von 13:56 hatte Backend schon
  drin), live über Tailscale verifiziert. Refresh: Earnings 36/42, F-Scores, Evidence,
  Insights (12 Titel), Voll-Scout 14:38 MESZ (7.499 Titel). Telegram: Link (msg 57) +
  Frisch-Update an Nico.
- **Stehender Umbau-Auftrag** (`7b8ae4c`): Plan
  `docs/superpowers/plans/2026-08-07-cockpit-rebuild-from-mockup-v2.md`, SessionStart-Hook
  `scripts/session_start_cockpit_rebuild.sh` (in ~/private/.claude/settings.local.json
  eingehängt; verstummt bei "Outcome: DONE"), Backup: Tag `pre-cockpit-rebuild-2026-08-07`
  + Bundle `~/backups/equity-scout-pre-cockpit-rebuild-2026-08-07.bundle`.

## Entscheidungen
- Scout-Ziel-Heuristik statt Warten auf entry_tb-Champion — Nico hat seine frühere
  "kein Modell-Kursziel"-Entscheidung explizit umgedreht; Provenance-Tag hält es ehrlich.
- company_api.py als eigenes Router-Modul — api.py wurde zeitgleich vom Assistant-Strang
  editiert (Koordination: nur explizite Pfad-Commits, heiße Dateien gemieden).
- News-Links als eigener "Original-Quellen"-Block — headlines_de stammen aus anderer
  Quelle + LLM-Pass, 1:1-Link-Matching wäre geraten.
- Ergebnisse raus aus der Bottom-Bar, Personen+Stimmen fusioniert, Forschung → "Labor" —
  Mockup-Entscheidungen, von Nico abgenickt ("fand das fein").
- **Lesson (im Memory):** Nicos "freie Macht" gilt bis Widerruf — kein erneutes Gaten.

## Offene Fragen
- Ollama rein auf CPU (Assistent 60–106 s bis erstes Token) — GPU/API-Entscheidung liegt
  bei Nico (aus Parallelstrang, betrifft auch KI-Texte).

## To-dos
### Nico
1. Nichts Pflichtiges. Optional: Mockup v2 nochmal durchklicken, falls dir beim Umbau
   noch Detailwünsche einfallen — einfach in der nächsten Session sagen.
### Nächste Session (Agent)
1. SessionStart-Hook zeigt den Auftrag: Umbau nach Plan
   `docs/superpowers/plans/2026-08-07-cockpit-rebuild-from-mockup-v2.md` bauen — ohne
   Rückfragen, Backup vorher verifizieren.
2. Darin enthalten: brief.model_target auf resolve_target_stop umstellen; /api/stack-Bug
   (`factors` vs `breakdown`) beim Anfassen fixen.
3. Kleinere Lücke: SEC hatte bei 7 Insider-Tickern rate-limitiert (Nightly holt nach —
   nur prüfen, ob passiert).

## Einstieg für die nächste Session
Branch autopilot/work, Working Tree war clean (nur ggf. Parallelstrang beachten —
`git status` zuerst). Den SessionStart-Hook-Auftrag direkt ausführen: Plan lesen, Mockup
`docs/design/2026-08-07-phone-cockpit-mockup-v2.html` im Browser als Referenz, dann per
executing-plans umsetzen. Abschluss laut Plan: Gates, dist bauen, Dash-Neustart,
Telegram an Nico, "Outcome: DONE" in den Plan.
