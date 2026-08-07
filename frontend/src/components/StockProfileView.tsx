import { Fragment, useEffect, useState } from "react";

import { riskMeta } from "../aktien";
import {
  fetchBrief,
  fetchCompany,
  fetchInbox,
  fetchModel,
  fetchStack,
  type CompanyResponse,
  type ModelResponse,
  type Pitch,
  type StackResponse,
  type StockBrief,
} from "../api";
import { shortCompanyName } from "../company";
import { delayNote, moveLabel, personOf, roleOf } from "../people";
import {
  FACTOR_LABELS,
  FSCORE_LABELS,
  READING_LABELS,
  formatEarnings,
  fscoreSummary,
  keyFigureRows,
  upsidePct,
} from "../profil";
import { EntryPlanBlock } from "./EntryPlanBlock";
import { InsightBlock } from "./InsightBlock";
import { MiniYearChart } from "./MiniYearChart";
import { StockLogo } from "./StockLogo";
import { ZoneBar } from "./ZoneBar";
import { Disclosure } from "./ui/Disclosure";

// The heart of the rebuild (mockup v2): ONE canonical drill-down per stock, reachable
// from every list. The three old drill-downs (BriefRow accordion, PickCard detail,
// RadarPanel entry) served different depths depending on where you came from — here
// the full depth lives behind three plain-language score bars plus disclosures.

function money(value: number, currency: string | null): string {
  const formatted = value.toLocaleString("de-DE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return currency ? `${formatted} ${currency}` : formatted;
}

/** One plain-language score bar with its full depth folded underneath. */
function WhyRow({
  label,
  score,
  scale,
  plain,
  detail,
  children,
}: {
  label: string;
  score: number | null;
  scale: number;
  plain: string;
  detail: string;
  children: React.ReactNode;
}) {
  return (
    <div className="why-row">
      <div className="why-head">
        <span>{label}</span>
        <span className="tnum">{score === null ? "—" : `${score}/${scale}`}</span>
      </div>
      {score !== null && (
        <div className="why-meter" aria-hidden="true">
          <i style={{ width: `${Math.max(0, Math.min(100, (score / scale) * 100))}%` }} />
        </div>
      )}
      <p className="why-plain">{plain}</p>
      <Disclosure summary={detail}>{children}</Disclosure>
    </div>
  );
}

export function StockProfileView({
  ticker,
  onBack,
  onNavigate,
}: {
  ticker: string;
  onBack: () => void;
  onNavigate: (view: string) => void;
}) {
  const [brief, setBrief] = useState<StockBrief | null>(null);
  const [stack, setStack] = useState<StackResponse | null>(null);
  const [company, setCompany] = useState<CompanyResponse | null>(null);
  const [model, setModel] = useState<ModelResponse | null>(null);
  const [pitch, setPitch] = useState<Pitch | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let ignore = false;
    setLoading(true);
    setFailed(false);
    setBrief(null);
    setStack(null);
    setCompany(null);
    setPitch(null);
    // brief + stack decide whether the page can render at all; company, model and the
    // open pitch each degrade to an honest gap on their own.
    Promise.all([fetchBrief(ticker), fetchStack(ticker)])
      .then(([b, s]) => {
        if (ignore) return;
        setBrief(b);
        setStack(s);
        setLoading(false);
      })
      .catch(() => {
        if (!ignore) {
          setFailed(true);
          setLoading(false);
        }
      });
    fetchCompany(ticker)
      .then((c) => {
        if (!ignore) setCompany(c);
      })
      .catch(() => {});
    fetchModel()
      .then((m) => {
        if (!ignore) setModel(m);
      })
      .catch(() => {});
    fetchInbox()
      .then((r) => {
        if (!ignore) {
          setPitch(r.pitches.find((p) => p.ticker === ticker && p.status === "open") ?? null);
        }
      })
      .catch(() => {});
    return () => {
      ignore = true;
    };
  }, [ticker]);

  if (loading) return <p className="brief-muted">lädt …</p>;
  if (failed) return <p className="brief-muted">Aktien-Daten nicht erreichbar.</p>;

  const risk = riskMeta(brief?.bucket ?? null);
  const analystUp = brief ? upsidePct(brief.analyst_target, brief.price) : null;
  const scoutUp = brief ? upsidePct(brief.model_target, brief.price) : null;
  const screener = stack?.screener ?? null;
  const radar = stack?.radar ?? null;
  const ml = stack?.ml ?? null;
  const events = stack?.evidence_events ?? [];
  const hitRate = model?.resolved?.hit_rate ?? null;
  const figureRows = keyFigureRows(company?.metrics ?? null);
  const earnings = formatEarnings(company?.next_earnings ?? null);

  return (
    <section className="profil">
      <button className="stock-more profil-back" onClick={onBack}>
        ‹ Zurück
      </button>

      {brief === null ? (
        <p className="brief-muted">
          {ticker} steht nicht auf der aktuellen Watchlist — es gibt kein aufbereitetes
          Profil. Was der Scout trotzdem weiß, steht unten.
        </p>
      ) : (
        <>
          <header className="profil-head">
            <StockLogo ticker={brief.ticker} name={brief.name} />
            <div className="profil-ident">
              <h1>{shortCompanyName(brief.name)}</h1>
              <p className="brief-muted">
                {brief.ticker}
                {brief.sector ? ` · ${brief.sector}` : ""}
                {brief.industry ? ` · ${brief.industry}` : ""}
              </p>
            </div>
            <div className="profil-price tnum">{money(brief.price, brief.currency)}</div>
          </header>

          {risk && (
            <p className="profil-risk">
              <span className={risk.chip}>{risk.label}</span>
              <span className="brief-muted">{risk.note}</span>
            </p>
          )}

          <MiniYearChart chart={brief.chart} currency={brief.currency} />
          <ZoneBar brief={brief} />
          <p className={brief.in_zone ? "brief-good brief-verdict" : "brief-warn brief-verdict"}>
            {brief.in_zone ? "✓" : "⚠"} {brief.zone_verdict}
          </p>
          <p className="brief-muted brief-note">{brief.entry_note}</p>

          <h2 className="brief-section-head">Was wäre drin?</h2>
          <div className="profil-hero">
            <div className="profil-hero-box">
              <span className="profil-hero-label">Analysten sehen</span>
              <span className="profil-hero-big tnum">
                {analystUp === null ? "—" : `${analystUp > 0 ? "+" : ""}${analystUp} %`}
              </span>
              <span className="brief-muted">
                {brief.analyst_target === null
                  ? "keine Schätzung"
                  : `Ziel ${money(brief.analyst_target, brief.currency)} · Schnitt von ${
                      brief.analyst_count ?? "?"
                    } Analysten`}
              </span>
            </div>
            <div className="profil-hero-box">
              <span className="profil-hero-label">Scout sieht</span>
              <span className="profil-hero-big tnum">
                {scoutUp === null ? "—" : `${scoutUp > 0 ? "+" : ""}${scoutUp} %`}
              </span>
              <span className="brief-muted">
                {brief.model_target === null
                  ? "noch keine Berechnung"
                  : `Ziel ${money(brief.model_target, brief.currency)} · ${
                      brief.target_source === "model"
                        ? "trainiertes Modell"
                        : "konservative Faustformel"
                    }`}
              </span>
            </div>
          </div>
          <dl className="brief-detail">
            <dt>Guter Einstieg</dt>
            <dd className="num">
              {money(brief.zone_low, null)}–{money(brief.zone_high, brief.currency)}
            </dd>
            <dt>Absicherung (Stop)</dt>
            <dd className="num">
              {brief.model_stop === null
                ? "—"
                : `${money(brief.model_stop, brief.currency)} · darunter gilt die Idee als gescheitert`}
            </dd>
            <dt>Nächste Quartalszahlen</dt>
            <dd className="num">
              {earnings === null ? "— kein Termin bekannt" : `${earnings} · hier springen Kurse oft`}
            </dd>
          </dl>
          <Disclosure summary="Einstiegsplan im Detail">
            <EntryPlanBlock ticker={brief.ticker} />
          </Disclosure>
          <Disclosure summary="Was bedeuten diese Zahlen?">
            <p>
              Kursziele sind Schätzungen, keine Versprechen. Das Analysten-Ziel ist der
              Durchschnitt der Profi-Schätzungen, das Scout-Ziel unsere eigene Berechnung aus
              Kursverlauf und Schwankung — bewusst vorsichtiger. Die Absicherung ist der Kurs,
              ab dem die Idee als gescheitert gilt. Mehr unter „Wie funktioniert das?".
            </p>
          </Disclosure>
        </>
      )}

      <h2 className="brief-section-head">Warum interessant</h2>
      <div className="profil-why">
        <WhyRow
          label="Qualität der Firma"
          score={screener?.composite != null ? Math.round(screener.composite * 100) : null}
          scale={100}
          plain={
            screener
              ? `Gewichteter Faktor-Score im ${
                  riskMeta((screener.bucket as StockBrief["bucket"]) ?? null)?.label ??
                  screener.bucket
                }-Profil — aus fünf Faktoren über alle geprüften Aktien.`
              : "Nicht unter den Picks des letzten Screener-Laufs."
          }
          detail="Im Detail: die 5 Faktoren"
        >
          {screener?.breakdown ? (
            <dl className="brief-detail">
              {Object.entries(screener.breakdown).map(([key, value]) => (
                <Fragment key={key}>
                  <dt>{FACTOR_LABELS[key] ?? key}</dt>
                  <dd className="num">
                    {Math.round(value * 100)}. Perzentil · besser als {Math.round(value * 100)} %
                    der geprüften Aktien
                  </dd>
                </Fragment>
              ))}
            </dl>
          ) : (
            <p>Für diesen Titel liegen keine Faktor-Perzentile aus dem letzten Lauf vor.</p>
          )}
        </WhyRow>

        <WhyRow
          label="Kurs-Timing"
          score={brief ? brief.score : radar ? Math.round(radar.composite * 100) : null}
          scale={100}
          plain={
            radar
              ? radar.zone_note || "Timing-Score aus drei Signalen am aktuellen Kurs."
              : "Kein Radar-Eintrag — der Titel steht nicht auf der Watchlist."
          }
          detail="Im Detail: die 3 Timing-Signale"
        >
          {radar && radar.readings.length > 0 ? (
            <dl className="brief-detail">
              {radar.readings.map((r) => (
                <Fragment key={r.name}>
                  <dt>{READING_LABELS[r.name] ?? r.name}</dt>
                  <dd>
                    <span className="num">{Math.round(r.score * 100)}/100</span> — {r.reason}
                  </dd>
                </Fragment>
              ))}
            </dl>
          ) : (
            <p>Keine Timing-Signale vorhanden.</p>
          )}
          <p className="brief-muted">
            Timing sagt nichts über die Qualität der Firma — nur darüber, ob der Kurs gerade
            einen attraktiven Moment bietet.
          </p>
        </WhyRow>

        <WhyRow
          label="KI-Zweitmeinung"
          score={ml ? Math.round(ml.score) : null}
          scale={100}
          plain={
            ml
              ? `${Math.round(ml.score)} von 100 — kalibrierte Wahrscheinlichkeit, keine Kursprognose.`
              : "Noch nie gescort — der Score-Lauf läuft täglich."
          }
          detail="Im Detail: was das Modell macht"
        >
          <p>
            Das Modell schätzt die Chance, dass der Titel den US-Markt in den nächsten ~20
            Handelstagen schlägt. Es lernt ausschließlich aus ehrlich aufgelösten früheren
            Fällen
            {hitRate !== null
              ? `; aktuelle Trefferquote rund ${Math.round(hitRate * 100)} %`
              : ""}
            . Werte über 60 sind Rückenwind — ein Hinweis, kein Versprechen.
          </p>
          <button className="stock-more" onClick={() => onNavigate("labor")}>
            Ob das Modell besser wird → Labor
          </button>
        </WhyRow>
      </div>

      <h2 className="brief-section-head">
        Wer kauft gerade
        <button className="stock-more profil-sect-link" onClick={() => onNavigate("werkauft")}>
          Alle ansehen →
        </button>
      </h2>
      {events.length === 0 ? (
        <p className="brief-muted">Keine gemeldeten Käufe in den letzten 30 Tagen.</p>
      ) : (
        <ul className="profil-buyers">
          {events.map((event) => (
            <li key={event.event_key}>
              <b>
                {personOf(event) ?? "Unbekannt"} · {roleOf(event)}
              </b>
              <span className="brief-muted">
                {moveLabel(event)}
                {delayNote(event) ? ` · ${delayNote(event)}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}

      {(brief?.insight || screener?.news?.length) && (
        <>
          <h2 className="brief-section-head">News</h2>
          <InsightBlock insight={brief?.insight} news={screener?.news} />
        </>
      )}

      {(figureRows.length > 0 || company?.f_score) && (
        <>
          <h2 className="brief-section-head">Zahlen im Klartext</h2>
          <dl className="brief-detail">
            {figureRows.map((row) => (
              <Fragment key={row.label}>
                <dt>{row.label}</dt>
                <dd className="num">{row.value}</dd>
              </Fragment>
            ))}
            {company?.f_score && (
              <>
                <dt>Bilanz-Check</dt>
                <dd className="num">{fscoreSummary(company.f_score)}</dd>
              </>
            )}
          </dl>
          {company?.f_score && (
            <Disclosure summary="Bilanz-Check im Detail (9 Kriterien)">
              <ul className="profil-fscore">
                {Object.entries(company.f_score.criteria).map(([key, passed]) => (
                  <li key={key}>
                    <span aria-hidden="true">{passed === null ? "·" : passed ? "✓" : "✗"}</span>{" "}
                    {FSCORE_LABELS[key] ?? key}
                    {passed === null ? " (nicht bewertbar)" : ""}
                  </li>
                ))}
              </ul>
              <p className="brief-muted">
                Piotroski-F-Score aus dem letzten Jahresabschluss
                {company.f_score.fiscal_year ? ` (${company.f_score.fiscal_year})` : ""}: neun
                simple Ja/Nein-Fragen zur Bilanz — je mehr Punkte, desto solider.
              </p>
            </Disclosure>
          )}
          {company?.metrics_fetched_on && (
            <p className="brief-muted profil-stand">Kennzahlen-Stand: {company.metrics_fetched_on}</p>
          )}
        </>
      )}

      {pitch && (
        <div className="profil-pitch-teaser">
          <p>
            <b>Dieser Titel wartet in „Entscheiden" auf dich</b> — der Scout hat eine Kauf-Idee
            vorbereitet. Kaufen, Später oder Ablehnen entscheidest du dort; auch Ablehnen
            fließt in die Messung ein.
          </p>
          <button className="stock-more" onClick={() => onNavigate("entscheiden")}>
            Zur Entscheidung →
          </button>
        </div>
      )}
    </section>
  );
}
