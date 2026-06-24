import type { RunSummary } from "../api";

export function RunHistory({ runs }: { runs: RunSummary[] }) {
  if (runs.length === 0) return <p className="muted">Noch keine Läufe.</p>;
  return (
    <table className="history">
      <thead>
        <tr>
          <th>Lauf</th>
          <th>Universum</th>
          <th>Aussortiert</th>
          <th>Picks je Bucket</th>
        </tr>
      </thead>
      <tbody>
        {runs.map((run, index) => (
          <tr key={index}>
            <td>{run.created_at}</td>
            <td className="num tnum">{run.universe_size}</td>
            <td className="num tnum">{run.total_gated}</td>
            <td>
              {Object.entries(run.picks)
                .map(([bucket, tickers]) => `${bucket} ${tickers.length}`)
                .join(" · ")}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
