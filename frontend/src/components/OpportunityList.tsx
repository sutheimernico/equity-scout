import { useEffect, useState } from "react";

import { fetchOpportunities, type OpportunityRow } from "../api";

// Der Verlauf der Meldungen. Eine Benachrichtigung ist weg, sobald man sie wegwischt —
// hier steht sie mit der ganzen Begründung, nach der man am Sperrbildschirm keine Zeit
// hatte. Jede Zeile trägt Kurs und Limit von DAMALS, nicht von heute: nur so ist später
// nachrechenbar, was die Meldung wert war.
function money(value: number | null, currency: string | null): string {
  if (value === null || value === undefined) return "—";
  const symbol =
    ({ USD: "$", EUR: "€", GBP: "£", CHF: "CHF", JPY: "¥" } as Record<string, string>)[
      (currency ?? "").toUpperCase()
    ] ?? (currency ?? "");
  return `${value.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${symbol}`.trim();
}

function dayLabel(iso: string): string {
  const day = iso.slice(0, 10);
  const today = new Date().toISOString().slice(0, 10);
  if (day === today) return "Heute";
  const yesterday = new Date(Date.now() - 86_400_000).toISOString().slice(0, 10);
  if (day === yesterday) return "Gestern";
  return day.split("-").reverse().join(".");
}

export function OpportunityList({ onOpenStock }: { onOpenStock?: (ticker: string) => void }) {
  const [rows, setRows] = useState<OpportunityRow[] | null>(null);
  const [open, setOpen] = useState<number | null>(null);

  useEffect(() => {
    let ignore = false;
    fetchOpportunities()
      .then((r) => {
        if (!ignore) setRows(r.opportunities);
      })
      .catch(() => {
        if (!ignore) setRows([]);
      });
    return () => {
      ignore = true;
    };
  }, []);

  if (rows === null) return <p className="brief-muted">lädt …</p>;
  if (rows.length === 0) {
    return (
      <p className="brief-muted">
        Noch keine Meldung verschickt. Das ist kein Fehler: gemeldet wird nur, was die
        Qualitätsschwelle schafft, handelbar ist und in den letzten sieben Tagen nicht schon
        dran war.
      </p>
    );
  }

  return (
    <ul className="opp-list">
      {rows.map((row) => {
        const isOpen = open === row.id;
        const ready = row.stance === "kaufbereit";
        return (
          <li key={row.id} className="opp-item">
            <button
              className="opp-head"
              onClick={() => setOpen(isOpen ? null : row.id)}
              aria-expanded={isOpen}
            >
              <span className={ready ? "opp-badge ready" : "opp-badge soon"}>
                {ready ? "Chance" : "Bald"}
              </span>
              <span className="opp-title">{row.headline}</span>
              <span className="opp-day tnum">{dayLabel(row.notified_at)}</span>
            </button>
            <p className="opp-line">{row.one_liner}</p>
            {isOpen && (
              <div className="opp-detail">
                {row.verdict && <p className="opp-verdict">{row.verdict}</p>}
                <h4>Warum</h4>
                <ul className="opp-reasons">
                  {row.why_now.map((line, i) => (
                    <li key={i}>{line}</li>
                  ))}
                </ul>
                <h4>Was dagegen spricht</h4>
                <p className="muted">{row.risk}</p>
                {row.plan_line && (
                  <>
                    <h4>Der Plan von damals</h4>
                    <p className="muted">{row.plan_line}</p>
                  </>
                )}
                <dl className="brief-detail">
                  <dt>Kurs bei der Meldung</dt>
                  <dd className="tnum">{money(row.price, row.currency)}</dd>
                  <dt>Limit</dt>
                  <dd className="tnum">{money(row.buy_limit, row.currency)}</dd>
                  <dt>Text von</dt>
                  <dd>{row.explained_by === "llm" ? "KI-Zusammenfassung" : "Regeln"}</dd>
                </dl>
                {row.track_record && <p className="opp-track">{row.track_record}</p>}
                {onOpenStock && (
                  <button className="tab primary" onClick={() => onOpenStock(row.ticker)}>
                    Aktie ansehen →
                  </button>
                )}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
