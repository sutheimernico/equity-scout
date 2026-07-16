import { useEffect, useState } from "react";

import { decidePitch, fetchInbox, type InboxResponse, type Pitch } from "../api";
import { toPercent } from "../format";
import { DisclaimerBar } from "./ui/DisclaimerBar";

// ISO timestamp → compact "YYYY-MM-DD HH:MM" (backend emits tz-aware isoformat).
function formatStamp(iso: string): string {
  return iso.slice(0, 16).replace("T", " ");
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

  const pitches = data.pitches;

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
          {pitches.map((p) => {
            const busy = pending.has(p.id);
            return (
              <article className="panel pitch" key={p.id}>
                <div className="pitch-head">
                  <span className="ticker">{p.ticker}</span>
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

                <p className="pitch-text">{p.pitch}</p>

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
              </article>
            );
          })}
        </div>
      )}

      <DisclaimerBar text={data.disclaimer} />
    </>
  );
}
