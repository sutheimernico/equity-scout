import { useEffect, useState } from "react";

import { fetchMlReport, type MlResponse, type StrategyMetrics } from "../api";
import { METRIC_HELP, METRIC_LABELS, ML_FEATURE_LABELS, num, pct, pctAbs } from "../format";
import { EquityChart } from "./EquityChart";
import { formatMetric } from "./StrategyPanel";

const STD_METRICS: (keyof StrategyMetrics)[] = [
  "cagr",
  "sharpe",
  "sortino",
  "max_drawdown",
  "calmar",
  "annual_volatility",
];

export function MLPanel() {
  const [data, setData] = useState<MlResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchMlReport()
      .then(setData)
      .catch((e: unknown) => setError(String(e)));
  }, []);

  if (error) return <p className="state err">Fehler: {error}</p>;
  if (!data) return <p className="state">Lädt… (Modell wird trainiert, einen Moment)</p>;
  if (!data.available || !data.report)
    return <p className="explain">Noch keine Daten. Bitte zuerst die Backtests erzeugen.</p>;

  const r = data.report;
  if (!r.trained || !r.metrics)
    return (
      <p className="explain">
        Noch nicht genug Historie, um das Modell out-of-sample zu trainieren.
      </p>
    );

  const importance = Object.entries(r.feature_importance).sort((a, b) => b[1] - a[1]);
  const maxImportance = importance[0]?.[1] || 1;

  return (
    <>
      <p className="explain">
        Das <strong>Meta-Modell</strong> entscheidet nicht, <em>was</em> steigt, sondern{" "}
        <strong>ob man dem Trendsignal folgen sollte</strong> — anhand des Marktregimes
        (Volatilität, Marktbreite, Drawdown). Trainiert per{" "}
        <strong>purged Walk-Forward</strong>, alle Zahlen sind <strong>out-of-sample</strong>. Das
        wiederholte Nachtrainieren auf neuen Daten <em>ist</em> die Feedbackschleife. Ehrliche
        Erwartung: Risiko­reduktion, kein Alpha — gemessen gegen schlichtes Halten von SPY.
      </p>

      <EquityChart
        equity={r.equity}
        benchmark={r.benchmark_equity}
        label="ML-Meta (OOS)"
        benchmarkLabel="SPY halten"
      />

      <div className="metric-grid">
        <div className="metric" title="Anteil der Folgen/Meiden-Entscheidungen, die out-of-sample richtig waren.">
          <div className="metric-label">Trefferquote</div>
          <div className="metric-value tnum">{pctAbs(r.oos_hit_rate, 0)}</div>
        </div>
        <div className="metric" title="Wie viele Signale das Modell out-of-sample bewertet hat.">
          <div className="metric-label">OOS-Signale</div>
          <div className="metric-value tnum">{r.n_bets}</div>
        </div>
        <div className="metric" title="Durchschnittliches Marktexposure (Rest in Cash/T-Bills).">
          <div className="metric-label">Ø Exposure</div>
          <div className="metric-value tnum">{pctAbs(r.avg_exposure, 0)}</div>
        </div>
        {STD_METRICS.map((key) => (
          <div className="metric" key={key} title={METRIC_HELP[key]}>
            <div className="metric-label">{METRIC_LABELS[key]}</div>
            <div className="metric-value tnum">
              {key === "cagr" || key === "max_drawdown"
                ? pct(r.metrics![key] as number)
                : key === "annual_volatility"
                  ? pctAbs(r.metrics![key] as number)
                  : formatMetric(key, r.metrics![key])}
            </div>
          </div>
        ))}
      </div>

      <section className="strat-block">
        <h3 className="block-title">Was das Modell gelernt hat (Feature-Gewichtung)</h3>
        <p className="block-hint">
          Relativer Einfluss der Regime-Merkmale auf die Entscheidung — gemittelt über alle
          Trainingsfenster.
        </p>
        {importance.map(([feature, weight]) => (
          <div className="alloc-row feat-row" key={feature}>
            <span className="alloc-ticker feat">{ML_FEATURE_LABELS[feature] ?? feature}</span>
            <div className="bar-track alloc-bar">
              <div className="bar-fill" style={{ width: `${Math.round((weight / maxImportance) * 100)}%` }} />
            </div>
            <span className="alloc-pct tnum">{num(weight, 2)}</span>
          </div>
        ))}
      </section>
    </>
  );
}
