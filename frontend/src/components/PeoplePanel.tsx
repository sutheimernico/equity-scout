import { useEffect, useState } from "react";

import { fetchEvidence, type EvidenceEvent, type EvidenceResponse, type PersonScore } from "../api";
import { shortCompanyName } from "../company";
import { Chip } from "./ui/Chip";
import { DisclaimerBar } from "./ui/DisclaimerBar";
import { Explain } from "./ui/Explain";

// Person-centred view over the evidence events (Nico 2026-08-07: "eine Page für die
// Kongressmitglieder oder die Person, die Aktien grad gekauft haben — Michael Burry,
// Warren Buffett …"). The ticker-centred data already exists (/api/evidence, 30-day
// window); this only regroups it by WHO — no new signal, no new fetch.

const MAX_MOVES_SHOWN = 6;

interface PersonBucket {
  person: string;
  role: string; // "Kongress (Senat, R)" | "Investor" | "Insider" | "Fonds"
  events: EvidenceEvent[];
  newest: string;
}

function roleOf(event: EvidenceEvent): string {
  const details = event.details;
  if (event.source === "congress") {
    const chamber = details.chamber === "senate" ? "Senat" : "Repräsentantenhaus";
    const party = details.party ? `, ${String(details.party)}` : "";
    return `Kongress (${chamber}${party})`;
  }
  if (event.source === "insider") return "Insider (Führungskraft)";
  if (event.source === "13f") return "Fonds";
  return "Investor / Stimme";
}

function personOf(event: EvidenceEvent): string | null {
  const details = event.details;
  const raw = details.politician ?? details.insider ?? details.fund ?? details.speaker;
  return raw ? String(raw) : null;
}

/** What this person DID, in one plain clause — from the recorded facts only. */
function moveLabel(event: EvidenceEvent): string {
  const details = event.details;
  if (event.source === "congress") {
    const amount = details.amount_range ? ` (${String(details.amount_range)})` : "";
    return `hat gekauft${amount}`;
  }
  if (event.source === "insider") return "hat als Insider gekauft";
  if (event.source === "13f") {
    return details.change === "new" ? "neue Position gemeldet" : "Position aufgestockt";
  }
  const kind = String(details.kind ?? "context");
  if (kind === "context") return "wird in der Presse erwähnt";
  return details.direction === "bullish"
    ? "äußert sich positiv (Kauf/Empfehlung)"
    : "äußert sich negativ (Verkauf/Short/Warnung)";
}

/** The reporting delay, said out loud: a congress trade from March filed in August is
 *  history, not news — hiding that would turn a disclosure into a fake signal. */
function delayNote(event: EvidenceEvent): string | null {
  const days = event.details.days_to_file;
  if (typeof days !== "number" || days <= 0) return null;
  return days >= 45
    ? `erst ${days} Tage nach dem Handel gemeldet`
    : `${days} Tage nach dem Handel gemeldet`;
}

function buildBuckets(eventsByTicker: Record<string, EvidenceEvent[]>): PersonBucket[] {
  const byPerson = new Map<string, PersonBucket>();
  for (const events of Object.values(eventsByTicker)) {
    for (const event of events) {
      const person = personOf(event);
      if (!person) continue;
      const bucket = byPerson.get(person) ?? {
        person,
        role: roleOf(event),
        events: [],
        newest: "",
      };
      bucket.events.push(event);
      byPerson.set(person, bucket);
    }
  }
  for (const bucket of byPerson.values()) {
    bucket.events.sort((a, b) => String(b.event_date).localeCompare(String(a.event_date)));
    bucket.newest = String(bucket.events[0]?.event_date ?? "");
  }
  return [...byPerson.values()].sort((a, b) => b.newest.localeCompare(a.newest));
}

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

export function PeoplePanel() {
  const [data, setData] = useState<EvidenceResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  return (
    <>
      <header className="section-head reveal">
        <p className="eyebrow">Signale · Personen</p>
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

      {buckets.length === 0 ? (
        <p className="state">Keine personenbezogenen Ereignisse in den letzten 30 Tagen.</p>
      ) : (
        <div className="voice-grid">
          {buckets.map((bucket) => (
            <PersonCard
              key={bucket.person}
              bucket={bucket}
              names={data.names ?? {}}
              score={scoreByPerson.get(bucket.person)}
            />
          ))}
        </div>
      )}

      <DisclaimerBar text={data.disclaimer} />
    </>
  );
}
