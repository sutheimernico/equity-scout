"""Hätten die Vorschläge getragen? (Nachtschicht 2026-08-27)

Die Lücke, die das schließt: `proof.py` misst die BÜCHER — Auto-Depot, Arena-Lanes, alles was
die Maschine selbst handelt. Was nie gemessen wurde, ist die Liste, die Nico tatsächlich zu
sehen bekommt: die Pitches und die Rangliste. Am 2026-08-27 wollte er anfangen, danach echtes
Geld einzusetzen, und niemand konnte sagen, ob ein Vorschlag dieser Maschine je etwas wert war.

Was hier gemessen wird, und was ausdrücklich nicht:

- **Gemessen:** die Rendite eines Titels ab dem ersten Kurs, den ein Mensch nach dem Vorschlag
  wirklich hätte bezahlen können, über feste Horizonte, **minus** dem Heimatindex desselben
  Marktes. Ohne diesen Abzug misst man im Sommer 2026 den Markt, nicht den Screen.
- **Nicht gemessen:** ob das so bleibt. Das hier ist Rückschau auf eine kurze, einmalige
  Stichprobe, kein Backtest und erst recht keine Prognose.

Ehrlichkeitsgrenzen, die die Zahlen lesbar halten (LOOP.md-Messregeln, hier angewandt):

- **Einstieg NIE zum Kurs des Vorschlagstags.** Ein Vorschlag entsteht während der Sitzung;
  wer ihn abends liest, kauft frühestens am nächsten Handelstag. `first_tradable_close`
  nimmt deshalb den ersten Schluss NACH dem Vorschlagszeitpunkt. Der Kurs, den der Pitch
  selbst nennt, ist Anzeige, nicht Einstieg — er wird als `quoted_price` mitgeführt, damit
  die Differenz sichtbar bleibt, statt still den Rückblick zu schönen.
- **Überlappende Fenster sind keine unabhängigen Beobachtungen.** Derselbe Titel steht in
  16 Runs; 16 Messungen über 20 Tage teilen fast denselben Kursverlauf.
  `independent_outcomes` dünnt pro Titel auf nicht-überlappende Fenster aus, und jedes
  Aggregat berichtet BEIDE Zahlen — die volle und die unabhängige.
- **Auch die unabhängige Stichprobe ist nicht unkorreliert.** Die Liste war im Sommer 2026
  schwer mit Tankschifffahrt besetzt; acht gleichzeitige Reeder sind ein Sektorwette, keine
  acht Experimente. Der Benchmark-Abzug nimmt den Markt heraus, den Sektor nicht.
  `sector_concentration` beziffert das, statt es zu verschweigen.
- **Ohne Heimatindex kein Exzess.** Für einen Markt ohne Mapping bleibt `excess_pct` None und
  der Vorschlag zählt in der Rohrendite, aber nicht im Urteil. Ein fehlender Benchmark wird
  nie durch einen fremdwährigen ersetzt — das misst dann Wechselkurse.
- **n ist klein.** Der Screen läuft im vollen Universum erst seit 2026-07-14. Das Urteil aus
  `assess_excess` sagt darum meistens „noch nicht aussagekräftig", und das ist die ehrliche
  Antwort, keine Ausflucht.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from equity_scout.significance import SignificanceVerdict, assess_trades

# Horizonte in Handelstagen. 5/20/60 ~ Woche/Monat/Quartal — dieselbe Staffel, die
# entry_predictions verwendet, damit die beiden Messungen vergleichbar bleiben.
HORIZONS = (5, 20, 60)

# Heimatindex je Markt. Der Index MUSS in der Währung des Titels notieren, sonst misst die
# Differenz Wechselkurse statt Auswahl. Suffix schlägt Region: `.NS` ist Indien, egal was
# die Regionsspalte des Runs sagt.
BENCHMARK_BY_SUFFIX: dict[str, str] = {
    ".NS": "^NSEI",     # Indien, INR
    ".BO": "^BSESN",    # Indien, INR
    ".T": "^N225",      # Japan, JPY
    ".HK": "^HSI",      # Hongkong, HKD
    ".SA": "^BVSP",     # Brasilien, BRL
    ".TO": "^GSPTSE",   # Kanada, CAD
    ".V": "^GSPTSE",    # Kanada (Venture), CAD
    ".AX": "^AXJO",     # Australien, AUD
    ".L": "^FTSE",      # UK, GBp
    ".SW": "^SSMI",     # Schweiz, CHF
    ".ST": "^OMX",      # Schweden, SEK
    ".CO": "^OMXC25",   # Dänemark, DKK
    ".OL": "^OSEAX",    # Norwegen, NOK
    ".HE": "^OMXH25",   # Finnland, EUR
    ".DE": "^GDAXI",    # Deutschland, EUR
    ".PA": "^FCHI",     # Frankreich, EUR
    ".AS": "^AEX",      # Niederlande, EUR
    ".BR": "^BFX",      # Belgien, EUR
    ".MI": "FTSEMIB.MI",  # Italien, EUR
    ".MC": "^IBEX",     # Spanien, EUR
    ".LS": "PSI20.LS",  # Portugal, EUR
    ".VI": "^ATX",      # Österreich, EUR
}

# Nur für suffixlose Symbole (US-Notierungen). Eine Region ohne Suffix, die nicht US ist,
# bekommt bewusst KEINEN Benchmark statt einen falschen.
BENCHMARK_BY_REGION: dict[str, str] = {"US": "^GSPC"}

# Ein Vorschlag zählt für den Horizont erst, wenn die Kursreihe ihn wirklich abdeckt. 80 %
# lässt Feiertage und einzelne Lücken durch, aber kein halb gemessenes Quartal.
MIN_HORIZON_COVERAGE = 0.8


@dataclass(frozen=True)
class Suggestion:
    """Ein Vorschlag, wie er Nico gegenüber aufgetreten ist.

    `source` ist "pitch" (per Telegram vorgeschlagen) oder "rank" (Platz in der Rangliste
    eines Runs). Die beiden sind NICHT dasselbe: ein Pitch ist eine Aufforderung, ein Rang
    ist eine Sortierung. Sie werden getrennt ausgewertet und nie in einen Topf geworfen.
    """

    source: str
    ticker: str
    suggested_at: str  # ISO-Zeitstempel
    score: float | None = None
    bucket: str | None = None
    region: str | None = None
    sector: str | None = None
    rank: int | None = None
    quoted_price: float | None = None  # Kurs, den der Vorschlag anzeigte — nie der Einstieg


@dataclass(frozen=True)
class Outcome:
    """Was aus einem Vorschlag über EINEN Horizont geworden ist."""

    suggestion: Suggestion
    horizon_days: int
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    return_pct: float
    benchmark_ticker: str | None
    benchmark_return_pct: float | None
    excess_pct: float | None
    bars_available: int  # wie viele Handelstage die Reihe wirklich hergab

    @property
    def key(self) -> str:
        return f"{self.suggestion.source}:{self.suggestion.ticker}:{self.suggestion.suggested_at}"


@dataclass(frozen=True)
class ReviewSummary:
    """Das Aggregat über eine Menge von Outcomes — mit beiden n, nie nur dem schmeichelhaften."""

    label: str
    horizon_days: int
    n: int
    n_independent: int
    hit_rate: float | None  # Anteil mit positivem Exzess (unabhängige Stichprobe)
    mean_excess_pct: float | None
    median_excess_pct: float | None
    mean_return_pct: float | None
    best: tuple[str, float] | None
    worst: tuple[str, float] | None
    verdict: SignificanceVerdict | None
    sector_concentration: float | None
    tickers: list[str] = field(default_factory=list)


def benchmark_for(ticker: str, region: str | None = None) -> str | None:
    """Heimatindex für einen Titel, oder None wenn es keinen ehrlichen gibt.

    Suffix schlägt Region, weil das Suffix den Handelsplatz und damit die Währung festlegt.
    """
    for suffix, index in BENCHMARK_BY_SUFFIX.items():
        if ticker.upper().endswith(suffix.upper()):
            return index
    if "." in ticker:
        return None  # unbekannter Handelsplatz — lieber kein Benchmark als ein fremdwähriger
    return BENCHMARK_BY_REGION.get((region or "US").upper())


def first_tradable_close(
    series: list[tuple[str, float]], after: str
) -> tuple[int, str, float] | None:
    """Erster Schluss NACH `after` (Index, Datum, Kurs), oder None.

    Streng nach dem Vorschlagsdatum: ein Vorschlag um 16:05 UTC kann nicht zum Schluss
    desselben Tages gekauft werden, und ein Vorschlag um 03:30 UTC bezieht sich auf den
    Schluss des Vortages. Beide Fälle landen korrekt auf dem nächsten Bar.
    """
    day = after[:10]
    for i, (date_str, close) in enumerate(series):
        if date_str[:10] > day and close > 0:
            return i, date_str[:10], float(close)
    return None


def _return_between(series: list[tuple[str, float]], start: int, horizon: int) -> tuple[float, str, float, int] | None:
    """(Rendite, Enddatum, Endkurs, verfügbare Bars) ab Index `start` über `horizon` Bars."""
    entry = float(series[start][1])
    if entry <= 0:
        return None
    available = len(series) - 1 - start
    if available < 1:
        return None
    end = min(start + horizon, len(series) - 1)
    exit_price = float(series[end][1])
    if exit_price <= 0:
        return None
    return exit_price / entry - 1.0, series[end][0][:10], exit_price, available


def measure(
    suggestion: Suggestion,
    series: list[tuple[str, float]],
    horizon_days: int,
    benchmark_series: list[tuple[str, float]] | None = None,
) -> Outcome | None:
    """Ein Vorschlag über einen Horizont. None, wenn die Reihe ihn nicht trägt.

    Der Benchmark wird über DIESELBEN Kalendertage gemessen, nicht über dieselbe Anzahl Bars:
    Feiertage fallen in Bombay und New York auf verschiedene Tage, und ein Index, der zwei
    Bars weiter läuft als der Titel, erfindet Exzessrendite.
    """
    entry = first_tradable_close(series, suggestion.suggested_at)
    if entry is None:
        return None
    idx, entry_date, entry_price = entry
    measured = _return_between(series, idx, horizon_days)
    if measured is None:
        return None
    return_pct, exit_date, exit_price, available = measured
    if available < horizon_days * MIN_HORIZON_COVERAGE and available < horizon_days:
        # Das Fenster ist noch nicht durchlaufen — als Teilmessung nur zulassen, wenn es
        # weit genug ist. Sonst wird ein frischer Vorschlag als "Ergebnis" gezählt.
        return None

    benchmark_ticker = benchmark_for(suggestion.ticker, suggestion.region)
    benchmark_return: float | None = None
    if benchmark_series:
        benchmark_return = _calendar_return(benchmark_series, entry_date, exit_date)
    excess = None if benchmark_return is None else return_pct - benchmark_return
    return Outcome(
        suggestion=suggestion,
        horizon_days=horizon_days,
        entry_date=entry_date,
        entry_price=entry_price,
        exit_date=exit_date,
        exit_price=exit_price,
        return_pct=return_pct,
        benchmark_ticker=benchmark_ticker,
        benchmark_return_pct=benchmark_return,
        excess_pct=excess,
        bars_available=available,
    )


def _calendar_return(series: list[tuple[str, float]], start_date: str, end_date: str) -> float | None:
    """Benchmark-Rendite über dasselbe KALENDERFENSTER — letzter Schluss am/vor dem Datum."""
    start_price = _close_on_or_before(series, start_date)
    end_price = _close_on_or_before(series, end_date)
    if start_price is None or end_price is None or start_price <= 0:
        return None
    return end_price / start_price - 1.0


def _close_on_or_before(series: list[tuple[str, float]], day: str) -> float | None:
    found = None
    for date_str, close in series:
        if date_str[:10] <= day and close > 0:
            found = float(close)
        elif date_str[:10] > day:
            break
    return found


def independent_outcomes(outcomes: list[Outcome]) -> list[Outcome]:
    """Pro Titel nur nicht-überlappende Fenster — der ehrliche n für jeden Test.

    Greedy vom ältesten Vorschlag an: der nächste Vorschlag desselben Titels zählt erst,
    wenn das Fenster des vorigen abgelaufen ist. Die Auswahl hängt damit nur vom Datum ab,
    nie vom Ergebnis — sonst wäre sie eine Ergebnisauswahl.
    """
    by_ticker: dict[str, list[Outcome]] = {}
    for outcome in sorted(outcomes, key=lambda o: o.suggestion.suggested_at):
        by_ticker.setdefault(outcome.suggestion.ticker, []).append(outcome)

    kept: list[Outcome] = []
    for series in by_ticker.values():
        last_exit: str | None = None
        for outcome in series:
            if last_exit is None or outcome.entry_date >= last_exit:
                kept.append(outcome)
                last_exit = outcome.exit_date
    return sorted(kept, key=lambda o: o.suggestion.suggested_at)


def sector_concentration(outcomes: list[Outcome]) -> float | None:
    """Anteil des größten Sektors. Ohne Sektorangabe None — nie 0, das wäre eine Behauptung."""
    sectors = [o.suggestion.sector for o in outcomes if o.suggestion.sector]
    if not sectors:
        return None
    top = max(sectors.count(s) for s in set(sectors))
    return top / len(sectors)


def summarise(outcomes: list[Outcome], label: str, horizon_days: int) -> ReviewSummary:
    """Aggregat. Alle Urteilszahlen kommen aus der UNABHÄNGIGEN Stichprobe, `n` zeigt beide."""
    independent = independent_outcomes(outcomes)
    with_excess = [o for o in independent if o.excess_pct is not None]

    excesses = [o.excess_pct for o in with_excess if o.excess_pct is not None]
    returns = [o.return_pct for o in independent]
    verdict = assess_trades(excesses) if excesses else None

    best = worst = None
    if with_excess:
        best_o = max(with_excess, key=lambda o: o.excess_pct or 0.0)
        worst_o = min(with_excess, key=lambda o: o.excess_pct or 0.0)
        best = (best_o.suggestion.ticker, (best_o.excess_pct or 0.0) * 100)
        worst = (worst_o.suggestion.ticker, (worst_o.excess_pct or 0.0) * 100)

    return ReviewSummary(
        label=label,
        horizon_days=horizon_days,
        n=len(outcomes),
        n_independent=len(independent),
        hit_rate=(sum(1 for e in excesses if e > 0) / len(excesses)) if excesses else None,
        mean_excess_pct=(sum(excesses) / len(excesses) * 100) if excesses else None,
        median_excess_pct=(_median(excesses) * 100) if excesses else None,
        mean_return_pct=(sum(returns) / len(returns) * 100) if returns else None,
        best=best,
        worst=worst,
        verdict=verdict,
        sector_concentration=sector_concentration(independent),
        tickers=sorted({o.suggestion.ticker for o in independent}),
    )


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def verdict_line(summary: ReviewSummary) -> str:
    """Ein deutscher Satz für die Oberfläche. Sagt IMMER zuerst, worauf er sich stützt."""
    if summary.n_independent == 0:
        return "Noch kein abgeschlossenes Fenster — nichts zu urteilen."
    if summary.mean_excess_pct is None:
        return (
            f"{summary.n_independent} unabhängige Vorschläge, aber keiner mit Heimatindex — "
            "ohne Vergleichsmaßstab kein Urteil."
        )
    direction = "über" if summary.mean_excess_pct > 0 else "unter"
    core = (
        f"{summary.n_independent} unabhängige Vorschläge über {summary.horizon_days} "
        f"Handelstage: im Schnitt {abs(summary.mean_excess_pct):.1f} Prozentpunkte "
        f"{direction} dem jeweiligen Heimatindex"
    )
    if summary.hit_rate is not None:
        core += f", {summary.hit_rate * 100:.0f} % davon im Plus gegen den Index"
    if summary.verdict is None or summary.verdict.p_value is None:
        return core + ". Zu wenige für einen Test — das ist eine Beobachtung, kein Befund."
    if summary.verdict.p_value < 0.05:
        return core + f" (p={summary.verdict.p_value:.3f} — von null unterscheidbar)."
    return (
        core + f" (p={summary.verdict.p_value:.2f} — von reinem Zufall NICHT unterscheidbar). "
        "Bei dieser Stichprobengröße ist das der erwartete Befund, kein Freispruch."
    )
