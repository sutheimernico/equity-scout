import { Fragment, useEffect, useState } from "react";

import { decidePitch, fetchInbox, type InboxResponse, type Pitch } from "../api";
import { companyNameFromPitch, shortCompanyName } from "../company";
import { toPercent } from "../format";
import { isUnrated, sortByVerdict } from "../inbox";
import { StockLogo } from "./StockLogo";
import { DisclaimerBar } from "./ui/DisclaimerBar";
import { Disclosure } from "./ui/Disclosure";

// ISO timestamp → compact "YYYY-MM-DD HH:MM" (backend emits tz-aware isoformat).
function formatStamp(iso: string): string {
  return iso.slice(0, 16).replace("T", " ");
}

// The pitches table stores only the ticker, but pitch.py writes "📈 <TICKER> — <NAME>" as
// the text's first line, so the company name is recoverable without a schema migration.
// null when the format does not match — the ticker is then shown alone rather than a guess.
function pitchName(pitch: Pitch): string | null {
  const name = companyNameFromPitch(pitch.pitch, pitch.ticker);
  return name === null ? null : shortCompanyName(name);
}

// Decided-outcome badge: label + color class (buy=grün, pass=rot, later=grau).
const OUTCOME: Record<Exclude<Pitch["status"], "open">, { label: string; cls: string }> = {
  buy: { label: "Gekauft", cls: "pitch-badge--buy" },
  pass: { label: "Abgelehnt", cls: "pitch-badge--pass" },
  later: { label: "Später", cls: "pitch-badge--later" },
};

// v8 verdict badge — same wording as the Telegram pitch so both surfaces agree.
const VERDICT: Record<NonNullable<Pitch["verdict"]>, { label: string; cls: string }> = {
  green: { label: "🟢 Einstieg attraktiv", cls: "verdict-badge--green" },
  yellow: { label: "🟡 Einstieg neutral", cls: "verdict-badge--yellow" },
  red: { label: "🔴 Einstieg schwach", cls: "verdict-badge--red" },
};

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

  // Best entry first (Nico 2026-08-06). The bands themselves come from the server
  // (pitch.compute_verdict) — this only orders them; see ../inbox.ts.
  const pitches = sortByVerdict(data.pitches);

  return (
    <>
      <header className="section-head reveal">
        <p className="eyebrow">Inbox</p>
        <h1>Entscheidungen — ein Tipp pro Pitch</h1>
        <p className="section-sub">
          Offene Pitches zuerst. Jede Entscheidung ist eine Papier-Notiz, kein realer Handel und
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
            // Unrated pitches are a GROUP, not the weakest band: the heading says the rating is
            // missing rather than letting the reader infer a bad one (Nico 2026-08-06).
            const opensUnrated = isUnrated(p) && (index === 0 || !isUnrated(pitches[index - 1]!));
            return (
              <Fragment key={p.id}>
              {opensUnrated && (
                <h3 className="inbox-group">
                  Ohne Bewertung — für diese Titel fehlt ein Einstiegs-Score
                </h3>
              )}
              <article className="panel pitch">
                <div className="pitch-head">
                  <StockLogo ticker={p.ticker} name={pitchName(p) ?? p.ticker} />
                  <span className="pitch-ident">
                    {/* The company name is what identifies a holding; the ticker is the
                        lookup key. Both, name first — a bare 9064.T means nothing. */}
                    <span className="pitch-company">{pitchName(p) ?? p.ticker}</span>
                    <span className="ticker">{p.ticker}</span>
                  </span>
                  <span className="pitch-score tnum">{toPercent(p.composite)}</span>
                  {p.verdict && (
                    <span className={`badge pitch-badge ${VERDICT[p.verdict].cls}`}>
                      {VERDICT[p.verdict].label}
                    </span>
                  )}
                  {p.status !== "open" && (
                    <span className={`badge pitch-badge ${OUTCOME[p.status].cls}`}>
                      {OUTCOME[p.status].label}
                    </span>
                  )}
                </div>

                {p.verdict_why && <p className="pitch-verdict-why">{p.verdict_why}</p>}

                <div className="pitch-meta">
                  <span className="nobr">
                    Kurs <span className="tnum">{p.price}</span>
                  </span>
                  <span className="nobr">
                    Zone{" "}
                    <span className="tnum">
                      {p.zone_low}–{p.zone_high}
                    </span>
                  </span>
                  <span className="nobr">{formatStamp(p.created_at)}</span>
                </div>

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
                    <p className="pitch-decided">Entschieden {formatStamp(p.decided_at)}</p>
                  )
                )}

                {inlineErrors[p.id] && (
                  <p className="pitch-error" role="alert">
                    {inlineErrors[p.id]}
                  </p>
                )}

                <Disclosure summary="Ausführliche Begründung">
                  <p className="pitch-text">{p.pitch}</p>
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
