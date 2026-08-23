import { useEffect, useState } from "react";

import { fetchEvidence, type EvidenceEvent, type EvidenceResponse } from "../api";
import { VOICE_PAGE, isDirected, voiceRows, voiceView, type VoiceFilter } from "../voices";
import { Chip } from "./ui/Chip";
import { DisclaimerBar } from "./ui/DisclaimerBar";
import { Explain } from "./ui/Explain";

// What the headline MEANS, said out loud (Nico 2026-08-07: "ich will selber nicht
// unnötig nachdenken müssen — heißt die Schlagzeile: kauft die Aktie oder verkauft?").
// The direction comes from the deterministic verb match, never from an LLM — so the
// label states the recorded direction, not an interpretation of ours.
function toneOf(event: EvidenceEvent): { label: string; explain: string } {
  const kind = String(event.details.kind ?? "context");
  if (kind === "context") {
    return {
      label: "nur Erwähnung",
      explain: "Die Person wird nur im Zusammenhang genannt — keine erkennbare Kauf- oder Verkaufsrichtung.",
    };
  }
  if (String(event.details.direction ?? "") === "bullish") {
    return {
      label: "🟢 Richtung Kauf",
      explain:
        "Die Schlagzeile meldet Kauf, Aufstockung oder Empfehlung. Diese Aussage bekommt einen Track-Record — wir messen später, ob sie recht hatte.",
    };
  }
  return {
    label: "🔴 Richtung Verkauf",
    explain:
      "Die Schlagzeile meldet Verkauf, Short oder eine Warnung. Wird angezeigt, zählt aber noch nicht in die Statistik (Auflösung für Short-Richtung fehlt noch).",
  };
}

function VoiceRow({ event, names }: { event: EvidenceEvent; names: Record<string, string> }) {
  const details = event.details;
  const tone = toneOf(event);
  const company = names[event.ticker];
  return (
    <article className="panel voice-row">
      <div className="voice-head">
        <span className="pitch-company">{company ?? event.ticker}</span>
        {company && <span className="ticker">{event.ticker}</span>}
        <Chip>{String(details.speaker ?? "unbekannt")}</Chip>
        <Chip>{tone.label}</Chip>
        <span className="muted tnum">{String(details.published ?? event.event_date)}</span>
      </div>
      <p className="voice-headline">»{String(details.headline ?? "?")}«</p>
      {/* The context explanation was identical on ~200 cards and said only that nothing
          was recognisable. It lives in the Explain block above now; here it would be
          noise repeated per row. Directed calls keep theirs — those differ and matter. */}
      {isDirected(event) && <p className="muted">{tone.explain}</p>}
    </article>
  );
}

export function VoicesPanel() {
  const [data, setData] = useState<EvidenceResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<VoiceFilter>("gerichtet");
  const [limit, setLimit] = useState(VOICE_PAGE);

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
  const view = voiceView(rows, filter, limit);
  const voiceScores = data.person_scores.filter((s) => s.source === "voice" && s.scoreable);

  const pick = (next: VoiceFilter) => {
    setFilter(next);
    setLimit(VOICE_PAGE); // a new filter starts at the top, not deep inside the old page
  };

  return (
    <>
      <header className="section-head reveal">
        <p className="eyebrow">Mehr · Wer kauft? · Stimmen</p>
        <h1>Was bekannte Investoren öffentlich sagen</h1>
        <p className="section-sub">
          Presse-Erwähnungen der beobachteten Fonds-Manager (Buffett, Burry, Ackman, …) aus freien
          News-Feeds — Kontext, kein Frühsignal: was hier steht, ist bereits öffentlich.
          Zuerst die Schlagzeilen mit erkennbarer Richtung; die reinen Erwähnungen sind die
          große Mehrheit und stehen unter „Alle".
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
        <>
          <div className="tabbar">
            <button
              className={filter === "gerichtet" ? "tab active" : "tab"}
              onClick={() => pick("gerichtet")}
            >
              Mit Richtung ({view.directed})
            </button>
            <button
              className={filter === "alle" ? "tab active" : "tab"}
              onClick={() => pick("alle")}
            >
              Alle ({view.total})
            </button>
          </div>
          {view.shown.length === 0 ? (
            <p className="state">
              Keine Schlagzeile der letzten 30 Tage nennt eine klare Kauf- oder
              Verkaufsrichtung. Das ist ein Ergebnis, kein Fehler — unter „Alle" stehen die
              reinen Erwähnungen.
            </p>
          ) : (
            <div className="voice-grid">
              {view.shown.map((event) => (
                <VoiceRow
                  key={`${event.ticker}-${event.event_key}`}
                  event={event}
                  names={data.names ?? {}}
                />
              ))}
            </div>
          )}
          {view.hidden > 0 && (
            <button className="stock-more" onClick={() => setLimit(limit + VOICE_PAGE)}>
              + {view.hidden} weitere anzeigen
            </button>
          )}
        </>
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
