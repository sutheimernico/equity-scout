# Strang B — Forward-Paper-Persistenz (Spec)

Stand 2026-06-25. Zweiter Strang. Branch `feat/multi-strategy-ml`.

## Problem / Ziel

Die Strategien existieren nur als **Backtest** (rückläufig, `engine.run_backtest` über Historie).
Nico will sie **fortlaufend vorwärts** laufen lassen: ein echter, persistenter Forward-Track-Record
pro Strategie, der sich ab heute aufbaut. Das ist die ehrlichste mögliche Evidenz — strikt
out-of-sample, weil die Strategie nicht auf diese Zukunft optimiert wurde. Passt exakt zum
„Prozess, kein Alpha"-Ethos.

## Konzept

Das Projekt trennt schon sauber: **Strategy ist state-free** (`decide(as_of, market)` pure), der
**Account ist stateful**. Ich folge dem: ein `ForwardAccount` akkumuliert über die Zeit (Equity,
aktuelle Gewichte, Benchmark, letztes Bewertungsdatum). `decide` bleibt unverändert — derselbe
Code-Pfad wie im Backtest, kein zweiter.

Ein `advance`-Schritt schiebt einen Account auf das neueste Panel-Datum:
1. **Drift** seit letztem advance: Periodrendite der gehaltenen Gewichte (konsistent mit der
   Engine-Drift-Formel `w·(1+r)/(1+r_port)`), Equity + Benchmark mitziehen.
2. **decide** für heute (Daten bis einschl. heute), neue Zielgewichte.
3. **Turnover-Kosten** auf `Σ|Δweight|` (gleiche Konvention wie Engine, default 10 bps).
4. Snapshot persistieren.

**Idempotent:** läuft advance zweimal am selben Tag (kein neues Panel-Datum), passiert nichts.

## Datenmodell (`src/equity_scout/forward_paper.py`)

```
@dataclass(frozen=True) ForwardAccount:
    strategy_name, initial_capital, equity, weights: dict[str,float],
    benchmark_ticker, benchmark_equity, last_as_of: str | None
    classmethod fresh(strategy_name, *, initial_capital=10_000, benchmark_ticker="SPY")

@dataclass(frozen=True) ForwardValuation:
    created_at, equity, total_return, benchmark_equity, benchmark_return

advance_account(account, strategy, panel, *, costs_bps=10.0) -> (ForwardAccount, ForwardValuation | None)
    # None wenn schon aktuell (idempotent)
```

## Persistenz (`src/equity_scout/forward_storage.py`)

Folgt dem `portfolio_storage`-Muster (SQLite, JSON-Blob für den Account-State, getrennte Valuation-
Timeseries), neue DB-Datei `forward_paper.db` (Default in `constants.py`), separat von Runs/Portfolio.

```sql
forward_accounts(strategy_name TEXT PRIMARY KEY, data TEXT, updated_at TEXT)
forward_valuations(id PK, strategy_name TEXT, created_at TEXT, equity REAL,
                   total_return REAL, benchmark_equity REAL, benchmark_return REAL,
                   UNIQUE(strategy_name, created_at))   -- INSERT OR IGNORE = idempotent/Tag
```

Funktionen: `init_forward_db`, `save_account`, `load_account`, `load_all_accounts`,
`append_valuation`, `load_valuations(strategy_name)`.

## CLI (`scripts/run_forward_paper.py`)

Lädt (optional `--refresh`) das ETF-Panel, iteriert `default_strategies()`, lädt/initialisiert jeden
Account, `advance_account`, speichert Account + Valuation, druckt Zusammenfassung. Idempotent.

## API (`/api/forward` in `api.py`)

Liefert alle Accounts mit `{strategy_name, equity, total_return, benchmark_return, last_as_of,
n_points, equity_curve: [[date, equity, benchmark_equity], …]}`. Kein Cache (live aus der DB).

## UI (Strategien-Tab)

Neuer Reiter **„Live"** neben „Vergleich" in `StrategyDashboard`: pro Strategie der Forward-Track
(Equity-Kurve vs. Benchmark via bestehendem `EquityChart`, Tage live, Rendite via `Metric`).
Ehrlicher Leerzustand, wenn noch nichts gelaufen ist: erklärt, dass der Track sich ab dem ersten
`run_forward_paper.py` über echte Tage aufbaut. Nutzt die Strang-A-Primitives.

## Abgrenzung

- **Screener-Demodepot (`Portfolio`/`run_paper.py`) bleibt unangetastet** — es ist ein anderes Konzept
  (Buy-and-hold der Einzelaktien-Picks), kein Strategie-Forward. Es destruktiv zu entfernen brächte
  keinen Gewinn. (Korrigiert die in Strang A getroffene Annahme „Demodepot → B": B *ergänzt* den
  Forward-Track für Strategien, ersetzt das Screener-Depot nicht.)
- Kein Scheduler/Cron in diesem Strang (YAGNI) — manueller/extern geplanter CLI-Lauf reicht.

## Tests (`tests/test_forward_paper.py`)

Gegen `wavy_panel`: (1) erster advance initialisiert Equity ≈ initial − Aufbaukosten, setzt Gewichte;
(2) zweiter advance über spätere Panel-Daten driftet Equity korrekt; (3) advance ohne neues Datum ist
idempotent (Valuation None, Account unverändert); (4) Turnover-Kosten reduzieren Equity bei Rebalance;
(5) Storage round-trip (save→load identisch), Valuation-UNIQUE verhindert Doppel pro Tag.

## Gate

`uv run pytest -q` + `uv run ruff check .` + FE `typecheck` + `build` grün.

## Erfolgskriterien

Strategien laufen per CLI fortlaufend vorwärts, der Track persistiert über Läufe, die UI zeigt ihn
ehrlich (inkl. Leerzustand). Kein Look-ahead (derselbe `decide`-Pfad), Kosten verrechnet, Benchmark
mitgeführt.

---

## Outcome (2026-06-25)

Umgesetzt + live verifiziert, alle Gates grün (FE `typecheck`+`build`, `ruff`, `pytest` 136 grün —
6 neue Forward-Tests). Spec→direkt Umsetzung (kein separater Plan-Doc; Spec war konkret genug, inline-
Ausführung unter dem Autonomie-Mandat). Commits auf `feat/multi-strategy-ml`:

- `feat(forward)` core: `ForwardAccount` + `advance_account` (Drift + Turnover-Kosten konsistent mit
  der Engine; idempotent pro Tag) + `forward_storage` (SQLite, `forward_paper.db`).
- DRY: `turnover()` von `engine.py` nach `strategies/base.py` gehoben (zweiter Konsument existiert jetzt).
- `feat(forward)` CLI `scripts/run_forward_paper.py` (live getestet: advanced alle 7 Strategien) +
  `GET /api/forward` (live getestet, liefert alle Accounts + Equity-Kurven).
- `feat(forward)` UI: „Live (Forward)"-Tab im Strategien-Dashboard, `ForwardPanel` (nutzt Strang-A-
  Primitives + `EquityChart`, normalisiert auf growth-of-1, ehrlicher Leerzustand bei < 2 Punkten).

**Abweichung von der ursprünglichen Strang-A-Annahme:** Das Screener-Demodepot wird NICHT ersetzt —
es ist ein anderes Konzept (Einzelaktien-Picks). B *ergänzt* den Forward-Track für die ETF-Strategien.

**Offen / Natur der Sache:** Der Forward-Track hat erst 1 Punkt pro Strategie (erster advance heute).
Eine sichtbare Kurve braucht ≥ 2 reale Handelstage — Nico lässt `run_forward_paper.py` täglich (oder
per Cron) laufen. Die Drift-Logik für ≥ 2 Punkte ist durch Unit-Tests abgedeckt.
