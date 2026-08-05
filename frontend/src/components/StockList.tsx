import { useEffect, useState } from "react";

import { fetchBriefs, type StockBrief } from "../api";
import { shortCompanyName } from "../company";
import { splitSections } from "../stocklist";
import { MiniYearChart } from "./MiniYearChart";
import { StockLogo } from "./StockLogo";
import { ZoneBar } from "./ZoneBar";

// Answers the questions Nico actually has on one daily look (2026-08-05: "auf den ersten
// Blick Potenzial plus dreißig Prozent"): which company is this, what is the potential,
// would this be a good price — then, one tap deeper, what would a good entry be, what do
// the numbers say, what happened over the year, and what is in the news.
//
// Deliberately NOT a "hot stocks" list: the ranking is value/quality from the funnel, and
// the potential is third-party analyst consensus — never our own forecast. The two
// sections keep those two things apart (see ../stocklist.ts).

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

/** The headline number. Big on purpose — it is the reason to look at all — but it is a
 *  third-party opinion, so the label under it says so instead of a legend elsewhere. */
function PotentialBlock({ brief }: { brief: StockBrief }) {
  if (brief.analyst_upside_pct === null || brief.analyst_target === null) {
    return (
      <span className="brief-potential brief-potential-none">
        <span className="brief-potential-num">—</span>
        <span className="brief-potential-label">keine Analystenschätzung</span>
      </span>
    );
  }
  const up = brief.analyst_upside_pct >= 0;
  return (
    <span className={up ? "brief-potential brief-good" : "brief-potential brief-warn"}>
      <span className="brief-potential-num num">{signedPct(brief.analyst_upside_pct)}</span>
      <span className="brief-potential-label">
        laut {brief.analyst_count ?? "?"} Analysten
      </span>
    </span>
  );
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

/** The two AI texts. Labelled as machine-written, because they are — and dated, because
 *  a summary of last week's headlines read as today's news would be misleading. */
function BriefInsight({ brief }: { brief: StockBrief }) {
  const insight = brief.insight;
  if (!insight) {
    return (
      <p className="brief-muted brief-insight">
        Noch keine KI-Zusammenfassung erzeugt (läuft im 18:00-Lauf).
      </p>
    );
  }
  const when = new Date(insight.generated_at).toLocaleDateString("de-DE", {
    day: "2-digit",
    month: "2-digit",
  });
  return (
    <div className="brief-insight">
      {insight.business && <p className="brief-insight-business">{insight.business}</p>}
      {insight.news_summary ? (
        <p className="brief-insight-news">📰 {insight.news_summary}</p>
      ) : (
        <p className="brief-muted">Keine aktuellen Schlagzeilen gefunden.</p>
      )}
      {insight.headlines.length > 0 && (
        <ul className="brief-headlines">
          {insight.headlines.map((title) => (
            <li key={title}>{title}</li>
          ))}
        </ul>
      )}
      <p className="brief-muted brief-insight-foot">
        KI-Zusammenfassung ({insight.model ?? "lokal"}) vom {when} — keine Empfehlung.
      </p>
    </div>
  );
}

function BriefRow({ brief }: { brief: StockBrief }) {
  const [open, setOpen] = useState(false);
  const business = [brief.sector, brief.industry].filter(Boolean).join(" · ");

  return (
    <li className="brief-row">
      <button className="brief-main" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <StockLogo ticker={brief.ticker} name={brief.name} />
        <span className="brief-body">
          <span className="brief-head">
            <span className="brief-name" title={brief.name}>
              {shortCompanyName(brief.name)}
            </span>
            <span className="brief-ticker">{brief.ticker}</span>
          </span>
          {business && <span className="brief-business">{business}</span>}
          <PotentialBlock brief={brief} />
          <span className="brief-price num">{money(brief.price, brief.currency)}</span>
          <ZoneBar brief={brief} />
          <ZoneLine brief={brief} />
        </span>
      </button>
      {open && (
        <div className="brief-detail-wrap">
          <MiniYearChart chart={brief.chart} currency={brief.currency} />
          <dl className="brief-detail">
            <dt>Guter Einstieg</dt>
            <dd className="num">
              {money(brief.zone_low, null)}–{money(brief.zone_high, brief.currency)}
            </dd>
            <dt>Analysten-Ziel</dt>
            <dd className="num">
              {brief.analyst_target === null
                ? "— keine Schätzung"
                : money(brief.analyst_target, brief.currency)}
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
          <BriefInsight brief={brief} />
        </div>
      )}
    </li>
  );
}

export function StockList({ limit = 12, onOpen }: { limit?: number; onOpen?: () => void }) {
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

  const { inZone, potential } = splitSections(briefs);

  return (
    <>
      <h3 className="brief-section-head">Jetzt im Einstiegsbereich</h3>
      {inZone.length > 0 ? (
        <ul className="brief-list">
          {inZone.map((brief) => (
            <BriefRow key={brief.ticker} brief={brief} />
          ))}
        </ul>
      ) : (
        <p className="brief-muted">
          Heute liegt kein Titel in seiner Einstiegszone — das ist ein Ergebnis, kein Fehler.
        </p>
      )}

      {potential.length > 0 && (
        <>
          <h3 className="brief-section-head">
            Höchstes Potenzial
            <span className="brief-muted"> · laut Analysten, nicht unser Modell</span>
          </h3>
          <ul className="brief-list">
            {potential.map((brief) => (
              <BriefRow key={brief.ticker} brief={brief} />
            ))}
          </ul>
        </>
      )}

      {onOpen && (
        <button className="stock-more" onClick={onOpen}>
          Alle im Radar →
        </button>
      )}
    </>
  );
}
