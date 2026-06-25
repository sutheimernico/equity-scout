# Strang A — UX & Design-Fundament (Spec)

Stand 2026-06-25. Erster von vier Strängen einer größeren Ausbau-Runde
(A: UX/Design · B: Forward-Paper-Persistenz · C: Ehrlichkeits-Analytik · D: lokaler Chatbot).
Branch: `feat/multi-strategy-ml`.

## Problem

Das Dashboard ist „nicht intuitiv / nicht übersichtlich" (User-Feedback). Diagnose nach Code-Review:
das visuelle Fundament ist solide (sauberes CSS-Token-System, gute Texte) — das Problem ist zu ~70 %
**Informationsarchitektur**, nicht Farbe. Drei konkrete Ursachen:

1. **Demodepot ist kontextuell verloren** — lebt ganz unten im Aktien-Screener-Tab, ist aber ein eigenes
   Konzept (Paper-Depot der Picks). Zwei „depotartige" Dinge ohne erkennbare Beziehung.
2. **Zahlen ohne Bezugsrahmen** — „Hit Rate 64 %", „Sharpe 0.93" stehen nackt da. Ohne Anker
   (Zufall ≈ 50 %, 60/40 ≈ 0.60, SPY −55 %) nicht einzuordnen. Hauptgrund für „ML-Tab checkt man nicht ganz".
3. **Textwände statt progressiver Offenlegung** — Erklärtexte (v. a. ML-Intro) sind inhaltlich gut, aber
   am Stück. Kernaussage sichtbar + Details auf Abruf fehlt durchgängig.

## Entscheidungen (vom User bestätigt)

- **Palette bleibt Lilac** (`--accent: #7c5cff` etc. unverändert). Gewinn liegt in Architektur, nicht Farbe.
- **Architektur-first**, visueller Polish nur via Komponenten-Konsistenz (kein Re-Theming).
- **Demodepot gehört NICHT in diesen Strang** — es wird in Strang B (Forwarding) durch das echte
  fortlaufende System ersetzt. Doppelarbeit vermeiden.

## Scope

**In:**
- Wiederverwendbare UI-Primitives, die die im Review gefundene Duplikation beseitigen.
- Selbsterklärung der Schlüsselzahlen (Bezugsrahmen-Anker + Vergleichsbalken).
- Progressive Offenlegung als durchgängiges Muster (Kernaussage + einklappbare Tiefe).
- Konsistenter Bereichs-Header pro Tab (Eyebrow + Ein-Satz-Einordnung „worum geht's hier").
- Aufsplitten der zu großen Komponenten (ResearchPanel 158 Z., FunnelView 101 Z.).

**Out (bewusst):** Demodepot-Redesign (→ B), Farb-/Theme-Änderung, neue fachliche Features,
Refactoring ohne UX-Nutzen, Backend-Änderungen (außer ggf. Bereitstellung von Benchmark-Ankern, s. u.).

## Neue Primitives (`frontend/src/components/ui/`)

Jede ist klein, hat einen Zweck, ein typisiertes Props-Interface, ist isoliert testbar:

- **`<Disclosure summary={…}>children</Disclosure>`** — das `<details>`-Muster: Kernaussage sichtbar,
  Tiefe einklappbar, Chevron-Rotation. Ersetzt die ML-Textwand und vereinheitlicht `MethodologyNote`.
- **`<Explain title? tone="info|hint">`** — vereint die heute getrennten `.explain` + `.block-hint`-Boxen.
- **`<Metric label value reference?>`** — Label + Wert + optionaler Bezugsrahmen (Anker-Text +
  `<Bar>` mit Referenz-Marker). Trägt die „Zahl-mit-Kontext"-Logik zentral.
- **`<Bar value max marker?>`** — ersetzt die ad-hoc `bar-track/bar-fill`-Divs überall; optionaler
  Vergleichsmarker (z. B. „Zufall 50 %").
- **`<Badge tone="region|news|bench|status">`** — die heute inline gebauten Tags/Badges.
- **`<Chip>` / `<StatusChip live?>`** — Status-Chips (Auto-Research „läuft", Versuche, steigende Hürde).

Bestehende Tokens/Klassen aus `index.css` werden wiederverwendet, nicht ersetzt. Neue Komponenten-CSS
folgt dem vorhandenen Token-System.

## Änderungen pro Bereich

- **Shell (`App.tsx` + neuer Bereichs-Header):** pro Tab ein konsistenter Header (Eyebrow + 1 Satz).
  Beantwortet „worum geht's in diesem Bereich" beim ersten Blick.
- **ML-Tab (`MLSection`/`MLPanel`/`ResearchPanel`):** Intro-Textwand → `<Disclosure>` (wie Mockup).
  Metriken über `<Metric>` mit Ankern: Trefferquote vs. 50 %, Sharpe vs. 60/40, MaxDD vs. SPY,
  Deflated Sharpe vs. Schwelle. `ResearchPanel` in `StatusChips` + `ChampionCard` + `Leaderboard` splitten.
- **Strategien-Tab (`StrategyPanel`/`CompareTable`):** Metrik-Kacheln auf `<Metric>` umstellen; wo sinnvoll
  Anker gegen den 60/40-Benchmark (Daten liegen bereits im Report vor). Pitch ggf. in `<Disclosure>`.
- **Screener-Tab (`FunnelView`/`PickCard`):** `MethodologyNote` auf `<Disclosure>`, Score-Balken auf `<Bar>`,
  Tags auf `<Badge>`. `FunnelView` ggf. in Sub-Views entzerren. **Demodepot bleibt unangetastet (→ B).**

## Offene Frage: Herkunft der Bezugsrahmen-Werte

Anker sollen möglichst aus echten Daten kommen, nicht hartkodiert:
- **60/40-Sharpe/MaxDD:** liegt als Benchmark bereits im Strategie-Report vor → von dort ziehen.
- **SPY-MaxDD (−55 %):** im ML-Report ist SPY die Benchmark-Equity → daraus berechnen statt Konstante.
- **Zufall 50 %:** fix, korrekt als Konstante.

Wo ein Wert nicht ohne Backend-Aufwand verfügbar ist, wird er als klar benannte Konstante gesetzt und
das im Code vermerkt. Keine Backend-Erweiterung in diesem Strang ohne Rückfrage.

## Testing & Verifikation

- Kein FE-Test-Setup vorhanden. Gate: `npm run typecheck --prefix frontend` + `npm run build --prefix frontend`
  grün, Backend-Gate (`uv run pytest -q` + `uv run ruff check .`) unverändert grün.
- Visuelle Verifikation am laufenden Dashboard (API + Build) — pro Tab durchklicken.
- Primitives so bauen, dass ein leichtes FE-Test-Setup später andocken kann (reine Props, kein verstecktes State).

## Erfolgskriterien

- ML-Tab: jede Schlüsselzahl ist ohne Vorwissen einzuordnen (hat einen sichtbaren Anker).
- Keine Erklärungs-Textwand mehr ohne Disclosure-Muster.
- Sichtbar konsistenteres Look-&-Feel über alle Tabs durch gemeinsame Primitives; messbar weniger
  Styling-Duplikation (kein `bar-track/bar-fill`-Copy-Paste, eine Info-Box statt zweier).
- Build + Lint grün, Lilac-Palette unverändert.

## Nicht verhandelbar (projektweit)

Paper-only, ehrliches Framing (Prozess/Bildung/Risiko, kein Alpha), Disclaimer auf jeder Surface bleibt.
