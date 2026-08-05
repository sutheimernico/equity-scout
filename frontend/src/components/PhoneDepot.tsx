import { useEffect, useState } from "react";

import {
  fetchAutodepot,
  fetchShortterm,
  type AutodepotResponse,
  type AutodepotTrade,
  type ShortTermLane,
  type ShortTermResponse,
} from "../api";
import { StockLogo } from "./StockLogo";

// The phone's answer to "what did my traders do?" (Nico 2026-08-05): what each trader
// holds right now and which trades got it there — long-term auto-depot and the short-term
// lanes on one screen. The desktop DepotsView keeps its seven tabs; six panels of
// paper-depot detail is a laptop layout, and hunting one number across tabs defeats a
// daily glance.
//
// The two traders are NOT symmetric and are not drawn as if they were: the auto-depot
// holds an ETF allocation and rebalances weights, the lanes hold single stocks with a
// quantity and an entry price. All of it is paper money.
//
// MUST stay equal to digest.MATERIAL_DELTA_WEIGHT (src/equity_scout/digest.py:34). A
// weight change below this is a rounding rebalance — live example GLD at 1.4e-05 = 1.40 $.
// The small ones stay reachable behind a toggle, because the digest's rule is that nothing
// leaves Telegram which the dashboard does not show.
const MATERIAL_DELTA_WEIGHT = 0.01;

function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  const p = value * 100;
  // de-DE, not toFixed: "+10.0 %" sat next to "10.065" (money's German thousands dot) in
  // the same row, so the two dots meant different things and neither was readable.
  const magnitude = Math.abs(p).toLocaleString("de-DE", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return `${p > 0 ? "+" : p < 0 ? "−" : ""}${magnitude}\u202F%`;
}

function money(value: number): string {
  return value.toLocaleString("de-DE", { maximumFractionDigits: 0 });
}

/** Share/coin quantity, readable at phone width.
 *
 * The books store exact fractional quantities, and printed raw they are 16-digit floats
 * ("BUSE 32.19510896380651", "BTC 0.038163611924095855") that push the price off the row
 * and force mid-token line breaks. Significant digits rather than a fixed number of
 * decimals, because one row can hold 2297 XRP and 0.038 BTC and both must stay compact.
 */
function qty(value: number): string {
  return value.toLocaleString("de-DE", { maximumSignificantDigits: 4 });
}

/** DD.MM. — on a phone row the day is what orients you, the year never changes mid-list. */
function dayOf(iso: string): string {
  const [, month, day] = iso.slice(0, 10).split("-");
  return month && day ? `${day}.${month}.` : "—";
}

export function PhoneDepot() {
  const [auto, setAuto] = useState<AutodepotResponse | null>(null);
  const [short, setShort] = useState<ShortTermResponse | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let ignore = false;
    Promise.all([fetchAutodepot(), fetchShortterm()])
      .then(([a, s]) => {
        if (!ignore) {
          setAuto(a);
          setShort(s);
        }
      })
      .catch(() => {
        if (!ignore) setFailed(true);
      });
    return () => {
      ignore = true;
    };
  }, []);

  if (failed) return <p className="brief-muted">Depot-Daten nicht erreichbar.</p>;
  if (!auto || !short) return <p className="brief-muted">lädt …</p>;

  const account = auto.available ? auto.account : undefined;
  const lanes = short.available ? short.lanes : [];

  return (
    <div className="phone-depot">
      <h3 className="brief-section-head">Langfrist · Auto-Depot</h3>
      {account ? (
        <>
          <div className="pd-kpis">
            <span>
              <b className="num">{money(account.equity)}</b>
              <small>Depotwert</small>
            </span>
            <span>
              <b className={account.total_return >= 0 ? "brief-good num" : "brief-warn num"}>
                {pct(account.total_return)}
              </b>
              <small>seit Start</small>
            </span>
            <span>
              <b className="num">{pct(account.benchmark_return)}</b>
              <small>{account.benchmark_ticker}</small>
            </span>
          </div>
          <p className="brief-muted pd-stamp">
            Stand {account.last_as_of ?? "—"}
            {auto.fill_convention ? ` · Fills ${auto.fill_convention}` : ""}
          </p>

          <h4 className="pd-sub">Aktuelle Aufteilung</h4>
          <Allocation weights={account.weights} equity={account.equity} />

          <h4 className="pd-sub">Letzte Umschichtungen</h4>
          <RebalanceList trades={auto.trades ?? []} />
        </>
      ) : (
        <p className="brief-muted">
          Noch kein Auto-Depot — der nächtliche Lauf hat es noch nicht angelegt.
        </p>
      )}

      <h3 className="brief-section-head">Kurzfrist · Arena-Lanes</h3>
      {lanes.length > 0 ? (
        lanes.map((lane) => <LaneCard key={lane.lane} lane={lane} />)
      ) : (
        <p className="brief-muted">Noch keine Lane-Bücher angelegt.</p>
      )}
    </div>
  );
}

/** The ETF allocation as a weight bar per holding — this IS the long-term "depot". */
function Allocation({
  weights,
  equity,
}: {
  weights: Record<string, number>;
  equity: number;
}) {
  const rows = Object.entries(weights)
    .filter(([, weight]) => Math.abs(weight) > 0)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  if (rows.length === 0) return <p className="brief-muted">Keine Allokation gebucht.</p>;
  const invested = rows.reduce((sum, [, weight]) => sum + weight, 0);
  const largest = Math.max(...rows.map(([, weight]) => Math.abs(weight)));

  return (
    <>
      <ul className="pd-alloc">
        {rows.map(([ticker, weight]) => (
          <li key={ticker}>
            <span className="pd-alloc-ticker">{ticker}</span>
            {/* Bars are scaled to the LARGEST holding, not to 100 %: at a 10 % maximum
                every bar would otherwise be a sliver and comparing them impossible. */}
            <span className="pd-alloc-bar" aria-hidden="true">
              <span style={{ width: `${(Math.abs(weight) / largest) * 100}%` }} />
            </span>
            <span className="num pd-alloc-num">{pct(weight)}</span>
            <span className="num brief-muted">{money(weight * equity)}</span>
          </li>
        ))}
      </ul>
      <p className="brief-muted pd-stamp">{pct(invested)} investiert · Rest Kasse</p>
    </>
  );
}

/** Depot rebalances: material ones named, rounding ones counted behind a toggle. */
function RebalanceList({ trades }: { trades: AutodepotTrade[] }) {
  const [showSmall, setShowSmall] = useState(false);
  if (trades.length === 0) return <p className="brief-muted">Noch keine Trades gebucht.</p>;

  const material = trades.filter((t) => Math.abs(t.delta_weight) >= MATERIAL_DELTA_WEIGHT);
  const small = trades.length - material.length;
  const shown = showSmall ? trades : material.slice(0, 8);

  return (
    <>
      {shown.length > 0 ? (
        <ul className="pd-trades">
          {shown.map((t, i) => (
            <li key={`${t.created_at}-${t.ticker}-${i}`}>
              <span className="pd-trade-day">{dayOf(t.created_at)}</span>
              <span
                className={
                  t.delta_weight >= 0 ? "pd-trade-side brief-good" : "pd-trade-side brief-warn"
                }
              >
                {t.delta_weight >= 0 ? "auf" : "ab"}
              </span>
              <span className="pd-trade-ticker">{t.ticker}</span>
              <span className="num">
                {pct(t.delta_weight)} · {money(t.notional)}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="brief-muted">
          Keine wesentliche Umschichtung — nur Rundungs-Rebalances.
        </p>
      )}
      {small > 0 && (
        <button className="pd-toggle" onClick={() => setShowSmall((s) => !s)}>
          {showSmall ? "kleine Rebalances ausblenden" : `+ ${small} kleine Rebalances zeigen`}
        </button>
      )}
    </>
  );
}

/** One short-term lane: return, the single stocks it holds, and its last trades. */
function LaneCard({ lane }: { lane: ShortTermLane }) {
  return (
    <div className="pd-lane">
      <div className="pd-lane-head">
        <b>{lane.lane}</b>
        <span className={lane.total_return >= 0 ? "brief-good num" : "brief-warn num"}>
          {pct(lane.total_return)}
        </span>
        <span className="brief-muted num">{money(lane.equity)}</span>
        {lane.promoted && <span className="pd-badge">handelt ein echtes Sleeve</span>}
      </div>
      {lane.open_positions.length > 0 ? (
        <ul className="pd-positions">
          {lane.open_positions.map((p) => (
            <li key={p.ticker}>
              <StockLogo ticker={p.ticker} name={p.ticker} />
              <span className="pd-trade-ticker">{p.ticker}</span>
              <span className="num">
                {qty(p.qty)} @ {p.entry_price.toFixed(2)}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="brief-muted">keine offene Position</p>
      )}
      {lane.recent_trades.length > 0 ? (
        <ul className="pd-trades">
          {lane.recent_trades.slice(0, 5).map((t, i) => (
            <li key={`${t.executed_at}-${t.ticker}-${i}`}>
              <span className="pd-trade-day">{dayOf(t.executed_at)}</span>
              <span
                className={
                  t.side.toLowerCase().startsWith("b")
                    ? "pd-trade-side brief-good"
                    : "pd-trade-side brief-warn"
                }
              >
                {t.side}
              </span>
              <span className="pd-trade-ticker">{t.ticker}</span>
              <span className="num">
                {qty(t.qty)} @ {t.price.toFixed(2)}
              </span>
              {t.realized_pnl !== null && (
                <span className={t.realized_pnl >= 0 ? "brief-good num" : "brief-warn num"}>
                  {t.realized_pnl >= 0 ? "+" : "−"}
                  {Math.abs(t.realized_pnl).toFixed(0)}
                </span>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="brief-muted">noch keine Trades</p>
      )}
    </div>
  );
}
