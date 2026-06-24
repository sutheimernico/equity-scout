# equity-scout — Design Spec

**Stand:** 2026-06-24 · **Status:** Phase 0 (Scaffold) → Phase 1 (Vertical Slice v1)
Persönliche Regeln (`~/.claude/CLAUDE.md`) gelten. Schwesterprojekt & Muster-Referenz: `~/private/signal-trader-demo` (Provider-Seams, Cache, ehrliche Caveats, FastAPI+React-Dashboard).

---

## 1 · Vision & non-negotiables

Lokales, kostenfreies System, das ein globales Aktien-Universum per **quantitativem Faktor-Funnel** auf eine Shortlist eindampft, die Finalisten von Claude qualitativ einordnen lässt und das Ergebnis in **drei Risiko-Buckets** über ein Dashboard präsentiert. Läuft regelmäßig automatisch.

**Das Deliverable ist ein Recherche-Assistent — kein Edge-Versprechen, keine Anlageberatung.** Faktor-Screens sind gut erforscht, schlagen den Markt aber nicht zuverlässig; das ist explizit ein Lern-/Recherche-/Showcase-Tool, kein Geldautomat.

Non-negotiables:
- Kein „bester Pick"-Versprechen. Jeder Output trägt transparenten Score-Breakdown + Begründung + Daten-Caveats.
- Disclaimer „keine Anlageberatung", strikt privat/lokal.
- Die LLM-Stufe ist **Einordnung auf Basis von (cutoff-behaftetem) Wissen + gelieferten Kennzahlen — nie eine Kursprognose.**
- Vollständig kostenfreie Datenquellen.

## 2 · Architektur — der Funnel (5 Stufen + LLM + Interface)

Provider-Seams wie bei signal-trader (Netz/LLM hinter Interface, in Tests gefakt).

```
Universe-Liste (Konstituenten großer Welt-Indizes)
  → Data    (yfinance hinter Provider-Seam; SQLite/Parquet-Cache, point-in-time pro Lauf)
  → Gate    (Daten-Vollständigkeit/-Alter; dünn/veraltet → raus oder markiert)
  → Score   (Faktor-Familien Value · Quality · Momentum · Growth, cross-sektional als Perzentile — Quant, KEIN LLM)
  → Buckets (Faktor-Gewichtung je Profil → Top-N je Bucket)
  → LLM     (headless `claude -p` NUR auf die ~30–45 Finalisten: These, Risiken, „warum dieser Bucket")
  → SQLite  (jeder Lauf = Snapshot) → Dashboard (FastAPI + React) liest neuesten Stand
  ⤴ Scheduler triggert den Lauf regelmäßig
```

Entscheidend für Kosten/Machbarkeit: Der teure LLM-Teil sieht **nur die Finalisten**, nicht den Markt. Kosten Cent bis wenige Euro pro Lauf statt vierstellig.

## 3 · Scope

**Drin (Zielbild):** Globales Universum als Konstituenten großer Indizes (S&P 500, STOXX Europe 600, Nikkei 225, …), yfinance-Anbindung + Cache, Daten-Gate, vier Faktor-Familien als Perzentil-Ranking, drei Risiko-Buckets, headless-LLM-Einordnung der Finalisten, SQLite-Snapshots, FastAPI+React-Dashboard, regelmäßiger Scheduler-Lauf.

**Draußen:** Echtgeld-/Order-Anbindung jeder Art, bezahlte Daten-Feeds, Intraday/HFT, LLM-Kursprognose, „garantiertes Alpha", vollständige Abdeckung *jedes* Microcaps weltweit (bewusst nur Index-Konstituenten — siehe §6 Survivorship).

## 4 · Datenmodell (Kern)

- `Instrument` — Ticker (inkl. Yahoo-Börsensuffix `.DE`/`.HK`/…), Name, Exchange, Sektor, Region, Currency.
- `PriceBar` — point-in-time Kurse pro Instrument/Tag (Cache).
- `Fundamentals` — Kennzahlen-Snapshot pro Instrument + `as_of`-Datum (Cache).
- `FactorScore` — pro Instrument/Lauf: Roh- und Perzentil-Werte je Faktor-Familie + Gesamt-Score je Bucket.
- `Pick` — pro Lauf/Bucket: Instrument, Rang, Score-Breakdown, LLM-These, Caveat-Flags.
- `Run` — Lauf-Metadaten (Zeitstempel, Universum-Größe, Gate-Statistik, Datenquellen-Version).

## 5 · Tech-Stack

Python (`uv`) · SQLite + Parquet-Cache · yfinance hinter Provider-Seam · FastAPI + React 19 · headless `claude -p` für die Analyse-Stufe. Neue Logik mit Tests; Netz-/LLM-Calls hinter Interface, in Tests gefakt — keine Live-Calls in Tests. Begründung Stack: bewährt im Schwesterprojekt signal-trader, maximale Muster-Wiederverwendung.

## 6 · Ehrlichkeits-Leitplanken & Daten-Caveats (mit Belegen)

- **yfinance ist inoffiziell und fragil** — kann jederzeit brechen oder Felder leeren. Darum strikt hinter Provider-Seam, in Tests gefakt. Es ist die einzige realistische Gratis-Quelle mit globaler Reichweite (kann Börsensuffixe `.DE`/`.HK`/`.TO`).
- **EM-Coverage ist lückenhaft/verzögert.** Das **Daten-Gate ist Pflicht** — ohne es sortiert der Funnel Titel mit dünner Datenbasis nach oben. Gate-Statistik pro Lauf sichtbar.
- **Survivorship/Look-ahead im Universum:** Heutige Index-Konstituenten ≠ historische. v1 ist Point-in-Time-„heute"-Screening, kein Backtest — daher kein direkter Survivorship-Schaden, aber dokumentiert.
- **Recherche-Befund (warum wir den Funnel selbst bauen):** Die populären fertigen Claude-Aktien-Skills (tradermonty, xvary, InvestSkill, OctagonAI) sind verifiziert **alle US-zentriert oder bezahlt**: tradermonty erzwingt eine US-Exchange-Whitelist, xvary *verwirft Nicht-US-Ticker aktiv* (`.DE`/`.L`/`.HK`), InvestSkill heißt wörtlich `us-stock-analysis`, OctagonAI ist zwingend kommerziell. Keiner deckt „global + kostenlos" out-of-the-box ab. Konsequenz: Funnel + globale Datenanbindung bauen wir selbst; von den Skills leihen wir nur die Analyse-*Methodik* für die LLM-Stufe.

## 7 · Acceptance criteria

1. Funnel läuft end-to-end für ein Start-Universum und produziert drei gefüllte Buckets.
2. Daten-Gate aktiv; ausgeschlossene/markierte Titel pro Lauf nachvollziehbar.
3. Faktor-Scores transparent (Roh + Perzentil) und im Output sichtbar.
4. LLM-Einordnung nur für Finalisten; klar als Nicht-Prognose markiert; LLM hinter Seam in Tests gefakt.
5. Jeder Lauf als Snapshot persistiert; Dashboard zeigt den neuesten Stand.
6. Kein Output ohne Disclaimer + Daten-Caveats.
7. Vollständig kostenfreie Datenquellen.
8. Tests + `ruff` grün (objektives Gate, AUTOPILOT-tauglich).

## 8 · v1 (Vertical Slice — in dieser Session) vs. später (AUTOPILOT-Loop)

- **v1:** Universum = 1–2 Indizes · yfinance + Cache · Gate · Faktor-Scoring · alle 3 Buckets mit simpler Gewichtung · headless-Analyse Top-N · SQLite · minimales Dashboard · manueller Trigger. Tests + ruff grün.
- **Später (Loop):** Universum global ausweiten · Faktoren/Buckets verfeinern · Scheduler-Automatik · Dashboard-Politur · Lauf-History/Tracking · Selbst-Challenge/SOTA pro Phase (AUTOPILOT-Mandat).

## 9 · Open inputs (Nico)

- [ ] Anthropic-Zugang für headless `claude -p` in der Analyse-Stufe (vorhanden via Claude Code — bestätigen).
- [ ] Quelle für Index-Konstituenten-Listen (Wikipedia-Scrape vs. statische CSV) — im Plan entscheiden.
- [ ] Git-Remote/Visibility (privat) — vor erstem Push klären.
