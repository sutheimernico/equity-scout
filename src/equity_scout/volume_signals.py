"""Behavioural signals from traded volume (v17): how many people acted, not just at what price.

Nico's question, and it is the right one: "wann kaufen Menschen Aktien und wann nicht?" Price
alone cannot answer it — a price says at what level buyer and seller agreed, volume says how
many of them there were and therefore how much conviction stood behind that level. A 3 % drop
on normal volume is a shrug; the same drop on five times the volume is people leaving.

Until 2026-08-11 this project had NO volume data at all: `_download_closes` pulled `data["Close"]`
out of the yfinance response and dropped the rest. Every strategy, factor and ML feature here
was price-only. That was the blind spot; this module is the eye.

**The one rule everything obeys: normalise against the ticker's OWN history.** SPY trades ~50 M
shares a day, a small cap ~50 k. Absolute volume compares nothing; the ratio to that ticker's
own average is the behavioural statement.

The three signals, and what human behaviour each one is about:

- **Volume ratio** (today vs. its own 20-day median): attention. Spikes cluster around news,
  earnings and capitulation. Direction-free on purpose — a spike says "many people acted", and
  the price move alongside it says which way.
- **On-Balance Volume trend**: accumulation vs. distribution. Volume is added on up-days and
  subtracted on down-days, so a rising OBV while the price stalls means buyers are absorbing
  supply quietly — the classic "smart money accumulates before the move" reading (Granville
  1963). Treated here as a description of who is winning the tape, not as a forecast.
- **Capitulation**: a large DOWN move on extreme volume. Behaviourally the moment forced and
  panicked sellers finish, which is why it often marks a local bottom — and why buying it
  blindly is also how people catch falling knives. This module only DETECTS it; whether to act
  is a strategy's decision.

Honesty limits, because this family invites overreading:
- Volume is noisy and regime-dependent: index rebalancing days, quarterly expiries and holiday
  half-sessions produce spikes with no behavioural content. The median (not mean) baseline
  blunts single outliers but cannot know the calendar.
- Every signal here is descriptive. None of them is evidence of an edge; that is what the
  forward tracks and `significance.py` decide.
- Volume data quality from a free feed is worse than price quality — a missing day is 0, and a
  zero must never be treated as "nobody traded" without checking the price series alongside.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# 20 sessions ~ one trading month: long enough that one busy day does not move the baseline,
# short enough to follow a regime change. Median, not mean — a single 10x day would otherwise
# raise the baseline so much that the NEXT spike reads as normal.
BASELINE_DAYS = 20
# Below this many usable observations the baseline is guesswork.
MIN_BASELINE_OBS = 10
# What counts as "extreme" volume. 2.0 = twice the ticker's own median day. Chosen because it
# sits clearly outside normal fluctuation without needing a distribution assumption.
SPIKE_RATIO = 2.0
# A day is a capitulation candidate only if the move is at least this large AND down.
CAPITULATION_DROP = 0.03


@dataclass(frozen=True)
class VolumeReading:
    """What today's volume says, relative to this ticker's own recent behaviour.

    Every field is None-able on purpose: too little history is a normal state for a young
    ticker, and a fabricated 1.0 ratio would read as "perfectly average" — the one value that
    is never suspicious and therefore the most dangerous default.
    """

    ticker: str
    volume: float | None
    baseline: float | None            # median volume over the baseline window
    ratio: float | None               # volume / baseline; 2.0 = twice a normal day
    is_spike: bool
    obv_trend: float | None           # OBV change over the window, normalised by baseline
    is_capitulation: bool
    note: str


def _median(values: list[float]) -> float | None:
    usable = sorted(v for v in values if v is not None and math.isfinite(v) and v > 0)
    if len(usable) < MIN_BASELINE_OBS:
        return None
    mid = len(usable) // 2
    if len(usable) % 2:
        return usable[mid]
    return (usable[mid - 1] + usable[mid]) / 2.0


def on_balance_volume(closes: list[float], volumes: list[float]) -> float | None:
    """Cumulative volume signed by the day's price direction (Granville 1963).

    Up-day volume counts positive, down-day negative. The absolute level is meaningless (it
    depends on where the series starts), so callers use the CHANGE — which is why this returns
    the running total and `read_volume` normalises it.
    """
    if len(closes) != len(volumes) or len(closes) < 2:
        return None
    total = 0.0
    for i in range(1, len(closes)):
        prev, now = closes[i - 1], closes[i]
        vol = volumes[i]
        if not all(math.isfinite(x) for x in (prev, now, vol)) or prev <= 0:
            continue
        if now > prev:
            total += vol
        elif now < prev:
            total -= vol
        # An unchanged close adds nothing — no direction, no attribution.
    return total


def read_volume(
    ticker: str,
    closes: list[float],
    volumes: list[float],
    *,
    baseline_days: int = BASELINE_DAYS,
    spike_ratio: float = SPIKE_RATIO,
    capitulation_drop: float = CAPITULATION_DROP,
) -> VolumeReading:
    """Judge the LAST day in the series against the ticker's own recent behaviour.

    `closes` and `volumes` must be the same series, oldest first, ending on the day in
    question. Mismatched lengths return an honest empty reading rather than silently aligning
    two different histories — that mistake produces plausible numbers about nothing.
    """
    if len(closes) != len(volumes) or len(volumes) < 2:
        return VolumeReading(
            ticker=ticker, volume=None, baseline=None, ratio=None, is_spike=False,
            obv_trend=None, is_capitulation=False,
            note="Preis- und Volumenreihe passen nicht zusammen oder sind zu kurz.",
        )
    today = volumes[-1]
    # Baseline EXCLUDES today: comparing a day against a window containing itself dampens
    # exactly the spike the signal is looking for.
    window = volumes[-(baseline_days + 1):-1]
    baseline = _median(window)
    if baseline is None or not math.isfinite(today) or today < 0:
        return VolumeReading(
            ticker=ticker, volume=today if math.isfinite(today) else None, baseline=baseline,
            ratio=None, is_spike=False, obv_trend=None, is_capitulation=False,
            note=f"Zu wenig Volumen-Historie (<{MIN_BASELINE_OBS} brauchbare Tage) für einen Vergleich.",
        )
    ratio = today / baseline
    is_spike = ratio >= spike_ratio

    obv_window_closes = closes[-(baseline_days + 1):]
    obv_window_volumes = volumes[-(baseline_days + 1):]
    obv = on_balance_volume(obv_window_closes, obv_window_volumes)
    # Normalised by baseline volume so the number is comparable across tickers: "+3" means the
    # window accumulated three average days' worth of net buying volume.
    obv_trend = obv / baseline if obv is not None and baseline > 0 else None

    day_return = None
    if len(closes) >= 2 and closes[-2] > 0 and all(math.isfinite(c) for c in closes[-2:]):
        day_return = closes[-1] / closes[-2] - 1.0
    is_capitulation = bool(
        is_spike and day_return is not None and day_return <= -abs(capitulation_drop)
    )

    if is_capitulation:
        note = (f"Kapitulations-Signatur: {ratio:.1f}x normales Volumen bei {day_return:+.1%} — "
                "viele Verkäufer auf einmal. Oft ein lokaler Boden, oft auch nur die Mitte "
                "eines Absturzes.")
    elif is_spike:
        note = (f"{ratio:.1f}x normales Volumen — ungewöhnlich viele Menschen haben gehandelt. "
                "Richtungsfrei: der Kurs daneben sagt, wohin.")
    elif ratio < 0.5:
        note = f"Nur {ratio:.1f}x normales Volumen — kaum Beteiligung, Bewegungen tragen wenig Gewicht."
    else:
        note = f"{ratio:.1f}x normales Volumen — unauffällig."
    return VolumeReading(
        ticker=ticker, volume=today, baseline=baseline, ratio=ratio, is_spike=is_spike,
        obv_trend=obv_trend, is_capitulation=is_capitulation, note=note,
    )


# The asset-class sleeve for the behaviour picture: one liquid ETF per class, so the reading is
# "where is money moving between classes" rather than eleven slices of US equity risk.
BEHAVIOUR_SLEEVE: tuple[str, ...] = (
    "SPY",   # US equity
    "VEU",   # non-US equity
    "IEF",   # intermediate treasuries
    "TLT",   # long treasuries
    "GLD",   # gold
    "DBC",   # broad commodities
    "VNQ",   # real estate
)


def market_behaviour(
    closes: dict[str, list[float]],
    volumes: dict[str, list[float]],
    *,
    sleeve: tuple[str, ...] = BEHAVIOUR_SLEEVE,
) -> dict:
    """Who is trading what right now, across asset classes — Nico's question in one block.

    Returns the per-ticker readings plus a plain-language summary. Deliberately descriptive:
    it reports crowd behaviour, it does not recommend anything. Spikes and accumulation are
    facts about participation, not forecasts, and the summary says so where it matters.
    """
    readings = []
    for ticker in sleeve:
        c, v = closes.get(ticker), volumes.get(ticker)
        if not c or not v:
            continue
        readings.append(read_volume(ticker, c, v))
    usable = [r for r in readings if r.ratio is not None]
    spikes = [r for r in usable if r.is_spike]
    capitulations = [r for r in usable if r.is_capitulation]
    # OBV trend ranks who is being accumulated and who is being sold into.
    ranked = sorted(
        (r for r in usable if r.obv_trend is not None),
        key=lambda r: r.obv_trend, reverse=True,
    )
    parts: list[str] = []
    if capitulations:
        parts.append(
            "Kapitulation bei " + ", ".join(r.ticker for r in capitulations)
            + " (viel Volumen, deutlich runter)"
        )
    elif spikes:
        parts.append(
            "Auffällig viel Handel in " + ", ".join(f"{r.ticker} ({r.ratio:.1f}x)" for r in spikes)
        )
    if len(ranked) >= 2:
        parts.append(f"am stärksten aufgesammelt: {ranked[0].ticker}")
        parts.append(f"am stärksten abgegeben: {ranked[-1].ticker}")
    summary = " · ".join(parts) if parts else "Keine auffälligen Volumen-Muster."
    return {
        "available": bool(usable),
        "readings": [
            {
                "ticker": r.ticker, "ratio": r.ratio, "volume": r.volume,
                "baseline": r.baseline, "is_spike": r.is_spike,
                "obv_trend": r.obv_trend, "is_capitulation": r.is_capitulation,
                "note": r.note,
            }
            for r in readings
        ],
        "summary": summary,
        "caveat": (
            "Volumen sagt, wie viele Menschen gehandelt haben — nicht, wer richtig lag. "
            "Index-Umstellungen, Verfallstage und halbe Feiertags-Sitzungen erzeugen Spitzen "
            "ohne jede Aussage."
        ),
    }
