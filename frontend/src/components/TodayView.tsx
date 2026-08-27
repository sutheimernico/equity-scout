import { useEffect, useState } from "react";

import {
  fetchArena,
  fetchBriefs,
  fetchEvidence,
  fetchInbox,
  fetchProof,
  fetchRunHistory,
  type ArenaResponse,
  type EvidenceResponse,
  type InboxResponse,
  type ProofResponse,
  type RunSummary,
  type StockBrief,
} from "../api";
import { alertClaim } from "../alerts";
import { shortCompanyName } from "../company";
import { pct } from "../format";
import { DisclaimerBar } from "./ui/DisclaimerBar";
import { RegimeCard } from "./RegimeCard";
import { TodayAction } from "./TodayAction";
import { StockCard } from "./AktienView";

// The 3-minute briefing (mockup v2), answering Alex's daily questions in order:
// Wie ist die Lage? → Gibt's was Interessantes? → Muss ich was entscheiden? →
// Läuft mein Autopilot? → Was ist passiert? Every block degrades independently —
// a missing data source renders an honest placeholder, never a fake number.
export function TodayView({
  onNavigate,
  onOpenStock,
}: {
  onNavigate: (view: string) => void;
  onOpenStock: (ticker: string) => void;
}) {
  const [briefs, setBriefs] = useState<StockBrief[] | null>(null);
  const [inbox, setInbox] = useState<InboxResponse | null>(null);
  const [arena, setArena] = useState<ArenaResponse | null>(null);
  const [proof, setProof] = useState<ProofResponse | null>(null);
  const [evidence, setEvidence] = useState<EvidenceResponse | null>(null);
  const [runs, setRuns] = useState<RunSummary[] | null>(null);

  useEffect(() => {
    let ignore = false;
    const guard = <T,>(setter: (v: T) => void) => (v: T) => {
      if (!ignore) setter(v);
    };
    fetchBriefs(3)
      .then((r) => {
        if (!ignore) setBriefs(r.briefs);
      })
      .catch(() => undefined);
    fetchInbox().then(guard(setInbox)).catch(() => undefined);
    fetchArena().then(guard(setArena)).catch(() => undefined);
    fetchProof().then(guard(setProof)).catch(() => undefined);
    fetchEvidence().then(guard(setEvidence)).catch(() => undefined);
    fetchRunHistory()
      .then((r) => {
        if (!ignore) setRuns(r.runs);
      })
      .catch(() => undefined);
    return () => {
      ignore = true;
    };
  }, []);

  const openPitches = (inbox?.pitches ?? []).filter((p) => p.status === "open");
  const alerts = (evidence?.recent_alerts ?? []).slice(0, 3);
  const lastRun = runs?.[0];

  // Autopilot three-liner from the proof books (Langfrist = Auto-Depot, Kurzfrist =
  // the arena lanes' mean — every lane starts with the same capital, so the mean IS
  // the book's return) plus the arena "Du" lane.
  const langBook = proof?.books?.find((b) => b.label === "Auto-Depot") ?? null;
  const kurzBooks = (proof?.books ?? []).filter((b) => b.label.startsWith("Arena "));
  const kurzReturns = kurzBooks
    .map((b) => b.total_return_pct)
    .filter((v): v is number => typeof v === "number");
  const kurzMean =
    kurzReturns.length > 0 ? kurzReturns.reduce((a, b) => a + b, 0) / kurzReturns.length : null;
  const duLane = (arena?.lanes ?? []).find((lane) => lane.lane === "nico") ?? null;

  return (
    <>
      {/* Die Antwort zuerst, der Überblick danach. Wer die App öffnet, will wissen, ob
          heute etwas zu tun ist — nicht als Schluss aus fünf Blöcken, sondern als Satz. */}
      <TodayAction onNavigate={onNavigate} />

      <RegimeCard />

      <h2 className="brief-section-head">
        Heute interessant
        <button className="stock-more profil-sect-link" onClick={() => onNavigate("aktien")}>
          Alle ansehen →
        </button>
      </h2>
      {briefs === null ? (
        <p className="brief-muted">lädt …</p>
      ) : briefs.length === 0 ? (
        <p className="brief-muted">Noch keine Watchlist — der Screener lief noch nicht.</p>
      ) : (
        <ul className="brief-list">
          {briefs.map((brief) => (
            <StockCard key={brief.ticker} brief={brief} onOpen={() => onOpenStock(brief.ticker)} />
          ))}
        </ul>
      )}

      <h2 className="brief-section-head">Zu entscheiden</h2>
      {openPitches.length > 0 ? (
        <button className="today-decide" onClick={() => onNavigate("entscheiden")}>
          <b>
            {openPitches.length === 1
              ? "Ein Vorschlag wartet auf dich"
              : `${openPitches.length} Vorschläge warten auf dich`}
          </b>
          <span className="brief-muted">
            Der Scout hat Kauf-Ideen für dein Depot „Du" vorbereitet — auch Ablehnen zählt.
          </span>
        </button>
      ) : (
        <p className="brief-muted">{inbox ? "Nichts offen." : "—"}</p>
      )}

      <h2 className="brief-section-head">
        Dein Autopilot
        <button className="stock-more profil-sect-link" onClick={() => onNavigate("depot")}>
          Zum Depot →
        </button>
      </h2>
      {/* The figure carries `num` (mobile keeps it on one line so no percentage ever breaks
          mid-number); the words beside it must NOT, or the whole line goes nowrap and runs
          off a 390 px screen — measured 2026-08-16: "im Schnitt über 3 Taktiken" was cut
          after "Taktike". */}
      <dl className="brief-detail">
        <dt>Langfrist (ETFs)</dt>
        <dd>
          {langBook?.total_return_pct != null ? (
            <>
              <span className="num">{pct(langBook.total_return_pct / 100)}</span> ·{" "}
              {(langBook.vs_benchmark_pct ?? 0) >= 0 ? "vor" : "hinter"} dem Markt
            </>
          ) : (
            "—"
          )}
        </dd>
        <dt>Kurzfrist (Trading)</dt>
        <dd>
          {kurzMean !== null ? (
            <>
              <span className="num">{pct(kurzMean / 100)}</span> · im Schnitt über{" "}
              {kurzBooks.length} Taktiken
            </>
          ) : (
            "—"
          )}
        </dd>
        <dt>Du (deine Käufe)</dt>
        <dd>
          {duLane ? (
            <>
              <span className="num">{pct(duLane.total_return)}</span> · Markt{" "}
              <span className="num">{pct(duLane.benchmark_return)}</span>
            </>
          ) : (
            "leer — noch kein Pitch gekauft"
          )}
        </dd>
      </dl>

      <h2 className="brief-section-head">Was passiert ist</h2>
      <section className="strat-block">
        {alerts.length === 0 ? (
          <p className="muted">Keine Evidenz-Alarme in letzter Zeit.</p>
        ) : (
          // Company first, ticker small behind it — same identity as the stock list, so the
          // same company looks the same everywhere. Without a name on file the ticker stands
          // alone; nothing is invented (Nico 2026-08-06: "Was ist V? Du musst da schon die
          // Aktien hinschreiben").
          alerts.map((alert, i) => (
            <p className="muted" key={i}>
              {alert.name ? (
                <>
                  <span className="alert-name">{shortCompanyName(alert.name)}</span>{" "}
                  <span className="ticker">{alert.ticker}</span>
                </>
              ) : (
                <span className="ticker">{alert.ticker}</span>
              )}{" "}
              — {alertClaim(alert.reasons?.[0] ?? "Alarm")}{" "}
              <span className="tnum">({String(alert.created_at ?? "").slice(0, 10)})</span>
            </p>
          ))
        )}
        <p className="muted">
          {lastRun
            ? `Letzter Scout-Lauf: ${lastRun.created_at.slice(0, 10)} über ${lastRun.universe_size} Titel.`
            : "Noch kein Scout-Lauf gespeichert."}
        </p>
      </section>

      {/* "Direkt weiter" and the disclaimer bar are desktop-only (2026-08-06): the phone
          has the bottom tab bar for navigation, so a second set of jump links is a
          duplicate, and a paragraph of legal prose is not what a daily glance is for. */}
      <div className="only-desktop">
        <section className="strat-block">
          <h3 className="block-title">Direkt weiter</h3>
          <div className="tabbar wrap">
            <button className="tab" onClick={() => onNavigate("entscheiden")}>
              → Entscheiden {openPitches.length > 0 ? `(${openPitches.length})` : ""}
            </button>
            <button className="tab" onClick={() => onNavigate("aktien")}>
              → Aktien
            </button>
            <button className="tab" onClick={() => onNavigate("depot")}>
              → Depot
            </button>
            <button className="tab" onClick={() => onNavigate("labor")}>
              → Labor
            </button>
          </div>
        </section>

        {evidence && <DisclaimerBar text={evidence.disclaimer} />}
      </div>
    </>
  );
}
