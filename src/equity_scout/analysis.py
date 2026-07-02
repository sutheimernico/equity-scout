"""LLM analysis seam. Only finalists are sent. Theses are interpretation, NOT forecasts."""
from __future__ import annotations

import dataclasses
import json
import subprocess
from typing import Protocol

from equity_scout.models import Pick


class AnalysisProvider(Protocol):
    def thesis_for(self, pick: Pick) -> str:
        ...


class FakeAnalysis:
    """Deterministic, offline. Used in tests and --no-llm runs."""

    def thesis_for(self, pick: Pick) -> str:
        breakdown = pick.breakdown
        return (
            f"{pick.instrument.ticker} liegt im {pick.bucket}-Bucket "
            f"(Momentum {breakdown['momentum']:.2f}, Quality {breakdown['quality']:.2f}). "
            "Nur eine Einordnung — keine Prognose."
        )


# Prefix every degraded-path message starts with, so a caller (or a human scanning the dashboard)
# can tell "the LLM has nothing to say" apart from "the CLI is broken" at a glance, and — if ever
# needed — detect the state programmatically via str.startswith() without a new Pick field.
THESIS_UNAVAILABLE_PREFIX = "These nicht verfügbar"


def _unavailable(reason: str) -> str:
    return f"{THESIS_UNAVAILABLE_PREFIX} ({reason})."


class ClaudeCliAnalysis:
    """Real impl: one `claude -p` call per finalist returning a short thesis.

    A non-zero exit is a failure regardless of what (if anything) landed on stdout — the CLI can
    print an error message to stdout, and silently adopting that as "the thesis" would be worse than
    an honest gap. Every failure mode (missing binary, timeout, non-zero exit, empty output) degrades
    to an explicit `_unavailable(...)` message instead of empty/garbage text.
    """

    def __init__(self, model: str | None = None, timeout_s: int = 120) -> None:
        self._model = model
        self._timeout_s = timeout_s

    def thesis_for(self, pick: Pick) -> str:
        prompt = (
            "Du bist ein nüchterner Aktien-Analyst. Gegeben diese cross-sektionalen Faktor-Perzentile "
            f"für {pick.instrument.ticker} ({pick.instrument.name}, {pick.instrument.region}), "
            f"Bucket={pick.bucket}: {json.dumps(pick.breakdown)}. "
            "Schreibe 2-3 Sätze auf Deutsch: warum die Aktie in dieses Risiko-Profil passt und das "
            "größte Risiko. Mach KEINE Kursprognose. Sag explizit, dass dies eine Einordnung ist, "
            "keine Beratung."
        )
        cmd = ["claude", "-p", prompt]
        if self._model:
            cmd += ["--model", self._model]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self._timeout_s
            )
        except subprocess.TimeoutExpired:
            return _unavailable(f"Timeout nach {self._timeout_s}s")
        except OSError as exc:
            return _unavailable(f"CLI nicht ausführbar: {exc.strerror or type(exc).__name__}")

        if result.returncode != 0:
            detail = result.stderr.strip() or f"exit code {result.returncode}"
            return _unavailable(detail)

        thesis = result.stdout.strip()
        return thesis if thesis else _unavailable("leere Antwort")


def attach_theses(
    buckets: dict[str, list[Pick]],
    provider: AnalysisProvider | None,
    max_per_bucket: int | None = None,
) -> dict[str, list[Pick]]:
    """Return a copy of buckets with theses attached. provider=None -> unchanged.

    max_per_bucket caps cost: only picks ranked <= max_per_bucket get an LLM call (None = all).
    """
    if provider is None:
        return buckets
    out: dict[str, list[Pick]] = {}
    for bucket, picks in buckets.items():
        out[bucket] = [
            dataclasses.replace(p, thesis=provider.thesis_for(p))
            if (max_per_bucket is None or p.rank <= max_per_bucket) else p
            for p in picks
        ]
    return out
