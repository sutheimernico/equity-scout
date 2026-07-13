import { useState } from "react";

import { fetchStack, type StackResponse } from "../api";
import { toPercent } from "../format";

const SOURCE_LABELS: Record<string, string> = {
  congress: "Kongress",
  thirteen_f: "13F-Fonds",
  insider: "Insider (Form 4)",
  news_theme: "News-Thema",
  voice: "Stimme",
};

// Per-ticker signal stack (plan v6 P6): every signal layer side by side, lazy-loaded on
// first open. Absent layers say so — an honest "keine" beats a fabricated neutral.
export function SignalStackBlock({ ticker }: { ticker: string }) {
  const [data, setData] = useState<StackResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const load = () => {
    setOpen(true);
    if (data || error) return;
    fetchStack(ticker)
      .then(setData)
      .catch((e: unknown) => setError(String(e)));
  };

  if (!open) {
    return (
      <button className="tab stack-toggle" onClick={load}>
        Signal-Stack anzeigen
      </button>
    );
  }
  if (error) return <p className="state err">Fehler: {error}</p>;
  if (!data) return <p className="state">Lädt…</p>;

  return (
    <div className="stack-block">
      <p className="stack-line">
        <b>Faktor-Screen:</b>{" "}
        {data.screener
          ? `${data.screener.bucket}-Bucket, Composite ${
              data.screener.composite != null ? toPercent(data.screener.composite) : "—"
            } (Lauf ${data.screener.run_created_at?.slice(0, 10) ?? "?"})`
          : "nicht unter den aktuellen Screener-Picks"}
      </p>
      <p className="stack-line">
        <b>Radar-Composite:</b>{" "}
        {data.radar
          ? `${toPercent(data.radar.composite)}${data.radar.in_zone ? " · in der Einstiegszone" : ""}`
          : "nicht auf der Watchlist"}
      </p>
      <p className="stack-line">
        <b>ML-Score:</b>{" "}
        {data.ml
          ? `${data.ml.score}/100 (Modell v${data.ml.model_version}, Stand ${data.ml.created_at.slice(0, 10)}) — kalibrierte Wahrscheinlichkeit, keine Kursprognose`
          : "noch nie gescort (Score-Lauf läuft täglich)"}
      </p>
      <p className="stack-line">
        <b>Externe Evidenz (30 Tage):</b>{" "}
        {data.evidence_events.length === 0
          ? "keine Ereignisse"
          : data.evidence_events
              .map((e) => SOURCE_LABELS[e.source] ?? e.source)
              .filter((v, i, arr) => arr.indexOf(v) === i)
              .join(", ") + ` (${data.evidence_events.length} Ereignisse)`}
      </p>
      {data.person_scores.length > 0 && (
        <p className="stack-line">
          <b>Track-Records dazu:</b>{" "}
          {data.person_scores
            .filter((s) => s.scoreable && s.weighted_score != null)
            .map((s) => `${s.person} ${((s.weighted_score as number) * 100).toFixed(1)} %`)
            .join(" · ") || "keine gemessenen"}
        </p>
      )}
    </div>
  );
}
