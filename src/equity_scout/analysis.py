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
        b = pick.breakdown
        return (
            f"{pick.instrument.ticker} sits in the {pick.bucket} bucket "
            f"(momentum={b['momentum']:.2f}, quality={b['quality']:.2f}). "
            "Interpretation only — not a forecast."
        )


class ClaudeCliAnalysis:
    """Real impl: one `claude -p` call per finalist returning a short thesis."""

    def __init__(self, model: str | None = None, timeout_s: int = 120) -> None:
        self._model = model
        self._timeout_s = timeout_s

    def thesis_for(self, pick: Pick) -> str:
        prompt = (
            "You are a sober equity analyst. Given these cross-sectional factor percentiles "
            f"for {pick.instrument.ticker} ({pick.instrument.name}, {pick.instrument.region}), "
            f"bucket={pick.bucket}: {json.dumps(pick.breakdown)}. "
            "Write 2-3 sentences: why it fits this risk bucket, and the single biggest risk. "
            "Do NOT predict price. Be explicit this is interpretation, not advice."
        )
        cmd = ["claude", "-p", prompt]
        if self._model:
            cmd += ["--model", self._model]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self._timeout_s
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"No thesis produced ({type(exc).__name__})."
        return result.stdout.strip() or "No thesis produced."


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
