import { useState } from "react";

import { askChat } from "../api";
import { Explain } from "./ui/Explain";

interface Msg {
  role: "user" | "assistant" | "error";
  content: string;
}

const EXAMPLES = [
  "Welche Strategie hat den besten Sharpe?",
  "Was sagt der PBO-Wert über das Auto-Research?",
  "Wie läuft der Forward-Track im Vergleich zum Benchmark?",
];

export function ChatPanel() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  const ask = async (question: string) => {
    const q = question.trim();
    if (!q || loading) return;
    setMessages((m) => [...m, { role: "user", content: q }]);
    setInput("");
    setLoading(true);
    try {
      const reply = await askChat(q);
      setMessages((m) => [
        ...m,
        reply.error
          ? { role: "error", content: reply.error }
          : { role: "assistant", content: reply.answer ?? "(leere Antwort)" },
      ]);
    } catch {
      setMessages((m) => [...m, { role: "error", content: "Anfrage fehlgeschlagen." }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <header className="section-head">
        <p className="eyebrow">Assistent</p>
        <h1>Frag deine Daten</h1>
        <p className="section-sub">
          Ein lokaler Chatbot (über <strong>Ollama</strong>) beantwortet Fragen zu den aktuellen
          Dashboard-Zahlen — Strategien, ML-Modell, Auto-Research, Forward-Track. Läuft komplett lokal,
          nichts verlässt den Rechner. Keine Anlageberatung.
        </p>
      </header>

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
            {m.content}
          </div>
        ))}
        {loading && <div className="chat-msg chat-assistant muted">denkt nach…</div>}
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
