import { type StrategyMetrics, type StrategyReport } from "../api";
import { ETF_NAMES, METRIC_HELP, METRIC_LABELS, num, pct, pctAbs, STRATEGY_PITCH } from "../format";
import { AllocationAdvisor } from "./AllocationAdvisor";
import { EquityChart } from "./EquityChart";
import { Bar } from "./ui/Bar";
import { Explain } from "./ui/Explain";
import { Metric, type MetricReference } from "./ui/Metric";
import { PieChart, type PieSlice } from "./ui/PieChart";

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

// The three headline metrics get a reference anchor against the benchmark; the rest stay plain.
const ANCHOR_METRICS: (keyof StrategyMetrics)[] = ["cagr", "sharpe", "max_drawdown"];
const REST_METRICS: (keyof StrategyMetrics)[] = [
  "sortino",
  "calmar",
  "annual_volatility",
  "annual_turnover",
  "deflated_sharpe",
];

export function formatMetric(key: keyof StrategyMetrics, value: number | null): string {
  if (value === null || value === undefined) return "–";
  if (key === "cagr" || key === "max_drawdown") return pct(value);
  if (key === "annual_volatility") return pctAbs(value);
  if (key === "annual_turnover") return `${num(value)}×`;
  return num(value);
}

// Put value and benchmark on one [0,1] scale so the fill vs. the tick reads as better/worse.
function anchorRef(
  value: number,
  bench: number,
  caption: string,
  tone?: "accent" | "neg",
): MetricReference {
  const scale = Math.max(Math.abs(value), Math.abs(bench)) * 1.15 || 1;
  return { fillValue: Math.abs(value) / scale, markerAt: Math.abs(bench) / scale, caption, tone };
}

export function StrategyPanel({
  report,
  benchmarkName,
  benchmark,
}: {
  report: StrategyReport;
  benchmarkName: string;
  benchmark: StrategyMetrics | null;
}) {
  const baseline = report.cost_sweep[0]?.[1] ?? 1;
  const pitch = STRATEGY_PITCH[report.name];
  const m = report.metrics;

  const allocSlices: PieSlice[] = Object.entries(report.current_weights)
    .filter(([, w]) => w > 0)
    .map(([ticker, w]) => ({ label: ETF_NAMES[ticker] ?? ticker, value: w, info: ticker }));
  const invested = allocSlices.reduce((sum, s) => sum + s.value, 0);
  if (invested < 0.999) allocSlices.push({ label: "Cash", value: 1 - invested, info: "nicht investiert" });

  const refs: Partial<Record<keyof StrategyMetrics, MetricReference>> = {};
  if (benchmark) {
    refs.cagr = anchorRef(m.cagr, benchmark.cagr, `${benchmarkName}: ${pct(benchmark.cagr)}`);
    refs.sharpe = anchorRef(m.sharpe, benchmark.sharpe, `${benchmarkName}: ${num(benchmark.sharpe)}`);
    refs.max_drawdown = anchorRef(
      m.max_drawdown,
      benchmark.max_drawdown,
      `${benchmarkName}: ${pct(benchmark.max_drawdown)}`,
      "neg",
    );
  }

  return (
    <div className="strat-panel">
      {pitch && (
        <Explain>
          <strong>{report.name}.</strong> {pitch}
        </Explain>
      )}
      {report.is_benchmark && (
        <Explain tone="hint">
          Passiver Vergleichsmaßstab, keine aktive Strategie — jede aktive Strategie muss ihn nach
          Kosten schlagen, um ihren Aufwand zu rechtfertigen.
        </Explain>
      )}

      <EquityChart
        equity={report.equity}
        benchmark={report.benchmark_equity}
        label={report.name}
        benchmarkLabel={benchmarkName}
      />

      {benchmark ? (
        <>
          <div className="metric-grid with-ref">
            {ANCHOR_METRICS.map((key) => (
              <Metric
                key={key}
                label={METRIC_LABELS[key]}
                value={formatMetric(key, m[key])}
                help={METRIC_HELP[key]}
                reference={refs[key]}
              />
            ))}
          </div>
          <div className="metric-grid">
            {REST_METRICS.map((key) => (
              <Metric key={key} label={METRIC_LABELS[key]} value={formatMetric(key, m[key])} help={METRIC_HELP[key]} />
            ))}
          </div>
        </>
      ) : (
        <div className="metric-grid">
          {METRIC_ORDER.map((key) => (
            <Metric key={key} label={METRIC_LABELS[key]} value={formatMetric(key, m[key])} help={METRIC_HELP[key]} />
          ))}
        </div>
      )}

      {allocSlices.length > 0 && (
        <section className="strat-block">
          <h3 className="block-title">Aktuelle Allokation</h3>
          <Explain tone="hint">
            Wohin diese Strategie jetzt allokiert — die Aufteilung, die sie aktuell kaufen/halten würde.
          </Explain>
          <PieChart slices={allocSlices} fmt={(s) => pctAbs(s, 0)} />
        </section>
      )}

      <AllocationAdvisor weights={report.current_weights} />

      <section className="strat-block">
        <h3 className="block-title">Kosten-Sensitivität</h3>
        <Explain tone="hint">Endwert von 1× nach Round-Trip-Kosten — je flacher, desto robuster.</Explain>
        {report.cost_sweep.map(([bps, terminal]) => (
          <div className="alloc-row" key={bps}>
            <span className="alloc-ticker tnum">{bps} bp</span>
            <Bar value={terminal} max={baseline} tone="cost" />
            <span className="alloc-pct tnum">{num(terminal)}×</span>
          </div>
        ))}
      </section>

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
