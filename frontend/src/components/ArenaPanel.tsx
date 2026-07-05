import { useEffect, useState } from "react";

import { fetchArena, type ArenaResponse, type Lane, type LanePosition, type LaneTrade } from "../api";
import { eur, num, pct } from "../format";
import { EquityChart, type ChartSeries } from "./EquityChart";
import { StatTile } from "./StatTile";

// Lane id → German label + race color (nico = violet, autopilot = phosphor accent).
const LANE_LABELS: Record<string, string> = { nico: "Du", autopilot: "Autopilot" };
const LANE_COLORS: Record<string, string> = { nico: "var(--violet)", autopilot: "var(--accent)" };

function laneLabel(lane: string): string {
  return LANE_LABELS[lane] ?? lane;
}

// ISO timestamp → compact "YYYY-MM-DD" (trades/positions only need the day).
function formatDay(iso: string): string {
  return iso.slice(0, 10);
}

function PositionRow({ pos }: { pos: LanePosition }) {
  const unreal = pos.last_price !== null && pos.cost_basis ? pos.last_price / pos.cost_basis - 1 : null;
  return (
    <div className="arena-pos-row">
      <span className="ticker">{pos.ticker}</span>
      <span className="num tnum">{num(pos.shares, 2)}</span>
      <span className="num tnum">{num(pos.cost_basis, 2)}</span>
      <span className="num tnum">{pos.last_price !== null ? num(pos.last_price, 2) : "—"}</span>
      <span className={unreal === null ? "num tnum" : unreal >= 0 ? "num tnum pos" : "num tnum neg"}>
        {unreal !== null ? pct(unreal) : "—"}
      </span>
    </div>
  );
}

function TradeRow({ trade }: { trade: LaneTrade }) {
  const isBuy = trade.side === "buy";
  return (
    <div className="arena-trade-row">
      <span className="arena-trade-date">{formatDay(trade.created_at)}</span>
      <span className={isBuy ? "arena-side buy" : "arena-side sell"}>
        {isBuy ? "Kauf" : "Verkauf"} {trade.ticker}
      </span>
      <span className="num tnum">{num(trade.shares, 2)}</span>
      <span className="num tnum">{num(trade.fill_price, 2)}</span>
      {trade.reason && <p className="arena-trade-reason">{trade.reason}</p>}
    </div>
  );
}

function LaneDetail({ lane }: { lane: Lane }) {
  // Newest trades first; ISO timestamps sort lexically. Show the most recent handful.
  const trades = [...lane.trades].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 6);

  return (
    <section className="strat-block arena-lane">
      <h3 className="block-title">
        <span>{laneLabel(lane.lane)}</span>
        <span className="tnum">{eur(lane.total_value)}</span>
      </h3>

      {lane.open_positions.length > 0 ? (
        <div className="arena-table">
          <div className="arena-pos-head">
            <span>Titel</span>
            <span className="num">Stück</span>
            <span className="num">Einstand</span>
            <span className="num">Kurs</span>
            <span className="num">G/V</span>
          </div>
          {lane.open_positions.map((pos) => (
            <PositionRow key={pos.ticker} pos={pos} />
          ))}
        </div>
      ) : (
        <p className="arena-empty">Keine offenen Positionen.</p>
      )}

      {trades.length > 0 && (
        <div className="arena-table arena-trades">
          <div className="arena-trade-head">
            <span>Datum</span>
            <span>Aktion</span>
            <span className="num">Stück</span>
            <span className="num">Kurs</span>
          </div>
          {trades.map((t) => (
            <TradeRow key={t.id} trade={t} />
          ))}
        </div>
      )}
    </section>
  );
}

export function ArenaPanel() {
  const [data, setData] = useState<ArenaResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // `ignore` guards against a setState after the effect is torn down (unmount / refire).
    let ignore = false;
    fetchArena()
      .then((r) => {
        if (!ignore) setData(r);
      })
      .catch((e: unknown) => {
        if (!ignore) setError(String(e));
      });
    return () => {
      ignore = true;
    };
  }, []);

  if (error) return <p className="state err">Fehler: {error}</p>;
  if (!data) return <p className="state">Lädt…</p>;

  const lanes = data.lanes;
  if (!data.available || lanes.length === 0) {
    return (
      <>
        <header className="section-head reveal">
          <p className="eyebrow">Arena</p>
          <h1>Du vs. Autopilot vs. Markt</h1>
        </header>
        <p className="state">
          Arena noch leer — <code>run_lanes.py</code> ausführen.
        </p>
      </>
    );
  }

  // Normalize every curve to its starting capital → all lines start at 1× (a fair race).
  const laneSeries: ChartSeries[] = lanes.map((l) => ({
    label: laneLabel(l.lane),
    points: l.equity_curve.map(([d, v]) => [d, l.initial_capital ? v / l.initial_capital : v] as [string, number]),
    color: LANE_COLORS[l.lane] ?? "var(--text)",
  }));

  // SPY is the benchmark_value column — identical basis for every lane, so render it once.
  const spyLane = lanes.find((l) => l.equity_curve.length > 0);
  const series: ChartSeries[] = spyLane
    ? [
        ...laneSeries,
        {
          label: "Markt",
          points: spyLane.equity_curve.map(
            ([d, , b]) => [d, spyLane.initial_capital ? b / spyLane.initial_capital : b] as [string, number],
          ),
          color: "var(--text-muted)",
          dashed: true,
        },
      ]
    : laneSeries;

  const hasCurve = series.some((s) => s.points.length >= 2);
  const benchmarkReturn = lanes[0].benchmark_return;

  return (
    <>
      <header className="section-head reveal">
        <p className="eyebrow">Arena</p>
        <h1>Du vs. Autopilot vs. Markt</h1>
        <p className="section-sub">
          Zwei Papier-Depots im Rennen gegen den Markt (SPY), normiert auf den Start. Kein realer
          Handel, keine Anlageberatung.
        </p>
      </header>

      <div className="kpi-row">
        {lanes.map((l) => (
          <StatTile
            key={l.lane}
            label={laneLabel(l.lane)}
            value={eur(l.total_value)}
            sub={`Rendite ${pct(l.total_return)} · ${l.open_positions.length} ${
              l.open_positions.length === 1 ? "Position" : "Positionen"
            }`}
          />
        ))}
        <StatTile label="Markt (SPY)" value={pct(benchmarkReturn)} sub="Buy & Hold, gleiche Basis" />
      </div>

      {hasCurve ? (
        <EquityChart
          series={series}
          ariaLabel="Wertentwicklung im Vergleich: Du gegen Autopilot gegen den Markt (SPY), normiert auf Start = 1×."
        />
      ) : (
        <p className="state">Noch keine Wertverläufe — mindestens zwei Bewertungen nötig.</p>
      )}

      <div className="arena-lanes">
        {lanes.map((l) => (
          <LaneDetail key={l.lane} lane={l} />
        ))}
      </div>

      {/* Task 7 will formalize this as <DisclaimerBar/>; kept inline so the surface stays honest standalone. */}
      <p className="surface-disclaimer">{data.disclaimer}</p>
    </>
  );
}
