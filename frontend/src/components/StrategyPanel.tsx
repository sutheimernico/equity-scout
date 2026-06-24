import { type StrategyMetrics, type StrategyReport } from "../api";
import { METRIC_HELP, METRIC_LABELS, num, pct, pctAbs } from "../format";
import { EquityChart } from "./EquityChart";

const METRIC_ORDER: (keyof StrategyMetrics)[] = [
  "cagr",
  "sharpe",
  "sortino",
  "max_drawdown",
  "calmar",
  "annual_volatility",
  "annual_turnover",
  "deflated_sharpe",
];

export const COMPARE_METRICS: (keyof StrategyMetrics)[] = METRIC_ORDER;

export function formatMetric(key: keyof StrategyMetrics, value: number | null): string {
  if (value === null || value === undefined) return "–";
  if (key === "cagr" || key === "max_drawdown") return pct(value);
  if (key === "annual_volatility") return pctAbs(value);
  if (key === "annual_turnover") return `${num(value)}×`;
  return num(value);
}

export function StrategyPanel({
  report,
  benchmarkName,
}: {
  report: StrategyReport;
  benchmarkName: string;
}) {
  const weights = Object.entries(report.current_weights).sort((a, b) => b[1] - a[1]);
  const baseline = report.cost_sweep[0]?.[1] ?? 1;

  return (
    <div className="strat-panel">
      {report.is_benchmark && (
        <p className="explain">
          <strong>{report.name}</strong> ist ein passiver Vergleichsmaßstab, keine aktive Strategie —
          jede aktive Strategie muss ihn nach Kosten schlagen, um ihren Aufwand zu rechtfertigen.
        </p>
      )}

      <EquityChart
        equity={report.equity}
        benchmark={report.benchmark_equity}
        label={report.name}
        benchmarkLabel={benchmarkName}
      />

      <div className="metric-grid">
        {METRIC_ORDER.map((key) => (
          <div className="metric" key={key} title={METRIC_HELP[key]}>
            <div className="metric-label">{METRIC_LABELS[key]}</div>
            <div className="metric-value tnum">{formatMetric(key, report.metrics[key])}</div>
          </div>
        ))}
      </div>

      <div className="strat-cols">
        <section className="strat-block">
          <h3 className="block-title">Aktuelle Allokation</h3>
          {weights.length === 0 && <p className="muted">Aktuell in Cash.</p>}
          {weights.map(([ticker, weight]) => (
            <div className="alloc-row" key={ticker}>
              <span className="alloc-ticker">{ticker}</span>
              <div className="bar-track alloc-bar">
                <div className="bar-fill" style={{ width: `${Math.round(weight * 100)}%` }} />
              </div>
              <span className="alloc-pct tnum">{pctAbs(weight, 0)}</span>
            </div>
          ))}
        </section>

        <section className="strat-block">
          <h3 className="block-title">Kosten-Sensitivität</h3>
          <p className="block-hint">Endwert von 1× nach Round-Trip-Kosten — je flacher, desto robuster.</p>
          {report.cost_sweep.map(([bps, terminal]) => (
            <div className="alloc-row" key={bps}>
              <span className="alloc-ticker tnum">{bps} bp</span>
              <div className="bar-track alloc-bar">
                <div
                  className="bar-fill cost"
                  style={{ width: `${Math.round((terminal / baseline) * 100)}%` }}
                />
              </div>
              <span className="alloc-pct tnum">{num(terminal)}×</span>
            </div>
          ))}
        </section>
      </div>

      {report.recent_trades.length > 0 && (
        <section className="strat-block">
          <h3 className="block-title">Letzte Umschichtungen</h3>
          <ul className="trade-list">
            {report.recent_trades
              .slice()
              .reverse()
              .map((trade, i) => (
                <li key={`${trade.date}-${i}`}>
                  <span className="trade-date tnum">{trade.date}</span>
                  <span className="trade-alloc">
                    {Object.entries(trade.weights)
                      .sort((a, b) => b[1] - a[1])
                      .map(([t, w]) => `${t} ${Math.round(w * 100)}%`)
                      .join(" · ") || "Cash"}
                  </span>
                </li>
              ))}
          </ul>
        </section>
      )}
    </div>
  );
}
