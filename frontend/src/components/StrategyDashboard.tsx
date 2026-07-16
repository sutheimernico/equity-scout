import { useEffect, useState } from "react";

import { fetchStrategies, type StrategiesResponse, type StrategyReport } from "../api";
import { METRIC_LABELS } from "../format";
import { SectorsCard } from "./SectorsCard";
import { COMPARE_METRICS, formatMetric, StrategyPanel } from "./StrategyPanel";
import { Badge } from "./ui/Badge";
import { Explain } from "./ui/Explain";
import { TimeContextBadge } from "./ui/TimeContextBadge";

type Tab = number | "compare";

function CompareTable({ strategies }: { strategies: StrategyReport[] }) {
  return (
    <div className="table-scroll">
      <table className="history compare">
        <thead>
          <tr>
            <th>Strategie</th>
            {COMPARE_METRICS.map((key) => (
              <th className="num" key={key}>
                {METRIC_LABELS[key]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {strategies.map((s) => (
            <tr key={s.name}>
              <td>
                {s.name} {s.is_benchmark && <Badge tone="bench">Benchmark</Badge>}
              </td>
              {COMPARE_METRICS.map((key) => (
                <td className="num tnum" key={key}>
                  {formatMetric(key, s.metrics[key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function StrategyDashboard() {
  const [data, setData] = useState<StrategiesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<Tab>(0); // strategy index or "compare"

  useEffect(() => {
    fetchStrategies()
      .then(setData)
      .catch((e: unknown) => setError(String(e)));
  }, []);

  if (error) return <p className="state err">Fehler: {error}</p>;
  if (!data) return <p className="state">Lädt…</p>;
  if (!data.available) return <Explain>Noch keine Backtests vorhanden. {data.hint}</Explain>;

  const strategies = data.strategies;
  const benchmarkName = data.benchmark ?? "60/40";
  const benchmarkMetrics = strategies.find((s) => s.is_benchmark)?.metrics ?? null;

  return (
    <>
      <header className="section-head reveal">
        <p className="eyebrow">Forschung · Strategien</p>
        <h1>Sieben Systematiken, ehrlich gegen {benchmarkName} gemessen</h1>
        <p className="section-sub">
          Jede Strategie ist ein eigenes Demo-Depot, über ~19 Jahre und 21 ETFs zurückgerechnet — alle
          Ergebnisse <strong>nach Kosten</strong>, gegen <strong>{benchmarkName}</strong> als Vergleich.
          Kein Echtgeld, keine Renditeversprechen. Die vorwärtslaufenden Konten dieser Strategien
          findest du unter <strong>Entscheiden → Depots → Strategie-Forward</strong>.
        </p>
        <TimeContextBadge kind="backtest" />
      </header>

      <div className="tabbar wrap">
        {strategies.map((s, i) => (
          <button key={s.name} className={i === active ? "tab active" : "tab"} onClick={() => setActive(i)}>
            {s.name}
          </button>
        ))}
        <button
          className={active === "compare" ? "tab active" : "tab"}
          onClick={() => setActive("compare")}
        >
          Vergleich
        </button>
      </div>

      {active === "compare" ? (
        <CompareTable strategies={strategies} />
      ) : (
        <StrategyPanel
          report={strategies[active]}
          benchmarkName={benchmarkName}
          benchmark={strategies[active].is_benchmark ? null : benchmarkMetrics}
        />
      )}

      <SectorsCard />
    </>
  );
}
