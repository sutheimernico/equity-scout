import type { PortfolioState } from "../api";
import { StockChart } from "./StockChart";
import { PieChart, type PieSlice } from "./ui/PieChart";
import { StatTile } from "./StatTile";

const euro = (x: number) => `${x.toLocaleString("de-DE", { maximumFractionDigits: 0 })} €`;
const signedPercent = (x: number) => `${x >= 0 ? "▲ +" : "▼ "}${(x * 100).toFixed(1)} %`;
const signClass = (x: number) => (x > 0 ? "pos" : x < 0 ? "neg" : "");

// Demo-Depot: Kennzahlen oben, dann eine kurze Erklärung, wie gekauft wird, dann die Positionen
// mit Gewinn/Verlust pro Aktie. Gewinn/Verlust ist doppelt kodiert (Farbe + Pfeil + Vorzeichen).
export function Portfolio({ data }: { data: PortfolioState }) {
  if (!data.exists) {
    return (
      <p className="muted">
        Noch kein Demo-Depot — führe <code>scripts/run_paper.py</code> aus, um die Picks mit
        Spielgeld zu verfolgen.
      </p>
    );
  }

  const latest = data.valuations.at(-1);
  const totalReturn = latest?.total_return ?? 0;
  const benchmarkReturn = latest?.benchmark_return ?? 0;
  const totalValue = latest?.total_value ?? data.initial_capital ?? 0;

  const slices: PieSlice[] = data.positions.map((p) => ({
    label: p.ticker,
    value: p.market_value,
    info: `${p.name} · ${signedPercent(p.pnl_pct)}`,
  }));
  if ((data.cash ?? 0) > 0) slices.push({ label: "Cash", value: data.cash ?? 0, info: "nicht investiert" });

  return (
    <>
      <p className="explain">
        So kauft der Bot: 100.000 € Spielgeld, je <strong>5.000 € pro Aktie</strong>{" "}
        (gleichgewichtet) in jede mit <strong>Score ≥ 70</strong>, dann Buy-and-Hold. Keine echten
        Orders — das Depot misst über Zeit, ob die Picks aufgehen, gemessen am Benchmark{" "}
        {data.benchmark_ticker}.
      </p>

      <div className="kpi-row">
        <StatTile label="Gesamtwert" value={euro(totalValue)} sub="Spielgeld, letzter Kurs" />
        <div className="tile">
          <div className="label">Rendite</div>
          <div className={`value tnum ${signClass(totalReturn)}`}>{signedPercent(totalReturn)}</div>
          <div className="sub">
            Benchmark ({data.benchmark_ticker}) {signedPercent(benchmarkReturn)}
          </div>
        </div>
        <StatTile
          label="Positionen"
          value={String(latest?.open_positions ?? data.positions.length)}
          sub="Buy-and-Hold"
        />
        <StatTile label="Cash" value={euro(data.cash ?? 0)} sub="nicht investiert" />
      </div>

      {slices.length > 0 && (
        <section className="strat-block">
          <h3 className="block-title">Aufteilung des Depots</h3>
          <PieChart slices={slices} />
        </section>
      )}

      {data.positions.length > 0 && (
        <table className="history">
          <thead>
            <tr>
              <th>Aktie</th>
              <th>Region</th>
              <th>Investiert</th>
              <th>Akt. Wert</th>
              <th>Gewinn/Verlust</th>
              <th>Gekauft</th>
            </tr>
          </thead>
          <tbody>
            {data.positions.map((p) => (
              <tr key={p.ticker}>
                <td>
                  <strong>{p.ticker}</strong>
                </td>
                <td>{p.region}</td>
                <td className="num tnum">{euro(p.invested)}</td>
                <td className="num tnum">{euro(p.market_value)}</td>
                <td className={`num tnum ${signClass(p.pnl)}`}>{signedPercent(p.pnl_pct)}</td>
                <td>{p.opened_at.slice(0, 10)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {data.positions.length > 0 && (
        <section className="strat-block">
          <h3 className="block-title">Kurs-Charts (1 Jahr)</h3>
          <div className="chart-grid">
            {data.positions.map((p) => (
              <StockChart key={p.ticker} ticker={p.ticker} />
            ))}
          </div>
        </section>
      )}
    </>
  );
}
