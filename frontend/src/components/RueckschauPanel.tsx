import { useEffect, useState } from "react";

import { fetchRueckschau, type ReviewSummaryRow, type RueckschauResponse } from "../api";

// „Hätten die Vorschläge getragen?" (Nachtschicht 2026-08-27) — die Gegenfrage zu den
// Proof-Büchern darüber. Die messen, was die Maschine selbst handelt; hier steht, was die
// Liste taugte, die Nico zu sehen bekommt. Zwei verschiedene Fragen, nie eine Zahl.
//
// Der Urteilssatz kommt fertig aus dem Backend (`suggestion_review.verdict_line`) und wird
// hier NICHT nachgebaut: er trägt die Einordnung zum korrigierten Niveau, und ein zweiter
// Satz an dieser Stelle wäre die Gelegenheit, sie wegzulassen.

const SOURCE_TITLES: Record<string, string> = {
  pitch: "Was per Telegram vorgeschlagen wurde",
  rank: "Die Spitze der Rangliste",
};

function pp(value: number | null): string {
  if (value === null) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toFixed(1).replace(".", ",")} pp`;
}

function HorizonRow({ row }: { row: ReviewSummaryRow }) {
  return (
    <div className="plan-row">
      <span className="plan-row-label">{row.horizon_days} Handelstage</span>
      <span className="plan-row-value">{pp(row.mean_excess_pct)}</span>
      <span className="plan-row-hint">
        {row.n_independent} unabhängige Fälle
        {row.hit_rate !== null && ` · ${Math.round(row.hit_rate * 100)} % im Plus`}
        {row.best && row.worst && ` · best ${row.best[0]} ${pp(row.best[1])}, schlecht. ${row.worst[0]} ${pp(row.worst[1])}`}
      </span>
    </div>
  );
}

export function RueckschauPanel() {
  const [data, setData] = useState<RueckschauResponse | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let ignore = false;
    fetchRueckschau()
      .then((r) => !ignore && setData(r))
      .catch(() => !ignore && setFailed(true));
    return () => {
      ignore = true;
    };
  }, []);

  if (failed) return null; // ein fehlendes Panel ist besser als ein Fehlertext im Ergebnis-Tab
  if (data === null) return <p className="brief-muted">lädt …</p>;

  if (!data.available) {
    return (
      <section className="plan-block">
        <h3>Hätten die Vorschläge getragen?</h3>
        <p className="plan-sub">{data.note}</p>
      </section>
    );
  }

  const measured = (data.summaries ?? []).filter((s) => s.n > 0);
  if (measured.length === 0) {
    return (
      <section className="plan-block">
        <h3>Hätten die Vorschläge getragen?</h3>
        <p className="plan-sub">
          Noch kein abgeschlossenes Zeitfenster — die Vorschläge sind jünger als der kürzeste
          gemessene Horizont.
        </p>
      </section>
    );
  }

  const bySource = new Map<string, ReviewSummaryRow[]>();
  for (const row of measured) {
    bySource.set(row.source, [...(bySource.get(row.source) ?? []), row]);
  }

  return (
    <section className="proof-block">
      <h2>Hätten die Vorschläge getragen?</h2>
      <p className="plan-sub">
        Die Blöcke darüber messen, was die Maschine selbst handelt. Das hier misst die Liste,
        die du zu sehen bekommst: jeder Vorschlag ab dem ersten Kurs, den du nach ihm wirklich
        hättest zahlen können, gegen den Heimatindex desselben Marktes.
        {data.n_measured !== undefined &&
          ` ${data.n_suggestions} Vorschläge, ${data.n_measured} Messungen.`}
      </p>

      {[...bySource.entries()].map(([source, rows]) => (
        <div key={source} className="plan-block">
          <h3>{SOURCE_TITLES[source] ?? source}</h3>
          {rows
            .sort((a, b) => a.horizon_days - b.horizon_days)
            .map((row) => (
              <HorizonRow key={row.horizon_days} row={row} />
            ))}
          {/* Der längste gemessene Horizont trägt den Urteilssatz: er ist der, über den man
              nach einem Screen-Vorschlag tatsächlich entscheidet. */}
          <p className="plan-sub">
            {rows.sort((a, b) => b.horizon_days - a.horizon_days)[0]?.line}
          </p>
        </div>
      ))}

      <p className="plan-sub">
        <b>Was hier fehlt:</b> Kosten. Gemessen sind Schlusskurse — Spread, Ordergebühr und bei
        ausländischen Titeln Wechselkurs sind nicht abgezogen. Bei kurzen Haltedauern kann das
        eine Überrendite dieser Größe ganz aufzehren.
        {data.missing_prices !== undefined && data.missing_prices.length > 0 &&
          ` Ohne Kursreihe und darum ungemessen: ${data.missing_prices.join(", ")}.`}
      </p>
      {data.computed_at && (
        <p className="plan-sub">
          Gemessen am {new Date(data.computed_at).toLocaleString("de-DE")}.
        </p>
      )}
    </section>
  );
}
