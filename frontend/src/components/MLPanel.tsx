import { useEffect, useState } from "react";

import { fetchMlReport, type MlResponse, type StrategyMetrics } from "../api";
import { maxDrawdown, METRIC_HELP, METRIC_LABELS, ML_FEATURE_LABELS, num, pct, pctAbs } from "../format";
import { AttributionSection } from "./AttributionSection";
import { EquityChart } from "./EquityChart";
import { formatMetric } from "./StrategyPanel";
import { Bar } from "./ui/Bar";
import { Explain } from "./ui/Explain";
import { Metric, type MetricReference } from "./ui/Metric";

const STD_METRICS: (keyof StrategyMetrics)[] = ["cagr", "sortino", "calmar", "annual_volatility"];

const SHARPE_SCALE = 1.5; // anchor scale; the ~1.0 rule-of-thumb "solid" mark sits at 1/1.5

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
    return <Explain>Noch keine Daten. Bitte zuerst die Backtests erzeugen.</Explain>;

  const r = data.report;
  if (!r.trained || !r.metrics)
    return <Explain>Noch nicht genug Historie, um das Modell out-of-sample zu trainieren.</Explain>;

  const importance = Object.entries(r.feature_importance).sort((a, b) => b[1] - a[1]);
  const maxImportance = importance[0]?.[1] || 1;

  const sharpe = r.metrics.sharpe;
  const mdd = r.metrics.max_drawdown; // negative
  const spyMdd = maxDrawdown(r.benchmark_equity); // negative
  const mddScale = Math.abs(Math.min(spyMdd, mdd)) || 1;

  const hitRef: MetricReference = {
    fillValue: r.oos_hit_rate,
    markerAt: 0.5,
    caption: "Zufall ≈ 50 % — gemessen out-of-sample",
  };
  const sharpeRef: MetricReference = {
    fillValue: sharpe / SHARPE_SCALE,
    markerAt: 1 / SHARPE_SCALE,
    caption: "~1,0 gilt als solide",
  };
  const mddRef: MetricReference = {
    fillValue: Math.abs(mdd) / mddScale,
    markerAt: Math.abs(spyMdd) / mddScale,
    caption: `SPY ${pct(spyMdd)} — Verlust deutlich kleiner`,
    tone: "neg",
  };

  return (
    <>
      <Explain>
        Das <strong>Meta-Modell</strong> entscheidet nicht, <em>was</em> steigt, sondern{" "}
        <strong>ob man dem Trendsignal folgen sollte</strong> — anhand des Marktregimes. Alle Zahlen sind{" "}
        <strong>out-of-sample</strong> (purged Walk-Forward), gemessen gegen schlichtes Halten von SPY.
      </Explain>

      <EquityChart
        equity={r.equity}
        benchmark={r.benchmark_equity}
        label="ML-Meta (OOS)"
        benchmarkLabel="SPY halten"
      />

      <div className="metric-grid with-ref">
        <Metric
          label="Trefferquote"
          value={pctAbs(r.oos_hit_rate, 0)}
          help="Anteil der Folgen/Meiden-Entscheidungen, die out-of-sample richtig waren."
          reference={hitRef}
        />
        <Metric
          label={METRIC_LABELS.sharpe}
          value={num(sharpe)}
          help={METRIC_HELP.sharpe}
          reference={sharpeRef}
        />
        <Metric
          label={METRIC_LABELS.max_drawdown}
          value={pct(mdd)}
          help={METRIC_HELP.max_drawdown}
          reference={mddRef}
        />
      </div>

      <div className="metric-grid">
        <Metric label="OOS-Signale" value={String(r.n_bets)} help="Wie viele Signale das Modell out-of-sample bewertet hat." />
        <Metric label="Ø Exposure" value={pctAbs(r.avg_exposure, 0)} help="Durchschnittliches Marktexposure (Rest in Cash/T-Bills)." />
        {STD_METRICS.map((key) => (
          <Metric key={key} label={METRIC_LABELS[key]} value={formatMetric(key, r.metrics![key])} help={METRIC_HELP[key]} />
        ))}
      </div>

      <section className="strat-block">
        <h3 className="block-title">Was das Modell gelernt hat (Feature-Gewichtung)</h3>
        <Explain tone="hint">
          Relativer Einfluss der Regime-Merkmale auf die Entscheidung — gemittelt über alle Trainingsfenster.
        </Explain>
        {importance.map(([feature, weight]) => (
          <div className="alloc-row feat-row" key={feature}>
            <span className="alloc-ticker feat">{ML_FEATURE_LABELS[feature] ?? feature}</span>
            <Bar value={weight} max={maxImportance} />
            <span className="alloc-pct tnum">{num(weight, 2)}</span>
          </div>
        ))}
      </section>

      {r.attribution && <AttributionSection attribution={r.attribution} />}
    </>
  );
}
