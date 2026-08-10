"""W0 — does a behavioural signal predict anything on OUR history? (gate for W1–W6)

Nico's instruction of 2026-08-10, verbatim in effect: **every behavioural indicator gets measured
against our own history before it is built in.** Literature plus a reachability test is not a
measurement. This project has already paid for that lesson: the skip-month that is well documented
for US single stocks LOST on our 21 index ETFs, so an outside finding is a hypothesis here, never
a result.

This module is the measuring instrument. It answers one question per (signal, target, horizon):
does knowing the signal today tell you anything about what the market does next?

Four design decisions carry the whole thing, and each one exists because the obvious version
produces a beautiful, false answer:

1. **The forward window starts at t+1, not t.** The signal is read from closes up to and including
   day t — i.e. it is knowable in the evening. Acting on it is possible from the next session at
   the earliest. Measuring the return from t would credit the strategy with a day it could never
   have traded.

2. **Non-overlapping sampling is the primary test.** Daily observations of a 21-day forward return
   share 20 of 21 days with their neighbour. They are not independent, and a t-test on them
   overstates significance by roughly sqrt(horizon) — a factor of 4.6 at 21 days, which turns
   noise into a p-value of 0.01. So the verdict is decided on a subsample taking every
   (horizon+1)-th day, where the windows genuinely do not overlap. The overlapping rank-IC is
   still reported, labelled as descriptive, because it uses all the data and is a useful sanity
   check on the direction — it just cannot carry a significance claim.

3. **Risk is a target in its own right.** The planned use of these signals is exposure throttling,
   not stock picking. A signal that says nothing about the forward RETURN but reliably flags
   forward VOLATILITY is still valuable there — it improves the risk-adjusted result even with
   zero return predictability. Testing only returns would throw that away. Honesty caveat that
   belongs next to every volatility result: volatility clusters, so predicting it is a much
   easier task than predicting returns, and a hit there is far less impressive than it looks.

4. **The asymmetry gets checked separately.** Baker-Wurgler find sentiment predicts returns only
   from the high-sentiment side, because short-sale constraints stop rational investors from
   arbitraging overvaluation away while nothing stops them at undervaluation. A signal that works
   in one tail and not the other is the expected shape, not a defect — but a study that only
   reports the average across all buckets cannot see it either way.

What this module deliberately does NOT do: decide anything. It returns numbers and a German
verdict string. Whether a signal is built into `regime.py` or the protection chain is a separate
decision made by a human reading the report — the same separation `significance.py` keeps.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

# Below this many INDEPENDENT observations, no verdict is worth printing. Twelve non-overlapping
# 21-day windows is roughly one year of data — already thin, and the floor rather than the target.
MIN_INDEPENDENT_OBS = 12
# Buckets for the monotonicity read. Terciles, not deciles: with ~90 independent observations at a
# 63-day horizon, deciles would hold nine points each and every "pattern" would be noise.
DEFAULT_BUCKETS = 3
# What counts as an extreme for the asymmetry check.
EXTREME_QUANTILE = 0.20
TRADING_DAYS_PER_YEAR = 252
# A finding must survive the majority of possible subsample starting points. Offset 0 is one
# arbitrary choice out of horizon+1; a result that only appears there is a property of that
# choice, not of the market. The threshold is deliberately blunt — this is a robustness filter,
# not a second significance test, and a tunable cutoff would just become another search knob.
MIN_OFFSET_SHARE = 0.50


@dataclass(frozen=True)
class BucketStat:
    """One tercile of the signal and what the market did afterwards."""

    label: str
    n: int
    signal_lo: float
    signal_hi: float
    mean_target: float
    median_target: float


@dataclass(frozen=True)
class ExtremeStat:
    """One tail of the signal against the MIDDLE of the distribution — the asymmetry check.

    The reference is the middle band, not "everything else", and that is not a detail: with
    "everything else" the comparison for the low tail contains the high tail, so a one-sided
    effect sitting in the high tail shows up a second time, mirrored, in the low-tail result. The
    study would then report a two-sided effect where the data holds a one-sided one — the exact
    error the Baker-Wurgler check exists to avoid.
    """

    side: str  # "hoch" or "niedrig"
    n: int
    mean_in_tail: float
    mean_middle: float
    difference: float
    p_value: float | None


@dataclass(frozen=True)
class SignalStudy:
    """Everything measured for one (signal, target, horizon) triple."""

    signal: str
    target: str
    horizon_days: int
    n_overlapping: int
    n_independent: int
    rank_ic_overlapping: float | None
    rank_ic_independent: float | None
    buckets: tuple[BucketStat, ...]
    spread: float | None
    spread_p: float | None
    walk_forward_spreads: tuple[float | None, ...]
    high_extreme: ExtremeStat | None
    low_extreme: ExtremeStat | None
    offset_share_significant: float | None
    minimum_detectable: float | None
    alpha: float
    verdict: str
    note: str

    @property
    def is_significant(self) -> bool:
        return self.spread_p is not None and self.spread_p < self.alpha

    @property
    def walk_forward_stable(self) -> bool:
        """Same sign in every block. A signal that flips sign across eras is a data-mining
        artefact even when the pooled number looks good."""
        signs = [s for s in self.walk_forward_spreads if s is not None and s != 0.0]
        if len(signs) < 2:
            return False
        return all(s > 0 for s in signs) or all(s < 0 for s in signs)


def forward_return(closes: pd.Series, horizon_days: int) -> pd.Series:
    """Return from the close of t+1 to the close of t+1+horizon, indexed at t.

    Indexed at t is the whole point: row t pairs a signal knowable on day t with a return that
    only starts the NEXT session. Shifting by one is the difference between a study and a
    look-ahead.
    """
    if horizon_days < 1:
        raise ValueError("horizon_days must be >= 1")
    px = closes.astype(float)
    entry = px.shift(-1)
    exit_ = px.shift(-(1 + horizon_days))
    return (exit_ / entry - 1.0).replace([np.inf, -np.inf], np.nan)


def forward_volatility(closes: pd.Series, horizon_days: int) -> pd.Series:
    """Annualised stdev of daily returns over the same t+1..t+1+horizon window, indexed at t."""
    if horizon_days < 2:
        raise ValueError("horizon_days must be >= 2 for a volatility estimate")
    rets = closes.astype(float).pct_change()
    # Rolling over the window that ENDS at t+1+horizon, then shifted back so it lands on t.
    forward = rets.rolling(horizon_days).std().shift(-(1 + horizon_days))
    return (forward * math.sqrt(TRADING_DAYS_PER_YEAR)).replace([np.inf, -np.inf], np.nan)


def forward_drawdown(closes: pd.Series, horizon_days: int) -> pd.Series:
    """Worst peak-to-trough drop inside t+1..t+1+horizon, as a negative number, indexed at t.

    Computed by iteration rather than a clever rolling trick: the window is short, the panel is
    small, and a readable loop that is obviously correct beats a vectorised one that silently
    includes day t.
    """
    px = closes.astype(float).to_numpy()
    n = len(px)
    out = np.full(n, np.nan)
    for i in range(n):
        start, end = i + 1, i + 1 + horizon_days
        if end >= n:
            break
        window = px[start : end + 1]
        if not np.all(np.isfinite(window)) or window[0] <= 0:
            continue
        running_max = np.maximum.accumulate(window)
        out[i] = float(np.min(window / running_max - 1.0))
    return pd.Series(out, index=closes.index)


def align(signal: pd.Series, target: pd.Series) -> pd.DataFrame:
    """Inner-join the two series on date and drop rows where either side is missing."""
    frame = pd.DataFrame({"signal": signal.astype(float), "target": target.astype(float)})
    return frame.replace([np.inf, -np.inf], np.nan).dropna().sort_index()


def independent_subsample(frame: pd.DataFrame, horizon_days: int, offset: int = 0) -> pd.DataFrame:
    """Every (horizon+1)-th row starting at `offset`, so no two forward windows share a day.

    Offset 0 is one arbitrary choice out of horizon+1. The verdict is always computed on it, and
    never on a best-of-offsets search — that would be the purest form of the data mining this
    module exists to prevent. `offset_robustness` sweeps the others separately, as a check on the
    ARBITRARINESS of the choice rather than as a way to improve the result.
    """
    step = max(1, horizon_days + 1)
    return frame.iloc[offset::step]


def _split_frame(frame: pd.DataFrame, n_parts: int) -> list[pd.DataFrame]:
    """Split into `n_parts` contiguous chunks, the first few one row longer when it does not
    divide evenly.

    Hand-rolled rather than `np.array_split`, which converts a DataFrame to a bare ndarray under
    numpy 2 and silently drops the column names — the chunks still look right and every access
    by name then fails.
    """
    n = len(frame)
    if n_parts < 1:
        raise ValueError("n_parts must be >= 1")
    base, remainder = divmod(n, n_parts)
    chunks: list[pd.DataFrame] = []
    start = 0
    for i in range(n_parts):
        size = base + (1 if i < remainder else 0)
        chunks.append(frame.iloc[start : start + size])
        start += size
    return chunks


def residualise(signal: pd.Series, controls: list[pd.Series]) -> pd.Series:
    """What is left of `signal` after removing everything the controls already explain.

    This is the test that decides whether a candidate is worth BUILDING, as opposed to whether it
    correlates with anything. A signal can pass every test in this module and still be useless:
    if the traffic light already carries VIX level and breadth, a new indicator earns its place
    only through the part of it that those two do not already contain. Measuring the raw
    correlation instead answers a question nobody has — of course two fear gauges agree.

    Rank-transformed before the fit, for two reasons that both bite here: VIX is heavily
    right-skewed (a single 2020 print dominates a plain least-squares fit), and the study judges
    signals by rank correlation anyway, so residualising on levels would remove something
    different from what the verdict then measures.
    """
    if not controls:
        return signal.astype(float)
    frame = pd.DataFrame({"signal": signal.astype(float)})
    for i, control in enumerate(controls):
        frame[f"c{i}"] = control.astype(float)
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna().sort_index()
    if len(frame) < MIN_INDEPENDENT_OBS:
        return pd.Series(dtype=float)
    ranked = frame.rank(pct=True)
    y = ranked["signal"].to_numpy()
    x = np.column_stack(
        [np.ones(len(ranked))] + [ranked[f"c{i}"].to_numpy() for i in range(len(controls))]
    )
    coefficients, *_ = np.linalg.lstsq(x, y, rcond=None)
    return pd.Series(y - x @ coefficients, index=frame.index)


def _spearman(a: pd.Series, b: pd.Series) -> float | None:
    """Rank correlation, matching `ml.entry_eval.rank_ic` in contract: None below two points,
    0.0 when either side is constant (a real 'no observable ranking' result, not an error)."""
    if len(a) < 2:
        return None
    if a.nunique() < 2 or b.nunique() < 2:
        return 0.0
    return round(float(a.corr(b, method="spearman")), 4)


def _welch(a: np.ndarray, b: np.ndarray) -> tuple[float | None, float | None]:
    """Welch's t-test — unequal variances, which is the normal case here: high-stress buckets are
    far more volatile than calm ones, so the equal-variance version would be wrong by
    construction."""
    if len(a) < 2 or len(b) < 2:
        return None, None
    try:
        from scipy import stats
    except ImportError:  # pragma: no cover - scipy is a declared dependency
        return None, None
    result = stats.ttest_ind(a, b, equal_var=False)
    t_stat, p_value = float(result.statistic), float(result.pvalue)
    if not math.isfinite(t_stat) or not math.isfinite(p_value):
        return None, None
    return t_stat, p_value


def bucket_stats(frame: pd.DataFrame, n_buckets: int = DEFAULT_BUCKETS) -> tuple[BucketStat, ...]:
    """Split by signal quantile and report what followed in each bucket."""
    if len(frame) < n_buckets * 2:
        return ()
    ranked = frame.sort_values("signal")
    chunks = _split_frame(ranked, n_buckets)
    labels = ["niedrig", "mittel", "hoch"] if n_buckets == 3 else [f"Q{i + 1}" for i in range(n_buckets)]
    stats: list[BucketStat] = []
    for label, chunk in zip(labels, chunks):
        if chunk.empty:
            continue
        stats.append(
            BucketStat(
                label=label,
                n=len(chunk),
                signal_lo=float(chunk["signal"].min()),
                signal_hi=float(chunk["signal"].max()),
                mean_target=float(chunk["target"].mean()),
                median_target=float(chunk["target"].median()),
            )
        )
    return tuple(stats)


def extreme_stat(frame: pd.DataFrame, side: str, quantile: float = EXTREME_QUANTILE) -> ExtremeStat | None:
    """One tail against the middle band. `side` is "hoch" (top quantile) or "niedrig" (bottom).

    Both tails are excluded from the reference so the two sides can be read independently — see
    the note on `ExtremeStat`.
    """
    if len(frame) < MIN_INDEPENDENT_OBS:
        return None
    low_cut = frame["signal"].quantile(quantile)
    high_cut = frame["signal"].quantile(1.0 - quantile)
    middle = frame[(frame["signal"] > low_cut) & (frame["signal"] < high_cut)]
    tail = frame[frame["signal"] >= high_cut] if side == "hoch" else frame[frame["signal"] <= low_cut]
    if len(tail) < 2 or len(middle) < 2:
        return None
    _, p_value = _welch(tail["target"].to_numpy(), middle["target"].to_numpy())
    mean_tail, mean_middle = float(tail["target"].mean()), float(middle["target"].mean())
    return ExtremeStat(
        side=side,
        n=len(tail),
        mean_in_tail=mean_tail,
        mean_middle=mean_middle,
        difference=mean_tail - mean_middle,
        p_value=p_value,
    )


def walk_forward_spreads(
    frame: pd.DataFrame, n_blocks: int = 3, n_buckets: int = DEFAULT_BUCKETS
) -> tuple[float | None, ...]:
    """Top-minus-bottom bucket spread computed separately per chronological block.

    Blocks are cut on TIME, not on a shuffle: the question is whether the effect survived
    different market eras, and a random split would mix 2008 into every block and hide exactly
    the instability this is looking for.
    """
    if len(frame) < n_blocks * n_buckets * 2:
        return tuple([None] * n_blocks)
    blocks = _split_frame(frame.sort_index(), n_blocks)
    out: list[float | None] = []
    for block in blocks:
        stats = bucket_stats(block, n_buckets)
        if len(stats) < 2:
            out.append(None)
            continue
        out.append(stats[-1].mean_target - stats[0].mean_target)
    return tuple(out)


def _verdict_for(
    n_independent: int,
    spread: float | None,
    spread_p: float | None,
    alpha: float,
    stable: bool,
    offset_share: float | None,
    minimum_detectable: float | None,
) -> tuple[str, str]:
    """The German verdict + note, in the same register as `significance.SignificanceVerdict`."""
    if n_independent < MIN_INDEPENDENT_OBS:
        return (
            "zu wenig Historie",
            f"Nur {n_independent} unabhängige Fenster — unter {MIN_INDEPENDENT_OBS} ist jede "
            "Aussage Rauschen.",
        )
    if spread is None or spread_p is None:
        return ("nicht messbar", "Der Test ließ sich auf diesen Daten nicht rechnen.")
    if spread_p >= alpha:
        detectable = ""
        if minimum_detectable is not None:
            detectable = (f" Sichtbar wäre hier erst ein Unterschied ab {minimum_detectable:.2%} — "
                          "kleinere Effekte kann dieses Sample nicht ausschließen.")
        return (
            "kein Befund",
            f"Spitze minus Boden {spread:+.2%}, p={spread_p:.3f} bei α={alpha:.4f} — auf "
            f"{n_independent} unabhängigen Fenstern nicht von Zufall zu unterscheiden.{detectable}",
        )
    if offset_share is not None and offset_share < MIN_OFFSET_SHARE:
        return (
            "offset-abhängig",
            f"Spread {spread:+.2%} ist am gewählten Startpunkt signifikant (p={spread_p:.3f}), "
            f"hält aber nur bei {offset_share:.0%} der gleichwertigen Startpunkte der Stichprobe. "
            "Der Befund ist eine Eigenschaft dieser Wahl, nicht des Marktes.",
        )
    if not stable:
        return (
            "instabil",
            f"Spread {spread:+.2%} ist signifikant (p={spread_p:.3f}), wechselt aber über die "
            "Zeitblöcke das Vorzeichen — das Muster einer Data-Mining-Fundstelle, kein Signal.",
        )
    direction = "höher" if spread > 0 else "niedriger"
    robustness = "" if offset_share is None else f", robust über {offset_share:.0%} der Startpunkte"
    return (
        "trägt",
        f"Spread {spread:+.2%} (p={spread_p:.3f}, α={alpha:.4f}) über {n_independent} "
        f"unabhängige Fenster, Vorzeichen in allen Zeitblöcken gleich{robustness}: hohe "
        f"Signalwerte gehen mit {direction}en Folgewerten einher.",
    )


def minimum_detectable_effect(
    frame: pd.DataFrame,
    *,
    alpha: float,
    power: float = 0.80,
    n_buckets: int = DEFAULT_BUCKETS,
) -> float | None:
    """The smallest top-minus-bottom spread this sample could have detected.

    Without this number a null result is unreadable. "No effect found" can mean the effect is
    absent, or it can mean the test could only ever have seen an effect three times larger than
    anything that exists in markets — and those two statements lead to opposite decisions. This
    reports which one applies, in the same units as the measured spread.
    """
    independent = frame
    n_per_group = len(independent) // n_buckets
    if n_per_group < 2:
        return None
    spread = float(independent["target"].std())
    if not math.isfinite(spread) or spread <= 0:
        return None
    try:
        from scipy import stats
    except ImportError:  # pragma: no cover
        return None
    z_alpha = float(stats.norm.ppf(1.0 - alpha / 2.0))
    z_power = float(stats.norm.ppf(power))
    return (z_alpha + z_power) * spread * math.sqrt(2.0 / n_per_group)


def offset_robustness(
    signal: pd.Series,
    target: pd.Series,
    horizon_days: int,
    *,
    alpha: float,
    n_buckets: int = DEFAULT_BUCKETS,
) -> dict:
    """Repeat the top-vs-bottom test at every possible subsample offset.

    A finding that only exists at one of the horizon+1 equally valid offsets is an artefact of
    that choice. Reported as the share of offsets that clear alpha and the sign agreement, never
    used to pick a better offset.
    """
    frame = align(signal, target)
    p_values: list[float] = []
    spreads: list[float] = []
    for offset in range(horizon_days + 1):
        independent = independent_subsample(frame, horizon_days, offset=offset)
        if len(independent) < MIN_INDEPENDENT_OBS:
            continue
        ranked = independent.sort_values("signal")
        chunks = _split_frame(ranked, n_buckets)
        if len(chunks) < 2 or len(chunks[0]) < 2 or len(chunks[-1]) < 2:
            continue
        low, high = chunks[0], chunks[-1]
        _, p_value = _welch(high["target"].to_numpy(), low["target"].to_numpy())
        if p_value is None:
            continue
        p_values.append(p_value)
        spreads.append(float(high["target"].mean() - low["target"].mean()))
    if not p_values:
        return {"n_offsets": 0, "share_significant": None, "median_p": None, "sign_agreement": None}
    positive = sum(1 for s in spreads if s > 0)
    return {
        "n_offsets": len(p_values),
        "share_significant": sum(1 for p in p_values if p < alpha) / len(p_values),
        "median_p": float(np.median(p_values)),
        "sign_agreement": max(positive, len(spreads) - positive) / len(spreads),
    }


def study_signal(
    *,
    signal_name: str,
    target_name: str,
    signal: pd.Series,
    target: pd.Series,
    horizon_days: int,
    alpha: float = 0.05,
    n_buckets: int = DEFAULT_BUCKETS,
) -> SignalStudy:
    """Measure one signal against one forward target at one horizon.

    `target` must already BE a forward series indexed at the decision day (build it with
    `forward_return` / `forward_volatility` / `forward_drawdown`) — this function does no shifting
    of its own, so there is exactly one place in the code where the t+1 convention lives.
    """
    frame = align(signal, target)
    independent = independent_subsample(frame, horizon_days)
    buckets = bucket_stats(independent, n_buckets)
    spread: float | None = None
    spread_p: float | None = None
    if len(buckets) >= 2:
        ranked = independent.sort_values("signal")
        chunks = _split_frame(ranked, n_buckets)
        low, high = chunks[0], chunks[-1]
        spread = float(high["target"].mean() - low["target"].mean())
        _, spread_p = _welch(high["target"].to_numpy(), low["target"].to_numpy())
    wf = walk_forward_spreads(independent, n_buckets=n_buckets)
    signs = [s for s in wf if s is not None and s != 0.0]
    stable = len(signs) >= 2 and (all(s > 0 for s in signs) or all(s < 0 for s in signs))
    mde = minimum_detectable_effect(independent, alpha=alpha, n_buckets=n_buckets)
    # Only computed when there is something to defend: the sweep costs horizon+1 extra tests, and
    # a result that already failed on significance cannot be rescued or refuted by it.
    offset_share: float | None = None
    if spread_p is not None and spread_p < alpha:
        offset_share = offset_robustness(
            signal, target, horizon_days, alpha=alpha, n_buckets=n_buckets
        )["share_significant"]
    verdict, note = _verdict_for(
        len(independent), spread, spread_p, alpha, stable, offset_share, mde
    )
    return SignalStudy(
        signal=signal_name,
        target=target_name,
        horizon_days=horizon_days,
        n_overlapping=len(frame),
        n_independent=len(independent),
        rank_ic_overlapping=_spearman(frame["signal"], frame["target"]),
        rank_ic_independent=_spearman(independent["signal"], independent["target"]),
        buckets=buckets,
        spread=spread,
        spread_p=spread_p,
        walk_forward_spreads=wf,
        high_extreme=extreme_stat(independent, "hoch"),
        low_extreme=extreme_stat(independent, "niedrig"),
        offset_share_significant=offset_share,
        minimum_detectable=mde,
        alpha=alpha,
        verdict=verdict,
        note=note,
    )
