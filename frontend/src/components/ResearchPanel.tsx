import { useEffect, useState } from "react";

import { fetchResearch, type ResearchResponse } from "../api";
import { ML_FEATURE_LABELS, MODEL_LABELS, num } from "../format";
import { ChampionCard } from "./ChampionCard";
import { Leaderboard } from "./Leaderboard";
import { Bar } from "./ui/Bar";
import { Chip } from "./ui/Chip";
import { Explain } from "./ui/Explain";

function FreqBars({ counts }: { counts: Record<string, number> }) {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const max = entries[0]?.[1] || 1;
  return (
    <>
      {entries.map(([key, count]) => (
        <div className="alloc-row feat-row" key={key}>
          <span className="alloc-ticker feat">{ML_FEATURE_LABELS[key] ?? MODEL_LABELS[key] ?? key}</span>
          <Bar value={count} max={max} />
          <span className="alloc-pct tnum">{count}</span>
        </div>
      ))}
    </>
  );
}

export function ResearchPanel() {
  const [data, setData] = useState<ResearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      fetchResearch()
        .then((d) => alive && setData(d))
        .catch((e: unknown) => alive && setError(String(e)));
    load();
    const id = setInterval(load, 5000); // live: reflects the background loop as it writes the ledger
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  if (error) return <p className="state err">Fehler: {error}</p>;
  if (!data) return <p className="state">Lädt…</p>;

  return (
    <>
      <Explain>
        Ein <strong>Hintergrund-Loop</strong> probiert laufend Modell-Konfigurationen und bewertet jede{" "}
        <strong>out-of-sample</strong>. Der Overfitting-Schutz ist eingebaut: jeder Versuch hebt über die{" "}
        <strong>Deflated Sharpe Ratio</strong> die Hürde für alle an — je mehr gesucht wird, desto schwerer
        ist es, zufällig gut auszusehen. Diese Ansicht aktualisiert sich alle 5&nbsp;Sekunden.
      </Explain>

      {!data.available || data.n_trials === 0 ? (
        <section className="strat-block">
          <h3 className="block-title">Loop läuft noch nicht</h3>
          <Explain tone="hint">Im Hintergrund starten — läuft, solange der Laptop an ist:</Explain>
          <p>
            <code>nohup uv run python scripts/run_research.py &gt; research.log 2&gt;&amp;1 &amp;</code>
          </p>
        </section>
      ) : (
        <>
          <div className="chip-row">
            <Chip live>Live-Ansicht</Chip>
            <Chip>
              <b>{data.n_trials}</b>&nbsp;Versuche
            </Chip>
            <Chip>
              Overfitting-Hürde <b>{num(data.hurdle ?? 0, 3)}</b> ↑
            </Chip>
            <Chip>
              Champion-DSR <b>{num(data.champion?.dsr ?? 0, 2)}</b>
            </Chip>
          </div>

          {data.champion && <ChampionCard champion={data.champion} />}

          <div className="strat-cols">
            {data.model_frequency && (
              <section className="strat-block">
                <h3 className="block-title">Welche Algorithmen gewinnen</h3>
                <Explain tone="hint">Häufigkeit unter den besten Konfigurationen.</Explain>
                <FreqBars counts={data.model_frequency} />
              </section>
            )}
            {data.feature_frequency && (
              <section className="strat-block">
                <h3 className="block-title">Welche Merkmale gewinnen</h3>
                <Explain tone="hint">Häufigkeit unter den besten Konfigurationen.</Explain>
                <FreqBars counts={data.feature_frequency} />
              </section>
            )}
          </div>

          <Leaderboard rows={data.leaderboard} />
        </>
      )}
    </>
  );
}
