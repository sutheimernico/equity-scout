import { useCallback, useEffect, useState } from "react";

import { fetchJobs, startJob, type JobState } from "../api";
import { blockedText, describeProgress, formatMarker } from "../jobs";

// While something runs the panel is the only feedback there is, so it polls fast; idle it
// mostly waits. Both are far below the cheapest chain step, so this costs nothing real.
const POLL_RUNNING_MS = 5_000;
const POLL_IDLE_MS = 20_000;

const PHASE_LABELS: Record<string, string> = {
  scout: "Voll-Scout",
  daily: "Tages-Update",
  nightly: "Nachtlauf",
};

const JOB_NOTES: Record<string, string> = {
  daily:
    "Radar, Insights, Earnings, Evidenz, F-Score, Watchlist-Scoring, Auflösungen, Lanes, Digest. Dauert rund 26 Minuten und schickt am Ende den Telegram-Digest.",
  full:
    "Voll-Scout über das ganze Universum, danach Tages-Update, danach Nachtlauf (Training + Depot). Läuft je nach Universum ein bis mehrere Stunden.",
};

function JobCard({ job, now, onStarted }: { job: JobState; now: number; onStarted: () => void }) {
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  // Two-tap contract: the first tap on a blocked daily job (or on the hours-long full
  // refresh) only explains; the second one, with force, actually starts.
  const [armed, setArmed] = useState(false);

  const blocked = blockedText(job.blocked);
  // The full refresh IS the explicit "redo everything" button: unforced, each phase whose
  // marker is current would skip silently and the button would look broken.
  const alwaysForce = job.key === "full";

  async function start(force: boolean) {
    setPending(true);
    setMessage(null);
    try {
      const result = await startJob(job.key, force);
      if (result.status === 409) {
        setMessage(result.error ?? "Läuft bereits.");
      } else if (result.started === false) {
        setMessage(`${blockedText(result.reason ?? null)} Mit „Trotzdem starten" erzwingen.`);
        setArmed(true);
      } else if (result.status !== 200) {
        setMessage(result.error ?? `Fehler ${result.status}.`);
      } else {
        setMessage("Gestartet.");
        setArmed(false);
      }
      onStarted();
    } catch (error) {
      setMessage(`Start fehlgeschlagen: ${String(error)}`);
    } finally {
      setPending(false);
    }
  }

  const label = (() => {
    if (job.running) return "Läuft…";
    // The full card never says "Trotzdem" — it is not blocked, it is just expensive, so
    // its two taps read as "Alles neu laden" then "Wirklich alles neu laden".
    if (alwaysForce) return armed ? "Wirklich alles neu laden" : "Alles neu laden";
    if (armed || job.blocked !== null) return "Trotzdem starten";
    return "Jetzt starten";
  })();

  return (
    <section className="refresh-card">
      <header className="refresh-card-head">
        <h3>{job.label}</h3>
        <span className={job.running ? "refresh-state running" : "refresh-state"}>
          {describeProgress(job, now)}
        </span>
      </header>

      <p className="refresh-note">{JOB_NOTES[job.key]}</p>

      {job.sub_runs ? (
        <ul className="refresh-subruns">
          {Object.entries(job.sub_runs).map(([phase, marker]) => (
            <li key={phase}>
              <span>{PHASE_LABELS[phase] ?? phase}</span>
              <span>{formatMarker(marker)}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="refresh-last">Zuletzt gelaufen: {formatMarker(job.last_run)}</p>
      )}

      {blocked && !job.running && <p className="refresh-blocked">{blocked}</p>}

      <button
        className="refresh-button"
        disabled={pending || job.running}
        onClick={() => {
          if (alwaysForce && !armed) {
            setArmed(true);
            setMessage("Das lädt alles neu und läuft mehrere Stunden. Nochmal tippen zum Starten.");
            return;
          }
          void start(alwaysForce || armed);
        }}
      >
        {pending ? "…" : label}
      </button>

      {message && <p className="refresh-message">{message}</p>}

      {job.tail.length > 0 && (
        <details className="refresh-log">
          <summary>Log ansehen</summary>
          <pre>{job.tail.join("\n")}</pre>
        </details>
      )}
    </section>
  );
}

/** "Labor → Aktualisieren": start the data chains by hand and watch them run. */
export function RefreshPanel() {
  const [jobs, setJobs] = useState<JobState[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const load = useCallback(async () => {
    try {
      const response = await fetchJobs();
      setJobs(response.jobs);
      setError(null);
    } catch (e: unknown) {
      setError(String(e));
    }
  }, []);

  const anyRunning = jobs?.some((job) => job.running) ?? false;

  useEffect(() => {
    void load();
    const interval = window.setInterval(
      () => {
        setNow(Date.now());
        void load();
      },
      anyRunning ? POLL_RUNNING_MS : POLL_IDLE_MS,
    );
    return () => window.clearInterval(interval);
  }, [load, anyRunning]);

  if (error) return <p className="state err">Status nicht abrufbar: {error}</p>;
  if (jobs === null) return <p className="state">Lade Status…</p>;

  return (
    <div className="refresh-panel">
      <p className="refresh-note">
        Die Ketten laufen normalerweise nach Zeitplan (Tages-Update werktags 18:00, Nachtlauf 2:30,
        Voll-Scout montags 5:30). Hier startest du sie von Hand.
      </p>
      {jobs.map((job) => (
        <JobCard key={job.key} job={job} now={now} onStarted={load} />
      ))}
    </div>
  );
}
