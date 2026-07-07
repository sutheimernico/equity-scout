# Session 2026-06-25 18:01 — Entry-Levels (Bau + Design-Politur) & Pitching-Spec

## Kontext & Ziel
Fortsetzung nach dem Entry-Levels-Plan aus dem Vorlauf. Drei Stränge in dieser Session:
1. To-Do 1 **Kaufempfehlungen / Entry-Levels** subagent-driven bauen.
2. Visuelles Design-Feedback von Nico iterativ beheben (Tranchen, Level-Liste, Laien-Verständlichkeit).
3. To-Do 2 **„Pitching"** klären → Brainstorming → Spec.

## Ergebnis (Referenzen statt Kopien)
- **Entry-Levels-Feature komplett** auf Branch `feat/entry-levels` (NICHT gemerged). Plan + Outcome:
  `docs/superpowers/plans/2026-06-25-entry-levels-tranchen.md`. Backend `entry.py` (pure Mathe +
  `compute_entry_plan` + `fetch_entry_history`), Endpoint `GET /api/entry/{ticker}`, Frontend
  `EntryPlanBlock.tsx`. Gate grün: **169 pytest**, ruff/typecheck/build. Live gegen yfinance verifiziert.
- **Design-Politur** (mehrere Commits, zuletzt `19e5c46`): Tranchen einspaltig + DCA als Satz + Dip-
  Raster; Level-Liste als Tabelle `Referenz-Level | Preis | zum Kurs (±%)` statt verwirrender Balken;
  Label-Overlap/Umbruch gefixt; Disclosure flach (kein Karte-in-Karte); Design-Tokens statt Fremdwerte;
  „Fib" → „Fibonacci"; ausklappbares Glossar **„Was bedeuten diese Niveaus?"**.
- **ADR 0001** `docs/adr/0001-plain-language-everywhere.md` — Laien-Verständlichkeit als durchgängiges
  Prinzip (noch untracked, siehe To-dos).
- **Pitching-Spec** auf Branch `feat/stock-pitch` (von `feat/entry-levels` gebrancht):
  `docs/superpowers/specs/2026-06-25-stock-pitch-design.md` — Sub-Projekt 1 (strukturierte These).

## Entscheidungen (je 1 Satz Begründung)
- **Pitching = 3 Sub-Projekte**, gebaut in Reihenfolge These → aktives Top-Pick-Pitchen → Vergleich;
  die These ist das Fundament, auf dem die anderen aufbauen.
- **Pitch-Quelle = lokales Ollama** (`qwen2.5:7b`, gratis), NICHT claude-CLI; Nico will keine
  pay-per-use-API-Kosten (Token über sein Abo sind egal).
- **Laien-Verständlichkeit überall** (ADR 0001); Begriffe wie „Fib"/„ATR"/„Sharpe" sind für Nico
  bedeutungslos, deshalb Fachbegriff + Klartext-Erklärung an jeder Stelle.
- **`feat/stock-pitch` von `feat/entry-levels` gebrancht**, weil beide den PickCard-Drilldown anfassen —
  vermeidet Merge-Konflikt; Merge-Reihenfolge: erst entry-levels, dann stock-pitch.
- **Branch behalten** (kein Auto-Merge) — Nico reviewt + merged selbst, wie immer.

## Offene Fragen
- Passt das **Laien-Glossar-Muster** am Entry-Block visuell? → erst danach Dashboard-weiter Rollout.
- Pitching-Spec ok, oder Änderungen vor `writing-plans`?

## To-dos
### Nico
1. Den **Einstiegs-Block** im Browser abnehmen (Pick aufklappen → Tranchen-Plan, Level-Tabelle,
   „Was bedeuten diese Niveaus?"). App: **http://127.0.0.1:8000**.
2. Entscheiden, ob das **Klartext-Erklärungs-Muster** so passt — dann gebe ich den Rollout aufs ganze
   Dashboard frei (Strategie-Kennzahlen, ML-Tab, Screener).
3. Den **Pitching-Spec** kurz lesen (`docs/superpowers/specs/2026-06-25-stock-pitch-design.md`).
4. `feat/entry-levels` reviewen/mergen, danach `feat/stock-pitch`.
5. Offen seit länger: **GitHub-Backup** — `gh auth login` (deine Aktion), dann Repo anlegen.
6. Entscheiden: soll `docs/sessions/` getrackt oder gitignored werden (aktuell nicht ignoriert).

### Nächste Session (Agent)
- **Laien-Rollout (ADR 0001)** übers Dashboard: `frontend/src/format.ts` hat schon `METRIC_HELP` /
  `STRATEGY_PITCH` — konsistent als Disclosures/Inline-Notes ausspielen (Strategie-Metriken,
  Strategie-Namen, ML-Tab Triple-Barrier/PBO/DSR, Screener Composite/Perzentil/Buckets).
- **`feat/stock-pitch`**: zuerst die Entry-Levels-Design-Fixes nachziehen (merge `feat/entry-levels`
  rein), dann `writing-plans` für Sub-Projekt 1, dann bauen (Ollama `format:json`, Endpoint
  `/api/pitch/{ticker}`, `PitchBlock` im Drilldown).
- Danach Pitching-Sub-Projekte 2 (Top-Pick-Pitchen) + 3 (Vergleich), je eigener Spec/Plan.

## Einstieg für die nächste Session
Zwei offene Branches (keiner gemerged): **`feat/entry-levels`** (Feature + Design + Laien-Glossar,
12+ Commits) und **`feat/stock-pitch`** (nur der Pitching-Spec obendrauf). Auto-Memory
(`equity-scout-multistrategy-ml.md`) ist aktuell und wird automatisch geladen. Erster Schritt hängt an
Nicos Abnahme: entweder **Laien-Rollout (ADR 0001)** auf `feat/entry-levels`, oder **`writing-plans`**
für den Pitching-Spec auf `feat/stock-pitch`. App starten: `uv run python scripts/run_api.py --port 8000`.
Research-Loop + Forward-Cron + Ollama laufen lokal weiter.
