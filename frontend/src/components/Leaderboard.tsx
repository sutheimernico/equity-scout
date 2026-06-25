import { type ResearchConfig } from "../api";
import { num, pct, researchConfigLabel } from "../format";

// Top configurations by Deflated Sharpe — the leaderboard the loop keeps updating.
export function Leaderboard({ rows }: { rows: ResearchConfig[] }) {
  return (
    <section className="strat-block reveal">
      <h3 className="block-title">Bestenliste</h3>
      <div className="table-scroll">
        <table className="history compare">
          <thead>
            <tr>
              <th>#</th>
              <th>Konfiguration</th>
              <th className="num">DSR</th>
              <th className="num">Sharpe</th>
              <th className="num">Rendite p.a.</th>
              <th className="num">Max. Verlust</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c, i) => (
              <tr key={i}>
                <td className="tnum">{i + 1}</td>
                <td>{researchConfigLabel(c)}</td>
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
  );
}
