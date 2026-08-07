import { useState } from "react";

import { askChatStream } from "../api";
import { Explain } from "./ui/Explain";

interface Msg {
  role: "user" | "assistant" | "error";
  content: string;
}

const EXAMPLES = [
  "Was empfiehlst du mir heute?",
  "Welche Strategie ist die beste?",
  "Wie hoch ist das KGV von Micron?",
  "Welche Mitglieder haben Intel gekauft?",
];

// `overlay` renders the compact header with a close button instead of the full
// section head — the panel now lives behind the FAB on every screen (mockup v2),
// where the big explainer would push the log below the fold.
export function ChatPanel({
  overlay = false,
  onClose,
}: {
  overlay?: boolean;
  onClose?: () => void;
}) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  const ask = async (question: string) => {
    const q = question.trim();
    if (!q || loading) return;
    // Die Assistenten-Nachricht wird leer angelegt und dann fortgeschrieben — so sieht
    // man die Antwort entstehen, statt 40 s auf einen Spinner zu schauen.
    setMessages((m) => [...m, { role: "user", content: q }, { role: "assistant", content: "" }]);
    setInput("");
    setLoading(true);
    try {
      await askChatStream(q, (chunk) => {
        setMessages((m) => {
          const next = [...m];
          const last = next[next.length - 1]!;
          next[next.length - 1] = { ...last, content: last.content + chunk };
          return next;
        });
      });
    } catch {
      setMessages((m) => [...m, { role: "error", content: "Anfrage fehlgeschlagen." }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      {overlay ? (
        <header className="chat-overlay-head">
          <button className="stock-more" onClick={onClose}>
            ‹ Schließen
          </button>
          <span className="chat-overlay-title">Assistent</span>
          <span className="brief-muted">lokale KI</span>
        </header>
      ) : (
        <header className="section-head">
          <p className="eyebrow">Assistent</p>
          <h1>Frag deine Daten</h1>
          <p className="section-sub">
            Ein lokaler Chatbot (über <strong>Ollama</strong>) beantwortet Fragen zu jeder Aktie
            im Bestand — Kennzahlen wie KGV und Marge, wer gekauft hat (Kongress, Fonds,
            Stimmen), Einstiegs-Score, Pitches, Depots, Marktlage und Ergebnisse. Auf Wunsch
            gibt er dir eine klare, aus deinen Daten begründete Einschätzung — samt Risiko und
            der Bedingung, ab der sie kippt. Läuft komplett lokal, nichts verlässt den Rechner;
            alles Papier-Recherche, entscheiden tust du.
          </p>
        </header>
      )}

      <div className="chat-log">
        {messages.length === 0 && (
          <div className="chat-examples">
            <Explain tone="hint">Probier eine Frage:</Explain>
            {EXAMPLES.map((ex) => (
              <button key={ex} type="button" className="chat-example" onClick={() => ask(ex)}>
                {ex}
              </button>
            ))}
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`chat-msg chat-${m.role}`}>
            {/* Die leere Assistenten-Blase entsteht beim Start des Streams. Bis das erste
                Wort kommt, liest das lokale Modell den Datenkontext — auf CPU dauert das
                bei Aktienfragen gemessen 60–80 s, und eine leere Blase sähe wie ein Fehler
                aus. */}
            {m.content || (m.role === "assistant" ? "liest die Daten…" : "")}
          </div>
        ))}
      </div>

      <form
        className="chat-input"
        onSubmit={(e) => {
          e.preventDefault();
          ask(input);
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Frage zu den Dashboard-Daten…"
          aria-label="Frage an den Assistenten"
        />
        <button type="submit" disabled={loading || !input.trim()}>
          Fragen
        </button>
      </form>
    </>
  );
}
