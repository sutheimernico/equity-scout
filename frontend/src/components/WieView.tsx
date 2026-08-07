import { useEffect, useState } from "react";

import { fetchRunHistory, type RunSummary } from "../api";

// "Mehr → Wie funktioniert das?" (mockup v2, NEW): the app in a handful of plain
// answers — the funnel graphic replaces methodology prose. Numbers in the funnel are
// the REAL ones from the last scout run; while they load (or without a run yet) the
// rows show an honest dash, never invented counts.

function funnelRows(run: RunSummary | null): { label: string; value: string }[] {
  const de = (n: number) => n.toLocaleString("de-DE");
  const picks = run ? Object.values(run.picks).reduce((sum, list) => sum + list.length, 0) : null;
  return [
    { label: "Aktien weltweit geprüft", value: run ? de(run.universe_size) : "—" },
    {
      label: "Daten vollständig & Qualitäts-Gates bestanden",
      value: run ? de(Math.max(0, run.universe_size - run.total_gated)) : "—",
    },
    { label: "Deine Vorschläge nach dem letzten Lauf", value: picks === null ? "—" : de(picks) },
  ];
}

export function WieView() {
  const [run, setRun] = useState<RunSummary | null>(null);

  useEffect(() => {
    let ignore = false;
    fetchRunHistory()
      .then((r) => {
        if (!ignore) setRun(r.runs[0] ?? null);
      })
      .catch(() => {
        /* the funnel keeps its dashes */
      });
    return () => {
      ignore = true;
    };
  }, []);

  const rows = funnelRows(run);

  return (
    <>
      <header className="section-head reveal">
        <p className="eyebrow">Mehr · Wie funktioniert das?</p>
        <h1>Die App in sechs Antworten</h1>
        <p className="section-sub">
          Alles hier ist Recherche mit Papiergeld, keine Anlageberatung.
        </p>
      </header>

      <article className="wie-card">
        <h2>Woher kommen die Aktien-Vorschläge?</h2>
        <div className="wie-funnel" role="img" aria-label="Auswahltrichter des Scouts">
          {rows.map((row, i) => (
            <div key={row.label} className={i === rows.length - 1 ? "wie-step last" : "wie-step"}>
              <span>{row.label}</span>
              <span className="tnum">{row.value}</span>
            </div>
          ))}
        </div>
        <p>
          Läuft automatisch: Qualitäts-Check (verdient die Firma solide Geld?), dann
          Preis-Check (ist der Kurs gerade attraktiv?). Kein Mensch wählt aus, keine bezahlten
          Empfehlungen.
        </p>
      </article>

      <article className="wie-card">
        <h2>Was bedeutet „Potenzial"?</h2>
        <p>
          <b>Analysten-Ziel:</b> der Durchschnitt der Kursziele von Banken-Analysten, die die
          Aktie beobachten.
          <br />
          <b>Scout-Ziel:</b> unsere eigene Berechnung aus Kursverlauf und Schwankung — bewusst
          vorsichtiger.
          <br />
          Beides sind Schätzungen, keine Versprechen. Deshalb steht daneben immer eine
          Absicherung (Stop): der Kurs, ab dem die Idee als gescheitert gilt.
        </p>
      </article>

      <article className="wie-card">
        <h2>Was macht der Autopilot?</h2>
        <p>
          <b>Langfrist:</b> verteilt Geld nach festen Regeln auf ETFs und schichtet regelmäßig
          um. Bei Marktstress reduziert er automatisch das Risiko.
          <br />
          <b>Kurzfrist:</b> schnelle Handels-Taktiken mit Spielgeld — ein Experiment, das sich
          erst beweisen muss. Wie es läuft, steht unter „Mehr → Ergebnisse".
        </p>
      </article>

      <article className="wie-card">
        <h2>Ist das echtes Geld?</h2>
        <p>
          Nein. Alles läuft mit <b>Papiergeld zu echten Kursen</b> — auch deine Käufe. Die App
          misst ehrlich, was funktioniert und was nicht (siehe „Ergebnisse"). Erst wenn eine
          Strategie über Monate überzeugt, wäre echtes Geld überhaupt ein Thema.
        </p>
      </article>

      <article className="wie-card">
        <h2>Welche Modelle arbeiten im Hintergrund?</h2>
        <p>
          Drei — und sie laufen immer, egal welche Seite du ansiehst:
          <br />
          <b>1. Auswahl-Modell:</b> bewertet jede Nacht tausende Aktien nach Qualität und Preis —
          daraus entstehen die Vorschläge.
          <br />
          <b>2. KI-Zweitmeinung:</b> lernt aus ehrlich aufgelösten früheren Fällen, welche
          Signale wirklich funktionieren, und gibt jeder Aktie 0–100 Punkte.
          <br />
          <b>3. Auto-Research:</b> testet nachts neue Strategie-Ideen gegen strenge Hürden,
          damit kein Zufallstreffer durchrutscht.
          <br />
          Ob sie mit der Zeit besser werden, siehst du unter „Mehr → Labor".
        </p>
      </article>

      <article className="wie-card">
        <h2>Woher weiß die App, wer kauft?</h2>
        <p>
          US-Politiker, Firmen-Insider und große Fonds müssen ihre Käufe offiziell melden
          (SEC-Pflichtmeldungen). Der Scout liest diese Meldungen automatisch — oft Wochen
          verzögert, das steht ehrlich dabei — und prüft rückwirkend, wessen Käufe sich bisher
          gelohnt haben.
        </p>
      </article>
    </>
  );
}
