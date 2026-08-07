import { useEffect, useState } from "react";

import { fetchProof, type ProofBook, type ProofResponse } from "../api";
import { ArenaPanel } from "./ArenaPanel";
import { AutoDepotPanel } from "./AutoDepotPanel";
import { KurzfristArenaPanel } from "./KurzfristArenaPanel";
import { OverviewPanel } from "./OverviewPanel";
import { PhoneDepot } from "./PhoneDepot";
import { Disclosure } from "./ui/Disclosure";
import { TimeContextBadge } from "./ui/TimeContextBadge";

type DepotSicht = "lang" | "kurz" | "du";

// 7 Depot-Tabs → 3 Sichten (mockup v2): Langfrist (Auto-Depot), Kurzfrist (Arena-Lanes),
// Du (Arena-Wettkampf). The research depots (Screener-Depot, Strategie-Forward, ML-Bots)
// moved to Mehr → Labor; the all-books overview keeps living here behind a disclosure —
// nothing deleted, only re-filed. Every Sicht opens with the honest "Funktioniert es?"
// header from /api/proof.
const SICHTEN: { key: DepotSicht; label: string }[] = [
  { key: "lang", label: "Langfrist" },
  { key: "kurz", label: "Kurzfrist" },
  { key: "du", label: "Du" },
];

/** The daily "läuft der Autopilot?" glance: measured days vs. the 60-day bar plus the
 *  verdict sentence, straight from /api/proof — never a promise. */
function FunktioniertEs({
  books,
  minDays,
}: {
  books: ProofBook[];
  minDays: number;
}) {
  if (books.length === 0) return null;
  return (
    <div className="depot-proof">
      <h2 className="brief-section-head">Funktioniert es?</h2>
      {books.map((book) => {
        const days = book.n_days ?? 0;
        const pct = Math.max(0, Math.min(100, (days / minDays) * 100));
        return (
          <div key={book.label} className="depot-proof-row">
            <div className="depot-proof-head">
              <span>{book.label}</span>
              {book.vs_benchmark_pct !== null && (
                <span
                  className={`tnum ${book.vs_benchmark_pct >= 0 ? "brief-good" : "brief-warn"}`}
                >
                  {book.vs_benchmark_pct >= 0 ? "+" : ""}
                  {book.vs_benchmark_pct.toFixed(1)} %-Pkt. vs. Markt
                </span>
              )}
            </div>
            <div className="why-meter" aria-hidden="true">
              <i style={{ width: `${pct}%` }} />
            </div>
            <p className="brief-muted depot-proof-verdict">
              Messtag {days} von {minDays} · {book.verdict_label}
            </p>
          </div>
        );
      })}
    </div>
  );
}

export function DepotsView({ onNavigate }: { onNavigate: (view: string) => void }) {
  const [sicht, setSicht] = useState<DepotSicht>("lang");
  const [proof, setProof] = useState<ProofResponse | null>(null);

  useEffect(() => {
    let ignore = false;
    fetchProof()
      .then((p) => {
        if (!ignore) setProof(p);
      })
      .catch(() => {
        /* the Sicht renders without the proof header */
      });
    return () => {
      ignore = true;
    };
  }, []);

  const books = proof?.books ?? [];
  const minDays = proof?.min_judge_days ?? 60;
  const langBooks = books.filter((b) => b.label === "Auto-Depot");
  const kurzBooks = books.filter((b) => b.label.startsWith("Arena "));

  return (
    <>
      <header className="section-head reveal">
        <p className="eyebrow">Depot</p>
        <h1>Drei Sichten, alles Papiergeld</h1>
        <p className="section-sub">
          Langfrist (ETF-Autopilot), Kurzfrist (Trading-Experiment) und „Du" (deine eigenen
          Käufe im Wettkampf gegen den Autopiloten). Alles Spielgeld zu echten Kursen, keine
          Anlageberatung.
        </p>
      </header>

      <div className="seg-switch" role="tablist" aria-label="Depot-Sicht">
        {SICHTEN.map((s) => (
          <button
            key={s.key}
            role="tab"
            aria-selected={sicht === s.key}
            className={sicht === s.key ? "seg-btn active" : "seg-btn"}
            onClick={() => setSicht(s.key)}
          >
            {s.label}
          </button>
        ))}
      </div>

      <div className="chip-row" style={{ marginBottom: "var(--space-3)" }}>
        <TimeContextBadge kind={sicht === "du" ? "paper" : "forward"} />
      </div>

      {sicht === "lang" && (
        <>
          <FunktioniertEs books={langBooks} minDays={minDays} />
          <PhoneDepot fixedBook="long" />
          {/* "Wonach kauft der?" spelled out per Sicht (Nico 2026-08-08: three things
              called Autopilot next to each other read as one confusing thing). */}
          <article className="wie-card">
            <h2>Wonach kauft der Langfrist-Autopilot?</h2>
            <p>
              Er verteilt das Geld nach festen Regeln auf ETFs — mehrere Regelwerke,
              gewichtet nach ihrer bisherigen Güte — schichtet regelmäßig um und fährt bei
              Marktstress automatisch das Risiko herunter. Einzelaktien kauft er nie: Die
              Vorschläge aus „Aktien" und „Entscheiden" fließen hier nicht ein.
            </p>
          </article>
          <Disclosure summary="Alle Details: Gewichte, Trades, Schutzmechanismen">
            <AutoDepotPanel />
          </Disclosure>
        </>
      )}
      {sicht === "kurz" && (
        <>
          <FunktioniertEs books={kurzBooks} minDays={minDays} />
          <PhoneDepot fixedBook="day" />
          <article className="wie-card">
            <h2>Wonach handeln die Kurzfrist-Taktiken?</h2>
            <p>
              Drei feste Regelwerke mit je eigenem Spielgeld: <b>Ereignis-Trades</b> kaufen
              nach überraschend guten Quartalszahlen und halten Tage. <b>Tages-Handel</b>{" "}
              handelt Ausbrüche nach US-Börsenstart über ein echtes Broker-Testkonto —
              abends wird alles verkauft. <b>Krypto</b> folgt Ausbrüchen bei Bitcoin &amp;
              Co., rund um die Uhr. Auch hier: keine Scout-Vorschläge, eigene Regeln.
            </p>
          </article>
          <Disclosure summary="Alle Details: Lanes, Statistiken, Promotion-Messlatte">
            <KurzfristArenaPanel />
          </Disclosure>
        </>
      )}
      {sicht === "du" && (
        <>
          <article className="wie-card">
            <h2>Du gegen den Vergleichs-Autopiloten</h2>
            <p>
              Dein Gegner hier heißt auch „Autopilot" — ist aber <b>nicht</b> der
              ETF-Autopilot aus „Langfrist". Er ist dein automatischer Zwilling: Er kauft
              selbstständig jeden Scout-Vorschlag, der in der Einstiegszone liegt und gut
              genug bewertet ist. Du entscheidest dieselben Vorschläge von Hand unter
              „Entscheiden". Gleiches Startkapital, gleiche Regeln — der Vergleich misst,
              ob deine Auswahl die Automatik schlägt.
            </p>
          </article>
          <ArenaPanel embedded />
        </>
      )}

      <Disclosure summary="Alle Depots im Überblick (inkl. Forschungs-Depots)">
        <OverviewPanel />
        <p className="brief-muted">
          Die Forschungs-Depots (Screener-Depot, Strategie-Forward, ML-Bots) wohnen unter
          Mehr → Labor.
        </p>
      </Disclosure>

      <button className="stock-more" onClick={() => onNavigate("ergebnisse")}>
        Ausführliche Auswertung → Ergebnisse
      </button>
    </>
  );
}
