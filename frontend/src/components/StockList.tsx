import { type WatchlistEntry } from "../api";
import { shortCompanyName } from "../company";
import { StockLogo } from "./StockLogo";

// What the funnel currently ranks highest — the answer to "which companies are we talking
// about", which bare tickers (9064.T, PETR4.SA) never gave. In-zone names first: those are
// the ones where the entry rule says the price is where it should be; within a group the
// higher score wins. Deliberately NOT "hot stocks": this is a value/quality ranking, not a
// momentum or hype list.
function rank(a: WatchlistEntry, b: WatchlistEntry): number {
  if (a.in_zone !== b.in_zone) return a.in_zone ? -1 : 1;
  return b.composite - a.composite;
}

export function StockList({
  entries,
  limit = 5,
  onOpen,
}: {
  entries: WatchlistEntry[];
  limit?: number;
  onOpen?: () => void;
}) {
  const shown = [...entries].sort(rank).slice(0, limit);
  if (shown.length === 0) {
    return <p className="stock-empty">Noch keine Watchlist — der Screener lief noch nicht.</p>;
  }

  return (
    <ul className="stock-list">
      {shown.map((entry) => {
        const score = Math.round(entry.composite * 100);
        return (
          <li key={entry.ticker} className="stock-row">
            <StockLogo ticker={entry.ticker} name={entry.name} />
            <span className="stock-ident">
              {/* title carries the full legal name that the display form trims away. */}
              <span className="stock-name" title={entry.name}>
                {shortCompanyName(entry.name)}
              </span>
              <span className="stock-ticker">{entry.ticker}</span>
            </span>
            <span className="stock-figures">
              <span className="stock-score num">{score}</span>
              <span className="stock-price num">{entry.price.toFixed(2)}</span>
            </span>
            {entry.in_zone && <span className="stock-zone">in Zone</span>}
          </li>
        );
      })}
      {onOpen && (
        <li>
          <button className="stock-more" onClick={onOpen}>
            Alle {entries.length} im Radar →
          </button>
        </li>
      )}
    </ul>
  );
}
