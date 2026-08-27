import { useEffect, useState } from "react";

import { fetchInbox, fetchOpportunities, type OpportunityRow } from "../api";

// Die eine Frage, mit der jemand die App öffnet: MUSS ICH HEUTE ETWAS TUN?
//
// Bis heute stand ganz oben „Dein Überblick in drei Minuten" und darunter fünf Blöcke, aus
// denen man sich die Antwort selbst zusammensuchen musste. Diese Karte gibt sie in einem
// Satz — und „nein" ist eine vollwertige Antwort, keine leere Seite. In Wochen ohne
// Kandidaten ist Nichtstun die richtige Handlung, und die App muss das genauso deutlich
// sagen wie ein Fund, sonst liest sich Stille als Ausfall.
function isToday(iso: string): boolean {
  return iso.slice(0, 10) === new Date().toISOString().slice(0, 10);
}

export function TodayAction({ onNavigate }: { onNavigate: (view: string) => void }) {
  const [opportunities, setOpportunities] = useState<OpportunityRow[] | null>(null);
  const [openPitches, setOpenPitches] = useState<number | null>(null);

  useEffect(() => {
    let ignore = false;
    fetchOpportunities(10)
      .then((r) => {
        if (!ignore) setOpportunities(r.opportunities);
      })
      .catch(() => {
        if (!ignore) setOpportunities([]);
      });
    fetchInbox()
      .then((r) => {
        if (!ignore) setOpenPitches(r.pitches.filter((p) => p.status === "open").length);
      })
      .catch(() => undefined);
    return () => {
      ignore = true;
    };
  }, []);

  if (opportunities === null) {
    return (
      <section className="today-action loading">
        <p className="brief-muted">lädt …</p>
      </section>
    );
  }

  const today = opportunities.filter((o) => isToday(o.notified_at));
  const ready = today.filter((o) => o.stance === "kaufbereit");
  const soon = today.filter((o) => o.stance !== "kaufbereit");
  const decisions = openPitches ?? 0;
  const somethingToDo = ready.length > 0 || decisions > 0;

  return (
    <section className={somethingToDo ? "today-action live" : "today-action calm"}>
      <p className="today-action-eyebrow">Heute</p>
      <h1 className="today-action-head">
        {ready.length > 0
          ? ready.length === 1
            ? "Eine Chance, die du heute kaufen könntest"
            : `${ready.length} Chancen, die du heute kaufen könntest`
          : decisions > 0
            ? decisions === 1
              ? "Ein Vorschlag wartet auf deine Entscheidung"
              : `${decisions} Vorschläge warten auf deine Entscheidung`
            : "Heute nichts zu tun"}
      </h1>

      {ready.length > 0 && (
        <ul className="today-action-list">
          {ready.slice(0, 3).map((row) => (
            <li key={row.id}>
              <b>{row.name ?? row.ticker}</b> — {row.one_liner}
            </li>
          ))}
        </ul>
      )}

      {ready.length === 0 && soon.length > 0 && (
        <p className="today-action-sub">
          {soon.length === 1
            ? "Ein Titel steht kurz vor seiner Kaufzone — dafür lohnt sich ein Limit."
            : `${soon.length} Titel stehen kurz vor ihrer Kaufzone — dafür lohnt sich je ein Limit.`}
        </p>
      )}

      {!somethingToDo && soon.length === 0 && (
        <p className="today-action-sub">
          Kein Titel hat heute die Qualitätsschwelle geschafft. Das ist der Normalfall und
          kein Fehler — dein Autopilot läuft davon unabhängig weiter.
        </p>
      )}

      <div className="tabbar wrap">
        {(ready.length > 0 || soon.length > 0) && (
          <button className="tab primary" onClick={() => onNavigate("alarme")}>
            Meldungen ansehen →
          </button>
        )}
        {decisions > 0 && (
          <button className="tab primary" onClick={() => onNavigate("entscheiden")}>
            Entscheiden ({decisions}) →
          </button>
        )}
        <button className="tab" onClick={() => onNavigate("depot")}>
          Depot →
        </button>
      </div>
    </section>
  );
}
