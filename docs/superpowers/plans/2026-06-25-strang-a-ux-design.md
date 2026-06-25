# Strang A — UX & Design-Fundament Implementation Plan

> **For agentic workers:** Wird inline in der Session umgesetzt (Tasks bauen aufeinander auf:
> Primitives → Tabs). Daher Task-Granularität statt voll-ausgeschriebener Code pro Schritt —
> der echte Code entsteht beim Umsetzen, um Doppelpflege (DRY) zu vermeiden. Spec:
> `docs/superpowers/specs/2026-06-25-strang-a-ux-design.md`.

**Goal:** Das Dashboard übersichtlich + selbsterklärend machen — durch wiederverwendbare Primitives,
Zahlen mit Bezugsrahmen und progressive Offenlegung; Lilac-Palette bleibt, Demodepot bleibt (→ B).

**Architecture:** Neue `components/ui/`-Primitives kapseln die heute ad-hoc kopierten Patterns
(Balken, Info-Boxen, Metrik-Kacheln, Badges, Chips, Disclosure). Bestehende `index.css`-Tokens +
Klassen werden wiederverwendet, neue Klassen ergänzen nur. Tabs werden auf die Primitives umgestellt.

**Tech Stack:** React 19 + TypeScript + Vite, reines CSS mit Tokens (kein UI-Framework).
Gate: `npm run typecheck --prefix frontend` + `npm run build --prefix frontend` grün;
Backend-Gate `uv run pytest -q` + `uv run ruff check .` bleibt grün (kein Backend-Eingriff geplant).

---

### Task 1: UI-Primitives (`frontend/src/components/ui/`)

**Files:** Create `Bar.tsx`, `Metric.tsx`, `Disclosure.tsx`, `Explain.tsx`, `Badge.tsx`, `Chip.tsx`;
add helper `maxDrawdown(equity)` to a util; extend `index.css`.

- [ ] `<Bar value max marker?>` — kapselt `.bar-track`/`.bar-fill`; optionaler Referenz-Marker (Position
      in %, Label darunter). Marker muss außerhalb des `overflow:hidden`-Tracks liegen → Wrapper mit `position:relative`.
- [ ] `<Metric label value help? reference?>` — `.metric`-Kachel; `reference = {anchorLabel, valuePct, markerPct}`
      rendert Anker-Text + `<Bar>` mit Marker. Variante `.metric--wide` für Kacheln mit Referenz.
- [ ] `<Disclosure summary defaultOpen?>children` — `<details>` mit Chevron-Rotation; ersetzt Textwände + `MethodologyNote`.
- [ ] `<Explain tone="info|hint" title?>children` — vereint `.explain` + `.block-hint`.
- [ ] `<Badge tone="region|news|bench|neutral">` — vereint `.region-tag`/`.news-badge`/`.bench-tag`.
- [ ] `<Chip live?>` / Status-Chip — für Auto-Research-Status.
- [ ] Gate: `npm run typecheck --prefix frontend` grün. Commit.

### Task 2: ML-Tab auf Primitives + Anker umstellen

**Files:** Modify `MLSection.tsx`, `MLPanel.tsx`, `ResearchPanel.tsx`.

- [ ] `MLSection` Intro-Textwand → `<Disclosure>` (Kernaussage sichtbar, Methodik einklappbar).
- [ ] `MLPanel` Metriken → `<Metric>` mit Ankern: Trefferquote vs. 50 % (Konstante), MaxDD vs. SPY
      (aus `benchmark_equity` via `maxDrawdown`). Feature-Importance-Balken → `<Bar>`.
- [ ] `ResearchPanel` splitten in `StatusChips` (Versuche/Hürde/Champion-DSR als `<Chip>`),
      `ChampionCard`, `Leaderboard`. Champion-Metriken → `<Metric>`. Freq-Bars → `<Bar>`.
- [ ] Gate: typecheck + build grün. Commit.

### Task 3: Strategien-Tab auf Primitives + Anker umstellen

**Files:** Modify `StrategyDashboard.tsx` (Benchmark-Report durchreichen), `StrategyPanel.tsx`, `CompareTable.tsx`.

- [ ] `StrategyDashboard` findet den `is_benchmark`-Report (60/40) und reicht dessen `metrics` als
      `benchmark` an `StrategyPanel` (echt-datenbasierte Anker, kein Hardcode).
- [ ] `StrategyPanel` Metrik-Kacheln → `<Metric>`; Sharpe/MaxDD/Calmar bekommen Anker gegen 60/40.
      Pitch-`.explain` → `<Explain>`; Kosten-Balken → `<Bar>`.
- [ ] Gate: typecheck + build grün. Commit.

### Task 4: Screener-Tab konsolidieren (Demodepot unangetastet)

**Files:** Modify `FunnelView.tsx`, `PickCard.tsx`, `MethodologyNote.tsx`.

- [ ] `MethodologyNote` → `<Disclosure>`. `PickCard` Score-Balken → `<Bar>`, `region-tag`/`news-badge` → `<Badge>`.
- [ ] `Portfolio.tsx` (Demodepot) NICHT anfassen — gehört zu Strang B.
- [ ] Gate: typecheck + build grün. Commit.

### Task 5: Bereichs-Header pro Tab + Endabnahme

**Files:** Modify `App.tsx` (+ ggf. kleiner `SectionHeader`-Primitive), Tab-Container.

- [ ] Pro Tab ein konsistenter Header (Eyebrow + Ein-Satz-Einordnung „worum geht's hier"):
      Strategien / Machine Learning / Aktien-Screener. ML-Intro-h1 darin aufgehen lassen.
- [ ] Volle Builds + Lint, API neu starten, Dashboard pro Tab durchklicken (visuelle Verifikation).
- [ ] Outcome-Abschnitt an diesen Plan + HANDOFF.md aktualisieren. Commit.

---

## Self-Review (Plan vs. Spec)

- Spec „6 Primitives" → Task 1 ✓. „Zahl mit Anker" → Task 2/3 (echte Daten + benannte Konstante) ✓.
- „Progressive Offenlegung" → Disclosure in Task 2 (ML) + Task 4 (Methodology) ✓.
- „Bereichs-Header pro Tab" → Task 5 ✓. „ResearchPanel/FunnelView splitten" → Task 2/4 ✓.
- „Demodepot → B" → explizit ausgenommen in Task 4 ✓. „Lilac bleibt" → keine Token-Farbänderung ✓.
- Anker-Herkunft: 60/40 aus Report (Task 3), SPY-MaxDD berechnet (Task 2), Zufall 50 % Konstante ✓.
