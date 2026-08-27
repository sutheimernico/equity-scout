import { useEffect, useState } from "react";

import { fetchProof, type ProofBook, type ProofResponse } from "../api";
import { LANE_NOTES } from "../lanes";
import { HonestVerdict } from "./HonestVerdict";
import { RueckschauPanel } from "./RueckschauPanel";
import { Explain } from "./ui/Explain";
import { InfoIcon } from "./ui/InfoIcon";

// v12 P2, rebuilt 2026-08-06: the "kann das funktionieren?"-view as ONE plain question per
// block instead of a seven-column table (which the phone cut off after column three — the
// visible columns were exactly the "—" ones, so the page read as empty, Nico: "da checkt
// man auch gar nix"). Every metric that cannot be computed yet stays an honest absence;
// the under-60-days gate (proof.MIN_DAYS_FOR_RATES) is rendered as measuring PROGRESS with
// a date, never weakened.

// What each book actually is, in plain German. The Arena lanes reuse LANE_NOTES so the
// wording here can never drift from the Depot tab's lane cards.
function bookNote(label: string): string | null {
  if (label.startsWith("Auto-Depot")) {
    return "Das Langfrist-Papierdepot, das der Autotrader nach den Wochen-Scores führt.";
  }
  if (label.includes("Event-Swing")) return LANE_NOTES.swing.what;
  if (label.includes("Intraday-Session")) return LANE_NOTES.session.what;
  if (label.includes("Crypto")) return LANE_NOTES.crypto.what;
  if (label.startsWith("ML Long Bot")) {
    return "Der tägliche ML-Test: kauft auf dem Papier die Titel, die der Signal-Filter vorn sieht.";
  }
  return null;
}

function benchmarkName(label: string): string {
  if (label.includes("BTC")) return "Bitcoin";
  return "der Markt (S&P 500)";
}

function signedPoints(value: number): string {
  const rounded = Math.abs(value).toFixed(1).replace(".", ",");
  return `${rounded} Prozentpunkte`;
}

function fmtPct(value: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toFixed(1).replace(".", ",")} %`;
}

/** "noch N Tage, Urteil ab ~DD.MM." — the honest gate framed as progress, not as failure. */
function judgeEta(daysLeft: number): string {
  const eta = new Date(Date.now() + daysLeft * 86_400_000);
  const dd = String(eta.getDate()).padStart(2, "0");
  const mm = String(eta.getMonth() + 1).padStart(2, "0");
  return `${dd}.${mm}.`;
}

/** One question, one answer line, optional ⓘ explainer that folds open below. */
function QuestionRow({
  question,
  answer,
  explain,
}: {
  question: string;
  answer: string;
  explain?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="proof-q">
      <p className="proof-q-question">
        {question}
        {explain && (
          <button
            type="button"
            className="proof-q-info"
            aria-label={`Erklärung: ${question}`}
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
          >
            <InfoIcon />
          </button>
        )}
      </p>
      <p className="proof-q-answer">{answer}</p>
      {open && explain && <p className="proof-q-explain">{explain}</p>}
    </div>
  );
}

function BookCard({ book, minJudgeDays }: { book: ProofBook; minJudgeDays: number }) {
  const note = bookNote(book.label);
  const bench = benchmarkName(book.label);
  const enoughDays = book.n_days >= minJudgeDays;

  // vs_benchmark_pct = book minus benchmark over the same period, in percentage points.
  const vsMarket =
    book.total_return_pct !== null && book.vs_benchmark_pct !== null
      ? `Dieses Buch: ${fmtPct(book.total_return_pct)} · ${bench} im selben Zeitraum: ` +
        `${fmtPct(book.total_return_pct - book.vs_benchmark_pct)} — bisher ` +
        `${signedPoints(book.vs_benchmark_pct)} ${book.vs_benchmark_pct >= 0 ? "vorn" : "dahinter"}.`
      : "Noch nicht messbar.";

  const drawdown =
    book.max_drawdown_pct !== null
      ? `Größter zwischenzeitlicher Rückgang: −${Math.abs(book.max_drawdown_pct).toFixed(1).replace(".", ",")} %.`
      : "Noch nicht messbar.";

  // NOT format.pct(): that prefixes a sign, and "+50 % der Trades" reads as a gain figure
  // when it is a share of a count.
  const winRate =
    book.realized_win_rate !== null
      ? `${Math.round(book.realized_win_rate * 100)} % der abgeschlossenen Trades endeten im Plus.`
      : "Noch keine abgeschlossenen Trades.";

  const costs =
    book.cost_share_of_pnl !== null
      ? `Mindestens ${Math.round(book.cost_share_of_pnl * 100)} % des Handelsgewinns gingen für Gebühren und Spanne drauf.`
      : "Noch nicht messbar (braucht abgeschlossene Trades mit Gewinn).";

  return (
    <section className="strat-block proof-book">
      <h3>{book.label}</h3>
      {note && <p className="proof-book-note">{note}</p>}
      {book.period && (
        <p className="section-sub">
          Gemessen seit {book.period.split("–")[0].trim()} ({book.n_days} Tage)
        </p>
      )}

      {/* The measuring progress FIRST: it explains every "noch nicht" below it. */}
      {!enoughDays && (
        <div className="proof-progress">
          <div
            className="proof-progress-bar"
            role="progressbar"
            aria-valuenow={book.n_days}
            aria-valuemin={0}
            aria-valuemax={minJudgeDays}
          >
            <span style={{ width: `${Math.min(100, (book.n_days / minJudgeDays) * 100)}%` }} />
          </div>
          <p className="proof-progress-note">
            Messtag {book.n_days} von {minJudgeDays} — ein erstes Urteil (Rendite pro Jahr,
            Risiko-Kennzahl) gibt es ab ~{judgeEta(minJudgeDays - book.n_days)}. Bis dahin wären
            diese Zahlen Rauschen, keine Aussage.
          </p>
        </div>
      )}

      <QuestionRow
        question={`Hat es mehr gebracht, als einfach ${bench.startsWith("Bitcoin") ? "Bitcoin" : "den Markt"} zu kaufen?`}
        answer={vsMarket}
        explain={`Der ehrlichste Vergleich: dieselbe Zeit, dasselbe Geld — einmal dieses Buch, einmal einfach ${bench} kaufen und halten. Nur wenn das Buch dauerhaft vorn liegt, leistet es etwas.`}
      />
      <QuestionRow
        question="Wie viel ging zwischenzeitlich verloren?"
        answer={drawdown}
        explain="„Maximaler Drawdown“: der tiefste Punkt unter einem früheren Höchststand. Sagt, wie unangenehm die Fahrt bisher war — nicht, wie sie endet."
      />
      <QuestionRow question="Wie oft war ein abgeschlossener Trade im Plus?" answer={winRate} />
      <QuestionRow
        question="Wie viel fressen die Kosten?"
        answer={costs}
        explain="Untergrenze aus einem Kostenmodell (Gebühr + halbe Geld-Brief-Spanne), keine vollständige Realkosten-Messung — die echten Kosten liegen eher höher."
      />
      {enoughDays && (
        <p className="proof-verdict">
          <b>{book.vs_benchmark_pct !== null && book.vs_benchmark_pct > 0 ? "🟢" : "🔴"} {book.verdict_label}</b>
        </p>
      )}
    </section>
  );
}

export function ProofView() {
  const [data, setData] = useState<ProofResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let ignore = false;
    fetchProof()
      .then((d) => {
        if (!ignore) setData(d);
      })
      .catch((e: unknown) => {
        if (!ignore) setError(String(e));
      });
    return () => {
      ignore = true;
    };
  }, []);

  if (error) return <p className="state err">Fehler: {error}</p>;
  if (!data) return <p className="state">Lädt…</p>;

  return (
    <>
      <header className="section-head reveal">
        <p className="eyebrow">Mehr · Ergebnisse</p>
        <h1>Kann das funktionieren?</h1>
        <p className="section-sub">
          Jedes Papier-Buch wird laufend gegen „einfach den Markt kaufen“ gemessen — hier steht,
          was die Messung bisher hergibt und was noch nicht.
        </p>
      </header>

      {/* Die Antwort zuerst. Wer sich erst durch acht Bücher liest, um sie selbst zu
          ziehen, zieht sie meistens gar nicht. */}
      <HonestVerdict />

      {data.conviction && (
        <Explain tone="hint">
          Was würde den Einsatz von echtem Geld rechtfertigen? Mindestens{" "}
          <b>{data.conviction.min_track_days} Tage</b> Track Record, nach Kosten{" "}
          <b>nicht hinter der Benchmark</b>, und ein maximaler Rückgang von höchstens{" "}
          <b>{Math.round(data.conviction.max_drawdown_ratio_vs_benchmark * 100)} %</b> des
          Benchmark-Rückgangs — Rendite liefert der Markt, die Maschine liefert Disziplin und
          Risikokontrolle. Und selbst dann bleibt es deine Entscheidung, nicht die des Systems.
        </Explain>
      )}

      {!data.available && (
        <p className="state">Noch keine Bücher mit genug Historie — die Ergebnisse wachsen täglich.</p>
      )}
      {data.books?.map((book) => (
        <BookCard key={book.label} book={book} minJudgeDays={data.min_judge_days ?? 60} />
      ))}

      {/* Die Gegenfrage zu den Büchern: was die VORSCHLAGSLISTE taugte. Sie steht darunter
          und nicht dazwischen — es sind zwei Fragen, keine gemeinsame Kennzahl. */}
      <RueckschauPanel />

      <Explain tone="hint">{data.disclaimer}</Explain>
    </>
  );
}
