import { useEffect, useState } from "react";

import { fetchEvidence, type EvidenceResponse, type PersonScore } from "../api";
import { shortCompanyName } from "../company";
import {
  buildBuckets,
  congressByStock,
  delayNote,
  moveLabel,
  type PersonBucket,
} from "../people";
import { Chip } from "./ui/Chip";
import { DisclaimerBar } from "./ui/DisclaimerBar";
import { Explain } from "./ui/Explain";

// Person-centred view over the evidence events (Nico 2026-08-07: "eine Page für die
// Kongressmitglieder oder die Person, die Aktien grad gekauft haben — Michael Burry,
// Warren Buffett …"). Two projections of the same 30-day window: by person, and the
// congress buys regrouped by STOCK ("einfach screenen, welche Aktien die gekauft haben").
// No new signal, no new fetch — /api/evidence regrouped.

const MAX_MOVES_SHOWN = 6;

function PersonCard({
  bucket,
  names,
  score,
}: {
  bucket: PersonBucket;
  names: Record<string, string>;
  score: PersonScore | undefined;
}) {
  const [showAll, setShowAll] = useState(false);
  const moves = showAll ? bucket.events : bucket.events.slice(0, MAX_MOVES_SHOWN);
  const hidden = bucket.events.length - moves.length;

  return (
    <article className="panel person-card">
      <div className="person-head">
        <span className="person-name">{bucket.person}</span>
        <Chip>{bucket.role}</Chip>
      </div>
      {score?.scoreable && (
        <p className="person-score">
          Gemessener Track-Record: {score.n_calls} Calls, Ø{" "}
          {score.weighted_score != null ? `${(score.weighted_score * 100).toFixed(1)} %` : "—"} vs
          SPY über 3 Monate — Historie, keine Prognose.
        </p>
      )}
      <ul className="person-moves">
        {moves.map((event) => {
          const name = names[event.ticker];
          const delay = delayNote(event);
          return (
            <li key={`${event.ticker}-${event.event_key}`}>
              <span className="tnum person-date">{String(event.event_date)}</span>{" "}
              <span className="person-company">
                {name ? shortCompanyName(name) : event.ticker}
              </span>{" "}
              <span className="ticker">{event.ticker}</span> — {moveLabel(event)}
              {delay && <span className="person-delay"> · {delay}</span>}
            </li>
          );
        })}
      </ul>
      {hidden > 0 && !showAll && (
        <button className="stock-more" onClick={() => setShowAll(true)}>
          + {hidden} weitere anzeigen
        </button>
      )}
    </article>
  );
}

/** Congress buys as a stock screen: which names are members of congress buying. */
function CongressStockList({
  data,
  names,
}: {
  data: EvidenceResponse;
  names: Record<string, string>;
}) {
  const rows = congressByStock(data.events_by_ticker);
  if (rows.length === 0) {
    return <p className="state">Keine Kongress-Käufe in den letzten 30 Tagen gemeldet.</p>;
  }
  return (
    <div className="voice-grid">
      {rows.map((row) => {
        const name = names[row.ticker];
        const shownBuyers = row.buyers.slice(0, 3).join(", ");
        const moreBuyers = row.buyers.length - Math.min(3, row.buyers.length);
        return (
          <article className="panel person-card" key={row.ticker}>
            <div className="person-head">
              <span className="person-name">
                {name ? shortCompanyName(name) : row.ticker}
              </span>
              <span className="ticker">{row.ticker}</span>
              <Chip>
                {row.buys} {row.buys === 1 ? "Kauf" : "Käufe"} ·{" "}
                {row.buyers.length} {row.buyers.length === 1 ? "Mitglied" : "Mitglieder"}
              </Chip>
            </div>
            <p className="person-score">
              {shownBuyers}
              {moreBuyers > 0 ? ` +${moreBuyers} weitere` : ""} — letzte Meldung{" "}
              <span className="tnum">{row.latest}</span>. Gezählt werden Pflichtmeldungen,
              keine Empfehlungen.
            </p>
          </article>
        );
      })}
    </div>
  );
}

export function PeoplePanel() {
  const [data, setData] = useState<EvidenceResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"personen" | "kongress">("personen");

  useEffect(() => {
    let ignore = false;
    fetchEvidence()
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

  const buckets = buildBuckets(data.events_by_ticker);
  const scoreByPerson = new Map(data.person_scores.map((s) => [s.person, s]));
  const names = data.names ?? {};

  return (
    <>
      <header className="section-head reveal">
        <p className="eyebrow">Mehr · Wer kauft?</p>
        <h1>Wer kauft gerade was</h1>
        <p className="section-sub">
          Kongress-Pflichtmeldungen, Insider-Meldungen, Fonds-Quartalsberichte und
          Presse-Stimmen der letzten 30 Tage — nach Person gruppiert. Alles hier ist
          bereits öffentlich und oft Wochen alt: Kontext, kein Frühsignal und keine
          Anlageberatung.
        </p>
      </header>

      <Explain>
        Meldeverzug gehört zur Wahrheit: Kongress-Trades dürfen bis zu 45 Tage später
        gemeldet werden, manche kommen Monate bis Jahre zu spät — die Verzögerung steht
        deshalb an jeder Zeile.
      </Explain>

      <div className="tabbar">
        <button
          className={tab === "personen" ? "tab active" : "tab"}
          onClick={() => setTab("personen")}
        >
          Nach Person
        </button>
        <button
          className={tab === "kongress" ? "tab active" : "tab"}
          onClick={() => setTab("kongress")}
        >
          Kongress: welche Aktien
        </button>
      </div>

      {tab === "kongress" ? (
        <CongressStockList data={data} names={names} />
      ) : buckets.length === 0 ? (
        <p className="state">Keine personenbezogenen Ereignisse in den letzten 30 Tagen.</p>
      ) : (
        <div className="voice-grid">
          {buckets.map((bucket) => (
            <PersonCard
              key={bucket.person}
              bucket={bucket}
              names={names}
              score={scoreByPerson.get(bucket.person)}
            />
          ))}
        </div>
      )}

      <DisclaimerBar text={data.disclaimer} />
    </>
  );
}
