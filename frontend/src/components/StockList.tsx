import { useEffect, useState } from "react";

import { fetchBriefs, type StockBrief } from "../api";
import { shortCompanyName } from "../company";
import { StockLogo } from "./StockLogo";
import { ZoneBar } from "./ZoneBar";

// Answers the four questions Nico actually has when looking at a stock (2026-08-04:
// "man checkt nichts da"): which company is this, would this be a good price, are we in
// that range right now, and what would the exit be worth. Everything else (sector, KGV,
// score band, zone bounds) is second-level detail behind the row.
//
// Deliberately NOT a "hot stocks" list: the ranking is value/quality from the funnel, not
// momentum or hype, and the target is third-party analyst consensus — never our own
// forecast (the project makes no price promises).

function money(value: number, currency: string | null): string {
  // de-DE grouping so 1915.5 reads as 1.915,50 next to German labels. The currency code
  // stays as a code (JPY/USD) rather than a symbol: mixing $ and ¥ glyphs at this size is
  // harder to tell apart than three letters.
  const formatted = value.toLocaleString("de-DE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return currency ? `${formatted} ${currency}` : formatted;
}

function signedPct(value: number): string {
  const rounded = Math.round(value);
  return `${rounded > 0 ? "+" : rounded < 0 ? "−" : ""}${Math.abs(rounded)} %`;
}

function ZoneLine({ brief }: { brief: StockBrief }) {
  // The verdict already reads as plain German from the backend ("im Einstiegsbereich",
  // "59 % über der Zone — zu teuer"); colour only reinforces it.
  const cls = brief.in_zone ? "brief-zone brief-good" : "brief-zone brief-warn";
  return (
    <span className={cls}>
      {brief.in_zone ? "✓" : "⚠"} {brief.zone_verdict}
    </span>
  );
}

function UpsideLine({ brief }: { brief: StockBrief }) {
  if (brief.analyst_upside_pct === null || brief.analyst_target === null) {
    // Honest absence: small and non-US listings routinely have no analyst coverage.
    return <span className="brief-muted">Kursziel: keine Analystenschätzung</span>;
  }
  const up = brief.analyst_upside_pct >= 0;
  return (
    <span className={up ? "brief-good" : "brief-warn"}>
      {/* Same diamond as the marker in the bar — identity without a legend box. */}
      <span className="zonebar-key" aria-hidden="true" />
      Analysten-Ziel {money(brief.analyst_target, brief.currency)} ·{" "}
      {signedPct(brief.analyst_upside_pct)}
      <span className="brief-muted">
        {" "}
        ({brief.analyst_count} Schätzungen, fremde Meinung)
      </span>
    </span>
  );
}

function BriefRow({ brief }: { brief: StockBrief }) {
  const [open, setOpen] = useState(false);
  const business = [brief.sector, brief.industry].filter(Boolean).join(" · ");

  return (
    <li className="brief-row">
      <button
        className="brief-main"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <StockLogo ticker={brief.ticker} name={brief.name} />
        <span className="brief-body">
          <span className="brief-head">
            <span className="brief-name" title={brief.name}>
              {shortCompanyName(brief.name)}
            </span>
            <span className="brief-ticker">{brief.ticker}</span>
          </span>
          {business && <span className="brief-business">{business}</span>}
          <span className="brief-price num">{money(brief.price, brief.currency)}</span>
          <ZoneBar brief={brief} />
          <ZoneLine brief={brief} />
          <UpsideLine brief={brief} />
        </span>
      </button>
      {open && (
        <dl className="brief-detail">
          <dt>Guter Einstieg</dt>
          <dd className="num">
            {money(brief.zone_low, null)}–{money(brief.zone_high, brief.currency)}
          </dd>
          <dt>Einstiegs-Score</dt>
          <dd>
            {brief.score}/100 ({brief.score_band})
          </dd>
          <dt>KGV</dt>
          <dd className="num">
            {brief.trailing_pe === null ? "—" : brief.trailing_pe.toFixed(1)}
          </dd>
          <dt>Modell-Kursziel</dt>
          <dd>
            {brief.model_target === null
              ? "— kein trainiertes Modell"
              : money(brief.model_target, brief.currency)}
          </dd>
        </dl>
      )}
    </li>
  );
}

export function StockList({ limit = 5, onOpen }: { limit?: number; onOpen?: () => void }) {
  const [briefs, setBriefs] = useState<StockBrief[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let ignore = false;
    fetchBriefs(limit)
      .then((r) => {
        if (!ignore) setBriefs(r.briefs);
      })
      .catch(() => {
        if (!ignore) setFailed(true);
      });
    return () => {
      ignore = true;
    };
  }, [limit]);

  if (failed) return <p className="brief-muted">Aktien-Daten nicht erreichbar.</p>;
  if (briefs === null) return <p className="brief-muted">lädt …</p>;
  if (briefs.length === 0) {
    return <p className="brief-muted">Noch keine Watchlist — der Screener lief noch nicht.</p>;
  }

  return (
    <ul className="brief-list">
      {briefs.map((brief) => (
        <BriefRow key={brief.ticker} brief={brief} />
      ))}
      {onOpen && (
        <li>
          <button className="stock-more" onClick={onOpen}>
            Alle im Radar →
          </button>
        </li>
      )}
    </ul>
  );
}
