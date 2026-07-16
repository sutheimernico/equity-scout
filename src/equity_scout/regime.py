"""Market-regime traffic light (v8): four robust, deliberately boring signals.

Research-backed (session 2026-07-16): trend (SPY vs. 200d SMA), volatility (VIX
bands), breadth (% of universe above its own 200d SMA) and the yield curve
(10y minus 3m). The composite is a plain green-count — deliberately NOT a fitted
or ML regime model: a simple, explainable "how many of the four are green" resists
overfitting and stays honest on a dashboard.

Everything here is pure over injected values/series — no network, no yfinance
import. Callers (API / digest wiring, C2) fetch the inputs behind their own seams.
A missing input yields green=None and the signal drops out of `available` — an
honest absence, never a guessed default.
"""
from __future__ import annotations

# Thresholds (sources in docs/superpowers/specs/2026-07-16-vision-v8-*.md):
# VIX < 15 calm, 15-25 normal, > 25 risk-off; breadth > 60 % healthy, < 40 % correction.
VIX_RISK_OFF = 25.0
BREADTH_HEALTHY_PCT = 60.0
TREND_WINDOW = 200

LEVELS = {
    "green": ("🟢", "Risk-on"),
    "yellow": ("🟡", "Gemischt"),
    "red": ("🔴", "Risk-off"),
    "unknown": ("⚪", "Keine Daten"),
}


def sma(values: list[float], window: int) -> float | None:
    """Simple moving average of the LAST `window` values; None when too short."""
    if len(values) < window or window <= 0:
        return None
    tail = values[-window:]
    return sum(tail) / window


def _signal(key: str, label: str, green: bool | None, value: float | None, note: str) -> dict:
    return {"key": key, "label": label, "green": green, "value": value, "note": note}


def trend_signal(closes: list[float] | None) -> dict:
    """Green when the last close sits above its 200d SMA (Faber-style trend filter)."""
    closes = closes or []
    average = sma(closes, TREND_WINDOW)
    if average is None:
        return _signal("trend", "Trend (S&P 500 vs. 200-Tage-Linie)", None, None,
                       "zu wenig Kurshistorie")
    last = closes[-1]
    return _signal(
        "trend", "Trend (S&P 500 vs. 200-Tage-Linie)", last > average, last,
        f"Kurs {'über' if last > average else 'unter'} der 200-Tage-Linie",
    )


def vix_signal(level: float | None) -> dict:
    if level is None:
        return _signal("vix", "Volatilität (VIX)", None, None, "kein VIX-Stand verfügbar")
    if level < 15.0:
        note = f"VIX {level:.1f} — ruhig"
    elif level <= VIX_RISK_OFF:
        note = f"VIX {level:.1f} — normal"
    else:
        note = f"VIX {level:.1f} — erhöhte Nervosität"
    return _signal("vix", "Volatilität (VIX)", level <= VIX_RISK_OFF, level, note)


def breadth_signal(pct_above_200d: float | None, subject: str = "Titel") -> dict:
    """Green when >= 60 % of the measured group trades above its own 200d SMA.
    `subject` names that group honestly (e.g. "Sektoren" when the input is the
    11-sector-ETF breadth approximation rather than a full-universe scan)."""
    if pct_above_200d is None:
        return _signal("breadth", "Marktbreite (% über 200-Tage-Linie)", None, None,
                       "keine Breadth-Daten")
    healthy = pct_above_200d >= BREADTH_HEALTHY_PCT
    band = ("gesund" if healthy else "Korrektur" if pct_above_200d < 40.0 else "gemischt")
    return _signal(
        "breadth", "Marktbreite (% über 200-Tage-Linie)", healthy, pct_above_200d,
        f"{pct_above_200d:.0f} % der {subject} über ihrer 200-Tage-Linie — {band}",
    )


def yield_curve_signal(yield_10y: float | None, yield_3m: float | None) -> dict:
    """Green while the curve is not inverted. Both legs come from the same source in
    the same scale (e.g. ^TNX/^IRX, both CBOE yield-times-ten), so only the SIGN of
    the spread is interpreted — never its absolute size."""
    if yield_10y is None or yield_3m is None:
        return _signal("curve", "Zinskurve (10J − 3M)", None, None, "keine Zinsdaten")
    spread = yield_10y - yield_3m
    return _signal(
        "curve", "Zinskurve (10J − 3M)", spread > 0, spread,
        "invertiert — historisches Rezessionssignal" if spread <= 0 else "nicht invertiert",
    )


def combine(signals: list[dict]) -> dict:
    """Green-count composite. Missing signals never count as green (conservative) and
    are reported via `available`; the traffic light needs >= 3 evaluable signals,
    otherwise it stays honest "unknown"."""
    green_count = sum(1 for s in signals if s["green"] is True)
    available = sum(1 for s in signals if s["green"] is not None)
    if available < 3:
        level = "unknown"
    elif green_count >= 3:
        level = "green"
    elif green_count == 2:
        level = "yellow"
    else:
        level = "red"
    emoji, label = LEVELS[level]
    return {
        "level": level,
        "emoji": emoji,
        "label": label,
        "green_count": green_count,
        "available": available,
        "signals": signals,
    }


def compute_breadth(universe_closes: dict[str, list[float]]) -> float | None:
    """% of tickers whose last close is above their own 200d SMA. Tickers with less
    than 200 closes are skipped; None when nothing is evaluable."""
    above = evaluable = 0
    for closes in universe_closes.values():
        average = sma(closes, TREND_WINDOW)
        if average is None or not closes:
            continue
        evaluable += 1
        if closes[-1] > average:
            above += 1
    if evaluable == 0:
        return None
    return 100.0 * above / evaluable


def build_regime(
    spy_closes: list[float] | None,
    vix_level: float | None,
    pct_above_200d: float | None,
    yield_10y: float | None,
    yield_3m: float | None,
    breadth_subject: str = "Titel",
) -> dict:
    """The one-call assembly used by API/digest wiring (C2)."""
    return combine([
        trend_signal(spy_closes),
        vix_signal(vix_level),
        breadth_signal(pct_above_200d, subject=breadth_subject),
        yield_curve_signal(yield_10y, yield_3m),
    ])
