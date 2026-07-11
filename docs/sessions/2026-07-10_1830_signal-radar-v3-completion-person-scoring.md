# Session 2026-07-10/11 — Signal-Radar v3 abgeschlossen + Personen-Track-Record v4

**Auftrag (Nico, 2026-07-10, autonom/Loop):** Finance Report refactoren, maximalen Nutzen
rausholen; Telegram-Meldungen kommen nicht mehr an; Personen mit gutem Track-Record
(Burry-Beispiel) historisch bewerten und höher gewichten.

## Ergebnis (5 Commits auf `autopilot/work`, Gate: 482 pytest + ruff grün)

- `9f95025` Evidence in Pitches + gelabelte Evidenz-Alarme (eigene Tabelle, 14d Cooldown)
- `84874a7` run_evidence/run_resolve_evidence CLIs, /api/evidence, Digest-Trefferquoten
- `58270ed` daily_copilot.sh Cron-Kette + Receiver-Keepalive + install_crontab.sh
- `8ba6f50` Personen-Track-Record-Scoring (Plan: 2026-07-10-person-track-record-v4.md)
- `dcbc7e0` Review-Fix: fabriziertes 0 % bei unreifem 3M-Horizont + Doku-Abschluss

**Root Cause "keine Telegram-Meldungen":** Die Copilot-Kette war nie gescheduled — nur
Screener + Forward-Paper hatten Cron-Zeilen. Live-Beweis nach dem Bau: 18 Cluster-Alarme +
2 Track-Record-Alarme (KHC/Gary Peters, COHR/Sheldon Whitehouse) real zugestellt.

**Personen-Scoring live:** 977 Backfill-Käufe / 13 aktive Filer, eigene Methodik
(T0 = Filing-Datum, abnormal return vs SPY 1M/3M, n≥5-Gate auf dem 3M-Horizont,
540d-Halbwertszeit). Whitehouse +4,3 % (n=18) | Boozman −0,3 % (n=186) |
Trump −6,7 % (n=108) | Khanna −9,1 % (n=56). Peters nach Review-Fix korrekt gegated
(alle 5 Käufe jünger als 3M).

## Entscheidungen
- X/Twitter-Finfluencer bleibt draußen: 2026 keine freie API, Nitter tot (Recherche-Agent,
  Quellen im v4-Plan). Berühmte Investoren laufen über 13F (Burry = Scion).
- Evidence beeinflusst weiterhin NIE den Entry-Composite — Personen-Scores priorisieren
  nur Alerts und annotieren Pitches ("Historie, keine Prognose" auf jeder Surface).
- Review-Funde 2+3 (Helper-Duplikation, doppelte Log-Umleitung) bewusst belassen —
  Begründung im Commit-Body von `dcbc7e0`.

## Needs Nico
1. `./scripts/install_crontab.sh` einmal ausführen (Session war permission-blocked;
   idempotent, Forward-Paper-Zeile bleibt erhalten).
2. `EDGAR_USER_AGENT="Name (mail)"` in `.env` (Vorlage: `.env.example`) → 13F-Collector an.
3. `autopilot/work` → `main` mergen/pushen (Repo public; DBs/Logs/.env sind gitignored).

## Wiedereinstieg
PLAN.md (Phasen v3 + v4 DONE), Plan-Docs mit Outcomes, `/api/evidence`, `copilot.log`.
Receiver lief bei Session-Ende unter dem flock der künftigen Cron-Zeile.
