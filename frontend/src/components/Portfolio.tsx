import type { PortfolioState } from "../api";
import { StatTile } from "./StatTile";

const money = (x: number) => x.toLocaleString("en-US", { maximumFractionDigits: 0 });
const signedPercent = (x: number) => `${x >= 0 ? "▲ +" : "▼ "}${(x * 100).toFixed(1)}%`;
const signClass = (x: number) => (x > 0 ? "pos" : x < 0 ? "neg" : "");

// Paper portfolio view: headline value + return vs benchmark, then open positions.
// Gain/loss is double-coded (colour + arrow + sign) so it reads without relying on colour alone.
export function Portfolio({ data }: { data: PortfolioState }) {
  if (!data.exists) {
    return (
      <p className="muted">
        No paper portfolio yet — run <code>scripts/run_paper.py</code> to start forward-tracking the
        picks with demo money.
      </p>
    );
  }

  const latest = data.valuations.at(-1);
  const totalReturn = latest?.total_return ?? 0;
  const benchmarkReturn = latest?.benchmark_return ?? 0;
  const totalValue = latest?.total_value ?? data.initial_capital ?? 0;

  return (
    <>
      <div className="kpi-row">
        <StatTile label="Total value" value={money(totalValue)} sub="paper, mark-to-market" />
        <div className="tile">
          <div className="label">Total return</div>
          <div className={`value tnum ${signClass(totalReturn)}`}>{signedPercent(totalReturn)}</div>
          <div className="sub">
            benchmark ({data.benchmark_ticker}) {signedPercent(benchmarkReturn)}
          </div>
        </div>
        <StatTile
          label="Open positions"
          value={String(latest?.open_positions ?? data.positions.length)}
          sub="buy-and-hold"
        />
        <StatTile label="Cash" value={money(data.cash ?? 0)} sub="uninvested" />
      </div>

      {data.positions.length > 0 && (
        <table className="history">
          <thead>
            <tr>
              <th>Ticker</th>
              <th>Region</th>
              <th>Shares</th>
              <th>Cost basis</th>
              <th>Opened</th>
            </tr>
          </thead>
          <tbody>
            {data.positions.map((p) => (
              <tr key={p.ticker}>
                <td>{p.ticker}</td>
                <td>{p.region}</td>
                <td className="num tnum">{p.shares.toFixed(2)}</td>
                <td className="num tnum">{p.cost_basis.toFixed(2)}</td>
                <td>{p.opened_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
