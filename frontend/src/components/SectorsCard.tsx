import { useEffect, useState } from "react";

import { fetchSectors, type SectorsResponse } from "../api";
import { pct } from "../format";

// Fraction cell with sign + tone; null renders an honest dash (young ETF / stale panel).
function ReturnCell({ value }: { value: number | null }) {
  if (value === null) return <td className="num tnum">—</td>;
  return <td className={`num tnum ${value >= 0 ? "pos" : "neg"}`}>{pct(value)}</td>;
}

const WINDOWS = [
  { key: "m1", label: "1 M" },
  { key: "m3", label: "3 M" },
  { key: "m6", label: "6 M" },
  { key: "m12", label: "12 M" },
] as const;

/** v8 sector momentum snapshot — the same ranking signal the rotation strategy trades on. */
export function SectorsCard() {
  const [data, setData] = useState<SectorsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSectors()
      .then(setData)
      .catch((e: unknown) => setError(String(e)));
  }, []);

  if (error) return <p className="state err">Fehler: {error}</p>;
  if (!data) return <p className="state">Lädt…</p>;

  return (
    <section className="panel reveal">
      <header className="section-head">
        <p className="eyebrow">Sektoren</p>
        <h2>Sektor-Momentum — wer führt gerade?</h2>
        <p className="section-sub">
          Trailing-Renditen der 11 US-Sektor-ETFs, sortiert nach dem 12M/6M-Blend — exakt das
          Ranking-Signal der Sektor-Rotation. Beschreibung der Lage, keine Kaufempfehlung.
        </p>
      </header>
      {!data.available ? (
        <p className="state">Noch kein Kurs-Panel vorhanden. {data.hint}</p>
      ) : (
        <div className="table-scroll">
          <table className="history compare">
            <thead>
              <tr>
                <th>Sektor</th>
                {WINDOWS.map((w) => (
                  <th className="num" key={w.key}>
                    {w.label}
                  </th>
                ))}
                <th className="num">Blend (12M/6M)</th>
              </tr>
            </thead>
            <tbody>
              {data.sectors.map((row) => (
                <tr key={row.ticker}>
                  <td>
                    {row.sector} <span className="nobr">({row.ticker})</span>
                  </td>
                  {WINDOWS.map((w) => (
                    <ReturnCell key={w.key} value={row.returns[w.key]} />
                  ))}
                  <ReturnCell value={row.blend} />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
