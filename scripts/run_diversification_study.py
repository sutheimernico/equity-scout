"""Wie viele unabhängige Wetten steckt das Auto-Depot wirklich? (2026-08-27)

Der Allocator gewichtet elf Sleeves nach inverser Volatilität. Diese Gewichtung KENNT KEINE
KORRELATIONEN — sie behandelt elf Strategien, die dieselben ETFs handeln, als wären es elf
unabhängige Wetten. Wenn sie das nicht sind, ist das Depot ein teurer Nachbau des Marktes,
und dann kann es ihn per Konstruktion nicht schlagen.

Diese Studie misst das, statt es zu vermuten:

1. **Paarweise Korrelation** der täglichen Sleeve-Renditen aus dem Backtest (nicht aus den
   30 Forward-Beobachtungen — eine 11x11-Matrix aus 30 Zeilen ist Rauschen).
2. **Effektive Anzahl unabhängiger Wetten** über die Eigenwerte der Korrelationsmatrix
   (Meucci 2009, „Managing Diversification": die Entropie der normierten Eigenwerte). 11
   perfekt unkorrelierte Sleeves geben 11, elf identische geben 1.
3. **Beta gegen SPY** je Sleeve und für das gewichtete Depot — die direkte Antwort auf
   „ist das hier eigentlich nur der Markt".
4. **Vergleich der Gewichtungsverfahren** walk-forward: gleichgewichtet, inverse
   Volatilität (heute live), ERC (gleicher Risikobeitrag, korrelationsbewusst) und
   Minimum-Varianz — je mit Rendite, Volatilität, Sharpe, maximalem Rückgang.

    uv run python scripts/run_diversification_study.py [--out docs/research/...json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from equity_scout.data.etf_panel import DEFAULT_SNAPSHOT, load_snapshot  # noqa: E402
from equity_scout.engine import run_backtest  # noqa: E402
from equity_scout.market import TRADING_DAYS_PER_YEAR  # noqa: E402
from equity_scout.strategies.registry import default_strategies  # noqa: E402

# Das Rebalancing-Intervall der Gewichtungsverfahren. Monatlich, wie der Allocator live.
REWEIGHT_EVERY = 21
# Rückschau für Kovarianz/Volatilität. 252 statt der 63 des Live-Allocators: eine
# 11x11-Kovarianzmatrix aus 63 Beobachtungen ist grenzwertig singulär — der Vergleich soll
# die VERFAHREN trennen, nicht den Schätzfehler.
LOOKBACK = 252
# Finanzierungskosten für den hypothetischen Vola-Vergleich unten. Bewusst hoch angesetzt:
# ein Backtest, der Fremdkapital umsonst bekommt, beweist nichts.
FINANCING_RATE = 0.05


def effective_bets(correlation: np.ndarray) -> float:
    """Effektive Anzahl unabhängiger Wetten = exp(Entropie der normierten Eigenwerte).

    Meucci (2009). Die Eigenwerte einer Korrelationsmatrix summieren sich auf N; normiert
    bilden sie eine Verteilung, deren Entropie misst, auf wie viele Richtungen sich das
    Risiko verteilt. Ein Wert nahe 1 heißt: eine einzige gemeinsame Richtung (hier: der
    Aktienmarkt) erklärt fast alles.
    """
    eigenvalues = np.linalg.eigvalsh(correlation)
    eigenvalues = np.clip(eigenvalues, 1e-12, None)
    p = eigenvalues / eigenvalues.sum()
    entropy = -np.sum(p * np.log(p))
    return float(np.exp(entropy))


def erc_weights(cov: np.ndarray, *, iterations: int = 500) -> np.ndarray:
    """Equal Risk Contribution über die zyklische Fixpunkt-Iteration.

    Jeder Sleeve trägt denselben Anteil am Portfoliorisiko. Anders als inverse Volatilität
    zählt hier, wie viel Risiko ein Sleeve NACH Berücksichtigung seiner Korrelationen
    beisteuert: zwei Sleeves, die dasselbe halten, teilen sich einen Beitrag, statt beide
    voll zu zählen (Maillard/Roncalli/Teiletche 2010).
    """
    n = cov.shape[0]
    w = np.ones(n) / n
    for _ in range(iterations):
        marginal = cov @ w
        # w_i <- (1/n) / (marginal_i / sigma_p) ist die Fixpunktform; numerisch stabil als
        # Multiplikation mit dem Kehrwert des Grenzbeitrags.
        with np.errstate(divide="ignore", invalid="ignore"):
            updated = np.where(marginal > 0, 1.0 / marginal, 0.0)
        if updated.sum() <= 0:
            return np.ones(n) / n
        updated = updated / updated.sum()
        if np.max(np.abs(updated - w)) < 1e-10:
            w = updated
            break
        w = updated
    return w


def min_var_weights(cov: np.ndarray) -> np.ndarray:
    """Minimum-Varianz mit Long-only-Beschränkung über eine einfache Projektion.

    Bewusst als Referenz mitgeführt, nicht als Vorschlag: Minimum-Varianz ist berüchtigt
    dafür, den Schätzfehler der Kovarianzmatrix zu maximieren (Best/Grauer 1991). Wenn es
    im Vergleich gewinnt, ist das ein Warnsignal für Überanpassung, kein Ergebnis.
    """
    n = cov.shape[0]
    try:
        inverse = np.linalg.pinv(cov)
    except np.linalg.LinAlgError:
        return np.ones(n) / n
    ones = np.ones(n)
    w = inverse @ ones
    total = w.sum()
    if not np.isfinite(total) or abs(total) < 1e-12:
        return np.ones(n) / n
    w = w / total
    w = np.clip(w, 0.0, None)  # Long-only: Leerverkäufe kommen hier nicht vor
    return w / w.sum() if w.sum() > 0 else np.ones(n) / n


def inverse_vol_weights(cov: np.ndarray) -> np.ndarray:
    vols = np.sqrt(np.clip(np.diag(cov), 1e-16, None))
    inverse = 1.0 / vols
    return inverse / inverse.sum()


def equal_weights(cov: np.ndarray) -> np.ndarray:
    n = cov.shape[0]
    return np.ones(n) / n


SCHEMES = {
    "gleichgewichtet": equal_weights,
    "inverse_vol": inverse_vol_weights,
    "erc": erc_weights,
    "min_var": min_var_weights,
}


def walk_forward(returns: pd.DataFrame, weight_fn, *, lookback: int, every: int) -> pd.Series:
    """Tagesrenditen eines Depots, dessen Gewichte alle `every` Tage aus den letzten
    `lookback` Tagen NEU BERECHNET werden — strikt aus Daten VOR dem Wirksamwerden.

    Zurück kommt NUR der Teil ab der ersten Neugewichtung. Der erste Durchlauf dieser
    Studie schnitt die Reihe schon vorher um `lookback` und wertete dann trotzdem ab Tag 0
    aus: die ersten 252 Tage liefen also bei JEDEM Verfahren mit dem Startgewicht, und weil
    genau der Corona-Einbruch in dieses Fenster fiel, meldeten alle vier Verfahren exakt
    denselben maximalen Rückgang von -18,3232 % am 2020-03-23. Vier identische Zahlen auf
    vier Nachkommastellen sind kein Ergebnis, sondern ein Hinweis, dass gar nichts
    verglichen wurde.
    """
    values = returns.to_numpy()
    n_days, n_sleeves = values.shape
    weights = np.ones(n_sleeves) / n_sleeves
    out = np.zeros(n_days)
    first_reweight: int | None = None
    for i in range(n_days):
        if i >= lookback and i % every == 0:
            window = values[i - lookback : i]
            cov = np.cov(window, rowvar=False)
            weights = weight_fn(np.atleast_2d(cov))
            if first_reweight is None:
                first_reweight = i
        out[i] = float(values[i] @ weights)
    start = first_reweight if first_reweight is not None else 0
    return pd.Series(out[start:], index=returns.index[start:])


def stats(daily: pd.Series) -> dict:
    """Rendite, Risiko — und BEIDE Verhältniszahlen, weil sie hier verschiedene Sieger haben.

    `return_to_vol` ist Rendite durch Volatilität, ohne risikofreien Zins. Nach dieser Zahl
    steht das Depot mit 0,93 vor dem Markt mit 0,82 — und genau das wäre die bequeme
    Schlagzeile. Sie hält aber nicht, sobald jemand den Unterschied AUSNUTZEN will: dafür
    muss man den fehlenden Risikoanteil leihen, und dann zählt die Überrendite über den
    Finanzierungssatz, also der echte Sharpe. Nach dem liegt der Markt vorn. Beide Zahlen
    stehen deshalb nebeneinander; nur eine davon zu zeigen wäre in die eine oder andere
    Richtung geschönt.
    """
    equity = (1.0 + daily).cumprod()
    years = len(daily) / TRADING_DAYS_PER_YEAR
    cagr = equity.iloc[-1] ** (1.0 / years) - 1.0 if years > 0 else 0.0
    vol = float(daily.std(ddof=1)) * np.sqrt(TRADING_DAYS_PER_YEAR)
    drawdown = float((equity / equity.cummax() - 1.0).min())
    return {
        "cagr_pct": round(cagr * 100, 2),
        "vol_pct": round(vol * 100, 2),
        "return_to_vol": round(float(cagr / vol) if vol > 0 else 0.0, 2),
        "sharpe": round(float((cagr - FINANCING_RATE) / vol) if vol > 0 else 0.0, 2),
        "max_drawdown_pct": round(drawdown * 100, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", default=DEFAULT_SNAPSHOT)
    parser.add_argument("--cost-bps", type=float, default=10.0)
    parser.add_argument("--out", default="docs/research/2026-08-27-diversification.json")
    args = parser.parse_args()

    panel = load_snapshot(args.snapshot)
    print(f"Panel: {len(panel.dates)} Tage, {panel.dates[0].date()} bis {panel.dates[-1].date()}")

    series: dict[str, pd.Series] = {}
    for strategy in default_strategies():
        result = run_backtest(strategy, panel, costs_bps=args.cost_bps)
        series[strategy.name] = result.equity.pct_change().fillna(0.0)
        print(f"  {strategy.name:34s} fertig")

    returns = pd.DataFrame(series).dropna()
    # Bewusst NICHT hier abschneiden: `walk_forward` braucht die ersten `lookback` Tage als
    # Schätzfenster und gibt selbst nur den Teil ab der ersten Neugewichtung zurück. Ein
    # zweites Abschneiden hier hat genau diese Vergleichbarkeit zerstört (siehe dort).
    print(f"\nGemeinsame Reihe: {len(returns)} Tage über {returns.shape[1]} Sleeves "
          f"(bewertet ab Tag {LOOKBACK})")

    # Korrelation/Beta auf demselben Ausschnitt wie der Verfahrensvergleich, damit sich
    # die Zahlen einer Auswertung auf denselben Zeitraum beziehen.
    measured = returns.iloc[LOOKBACK:]
    correlation = measured.corr()
    off_diagonal = correlation.to_numpy()[np.triu_indices_from(correlation, k=1)]
    n_bets = effective_bets(correlation.to_numpy())

    spy = panel.closes["SPY"].pct_change().reindex(measured.index).fillna(0.0)
    betas = {
        name: round(float(np.cov(measured[name], spy)[0, 1] / np.var(spy)), 2)
        for name in measured.columns
    }

    print("\n=== Wie unabhängig sind die Sleeves? ===")
    print(f"Durchschnittliche Paar-Korrelation: {off_diagonal.mean():.2f} "
          f"(Spanne {off_diagonal.min():.2f} bis {off_diagonal.max():.2f})")
    print(f"Effektive unabhängige Wetten:       {n_bets:.2f} von {measured.shape[1]}")
    print("\nBeta gegen SPY je Sleeve:")
    for name, beta in sorted(betas.items(), key=lambda kv: -kv[1]):
        print(f"  {name:34s} {beta:5.2f}")

    print("\n=== Gewichtungsverfahren im Vergleich (walk-forward, monatlich neu) ===")
    comparison = {}
    for label, fn in SCHEMES.items():
        comparison[label] = stats(walk_forward(returns, fn, lookback=LOOKBACK, every=REWEIGHT_EVERY))
    comparison["SPY (Benchmark)"] = stats(spy)
    header = (f"{'Verfahren':20s} {'CAGR':>8s} {'Vola':>8s} {'Rend/Vola':>10s} "
              f"{'Sharpe':>8s} {'MaxDD':>8s}")
    print(header)
    print("-" * len(header))
    for label, row in comparison.items():
        print(f"{label:20s} {row['cagr_pct']:7.2f}% {row['vol_pct']:7.2f}% "
              f"{row['return_to_vol']:10.2f} {row['sharpe']:8.2f} "
              f"{row['max_drawdown_pct']:7.1f}%")
    print(f"(Sharpe hier mit {FINANCING_RATE * 100:.0f} % risikofreiem Zins — dem Satz, zu "
          "dem der Vergleich unten Fremdkapital leiht.)")

    # --- Die eigentliche Frage: schlägt das Depot den Markt? ---------------------------
    # Roh verglichen lautet die Antwort nein (9,5 % gegen 16,1 %). Nur ist das kein fairer
    # Vergleich: das Depot trägt halb so viel Risiko wie der Markt. Die Frage, die zählt,
    # ist deshalb „wie viel Rendite pro Einheit Risiko" — und die zweite, ob sich der
    # Unterschied überhaupt AUSNUTZEN ließe. Letzteres beantwortet ein Depot, das auf die
    # Marktvolatilität skaliert wird: derselbe Risikoappetit, dieselbe Messlatte.
    #
    # Mit ausdrücklichen FINANZIERUNGSKOSTEN. Ein Backtest, der Fremdkapital umsonst
    # bekommt, beweist gar nichts; Broker verlangen für den geliehenen Teil grob den
    # Geldmarktsatz plus Aufschlag. 5 % p. a. ist ein bewusst pessimistischer Ansatz.
    print("\n=== Auf Marktrisiko skaliert (hypothetisch, mit 5 % Finanzierungskosten) ===")
    best_label = max(
        (label for label in SCHEMES),
        key=lambda label: comparison[label]["return_to_vol"],
    )
    best_daily = walk_forward(
        returns, SCHEMES[best_label], lookback=LOOKBACK, every=REWEIGHT_EVERY
    )
    spy_vol = float(spy.std(ddof=1)) * np.sqrt(TRADING_DAYS_PER_YEAR)
    depot_vol = float(best_daily.std(ddof=1)) * np.sqrt(TRADING_DAYS_PER_YEAR)
    leverage = spy_vol / depot_vol if depot_vol > 0 else 1.0
    financing_daily = FINANCING_RATE / TRADING_DAYS_PER_YEAR
    scaled = best_daily * leverage - max(leverage - 1.0, 0.0) * financing_daily
    scaled_stats = stats(scaled)
    print(f"Verfahren:            {best_label} (bestes Rendite-Risiko-Verhältnis)")
    print(f"Nötiger Faktor:       {leverage:.2f}x  (Depot {depot_vol * 100:.1f} % "
          f"gegen Markt {spy_vol * 100:.1f} % Volatilität)")
    print(f"Danach:               CAGR {scaled_stats['cagr_pct']:.2f} %, "
          f"Vola {scaled_stats['vol_pct']:.2f} %, MaxDD {scaled_stats['max_drawdown_pct']:.1f} %")
    print(f"Markt zum Vergleich:  CAGR {comparison['SPY (Benchmark)']['cagr_pct']:.2f} %, "
          f"Vola {comparison['SPY (Benchmark)']['vol_pct']:.2f} %, "
          f"MaxDD {comparison['SPY (Benchmark)']['max_drawdown_pct']:.1f} %")
    verdict = (
        "schlägt den Markt bei gleichem Risiko"
        if scaled_stats["cagr_pct"] > comparison["SPY (Benchmark)"]["cagr_pct"]
        else "schlägt den Markt auch bei gleichem Risiko NICHT"
    )
    print(f"Befund:               {verdict}.")

    payload = {
        "panel": {
            "start": str(panel.dates[0].date()),
            "end": str(panel.dates[-1].date()),
            "days_used": len(measured),
        },
        "cost_bps": args.cost_bps,
        "mean_pairwise_correlation": round(float(off_diagonal.mean()), 3),
        "min_pairwise_correlation": round(float(off_diagonal.min()), 3),
        "max_pairwise_correlation": round(float(off_diagonal.max()), 3),
        "effective_bets": round(n_bets, 2),
        "sleeve_count": int(measured.shape[1]),
        "betas_vs_spy": betas,
        "correlation": {a: {b: round(float(correlation.loc[a, b]), 3) for b in correlation.columns}
                        for a in correlation.index},
        "schemes": comparison,
        "vol_matched": {
            "scheme": best_label,
            "leverage": round(leverage, 2),
            "financing_rate": FINANCING_RATE,
            **scaled_stats,
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\nGeschrieben: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
