import { Fragment, useEffect, useState } from "react";

import { decidePitch, fetchInbox, type InboxResponse, type Pitch } from "../api";
import { companyNameFromPitch, shortCompanyName } from "../company";
import { GROUP_HEADINGS, groupKey, sortByVerdict } from "../inbox";
import { PotentialBlock } from "./PotentialBlock";
import { StockLogo } from "./StockLogo";
import { DisclaimerBar } from "./ui/DisclaimerBar";
import { Disclosure } from "./ui/Disclosure";

// ISO timestamp → "16.07.2026". The old "2026-07-16 19:39" read as machine output, and
// the minute of a pitch never matters for the decision — the day does (a three-week-old
// pitch must be recognisable as one).
function pitchDate(iso: string): string {
  return `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}`;
}

function money(value: number, currency: string | null): string {
  const formatted = value.toLocaleString("de-DE", { maximumFractionDigits: 2 });
  return currency ? `${formatted} ${currency}` : formatted;
}

// The server-joined name (watchlist/run_scores) first; the pitch-text header is the
// fallback for tickers the server knows no name for. Ticker alone when both fail —
// never a guess.
function pitchName(pitch: Pitch): string | null {
  if (pitch.name) return shortCompanyName(pitch.name);
  const parsed = companyNameFromPitch(pitch.pitch, pitch.ticker);
  return parsed === null ? null : shortCompanyName(parsed);
}

// Decided-outcome badge: label + color class (buy=grün, pass=rot, later=grau).
const OUTCOME: Record<Exclude<Pitch["status"], "open">, { label: string; cls: string }> = {
  buy: { label: "Gekauft", cls: "pitch-badge--buy" },
  pass: { label: "Abgelehnt", cls: "pitch-badge--pass" },
  later: { label: "Später", cls: "pitch-badge--later" },
};

/** Today's entry state, same chip as the Heute list (StockList.ZoneChip) so the same
 *  fact looks the same everywhere. null zone_verdict (decided / off the watchlist)
 *  renders nothing — the meta line below carries the honest explanation. */
function TodayZoneChip({ pitch }: { pitch: Pitch }) {
  if (!pitch.zone_verdict) return null;
  const head = pitch.zone_verdict.split("—")[0].trim();
  const label = head.startsWith("im ") ? head.slice(3) : head;
  return (
    <span className={pitch.in_zone ? "brief-chip brief-chip-good" : "brief-chip brief-chip-warn"}>
      {pitch.in_zone ? "✓" : "⚠"} {label}
    </span>
  );
}

// The pitch text of every pitch since 2026-08-06 SAYS when no external signals were
// found. Older stored texts simply omitted the section — and by construction the section
// is present exactly when signals existed, so the absence can be stated honestly here.
function hasEvidenceSection(pitch: Pitch): boolean {
  return pitch.pitch.includes("Externe Signale:");
}

export function InboxPanel() {
  const [data, setData] = useState<InboxResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Pitch ids with an in-flight decision → all three buttons disabled while pending.
  const [pending, setPending] = useState<Set<number>>(() => new Set());
  // Per-pitch inline error (the 422 invalid-action path + network failures).
  const [inlineErrors, setInlineErrors] = useState<Record<number, string>>({});

  useEffect(() => {
    // `ignore` guards against a setState after the effect is torn down (unmount / refire).
    let ignore = false;
    fetchInbox()
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

  async function refetch() {
    try {
      setData(await fetchInbox());
    } catch (e: unknown) {
      setError(String(e));
    }
  }

  async function decide(id: number, action: "buy" | "pass" | "later") {
    setPending((prev) => new Set(prev).add(id));
    setInlineErrors((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
    try {
      const res = await decidePitch(id, action);
      if (res.ok && res.pitch) {
        const updated = res.pitch;
        setData((prev) =>
          prev ? { ...prev, pitches: prev.pitches.map((p) => (p.id === id ? updated : p)) } : prev,
        );
      } else if (res.status === 409) {
        // The receiver (Telegram) already decided this one — resync the whole inbox.
        await refetch();
      } else {
        // 422 (invalid action) or any other non-OK → surface the server message inline.
        setInlineErrors((prev) => ({
          ...prev,
          [id]: res.error ?? "Entscheidung fehlgeschlagen.",
        }));
      }
    } catch {
      setInlineErrors((prev) => ({ ...prev, [id]: "Netzwerkfehler — bitte erneut versuchen." }));
    } finally {
      setPending((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  }

  if (error) return <p className="state err">Fehler: {error}</p>;
  if (!data) return <p className="state">Lädt…</p>;

  // Open before decided, best band first, score descending inside a band (Nico
  // 2026-08-06). The bands come from the server (pitch.compute_verdict); see ../inbox.ts.
  const pitches = sortByVerdict(data.pitches);

  // A ticker can carry several open pitches (cooldown re-pitches) with DIFFERENT verdicts
  // — the same stock rated "neutral" and "schwach" two cards apart reads as a
  // contradiction unless the older card says a newer take exists. id order = pitch order.
  const newestOpenId = new Map<string, number>();
  for (const p of data.pitches) {
    if (p.status !== "open") continue;
    const known = newestOpenId.get(p.ticker);
    if (known === undefined || p.id > known) newestOpenId.set(p.ticker, p.id);
  }

  return (
    <>
      <header className="section-head reveal">
        <p className="eyebrow">Inbox</p>
        <h1>Entscheidungen — ein Tipp pro Pitch</h1>
        <p className="section-sub">
          Beste Einstiege zuerst. Jede Entscheidung ist eine Papier-Notiz, kein realer Handel und
          keine Anlageberatung.
        </p>
      </header>

      {pitches.length === 0 ? (
        <p className="state">
          Keine Pitches — <code>run_radar.py</code> erzeugt neue.
        </p>
      ) : (
        <div className="inbox-grid">
          {pitches.map((p, index) => {
            const busy = pending.has(p.id);
            const group = groupKey(p);
            // A heading opens every band, so the band-first order is READABLE — with the
            // score as the card's number, a hidden band order read as no order at all.
            const opensGroup = index === 0 || groupKey(pitches[index - 1]!) !== group;
            const score = Math.round(p.composite * 100);
            return (
              <Fragment key={p.id}>
              {opensGroup && (
                <div className="inbox-group">
                  <h3>{GROUP_HEADINGS[group].title}</h3>
                  <p className="inbox-group-sub">{GROUP_HEADINGS[group].sub}</p>
                </div>
              )}
              <article className="panel pitch">
                <div className="pitch-head">
                  <StockLogo ticker={p.ticker} name={pitchName(p) ?? p.ticker} />
                  <span className="pitch-ident">
                    {/* The company name is what identifies a holding; the ticker is the
                        lookup key. Both, name first — a bare 9064.T means nothing. */}
                    <span className="pitch-company">{pitchName(p) ?? p.ticker}</span>
                    <span className="ticker">{p.ticker}</span>
                    <TodayZoneChip pitch={p} />
                  </span>
                  {p.status === "open" ? (
                    <PotentialBlock upsidePct={p.analyst_upside_pct} analystCount={p.analyst_count} />
                  ) : (
                    <span className={`badge pitch-badge ${OUTCOME[p.status].cls}`}>
                      {OUTCOME[p.status].label}
                    </span>
                  )}
                </div>

                {p.verdict_why && <p className="pitch-verdict-why">{p.verdict_why}</p>}

                <div className="pitch-meta">
                  <span className="nobr">
                    Score <span className="tnum">{score}/100</span>
                  </span>
                  {p.current_price !== null ? (
                    <span className="nobr">
                      Kurs heute <span className="tnum">{money(p.current_price, p.currency)}</span>
                    </span>
                  ) : (
                    p.status === "open" && (
                      <span className="nobr">
                        Pitch-Kurs <span className="tnum">{money(p.price, null)}</span>
                      </span>
                    )
                  )}
                  <span className="nobr">Pitch vom {pitchDate(p.created_at)}</span>
                </div>

                {/* An open pitch whose ticker left the watchlist has NO current view —
                    said out loud instead of letting pitch-time numbers pass as today's. */}
                {p.status === "open" && p.current_price === null && (
                  <p className="pitch-stale">
                    Kein aktueller Kurs — der Titel steht nicht mehr auf der Beobachtungsliste.
                    Alle Zahlen stammen vom Pitch-Tag.
                  </p>
                )}

                {p.status === "open" && newestOpenId.get(p.ticker) !== p.id && (
                  <p className="pitch-stale">
                    Es gibt eine neuere Einschätzung zu diesem Titel — die Bewertung hier ist
                    der Stand vom {pitchDate(p.created_at)}.
                  </p>
                )}

                {/* Actions BEFORE the reasoning (2026-08-04): the full pitch text is ~20
                    lines, so on a phone the buttons used to sit below a wall of text and a
                    decision required scrolling past everything. Verdict, score, price and
                    zone above are enough to decide; the depth folds away. */}
                {p.status === "open" ? (
                  <div className="pitch-actions">
                    <button
                      type="button"
                      className="pitch-btn pitch-btn--buy"
                      onClick={() => decide(p.id, "buy")}
                      disabled={busy}
                    >
                      Kaufen
                    </button>
                    <button
                      type="button"
                      className="pitch-btn pitch-btn--pass"
                      onClick={() => decide(p.id, "pass")}
                      disabled={busy}
                    >
                      Ablehnen
                    </button>
                    <button
                      type="button"
                      className="pitch-btn pitch-btn--later"
                      onClick={() => decide(p.id, "later")}
                      disabled={busy}
                    >
                      Später
                    </button>
                  </div>
                ) : (
                  p.decided_at && (
                    <p className="pitch-decided">Entschieden am {pitchDate(p.decided_at)}</p>
                  )
                )}

                {inlineErrors[p.id] && (
                  <p className="pitch-error" role="alert">
                    {inlineErrors[p.id]}
                  </p>
                )}

                <Disclosure summary="Ausführliche Begründung">
                  <p className="pitch-text">{p.pitch}</p>
                  {!hasEvidenceSection(p) && (
                    <p className="pitch-evidence-none">
                      Externe Signale: keine gemeldet — kein Kongress-Handel, keine
                      Insider-Käufe, keine Fonds- oder Stimmen-Signale zu diesem Titel.
                    </p>
                  )}
                  {/* Why a high potential and a poor entry are not a contradiction —
                      same explainer the Heute list shows in its detail. */}
                  {p.entry_note && <p className="pitch-entry-note">{p.entry_note}</p>}
                </Disclosure>
              </article>
              </Fragment>
            );
          })}
        </div>
      )}

      <DisclaimerBar text={data.disclaimer} />
    </>
  );
}
