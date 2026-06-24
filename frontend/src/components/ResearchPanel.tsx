import { useEffect, useState } from "react";

import { fetchResearch, type ResearchConfig, type ResearchResponse } from "../api";
import { ML_FEATURE_LABELS, num, pct, pctAbs } from "../format";

const MODEL_LABELS: Record<string, string> = {
  elastic_net: "Elastic-Net",
  random_forest: "Random Forest",
};

function configLabel(c: ResearchConfig): string {
  const feats = c.features.map((f) => ML_FEATURE_LABELS[f] ?? f).join(" · ");
  return `${MODEL_LABELS[c.model] ?? c.model} · ${feats}`;
}

function FreqBars({ counts }: { counts: Record<string, number> }) {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const max = entries[0]?.[1] || 1;
  return (
    <>
      {entries.map(([key, count]) => (
        <div className="alloc-row feat-row" key={key}>
          <span className="alloc-ticker feat">{ML_FEATURE_LABELS[key] ?? MODEL_LABELS[key] ?? key}</span>
          <div className="bar-track alloc-bar">
            <div className="bar-fill" style={{ width: `${Math.round((count / max) * 100)}%` }} />
          </div>
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
      <p className="explain">
        Ein <strong>Hintergrund-Loop</strong> probiert laufend Modell-Konfigurationen (Features ×
        Algorithmus × Signal × Barrieren) und bewertet jede <strong>out-of-sample</strong>. Der Schutz
        gegen Overfitting ist eingebaut: Jeder Versuch hebt über die <strong>Deflated Sharpe Ratio</strong>{" "}
        die statistische Hürde für alle an — je mehr gesucht wird, desto schwerer ist es, zufällig gut
        auszusehen. Diese Ansicht aktualisiert sich alle 5&nbsp;Sekunden.
      </p>

      {!data.available || data.n_trials === 0 ? (
        <section className="strat-block">
          <h3 className="block-title">Loop läuft noch nicht</h3>
          <p className="block-hint">Im Hintergrund starten — läuft, solange der Laptop an ist:</p>
          <p>
            <code>nohup uv run python scripts/run_research.py &gt; research.log 2&gt;&amp;1 &amp;</code>
          </p>
        </section>
      ) : (
        <>
          <div className="kpi-row">
            <div className="tile">
              <div className="label">Versuche</div>
              <div className="value tnum">{data.n_trials}</div>
              <div className="sub">getestete Konfigurationen</div>
            </div>
            <div className="tile">
              <div className="label">Overfitting-Hürde</div>
              <div className="value tnum">{num(data.hurdle ?? 0, 3)}</div>
              <div className="sub">steigt mit jedem Versuch (DSR)</div>
            </div>
            <div className="tile">
              <div className="label">Champion-DSR</div>
              <div className="value tnum">{num(data.champion?.dsr ?? 0, 2)}</div>
              <div className="sub">Konfidenz, dass der Edge echt ist</div>
            </div>
          </div>

          {data.champion && (
            <section className="strat-block">
              <h3 className="block-title">Aktueller Champion</h3>
              <p className="champion-config">{configLabel(data.champion)}</p>
              <p className="block-hint">
                Signal-Lookback {data.champion.primary_lookback_months} Mon. · Horizont{" "}
                {data.champion.horizon_days} Tage · Barriere {pctAbs(data.champion.barrier, 0)}
              </p>
              <div className="metric-grid">
                <div className="metric"><div className="metric-label">DSR</div><div className="metric-value tnum">{num(data.champion.dsr, 2)}</div></div>
                <div className="metric"><div className="metric-label">Sharpe</div><div className="metric-value tnum">{num(data.champion.sharpe, 2)}</div></div>
                <div className="metric"><div className="metric-label">Rendite p.a.</div><div className="metric-value tnum">{pct(data.champion.cagr)}</div></div>
                <div className="metric"><div className="metric-label">Max. Verlust</div><div className="metric-value tnum">{pct(data.champion.max_drawdown)}</div></div>
                <div className="metric"><div className="metric-label">Trefferquote</div><div className="metric-value tnum">{pctAbs(data.champion.oos_hit_rate, 0)}</div></div>
              </div>
            </section>
          )}

          <div className="strat-cols">
            {data.model_frequency && (
              <section className="strat-block">
                <h3 className="block-title">Welche Algorithmen gewinnen</h3>
                <p className="block-hint">Häufigkeit unter den besten Konfigurationen.</p>
                <FreqBars counts={data.model_frequency} />
              </section>
            )}
            {data.feature_frequency && (
              <section className="strat-block">
                <h3 className="block-title">Welche Merkmale gewinnen</h3>
                <p className="block-hint">Häufigkeit unter den besten Konfigurationen.</p>
                <FreqBars counts={data.feature_frequency} />
              </section>
            )}
          </div>

          <section className="strat-block">
            <h3 className="block-title">Bestenliste</h3>
            <div className="table-scroll">
              <table className="history compare">
                <thead>
                  <tr>
                    <th>#</th><th>Konfiguration</th>
                    <th className="num">DSR</th><th className="num">Sharpe</th>
                    <th className="num">Rendite p.a.</th><th className="num">Max. Verlust</th>
                  </tr>
                </thead>
                <tbody>
                  {data.leaderboard.map((c, i) => (
                    <tr key={i}>
                      <td className="tnum">{i + 1}</td>
                      <td>{configLabel(c)}</td>
                      <td className="num tnum">{num(c.dsr, 2)}</td>
                      <td className="num tnum">{num(c.sharpe, 2)}</td>
                      <td className="num tnum">{pct(c.cagr)}</td>
                      <td className="num tnum">{pct(c.max_drawdown)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </>
  );
}
