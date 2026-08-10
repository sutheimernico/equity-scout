"""How long until a lane's result means anything? (v16 wave 3)

The gap this closes: on 2026-08-10 the session lane stood at −2.4 % over 46 closed legs and
nobody could say whether that was bad luck or a broken strategy. Without an answer, a dead
strategy runs for months and a good one gets killed after a bad week — both failures are
expensive, and both are avoidable with the numbers already in the trade log.

Two questions, deliberately separated:

1. **Is the average trade already distinguishable from zero?** A two-sided t-test on the
   realised P&L per trade.
2. **If not, how many trades would it take?** The sample size that would give 80 % power at
   the CURRENTLY OBSERVED effect size — answering "keep going" versus "this will never
   resolve at this rate".

Honesty limits, stated because they change how the numbers should be read:

- **Trade P&Ls are not normal.** They are skewed and fat-tailed (a few big winners, many
  small losses, or the reverse). The t-test is therefore optimistic: real significance needs
  MORE trades than `trades_needed` says, not fewer. The verdict wording never claims proof.
- **One lane is not one test.** Judging four lanes and twelve sleeves against zero is sixteen
  tests; at p<0.05 roughly one of them looks significant by chance alone. `bonferroni_alpha`
  exists so a caller comparing several books can pass the corrected level instead of
  pretending each look is independent.
- **A tiny observed effect inflates the requirement to absurdity.** At μ→0 the required n
  diverges; the function returns None rather than a made-up ceiling, and the verdict says
  "no measurable effect" instead of "needs 4 million trades".
- This measures whether a mean differs from zero. It says nothing about whether the strategy
  will keep working — that is what forward tracking and the promotion gate are for.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# Two-sided 95 % and 80 % power. Not parameters: every additional knob here is another way to
# search for the number you wanted, and this module exists to stop exactly that.
DEFAULT_ALPHA = 0.05
DEFAULT_POWER = 0.80
_Z_POWER_80 = 0.8416212335729143  # Phi^-1(0.80)
# Below this |mean| relative to the spread, the effect is indistinguishable from noise at any
# plausible sample size and the required-n formula stops being informative.
_MIN_EFFECT_SIZE = 0.01
MIN_TRADES_FOR_A_TEST = 5


@dataclass(frozen=True)
class SignificanceVerdict:
    """What the trade log can and cannot support yet.

    `verdict` is one of: "zu wenige Trades", "kein messbarer Effekt", "noch nicht aussagekräftig",
    "positiv", "negativ" — German because it renders straight onto Nico's surfaces.
    """

    n: int
    mean: float
    stdev: float
    t_stat: float | None
    p_value: float | None
    trades_needed: int | None
    alpha: float
    verdict: str
    note: str

    @property
    def is_significant(self) -> bool:
        return self.p_value is not None and self.p_value < self.alpha

    @property
    def trades_missing(self) -> int | None:
        if self.trades_needed is None:
            return None
        return max(0, self.trades_needed - self.n)


def _t_sf_two_sided(t: float, df: int) -> float | None:
    """Two-sided p-value for a t statistic. scipy is a declared dependency (ML stack), but it
    is imported lazily so importing this module stays cheap for callers that never test."""
    try:
        from scipy import stats
    except ImportError:  # pragma: no cover - scipy is declared, this is belt and braces
        return None
    return float(2.0 * stats.t.sf(abs(t), df))


def required_trades(mean: float, stdev: float, *, alpha: float = DEFAULT_ALPHA,
                    power: float = DEFAULT_POWER) -> int | None:
    """Sample size for `power` at the observed effect size. None when the effect is too small
    to resolve — an honest "not measurable" beats a seven-digit number nobody will reach."""
    if stdev <= 0 or not math.isfinite(stdev) or not math.isfinite(mean):
        return None
    effect = abs(mean) / stdev
    if effect < _MIN_EFFECT_SIZE:
        return None
    try:
        from scipy import stats
    except ImportError:  # pragma: no cover
        return None
    z_alpha = float(stats.norm.ppf(1.0 - alpha / 2.0))
    z_power = _Z_POWER_80 if power == DEFAULT_POWER else float(stats.norm.ppf(power))
    return max(MIN_TRADES_FOR_A_TEST, math.ceil(((z_alpha + z_power) / effect) ** 2))


def assess_trades(pnls: list[float], *, alpha: float = DEFAULT_ALPHA) -> SignificanceVerdict:
    """Judge a list of realised per-trade P&Ls against zero.

    Deliberately takes the P&L SERIES rather than a summary: the spread between trades is the
    whole input to the question, and a caller holding only "total and win rate" cannot answer
    it — which is why this is a module and not a one-liner in the dashboard.
    """
    n = len(pnls)
    clean = [p for p in pnls if p is not None and math.isfinite(p)]
    if len(clean) < MIN_TRADES_FOR_A_TEST:
        return SignificanceVerdict(
            n=len(clean), mean=(sum(clean) / len(clean)) if clean else 0.0, stdev=0.0,
            t_stat=None, p_value=None, trades_needed=None, alpha=alpha,
            verdict="zu wenige Trades",
            note=f"Unter {MIN_TRADES_FOR_A_TEST} abgeschlossenen Trades ist jede Aussage Rauschen.",
        )
    n = len(clean)
    mean = sum(clean) / n
    variance = sum((p - mean) ** 2 for p in clean) / (n - 1)
    stdev = math.sqrt(variance)
    if stdev <= 0:
        # Every trade returned exactly the same amount — synthetic data or a booking bug.
        return SignificanceVerdict(
            n=n, mean=mean, stdev=0.0, t_stat=None, p_value=None, trades_needed=None,
            alpha=alpha, verdict="kein messbarer Effekt",
            note="Alle Trades identisch — keine Streuung, also kein Test möglich.",
        )
    t_stat = mean / (stdev / math.sqrt(n))
    p_value = _t_sf_two_sided(t_stat, n - 1)
    needed = required_trades(mean, stdev, alpha=alpha)

    if p_value is not None and p_value < alpha:
        verdict = "positiv" if mean > 0 else "negativ"
        note = (f"Ø {mean:+.2f} pro Trade über {n} Trades, p={p_value:.3f}. "
                "Trade-Ergebnisse sind schief verteilt — der Test ist eher zu optimistisch.")
    elif needed is None:
        verdict = "kein messbarer Effekt"
        note = (f"Ø {mean:+.2f} bei einer Streuung von {stdev:.2f} — der Effekt ist so klein "
                "gegen das Rauschen, dass keine erreichbare Trade-Zahl ihn belegen würde.")
    else:
        verdict = "noch nicht aussagekräftig"
        missing = max(0, needed - n)
        note = (f"Ø {mean:+.2f} über {n} Trades, p={p_value:.3f} — für eine Aussage bei diesem "
                f"Effekt braucht es ~{needed} Trades, es fehlen also noch ~{missing}.")
    return SignificanceVerdict(
        n=n, mean=mean, stdev=stdev, t_stat=t_stat, p_value=p_value,
        trades_needed=needed, alpha=alpha, verdict=verdict, note=note,
    )


def bonferroni_alpha(n_comparisons: int, *, alpha: float = DEFAULT_ALPHA) -> float:
    """The level a caller should use when judging several books at once. Sixteen books at 0.05
    produce roughly one 'significant' result from noise alone; this is the crude but honest
    correction, and it is opt-in so a single-book caller is not silently made stricter."""
    return alpha / max(1, n_comparisons)
