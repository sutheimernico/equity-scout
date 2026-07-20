import { useEffect, useState } from "react";

import { fetchShortterm, type ShortTermLane, type ShortTermResponse } from "../api";
import { num, pct } from "../format";
import { Chip } from "./ui/Chip";
import { Explain } from "./ui/Explain";

const LANE_LABEL: Record<string, string> = {
  swing: "Event-Swing (1–5 Tage)",
  session: "Intraday-Session (ORB)",
  crypto: "Crypto-Daytrader (Donchian)",
};

const LANE_NOTE: Record<string, string> = {
  swing: "Kauft bullishe Earnings-Events zum Schlusskurs, Ziel +5 % / Stop −3 % / max. ~5 Handelstage.",
  session:
    "Opening-Range-Breakout auf ~15 Min. VERZÖGERTEN Kursen (Settled-Bar-Modell), nie über Nacht.",
  crypto: "Donchian-20-Ausbruch auf Kraken-ECHTZEIT-Bars, 24/7 — Benchmark ist BTC halten, nicht Cash.",
};

function LaneCard({ lane }: { lane: ShortTermLane }) {
  const lead =
    lane.benchmark_return !== null ? lane.total_return - lane.benchmark_return : null;
  return (
    <section className="strat-block">
      <div className="chip-row" style={{ marginBottom: "var(--space-3)" }}>
        <Chip>
          <b>{LANE_LABEL[lane.lane] ?? lane.lane}</b>
        </Chip>
        <Chip>Equity {num(lane.equity, 0)}</Chip>
        <Chip>{lane.open_positions.length} offen</Chip>
      </div>
      <Explain tone="hint">{LANE_NOTE[lane.lane]}</Explain>

      <table className="history">
        <thead>
          <tr>
            <th>Rendite</th>
            <th>Benchmark ({lane.benchmark_ticker})</th>
            <th>Vorsprung</th>
            <th>Max. Drawdown</th>
            <th>Trades</th>
            <th>Trefferquote</th>
            <th>Kosten</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>{pct(lane.total_return)}</td>
            <td>{lane.benchmark_return === null ? "—" : pct(lane.benchmark_return)}</td>
            <td>{lead === null ? "—" : pct(lead)}</td>
            <td>{pct(lane.max_drawdown)}</td>
            <td>{lane.stats.n_trades}</td>
            <td>{lane.stats.win_rate === null ? "—" : pct(lane.stats.win_rate, 0)}</td>
            <td>{num(lane.stats.fees_paid, 2)}</td>
          </tr>
        </tbody>
      </table>

      {lane.open_positions.length > 0 && (
        <p>
          Offen:{" "}
          {lane.open_positions
            .map((p) => `${p.ticker} (${num(p.qty, 4)} @ ${num(p.entry_price, 2)})`)
            .join(" · ")}
        </p>
      )}
      {lane.recent_trades.length > 0 && (
        <details>
          <summary>Letzte Trades ({lane.recent_trades.length})</summary>
          <table className="history">
            <thead>
              <tr>
                <th>Zeit</th>
                <th>Trade</th>
                <th>Preis</th>
                <th>Grund</th>
                <th>P&L</th>
              </tr>
            </thead>
            <tbody>
              {lane.recent_trades.map((t, i) => (
                <tr key={`${t.executed_at}-${t.ticker}-${t.side}-${i}`}>
                  <td>{t.executed_at.slice(0, 16).replace("T", " ")}</td>
                  <td>
                    {t.side === "buy" ? "↑" : "↓"} {t.ticker}
                  </td>
                  <td>{num(t.price, 2)}</td>
                  <td>{t.reason}</td>
                  <td>{t.realized_pnl === null ? "—" : num(t.realized_pnl, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </section>
  );
}

export function KurzfristArenaPanel() {
  const [data, setData] = useState<ShortTermResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchShortterm()
      .then(setData)
      .catch((e: unknown) => setError(String(e)));
  }, []);

  if (error) return <p className="state err">Fehler: {error}</p>;
  if (!data) return <p className="state">Lädt…</p>;

  return (
    <>
      <Explain>
        Drei Kurzfrist-Ansätze treten mit je 10.000 USD Spielgeld gegeneinander an — die Arena{" "}
        <strong>misst</strong>, welcher seine Kosten überlebt. Ehrliche Erwartung aus der
        Forschung: Kurzfrist-Trading verliert im Retail-Rahmen nach Kosten meistens. Alle Lanes
        long-only, alle Fills mit Slippage; die Session-Lane rechnet zusätzlich mit einem
        Verzögerungs-Modell für die ~15 Min. alten Gratis-Kurse.
      </Explain>

      {!data.available || data.lanes.length === 0 ? (
        <section className="strat-block">
          <h3 className="block-title">Noch keine Lane gestartet</h3>
          <Explain tone="hint">
            Die Lanes starten mit ihren Cron-Läufen (crypto: alle 15 Min.; session: im
            US-Marktfenster; swing: nächtlich) — oder per Hand:
          </Explain>
          <p>
            <code>uv run python scripts/run_shortterm.py --lane crypto</code>
          </p>
        </section>
      ) : (
        data.lanes.map((lane) => <LaneCard key={lane.lane} lane={lane} />)
      )}

      <p className="state">{data.disclaimer}</p>
    </>
  );
}
