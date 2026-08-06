import { useEffect, useState } from "react";

import {
  fetchAutodepot,
  fetchShortterm,
  type AutodepotResponse,
  type AutodepotTrade,
  type ShortTermLane,
  type ShortTermPosition,
  type ShortTermResponse,
  type ShortTermTrade,
} from "../api";
import { ETF_NOTES, rowName } from "../etfs";
import { StockLogo } from "./StockLogo";

// The phone's answer to "what did my traders do?" — one switch at the top between the two
// books, because they answer different questions and stacking both turned the screen into
// a scroll (Nico 2026-08-06: "bei Depot sollst Du irgendwie oben einen Switch haben
// zwischen Long Term und Day Trader").
//
// English names at Nico's request ("das kannst Du gern auf Englisch schreiben … Langfrist
// klingt scheiße"); the rest of the UI stays German.
//
// The two books are NOT symmetric and are not drawn as if they were: Long Term holds an
// ETF allocation and rebalances weights; Day Trader holds single stocks with an entry
// price and exit rules. All of it is paper money.

// MUST stay equal to digest.MATERIAL_DELTA_WEIGHT (src/equity_scout/digest.py:34).
const MATERIAL_DELTA_WEIGHT = 0.01;

type Book = "long" | "day";

function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  const p = value * 100;
  const magnitude = Math.abs(p).toLocaleString("de-DE", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return `${p > 0 ? "+" : p < 0 ? "−" : ""}${magnitude} %`;
}

function money(value: number, digits = 0): string {
  return value.toLocaleString("de-DE", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** Significant digits: one list can hold 2297 XRP and 0.038 BTC, and the raw book values
 *  are 16-digit floats that push the price out of the row. */
function qty(value: number): string {
  return value.toLocaleString("de-DE", { maximumSignificantDigits: 4 });
}

function dayOf(iso: string): string {
  const [, month, day] = iso.slice(0, 10).split("-");
  return month && day ? `${day}.${month}.` : "—";
}

function toneOf(value: number | null | undefined): string {
  if (value === null || value === undefined) return "";
  return value >= 0 ? "brief-good" : "brief-warn";
}

export function PhoneDepot() {
  const [book, setBook] = useState<Book>("long");
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

  return (
    <div className="phone-depot">
      <div className="pd-switch" role="tablist" aria-label="Depot">
        <button
          role="tab"
          aria-selected={book === "long"}
          className={book === "long" ? "pd-switch-btn active" : "pd-switch-btn"}
          onClick={() => setBook("long")}
        >
          Long Term
        </button>
        <button
          role="tab"
          aria-selected={book === "day"}
          className={book === "day" ? "pd-switch-btn active" : "pd-switch-btn"}
          onClick={() => setBook("day")}
        >
          Day Trader
        </button>
      </div>

      {book === "long" ? <LongTerm auto={auto} /> : <DayTrader lanes={short.lanes ?? []} />}
    </div>
  );
}

function LongTerm({ auto }: { auto: AutodepotResponse }) {
  const account = auto.available ? auto.account : undefined;
  if (!account) {
    return (
      <p className="brief-muted">
        Noch kein Long-Term-Depot — der nächtliche Lauf hat es noch nicht angelegt.
      </p>
    );
  }
  return (
    <>
      <div className="pd-kpis">
        <span>
          <b>{money(account.equity)}</b>
          <small>Depotwert</small>
        </span>
        <span>
          <b className={toneOf(account.total_return)}>{pct(account.total_return)}</b>
          <small>seit Start</small>
        </span>
        <span>
          <b>{pct(account.benchmark_return)}</b>
          <small>{account.benchmark_ticker}</small>
        </span>
      </div>
      <p className="brief-muted pd-stamp">
        Stand {account.last_as_of ?? "—"}
        {auto.fill_convention ? ` · Fills ${auto.fill_convention}` : ""}
      </p>

      <h4 className="pd-sub">Aufteilung</h4>
      <Allocation weights={account.weights} equity={account.equity} />

      <h4 className="pd-sub">Letzte Umschichtungen</h4>
      <RebalanceList trades={auto.trades ?? []} />
    </>
  );
}

function DayTrader({ lanes }: { lanes: ShortTermLane[] }) {
  if (lanes.length === 0) return <p className="brief-muted">Noch keine Lane-Bücher angelegt.</p>;
  return (
    <>
      {lanes.map((lane) => (
        <LaneCard key={lane.lane} lane={lane} />
      ))}
    </>
  );
}

/** The ETF allocation — the long-term book's "positions". Each holding is tappable,
 *  because a ticker like IEF says nothing about what is actually held. */
function Allocation({ weights, equity }: { weights: Record<string, number>; equity: number }) {
  const rows = Object.entries(weights)
    .filter(([, weight]) => Math.abs(weight) > 0)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  if (rows.length === 0) return <p className="brief-muted">Keine Allokation gebucht.</p>;
  const invested = rows.reduce((sum, [, weight]) => sum + weight, 0);
  const largest = Math.max(...rows.map(([, weight]) => Math.abs(weight)));

  return (
    <>
      <DonutChart rows={rows} cash={Math.max(0, 1 - invested)} />
      <ul className="pd-alloc">
        {rows.map(([ticker, weight]) => (
          <EtfRow key={ticker} ticker={ticker} weight={weight} equity={equity} largest={largest} />
        ))}
      </ul>
      <p className="brief-muted pd-stamp">{pct(invested)} investiert · Rest Kasse</p>
    </>
  );
}

function EtfRow({
  ticker,
  weight,
  equity,
  largest,
}: {
  ticker: string;
  weight: number;
  equity: number;
  largest: number;
}) {
  const [open, setOpen] = useState(false);
  const note = ETF_NOTES[ticker];
  const inlineName = rowName(ticker, weight);
  return (
    <li className="pd-alloc-row">
      <button className="pd-alloc-main" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="pd-alloc-line">
          <span className="pd-alloc-ticker">{ticker}</span>
          <span className="pd-alloc-bar" aria-hidden="true">
            <span style={{ width: `${(Math.abs(weight) / largest) * 100}%` }} />
          </span>
          <span className="num pd-alloc-num">{pct(weight)}</span>
          <span className="num brief-muted">{money(weight * equity)}</span>
        </span>
        {inlineName && <span className="pd-alloc-name">{inlineName}</span>}
      </button>
      {open && (
        <p className="pd-alloc-note">
          {note ? (
            // The name is only repeated when the row does not already carry it.
            <>
              {!inlineName && <b>{note.name} — </b>}
              {note.what}
            </>
          ) : (
            "Für diesen Ticker ist keine Kurzbeschreibung hinterlegt."
          )}
        </p>
      )}
    </li>
  );
}

/** Allocation as a donut: "how is the whole divided" is what a ring answers at a glance,
 *  which a bar list does not. The list stays below — it carries the exact numbers. */
function DonutChart({ rows, cash }: { rows: [string, number][]; cash: number }) {
  const segments: [string, number][] = cash > 0.001 ? [...rows, ["Kasse", cash]] : rows;
  const total = segments.reduce((sum, [, w]) => sum + Math.abs(w), 0);
  if (total <= 0) return null;

  const R = 42;
  const C = 2 * Math.PI * R;
  let offset = 0;
  return (
    <svg className="pd-donut" viewBox="0 0 100 100" aria-hidden="true">
      {segments.map(([ticker, weight], i) => {
        const share = Math.abs(weight) / total;
        // A gap in the surface colour separates neighbours — never a stroke border.
        const dash = Math.max(0, share * C - 1.5);
        const element = (
          <circle
            key={ticker}
            className={ticker === "Kasse" ? "pd-donut-cash" : "pd-donut-seg"}
            cx="50"
            cy="50"
            r={R}
            fill="none"
            strokeWidth="11"
            strokeDasharray={`${dash} ${C - dash}`}
            strokeDashoffset={-offset}
            // One hue, stepped down the ring: eleven categorical colours would fight the
            // status palette, and the ordering here is by size, so a ramp is honest.
            style={{ opacity: ticker === "Kasse" ? 0.35 : 1 - Math.min(i, 9) * 0.07 }}
          />
        );
        offset += share * C;
        return element;
      })}
    </svg>
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
        <p className="brief-muted">Keine wesentliche Umschichtung — nur Rundungs-Rebalances.</p>
      )}
      {small > 0 && (
        <button className="pd-toggle" onClick={() => setShowSmall((s) => !s)}>
          {showSmall ? "kleine Rebalances ausblenden" : `+ ${small} kleine Rebalances zeigen`}
        </button>
      )}
    </>
  );
}

/** One day-trading lane, split the way the question is actually asked (Nico 2026-08-06):
 *  what is still running and how it stands, then what is finished and what it made. */
function LaneCard({ lane }: { lane: ShortTermLane }) {
  const closed = (lane.recent_trades ?? []).filter(
    (t) => t.realized_pnl !== null && t.realized_pnl !== undefined,
  );
  const realised = closed.reduce((sum, t) => sum + (t.realized_pnl ?? 0), 0);

  return (
    <div className="pd-lane">
      <div className="pd-lane-head">
        <b>{lane.lane}</b>
        <span className={`${toneOf(lane.total_return)} num`}>{pct(lane.total_return)}</span>
        <span className="brief-muted num">{money(lane.equity)}</span>
        {lane.promoted && <span className="pd-badge">handelt ein echtes Sleeve</span>}
      </div>

      <h5 className="pd-group">Läuft noch</h5>
      {lane.open_positions.length > 0 ? (
        <ul className="pd-positions">
          {lane.open_positions.map((p) => (
            <OpenPosition key={p.ticker} position={p} />
          ))}
        </ul>
      ) : (
        <p className="brief-muted">keine offene Position</p>
      )}

      <h5 className="pd-group">
        Abgeschlossen
        {closed.length > 0 && (
          <span className={`${toneOf(realised)} pd-group-sum`}>
            {realised >= 0 ? "+" : "−"}
            {money(Math.abs(realised))}
          </span>
        )}
      </h5>
      {closed.length > 0 ? (
        <ul className="pd-trades">
          {closed.slice(0, 6).map((t, i) => (
            <ClosedTrade key={`${t.executed_at}-${t.ticker}-${i}`} trade={t} />
          ))}
        </ul>
      ) : (
        <p className="brief-muted">noch nichts realisiert</p>
      )}
    </div>
  );
}

/** An open position: where it stands now, and one tap for the rules that will close it. */
function OpenPosition({ position }: { position: ShortTermPosition }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="pd-position">
      <button
        className="pd-position-main"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <StockLogo ticker={position.ticker} name={position.ticker} />
        <span className="pd-position-body">
          <span className="pd-trade-ticker">{position.ticker}</span>
          <span className="brief-muted pd-position-sub">
            {qty(position.qty)} seit {dayOf(position.opened_at)} @{" "}
            {money(position.entry_price, 2)}
          </span>
        </span>
        <span className={`${toneOf(position.unrealized_pct)} num pd-position-pnl`}>
          {position.unrealized_pct === null ? "—" : pct(position.unrealized_pct)}
        </span>
      </button>
      {open && (
        <div className="pd-position-detail">
          <dl>
            <dt>Aktueller Kurs</dt>
            <dd className="num">
              {position.last_price === null
                ? "— kein Stand gespeichert"
                : money(position.last_price, 2)}
            </dd>
            <dt>Verkauf bei</dt>
            <dd className="num">
              {position.target_price === null
                ? "— kein fester Zielkurs"
                : money(position.target_price, 2)}
            </dd>
            <dt>Verlust ab</dt>
            <dd className="num">
              {position.stop_price === null
                ? "— kein fester Stopkurs"
                : money(position.stop_price, 2)}
            </dd>
            {position.max_hold_days !== null && (
              <>
                <dt>Spätestens nach</dt>
                <dd>{position.max_hold_days} Tagen</dd>
              </>
            )}
          </dl>
          <p className="brief-muted pd-rule">{position.rule}</p>
        </div>
      )}
    </li>
  );
}

function ClosedTrade({ trade }: { trade: ShortTermTrade }) {
  const pnl = trade.realized_pnl ?? 0;
  return (
    <li>
      <span className="pd-trade-day">{dayOf(trade.executed_at)}</span>
      <span className="pd-trade-ticker">{trade.ticker}</span>
      <span className="num brief-muted">
        {qty(trade.qty)} @ {money(trade.price, 2)}
      </span>
      <span className={`${toneOf(pnl)} num pd-position-pnl`}>
        {pnl >= 0 ? "+" : "−"}
        {money(Math.abs(pnl))}
      </span>
    </li>
  );
}
