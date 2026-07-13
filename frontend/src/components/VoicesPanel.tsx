import { useEffect, useState } from "react";

import { fetchEvidence, type EvidenceEvent, type EvidenceResponse } from "../api";
import { Chip } from "./ui/Chip";
import { DisclaimerBar } from "./ui/DisclaimerBar";
import { Explain } from "./ui/Explain";

// One flat, dated list of voice events across all tickers (calls first), newest first.
function voiceRows(eventsByTicker: Record<string, EvidenceEvent[]>): EvidenceEvent[] {
  const rows = Object.values(eventsByTicker)
    .flat()
    .filter((e) => e.source === "voice");
  const rank = (e: EvidenceEvent) => (e.details.kind === "context" ? 1 : 0);
  return rows.sort(
    (a, b) => rank(a) - rank(b) || String(b.event_date).localeCompare(String(a.event_date)),
  );
}

function VoiceRow({ event }: { event: EvidenceEvent }) {
  const details = event.details;
  const kind = String(details.kind ?? "context");
  const direction = String(details.direction ?? "");
  const tone =
    kind === "context" ? "Erwähnung" : direction === "bullish" ? "positiv" : "negativ";
  return (
    <article className="panel voice-row">
      <div className="voice-head">
        <span className="ticker">{event.ticker}</span>
        <Chip>{String(details.speaker ?? "unbekannt")}</Chip>
        <Chip>{tone}</Chip>
        <span className="muted tnum">{String(details.published ?? event.event_date)}</span>
      </div>
      <p className="voice-headline">»{String(details.headline ?? "?")}«</p>
      {kind !== "context" && (
        <p className="muted">
          Messbarer Call (Name vor Richtungs-Verb, eindeutiger Ticker).{" "}
          {kind === "call"
            ? "Geht in Ledger und Personen-Track-Record ein."
            : "Short-Richtung: wird angezeigt und alarmiert, zählt aber nicht in die Statistik, bis vorzeichenrichtige Auflösung existiert."}
        </p>
      )}
    </article>
  );
}

export function VoicesPanel() {
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

  const rows = voiceRows(data.events_by_ticker);
  const voiceScores = data.person_scores.filter((s) => s.source === "voice" && s.scoreable);

  return (
    <>
      <header className="section-head reveal">
        <p className="eyebrow">Signale · Stimmen</p>
        <h1>Was bekannte Investoren öffentlich sagen</h1>
        <p className="section-sub">
          Presse-Erwähnungen der beobachteten Fonds-Manager (Buffett, Burry, Ackman, …) aus freien
          News-Feeds — Kontext, kein Frühsignal: was hier steht, ist bereits öffentlich.
        </p>
      </header>

      <Explain>
        Nur wenn Name, Richtungs-Verb und ein eindeutiger Ticker deterministisch zusammenpassen,
        wird aus einer Schlagzeile ein <strong>messbarer Call</strong> mit eigenem
        Track-Record — alles andere bleibt Erwähnung. Kein LLM interpretiert hier etwas.
      </Explain>

      {rows.length === 0 ? (
        <p className="state">
          Keine Stimmen-Ereignisse in den letzten 30 Tagen — <code>run_evidence.py</code> sammelt
          sie (halbstündlich per Intraday-Kette, sobald der Cron installiert ist).
        </p>
      ) : (
        <div className="voice-grid">
          {rows.map((event) => (
            <VoiceRow key={`${event.ticker}-${event.event_key}`} event={event} />
          ))}
        </div>
      )}

      {voiceScores.length > 0 && (
        <section className="strat-block">
          <h3 className="block-title">Gemessene Stimmen-Track-Records</h3>
          {voiceScores.map((s) => (
            <p key={s.person} className="muted">
              {s.person}: {s.n_calls} Calls, Ø{" "}
              {s.weighted_score != null ? `${(s.weighted_score * 100).toFixed(1)} %` : "—"} vs SPY
              3M — Historie, keine Prognose.
            </p>
          ))}
        </section>
      )}
      {voiceScores.length === 0 && rows.length > 0 && (
        <p className="muted">
          Noch keine gemessenen Stimmen-Track-Records — Scores entstehen erst, wenn mindestens 5
          messbare bullishe Calls einer Person aufgelöst sind (das dauert bewusst).
        </p>
      )}

      <DisclaimerBar text={data.disclaimer} />
    </>
  );
}
