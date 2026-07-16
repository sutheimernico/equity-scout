# Vision v8 — Outcome (2026-07-16)

**Spec:** `docs/superpowers/specs/2026-07-16-vision-v8-clarity-sector-rotation.md`
**Backlog:** PLAN.md, Phase "Vision v8". **Alle 13 Tasks umgesetzt** in einer Session,
Commits `204813e..7538279` auf `autopilot/work` (nicht gepusht). Gate durchgängig grün
(`uv run pytest -q` + `uv run ruff check .` + Frontend typecheck/build).

## Was umgesetzt wurde

**Telegram-Klarheit (A1–A6):**
- HTML `parse_mode` mit `escape_html`/`strip_html` und Plain-Text-Retry bei Parse-Fehlern
  auf jedem Sende-/Edit-Pfad — eine kaputte Nachricht kostet nie die Tageslieferung.
- Ampel-Urteil 🟢/🟡/🔴 (`compute_verdict`: Score-Bänder, sehr schwaches Teilsignal
  downgraded eine Stufe) mit Ein-Satz-Warum auf Caption, Langpitch, Inbox-API, Dashboard.
- Caption-Layout: fetter Kopf, vier Absatz-Blöcke (Kopf/Zahlen/Kontext/Risiko); Langpitch:
  `<blockquote expandable>` für die Detailtiefe — NUR in Textnachrichten (Captions bewusst
  nur `<b>`, kein Caption-Support-Risiko). Overflow degradiert zu plain, nie zerrissene Tags.
- Qualitäts-Gate: Top-ups nie unter `--threshold`; 0 Kandidaten ⇒ ehrliche 📭-Einzeiler-
  Meldung; Schwellen-Transparenz in stdout und Digest.
- 🔎-Details-Button (`detail:<id>`): Receiver antwortet mit der persistierten HTML-Langversion
  (`pitch_html`-Spalte; ein gecachter Ollama-Call für beide Varianten); kein Decision-Effekt.
- Digest: fette Sektionsköpfe, Kopfzeile = Markt-Ampel + Top-3-Sektoren + Unter-Schwelle-
  Zähler; SMTP/stdout bleiben plain, Telegram bekommt HTML (splitsicher: 1 `<b>`-Paar/Zeile).

**Sektorrotation (B1–B3):**
- `SectorRotationStrategy`: 11 SPDR-Sektor-ETFs, Top-3 nach 12M/6M-Momentum-Blend,
  per-Slot-Absolut-Momentum-Hürde (Slot → IEF), junge Ticker übersprungen, < 6 rankbare
  ⇒ voll defensiv. Registriert, bewusst NICHT im Ensemble-Blend (C4-Lektion v7).
- ETF-Panel 10 → 21 Ticker; Forward-Paper-Konto entsteht automatisch beim nächsten
  `--refresh`-Lauf (alter Snapshot ⇒ ehrlich in Bonds, getestet).
- Sektor-Momentum-Snapshot (`sectors.py`, gleiche MarketView-Arithmetik wie die Strategie)
  → `/api/sectors` + "Sektoren"-Karte im Strategien-Dashboard + Digest-Kopfzeile.

**Markt-Regime-Ampel (C1–C2):**
- `regime.py`: 4 Signale (SPY vs. 200d, VIX-Band, Breadth, Zinskurve ^TNX−^IRX),
  Green-Count-Composite, ehrlich "unknown" unter 3 bewertbaren Signalen. Kein Regime-ML.
- `/api/regime` (Tages-Cache, per-Leg-Degradierung) + Ampel auf der "Heute"-Seite
  (Disclosure mit den 4 Einzelsignalen). Breadth = Sektor-ETF-Approximation aus dem
  lokalen Panel, ehrlich als "Sektoren" gelabelt.

**Faktor-Ausbau (D1–D2):**
- 52-Week-High-Proximity (George/Hwang 2004) als zweite Momentum-Metrik — Quelle
  `fiftyTwoWeekHigh` aus dem info-Call (null zusätzliche Fetches); alte Cache-Rows
  degradieren aufs 6M-Bein.
- Piotroski F-Score aus SEC EDGAR XBRL `companyfacts` (`fscore.py` + `run_fscore.py`
  in der Daily-Kette): 9 Kriterien, Kriterium ohne Daten = None, Score nur ab 5
  bewertbaren; 30-Tage-Cache; ohne `EDGAR_USER_AGENT` unconfigured.

## Abweichungen vom Plan

- **D2 nicht im Quality-Blend:** companyfacts ist nur watchlist-weit machbar (Universum-
  Sweep wäre GB-groß); eine Metrik, die 30 von 6 600 Titeln haben, darf nicht ins
  Universums-Perzentil. Stattdessen eigenständige Bilanz-Trend-Zeile, explizit
  "ohne Einfluss auf den Score".
- **A4 ohne neues `--min-score`-Flag:** bestehendes `--threshold` ist die Qualitätsgrenze
  der Top-ups — kein zweiter Knopf für dasselbe Konzept.
- **A3 expandable-Quote nur in Textnachrichten** (nicht in Captions) — bewusste
  Risikovermeidung, im PLAN dokumentiert.

## Offene Punkte / Needs Nico

- Live-Verify am echten Telegram: HTML-Rendering, expandable Quote, 🔎-Button — die
  Sandbox hat kein Netz; nächster 18:00-Lauf zeigt es (oder manuell
  `run_notify.py --min-pitches 5` + `run_digest.py`).
- Erster Panel-`--refresh` zieht die 11 Sektor-ETFs; bis dahin sitzt die Rotation defensiv
  und die Sektor-Karte zeigt ehrliche Lücken.
- `EDGAR_USER_AGENT` in `.env` (bestehender Needs-Nico-Punkt) — sonst bleiben F-Scores
  unconfigured.
- Merge/Push-Entscheidung `autopilot/work` → `main` (jetzt v7 + v8 aufgelaufen).
- Vorbestehender Test-Flake `test_entry_model::test_calibrated_model_scores_through_the_calibrator`
  (v7-dokumentiert) bleibt außerhalb des v8-Scopes.
