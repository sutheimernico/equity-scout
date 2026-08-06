import { useEffect, useState } from "react";

import { fetchBriefs, type StockBrief } from "../api";
import { shortCompanyName } from "../company";
import { shortVerdict, splitSections } from "../stocklist";
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
  // U+202F narrow no-break space: German typography puts a space before the % sign, but a
  // full space at 1.35rem tears the number and the unit apart.
  return `${rounded > 0 ? "+" : rounded < 0 ? "−" : ""}${Math.abs(rounded)}\u202F%`;
}

/** The headline number. Big on purpose — it is the reason to look at all — but it is a
 *  third-party opinion, so the label under it says so instead of a legend elsewhere. */
function PotentialBlock({ brief }: { brief: StockBrief }) {
  if (brief.analyst_upside_pct === null || brief.analyst_target === null) {
    return (
      <span className="brief-potential brief-potential-none">
        <span className="brief-potential-cap">Potenzial</span>
        <span className="brief-potential-num">—</span>
        <span className="brief-potential-label">keine Schätzung</span>
      </span>
    );
  }
  const up = brief.analyst_upside_pct >= 0;
  return (
    <span className={up ? "brief-potential brief-good" : "brief-potential brief-warn"}>
      {/* The number was unlabelled and read as a riddle: "ich kann nichts mit diesen minus
          sieben Prozent anfangen. Was meint das jetzt?" (Nico 2026-08-06). The caption says
          what it is, the footer says whose opinion it is. */}
      <span className="brief-potential-cap">Potenzial</span>
      <span className="brief-potential-num">{signedPct(brief.analyst_upside_pct)}</span>
      <span className="brief-potential-label">
        laut {brief.analyst_count ?? "?"} Analysten
      </span>
    </span>
  );
}

/** Entry state as a compact chip. Status colour never travels alone — the glyph and the
 *  word carry the same meaning, which is what makes the green/amber pair legal here. */
function ZoneChip({ brief }: { brief: StockBrief }) {
  return (
    <span className={brief.in_zone ? "brief-chip brief-chip-good" : "brief-chip brief-chip-warn"}>
      {brief.in_zone ? "✓" : "⚠"} {shortVerdict(brief)}
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
  // German one-liners when the generator produced them; the English wire titles are the
  // fallback for rows from before that existed (Nico 2026-08-06: "ich kann nichts mit
  // 'Yamato Holding Stock Faces Profit Strain Behind A Premium PE' anfangen").
  const headlines =
    insight.headlines_de.length > 0 ? insight.headlines_de : insight.headlines;
  return (
    <div className="brief-insight">
      {insight.business && <p className="brief-insight-business">{insight.business}</p>}
      {insight.news_summary ? (
        <p className="brief-insight-news">📰 {insight.news_summary}</p>
      ) : (
        <p className="brief-muted">Keine aktuellen Schlagzeilen gefunden.</p>
      )}
      {headlines.length > 0 && (
        <>
          <p className="brief-headlines-head">Schlagzeilen</p>
          <ul className="brief-headlines">
            {headlines.map((title) => (
              <li key={title}>{title}</li>
            ))}
          </ul>
        </>
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
      {/* Four things only (2026-08-05: "teilweise erdrückend, erschlagend"): who, how much
          potential, is the price good, and one tap for everything else. Price, sector and
          the zone meter moved into the detail — two large numbers per row competed, and
          seven stacked lines per stock is not a glance. */}
      <button className="brief-main" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <StockLogo ticker={brief.ticker} name={brief.name} />
        <span className="brief-body">
          <span className="brief-name" title={brief.name}>
            {shortCompanyName(brief.name)}
          </span>
          <ZoneChip brief={brief} />
        </span>
        <PotentialBlock brief={brief} />
      </button>
      {open && (
        <div className="brief-detail-wrap">
          <p className="brief-sub">
            {brief.ticker}
            {business ? ` · ${business}` : ""}
          </p>
          <MiniYearChart chart={brief.chart} currency={brief.currency} />
          {/* News before the figures (Nico 2026-08-06: "Ich find die News jetzt nicht mehr
              beim Aufklappen") — behind the five-row table they sat below the fold. */}
          <BriefInsight brief={brief} />
          <ZoneBar brief={brief} />
          <p className={brief.in_zone ? "brief-good brief-verdict" : "brief-warn brief-verdict"}>
            {brief.in_zone ? "✓" : "⚠"} {brief.zone_verdict}
          </p>
          {/* Says why a high potential and a poor entry are not a contradiction. */}
          <p className="brief-muted brief-note">{brief.entry_note}</p>
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
