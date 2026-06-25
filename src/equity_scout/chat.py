"""Local chatbot over the dashboard data via Ollama.

No RAG, no vector DB: the dashboard's numbers are small and structured, so we just fold a compact
snapshot of the current state into the prompt and let a local model answer from it. Talks to a local
Ollama server (localhost:11434 by default); if it isn't reachable, the caller gets a clear, honest
error instead of a hang. The system prompt keeps it grounded: answer from the data, no advice, no
price forecasts — the same honesty guardrails as every other surface.
"""
from __future__ import annotations

import os

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")

SYSTEM_PROMPT = (
    "Du bist der Assistent von equity-scout, einem lokalen Recherche-Tool für systematische "
    "Anlagestrategien (Paper-Trading, KEINE Anlageberatung). Beantworte Fragen ausschließlich anhand "
    "des DATEN-Kontexts unten. Gibt der Kontext die Antwort nicht her, sag das ehrlich. Keine "
    "Kursprognosen, keine Kauf-/Verkaufsempfehlungen. Antworte knapp und auf Deutsch."
)


class ChatError(Exception):
    """Raised when the local Ollama server can't be reached or the model isn't available."""


def _fmt_pct(x: float, *, signed: bool = False) -> str:
    return f"{x * 100:+.1f}%" if signed else f"{x * 100:.1f}%"


def build_dashboard_context(*, strategies: list, ml: dict | None, research: dict | None, forward: list) -> str:
    """A compact, model-readable snapshot of the current dashboard numbers."""
    lines: list[str] = []
    if strategies:
        lines.append("STRATEGIEN (Backtest nach Kosten, gegen 60/40):")
        for s in strategies:
            m = s["metrics"]
            lines.append(
                f"- {s['name']}: Sharpe {m['sharpe']:.2f}, Rendite p.a. {_fmt_pct(m['cagr'])}, "
                f"Max. Verlust {_fmt_pct(m['max_drawdown'])}"
            )
    if ml and ml.get("trained"):
        lines.append(
            f"\nML-META-MODELL (out-of-sample): Trefferquote {_fmt_pct(ml['oos_hit_rate'])}, "
            f"{ml['n_bets']} Signale, Ø Exposure {_fmt_pct(ml['avg_exposure'])}"
        )
    if research and research.get("available"):
        champ = research.get("champion")
        if champ:
            feats = ", ".join(champ["features"])
            lines.append(
                f"\nAUTO-RESEARCH: {research['n_trials']} Konfigurationen getestet. Champion: "
                f"{champ['model']} mit [{feats}], DSR {champ['dsr']:.2f}, Sharpe {champ['sharpe']:.2f}."
            )
        if research.get("pbo"):
            lines.append(
                f"PBO (Overfitting-Wahrscheinlichkeit): {_fmt_pct(research['pbo']['pbo'])} — "
                "hoch heißt, die Bestenliste ist eher Glück als Können."
            )
    if forward:
        lines.append("\nFORWARD (fortlaufend, live, nach Kosten):")
        for a in forward:
            lines.append(
                f"- {a['strategy_name']}: {_fmt_pct(a['total_return'], signed=True)} "
                f"(Benchmark {_fmt_pct(a['benchmark_return'], signed=True)}), {a['n_points']} Bewertung(en)"
            )
    return "\n".join(lines) if lines else "Keine Daten verfügbar."


def ask_ollama(
    question: str,
    context: str,
    *,
    model: str = OLLAMA_MODEL,
    host: str = OLLAMA_HOST,
    timeout: float = 120.0,
) -> str:
    import httpx

    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": f"{SYSTEM_PROMPT}\n\nDATEN-Kontext:\n{context}"},
            {"role": "user", "content": question},
        ],
    }
    try:
        resp = httpx.post(f"{host}/api/chat", json=payload, timeout=timeout)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ChatError(
            f"Ollama antwortet mit {exc.response.status_code}. Ist das Modell '{model}' geladen? "
            f"(`ollama pull {model}`)"
        ) from exc
    except Exception as exc:  # connection refused, timeout, DNS …
        raise ChatError(
            f"Ollama ist unter {host} nicht erreichbar. Läuft `ollama serve`? "
            "Modell wählbar über die Umgebungsvariable OLLAMA_MODEL."
        ) from exc

    content = resp.json().get("message", {}).get("content", "").strip()
    if not content:
        raise ChatError("Ollama hat eine leere Antwort geliefert.")
    return content
