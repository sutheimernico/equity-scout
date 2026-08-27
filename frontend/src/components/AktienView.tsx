import { useEffect, useState } from "react";

import { filterBriefs, riskMeta, zoneSegment, type ZoneSegment } from "../aktien";
import { fetchBriefs, fetchRunHistory, type StockBrief } from "../api";
import { shortCompanyName } from "../company";
import { PotentialBlock } from "./PotentialBlock";
import { ZoneChip } from "./StockList";
import { KaufplanView } from "./KaufplanView";
import { StockLogo } from "./StockLogo";
import { Chevron } from "./ui/Chevron";

// The ONE stock list (mockup v2): replaces Screener + Radar + Heute-Stockliste as the
// place to browse proposals. Timing (radar zones) is the segment filter, the factor
// bucket is a visible risk chip, and every card opens the full stock profile — the
// three old lists' depth lives there, nothing is deleted.

const SEGMENTS: { key: ZoneSegment; label: string }[] = [
  { key: "in", label: "Kaufbereit" },
  { key: "near", label: "Fast" },
  { key: "all", label: "Alle" },
];

// Kaufplan zuerst (2026-08-27, Nicos Auftrag „ich hätte gerne so ein Aktiending in der
// View"): wer die Aktien-Ansicht öffnet, will wissen, was er kaufen soll und zu welchem
// Preis. Die Kurzliste bleibt daneben — sie ist der schnellere Überblick, wenn man nur
// scrollen will, und wurde nicht ersetzt.
const MODES: { key: "plan" | "liste"; label: string }[] = [
  { key: "plan", label: "Kaufplan" },
  { key: "liste", label: "Kurzliste" },
];

const STYLES: { key: string; label: string }[] = [
  { key: "alle", label: "Alle Stile" },
  { key: "defensive", label: "Defensiv" },
  { key: "balanced", label: "Ausgewogen" },
  { key: "aggressive", label: "Aggressiv" },
];

/** Exported: TodayView's "Heute interessant" renders the same card, so the two
 *  surfaces can never drift apart. */
export function StockCard({ brief, onOpen }: { brief: StockBrief; onOpen: () => void }) {
  const risk = riskMeta(brief.bucket);
  return (
    <li className="brief-row">
      <button className="brief-main" onClick={onOpen}>
        <StockLogo ticker={brief.ticker} name={brief.name} />
        <span className="brief-body">
          <span className="brief-name" title={brief.name}>
            {shortCompanyName(brief.name)}
          </span>
          <span className="stock-chiprow">
            <ZoneChip brief={brief} />
            {risk && <span className={risk.chip}>{risk.label}</span>}
          </span>
        </span>
        <PotentialBlock upsidePct={brief.analyst_upside_pct} analystCount={brief.analyst_count} />
        <Chevron />
      </button>
      <p className="stock-reason">{brief.entry_note}</p>
    </li>
  );
}

export function AktienView({
  onOpenStock,
  onNavigate,
}: {
  onOpenStock: (ticker: string) => void;
  onNavigate: (view: string) => void;
}) {
  const [briefs, setBriefs] = useState<StockBrief[] | null>(null);
  const [universe, setUniverse] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);
  const [segment, setSegment] = useState<ZoneSegment>("in");
  const [style, setStyle] = useState("alle");
  const [mode, setMode] = useState<"plan" | "liste">("plan");

  useEffect(() => {
    let ignore = false;
    // 20 is the backend's hard cap on the fundamentals fan-out, not a UI choice.
    fetchBriefs(20)
      .then((r) => {
        if (!ignore) setBriefs(r.briefs);
      })
      .catch(() => {
        if (!ignore) setFailed(true);
      });
    fetchRunHistory()
      .then((r) => {
        if (!ignore) setUniverse(r.runs[0]?.universe_size ?? null);
      })
      .catch(() => {
        /* the subline just omits the universe size */
      });
    return () => {
      ignore = true;
    };
  }, []);

  // Der Umschalter steht VOR jeder Ladeschranke: sonst wäre der Kaufplan unerreichbar,
  // sobald die Kurzliste hakt — und er ist die Ansicht, um die es hier geht.
  const modeSwitch = (
    <div className="seg-switch" role="tablist" aria-label="Ansicht">
      {MODES.map((m) => (
        <button
          key={m.key}
          role="tab"
          aria-selected={mode === m.key}
          className={mode === m.key ? "seg-btn active" : "seg-btn"}
          onClick={() => setMode(m.key)}
        >
          {m.label}
        </button>
      ))}
    </div>
  );

  if (mode === "plan") {
    return (
      <>
        {modeSwitch}
        <KaufplanView onNavigate={onNavigate} />
      </>
    );
  }

  if (failed) {
    return (
      <>
        {modeSwitch}
        <p className="brief-muted">Aktien-Daten nicht erreichbar.</p>
      </>
    );
  }
  if (briefs === null) {
    return (
      <>
        {modeSwitch}
        <p className="brief-muted">lädt …</p>
      </>
    );
  }
  if (briefs.length === 0) {
    return (
      <>
        {modeSwitch}
        <p className="brief-muted">Noch keine Watchlist — der Screener lief noch nicht.</p>
      </>
    );
  }

  // Counts respect the style filter, so the numbers always match what a tap shows.
  const styled = filterBriefs(briefs, "all", style);
  const counts = {
    in: styled.filter((b) => zoneSegment(b) === "in").length,
    near: styled.filter((b) => zoneSegment(b) === "near").length,
  };
  const visible = filterBriefs(briefs, segment, style);

  return (
    <section>
      {modeSwitch}
      <header className="section-head reveal">
        <p className="eyebrow">Aktien</p>
        <h1>Die Vorschläge des Scouts</h1>
        <p className="section-sub">
          {briefs.length} Vorschläge
          {universe !== null &&
            `, gefiltert aus ${universe.toLocaleString("de-DE")} Aktien weltweit`}
          . Antippen öffnet das volle Aktienprofil.
        </p>
      </header>

      <div className="seg-switch" role="tablist" aria-label="Einstiegs-Status">
        {SEGMENTS.map((s) => (
          <button
            key={s.key}
            role="tab"
            aria-selected={segment === s.key}
            className={segment === s.key ? "seg-btn active" : "seg-btn"}
            onClick={() => setSegment(s.key)}
          >
            {s.label}
            {s.key !== "all" && ` (${counts[s.key]})`}
          </button>
        ))}
      </div>

      <div className="style-chips" role="group" aria-label="Risikoprofil">
        {STYLES.map((s) => (
          <button
            key={s.key}
            className={style === s.key ? "chip-btn active" : "chip-btn"}
            aria-pressed={style === s.key}
            onClick={() => setStyle(s.key)}
          >
            {s.label}
          </button>
        ))}
      </div>

      {visible.length > 0 ? (
        <ul className="brief-list">
          {visible.map((brief) => (
            <StockCard key={brief.ticker} brief={brief} onOpen={() => onOpenStock(brief.ticker)} />
          ))}
        </ul>
      ) : (
        <p className="brief-muted">
          Kein Treffer mit diesen Filtern — Status oder Stil lockern.
          {segment === "in" &&
            " Heute liegt kein Titel in seiner Einstiegszone — das ist ein Ergebnis, kein Fehler."}
        </p>
      )}

      <p className="brief-muted">
        <b>Kaufbereit</b> heißt: Der Kurs liegt gerade in dem Bereich, den der Scout als guten
        Einstieg berechnet.
        <button className="stock-more" onClick={() => onNavigate("wie")}>
          Wie die Auswahl entsteht →
        </button>
      </p>
    </section>
  );
}
