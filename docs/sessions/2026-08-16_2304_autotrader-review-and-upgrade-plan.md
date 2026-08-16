# Session 2026-08-16 23:04 — Autotrader-Review (extern) + Upgrade-Plan

## Kontext & Ziel
Nico wollte den Autotrader (equity-scout) und sein Konzept extern hinterfragt haben:
Recherche zu weiteren Techniken, Parametern, Informationsquellen und kürzeren/längeren
Zeitintervallen — kritisch gegen die Vision „läuft daily ohne meinen Input und wird eine
passive Einnahmequelle". Danach: „Schreib einen Plan dafür und mach handoff."

Ablauf: Repo-Faktensammlung (Explore-Agent über Strategien/Allocator/Protections/Lanes/
Gates/Kosten/Cron) + drei Web-Recherche-Agents (Techniken & Signale · Passive-Income-Realität
inkl. Steuern/Broker DE · Zeitintervalle & Execution). Review als Chat-Antwort geliefert,
daraus der Implementierungsplan.

## Ergebnis
- **Review geliefert (Chat, diese Session).** Kernaussagen:
  - Die Messmaschine ist außergewöhnlich sauber; die eigenen Nullbefunde (Achse 2, ORB,
    TOM, Overnight, Reversal, PEAD-Verwandte) decken sich mit der Literatur — das validiert
    den Harness.
  - Der Kernwiderspruch zur Vision: die Echtgeld-Schwellen (180 T, Sharpe > 1, MaxDD < 15 %)
    liegen über CTA-Realität (SG CTA ~0,4 netto) und sind in 180 Tagen statistisch
    unentscheidbar (~4 Jahre nötig); MaxDD ≈ 2·Vol/Sharpe macht die Kombination fast
    widersprüchlich. Ehrlicher Pivot: Risiko-Ziel statt Alpha-Ziel; passive Einnahme kommt
    aus Kapital × Marktrendite (10k ⇒ ~30–60 €/Monat nach Steuern selbst bei Sharpe 0,5–1,0).
  - Steuern DE: 20k-Termingeschäft-Grenze per JStG 2024 rückwirkend weg; Aktien-Verlusttopf
    bleibt; hoher Turnover kostet ~0,7–1 pp CAGR vs. B&H (Stundung + Teilfreistellung).
    Broker: praktisch nur IBKR reif; Alpaca-Live für DE unbestätigt; PDT-Abschaffung ab
    06/2026 mit Übergang bis 2027.
  - Zeitintervalle: jede Lane bekommt mehr Evidenz, je langsamer sie läuft; kürzer ist für
    dieses Setup beantwortet (nein), länger (Quartals-/Schwellen-Rebalance) ist der
    unerforschte Hebel.
- **Plan geschrieben:** `docs/superpowers/plans/2026-08-16-autotrader-review-upgrades.md`
  — 7 Tasks, TDD, mit konkretem Code: (1) VIX-Multiplikator in VolTarget, (2) proof.py-
  Schwellen als Risiko-Ziel (730 T, ≥ Benchmark nach Kosten, MaxDD ≤ 60 % der Benchmark),
  (3) Crypto-Verdict regime-sauber (Epoche 2026-08-10) + vorregistriertes Kill-Kriterium,
  (4) Allocator-Tilt Sharpe-Softmax → Inverse-Vol, (5) Timing-Luck-Studie (Messung vor
  Tranching-Bau), (6) Stooq-EOD-Kreuzcheck vor dem Depot-Advance, (7) Fundamentals-Horizont
  126 T vorregistrieren. Plus dokumentierte Nicht-Ziele.
- **Faktenkorrektur:** `~/private/STATUS.md` war stale — signal-stack-v5 ist committet
  (2026-07-12), beide dort geflaggten Methodik-Bugs sind längst gefixt, Working Tree war
  clean. (STATUS.md selbst wurde in dieser Session nicht angefasst.)

## Entscheidungen
- **VIX-Term-Structure als Regime-Signal 5 NICHT gebaut** — die eigene W0-Studie
  (2026-08-11) hat sie inkrementell widerlegt (Rank-IC 0,51 → 0,08 nach VIX-Level+Breadth);
  eigene Messung schlägt Literatur-Prior. Im Plan als Nicht-Ziel dokumentiert.
- **Tranching nur als Messung (Task 5), kein Bau** — Repo-Regel „geänderte Parameter = neue
  Sleeve-Identität" + erst Materialität auf dem eigenen Panel beweisen.
- **Crypto-Task ändert null Trading-Verhalten** — respektiert Nicos Standing-Decision vom
  16.08. („Lane unangetastet lassen"); nur das Bewertungsfenster wird regime-ehrlich.
- **Kreuzcheck-Fail-Richtung gesplittet:** Referenz nicht erreichbar ⇒ warnen + weiterlaufen;
  Referenz widerspricht ⇒ Advance abbrechen (guarded chain holt nach).

## Offene Fragen
- Task-2-Schwellenwerte (730 T / ≥ 0 pp vs. Benchmark / DD-Ratio 0,60) sind Vorschläge —
  Nicos Veto/Anpassung vor Umsetzung.
- Crypto-Framing bestätigen: Kill-Kriterium „≥ 30 Daily-Ära-Trades, Verdict negativ ⇒
  Cron-Zeile raus" dauert bei 20/10-Donchian grob 12–24 Monate — will Nico das, oder ein
  schnelleres Kriterium?
- STATUS.md unter ~/private/ ist bzgl. equity-scout veraltet (signal-stack-v5-Absatz) —
  beim nächsten status-sweep korrigieren?

## To-dos
### Nico
1. Plan lesen und Go geben (oder Tasks streichen): `docs/superpowers/plans/2026-08-16-autotrader-review-upgrades.md`.
2. Die zwei Zahlen-Entscheidungen treffen: neue Echtgeld-Schwellen (Task 2) und das
   Crypto-Kill-Kriterium (Task 3) — beides steht mit Vorschlagswerten im Plan.
3. Optional: entscheiden, ob die Review-Kernaussage („Risiko-Ziel statt Alpha-Ziel") auch in
   README/„Kann das funktionieren?" soll, bevor Task 2 sie dort verankert.

### Nächste Session (Agent)
- Nach Nicos Go: Plan per `executing-plans` oder `subagent-driven-development` abarbeiten;
  Reihenfolge beachten (Task 1 und 4 in VERSCHIEDENEN Nächten deployen — Attributionsregel).
- Task 5 (Timing-Luck-Studie) ist ohne Live-Risiko und kann als Erstes laufen, liefert
  sofort ein Research-Doc.
- Gate wie immer: `uv run pytest -q` + `uv run ruff check .`; Frontend-Task 2 zusätzlich
  `npm run build --prefix frontend`.

## Einstieg für die nächste Session
Branch `autopilot/work` (Tree war clean bis auf Plan- und Session-Doc dieser Session).
Startpunkt: `docs/superpowers/plans/2026-08-16-autotrader-review-upgrades.md` lesen —
Header nennt Provenienz, Nicht-Ziele und die zwei Nico-Gates. Umsetzung erst nach Go;
dann Task-Reihenfolge und die Eine-Nacht-eine-Änderung-Regel aus den Execution notes
einhalten. Die Review-Begründungen (Quellen) stehen im Chat-Verlauf dieser Session und
komprimiert im Plan-Header.
