import { useMemo, useState } from "react";

import { Disclosure } from "./ui/Disclosure";

// The data-completeness gate is mandatory honesty: thin/invalid-data names are dropped before ranking,
// never scored as noise. This view makes that visible — which tickers were excluded, and why.
export function GatedOutList({
  gatedOut,
  byRegion,
}: {
  gatedOut: Record<string, string>;
  byRegion: Record<string, number>;
}) {
  const [reason, setReason] = useState("all");

  const entries = useMemo(
    () => Object.entries(gatedOut).sort(([a], [b]) => a.localeCompare(b)),
    [gatedOut],
  );
  const reasons = useMemo(
    () => ["all", ...Array.from(new Set(entries.map(([, r]) => r))).sort()],
    [entries],
  );
  const visible = reason === "all" ? entries : entries.filter(([, r]) => r === reason);

  if (entries.length === 0) return null;

  const regionSummary = Object.entries(byRegion).sort(([a], [b]) => a.localeCompare(b));

  return (
    <Disclosure summary={`Aussortiert (${entries.length}) — Daten-Vollständigkeits-Gate`}>
      <p>
        Diese Titel haben das <strong>Daten-Vollständigkeits-Gate</strong> nicht bestanden und wurden{" "}
        <em>vor</em> dem Ranking entfernt — dünne oder ungültige Daten werden nicht als Rauschen
        bewertet. {regionSummary.length > 0 && (
          <>Pro Region: {regionSummary.map(([r, n]) => `${r} ${n}`).join(", ")}.</>
        )}
      </p>

      <div className="filter gated-filter">
        <select className="region" value={reason} onChange={(e) => setReason(e.target.value)}>
          {reasons.map((r) => (
            <option key={r} value={r}>
              {r === "all" ? "Alle Gründe" : r}
            </option>
          ))}
        </select>
      </div>

      <div className="table-scroll">
        <table className="history">
          <thead>
            <tr>
              <th>Ticker</th>
              <th>Grund</th>
            </tr>
          </thead>
          <tbody>
            {visible.map(([ticker, why]) => (
              <tr key={ticker}>
                <td className="tnum">{ticker}</td>
                <td>{why}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Disclosure>
  );
}
