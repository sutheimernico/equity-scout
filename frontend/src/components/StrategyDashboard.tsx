import { useEffect, useState } from "react";

import { fetchStrategies, type StrategiesResponse, type StrategyReport } from "../api";
import { METRIC_LABELS } from "../format";
import { MLPanel } from "./MLPanel";
import { ResearchPanel } from "./ResearchPanel";
import { COMPARE_METRICS, formatMetric, StrategyPanel } from "./StrategyPanel";

type Tab = number | "compare" | "ml" | "research";

function CompareTable({
  strategies,
}: {
  strategies: StrategyReport[];
}) {
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
                {s.name}
                {s.is_benchmark && <span className="bench-tag">Benchmark</span>}
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
  const [active, setActive] = useState<Tab>(0); // strategy index, "compare", or "ml"

  useEffect(() => {
    fetchStrategies()
      .then(setData)
      .catch((e: unknown) => setError(String(e)));
  }, []);

  if (error) return <p className="state err">Fehler: {error}</p>;
  if (!data) return <p className="state">Lädt…</p>;
  if (!data.available)
    return (
      <p className="explain">
        Noch keine Backtests vorhanden. {data.hint}
      </p>
    );

  const strategies = data.strategies;
  const benchmark = data.benchmark ?? "60/40";

  return (
    <>
      <p className="explain">
        Jede Strategie ist ein eigenes Demo-Depot, das über die volle Historie (~19 Jahre, 10 ETFs)
        zurückgerechnet wurde — alle Ergebnisse <strong>nach Kosten</strong>, gegen{" "}
        <strong>{benchmark}</strong> als Vergleich. Kein Echtgeld, keine Renditeversprechen.
      </p>

      <div className="tabbar wrap">
        {strategies.map((s, i) => (
          <button
            key={s.name}
            className={i === active ? "tab active" : "tab"}
            onClick={() => setActive(i)}
          >
            {s.name}
          </button>
        ))}
        <button className={active === "ml" ? "tab active ml" : "tab ml"} onClick={() => setActive("ml")}>
          ML-Meta ✨
        </button>
        <button
          className={active === "research" ? "tab active ml" : "tab ml"}
          onClick={() => setActive("research")}
        >
          Auto-Research ✨
        </button>
        <button
          className={active === "compare" ? "tab active" : "tab"}
          onClick={() => setActive("compare")}
        >
          Vergleich
        </button>
      </div>

      {active === "compare" ? (
        <CompareTable strategies={strategies} />
      ) : active === "ml" ? (
        <MLPanel />
      ) : active === "research" ? (
        <ResearchPanel />
      ) : (
        <StrategyPanel report={strategies[active]} benchmarkName={benchmark} />
      )}
    </>
  );
}
