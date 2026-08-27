"""Investierbarkeit: Größe und Handelsumsatz als Ausschlusskriterium (2026-08-27).

Der Anlass ist eine Messung, keine Meinung. Am 2026-08-27 stand auf Platz 2 der Watchlist
**EHLD**: 27 Mio $ Börsenwert, **4 071 gehandelte Stücke am Tag** — rund 40 000 $ Umsatz.
Eine 1 000-€-Order wäre 2,5 % eines ganzen Handelstages. Der Faktor-Screen fand den Titel
nicht zufällig: Value- und Quality-Perzentile sind bei Nano-Caps systematisch extrem, weil
dort ein einzelner Bilanzposten den Quotienten dominiert. Ein Faktor-Screen ohne
Größenfilter rankt deshalb verlässlich das, was niemand kaufen kann — das ist in der
Literatur seit Fama/French (1993) bekannt und war hier live nachweisbar.

Bewusst KEIN Faktor: Größe rankt nicht mit, sie schließt aus. Ein Titel ist investierbar
oder nicht; ihn „ein bisschen" schlechter zu bewerten würde ihn bei genug Value-Punkten
trotzdem nach oben lassen.

Beide Zahlen kommen aus demselben `info`-Abruf, den der Screen ohnehin macht — der Filter
kostet keinen einzigen zusätzlichen Netzabruf.
"""
from __future__ import annotations

from collections.abc import Callable

from equity_scout.models import Quote

# Untergrenzen in EUR. 300 Mio ist die übliche Trennlinie zwischen Small und Micro Cap;
# 1 Mio Tagesumsatz heißt, dass eine Order in Nicos Größenordnung (einige hundert bis
# wenige tausend Euro) den Kurs nicht bewegt.
MIN_MARKET_CAP_EUR = 300_000_000.0
MIN_TURNOVER_EUR = 1_000_000.0

# Wenn NUR der Umsatz bekannt ist, fehlt der Größencheck — dann muss der Umsatz mehr
# leisten. Faktor 2 statt einer eigenen Zahl, damit klar bleibt, dass es dieselbe Schwelle
# mit Sicherheitsaufschlag ist.
NO_CAP_TURNOVER_MULTIPLE = 2.0

REASON_NO_DATA = "weder Börsenwert noch Handelsumsatz bekannt"
REASON_SMALL = "Börsenwert unter der Schwelle"
REASON_ILLIQUID = "Handelsumsatz unter der Schwelle"

# yfinance mischt bei britischen Titeln zwei Einheiten in EINER Antwort: `regularMarketPrice`
# steht in Pence (GBp), `marketCap` in Pfund. Gemessen am 2026-08-27 an EZJ.L (easyJet):
# price 674,6 GBp, marketCap 5 042 811 904 — 674,6 p × ~750 Mio Aktien ≈ 5,04 Mrd GBP, also
# ist der Börsenwert bereits in Pfund. Ohne diese Unterscheidung wird easyJet als 59-Mio-
# Klitsche aussortiert. Der Kurs bleibt in Pence und wird weiter über "GBp" umgerechnet.
_CAP_CURRENCY_OVERRIDES = {"GBP": "GBP", "GBp": "GBP"}


def to_eur(
    value: float | None, currency: str | None, rate: Callable[[str | None], float | None]
) -> float | None:
    """Betrag in EUR. `eur_rate` gibt für EUR selbst None zurück — das heißt „Kurs 1", nicht
    „unbekannt", und genau diese Unterscheidung ist der Unterschied zwischen einem
    korrekten Filter und einem, der jeden Euro-Titel aussortiert."""
    if value is None:
        return None
    if not currency or currency.upper() == "EUR":
        return value
    factor = rate(currency)
    return None if factor is None else value * factor


def market_cap_eur(
    quote: Quote, rate: Callable[[str | None], float | None]
) -> float | None:
    """Börsenwert in EUR, mit dem GBp/GBP-Sonderfall."""
    currency = quote.instrument.currency
    return to_eur(quote.market_cap, _CAP_CURRENCY_OVERRIDES.get(currency, currency), rate)


def turnover_eur(
    quote: Quote, rate: Callable[[str | None], float | None]
) -> float | None:
    """Durchschnittlicher Tagesumsatz in EUR (Stücke × Kurs), oder None."""
    if quote.avg_volume is None or quote.price is None:
        return None
    return to_eur(quote.avg_volume * quote.price, quote.instrument.currency, rate)


def assess(
    quote: Quote,
    *,
    rate: Callable[[str | None], float | None],
    min_market_cap_eur: float = MIN_MARKET_CAP_EUR,
    min_turnover_eur: float = MIN_TURNOVER_EUR,
) -> str | None:
    """None = investierbar, sonst der Ablehnungsgrund im Klartext.

    Der Handelsumsatz ist das direktere Kriterium — er misst, ob eine Order den Kurs
    bewegt. Der Börsenwert ist der Stellvertreter für die Faktor-Verzerrung bei Winzlingen.
    Deshalb: sind beide da, müssen beide halten; fehlt der Börsenwert (yfinance lässt ihn
    bei Beteiligungsgesellschaften und einigen europäischen Titeln weg — gemessen an
    AGS.BR/Ageas, das mit 19 Mio € Tagesumsatz nicht illiquide ist), trägt der Umsatz die
    Entscheidung allein, dafür mit Aufschlag.
    """
    cap = market_cap_eur(quote, rate)
    turnover = turnover_eur(quote, rate)

    if cap is None and turnover is None:
        return REASON_NO_DATA
    if cap is None:
        threshold = min_turnover_eur * NO_CAP_TURNOVER_MULTIPLE
        if turnover < threshold:
            return (
                f"{REASON_ILLIQUID} ({turnover / 1e3:.0f} Tsd € Tagesumsatz, ohne "
                f"Börsenwert gilt {threshold / 1e3:.0f} Tsd €)"
            )
        return None
    if cap < min_market_cap_eur:
        return f"{REASON_SMALL} ({cap / 1e6:.0f} Mio € < {min_market_cap_eur / 1e6:.0f} Mio €)"
    if turnover is not None and turnover < min_turnover_eur:
        return (
            f"{REASON_ILLIQUID} ({turnover / 1e3:.0f} Tsd € Tagesumsatz "
            f"< {min_turnover_eur / 1e3:.0f} Tsd €)"
        )
    return None


def filter_investable(
    quotes: list[Quote],
    *,
    rate: Callable[[str | None], float | None] | None = None,
    min_market_cap_eur: float = MIN_MARKET_CAP_EUR,
    min_turnover_eur: float = MIN_TURNOVER_EUR,
) -> tuple[list[Quote], dict[str, str]]:
    """(investierbar, {ticker: Grund}). Gleiche Signatur wie `gate.apply_gate`, damit die
    Pipeline beide Stufen gleich behandelt und beide in denselben Bericht laufen."""
    if rate is None:
        from equity_scout.fx import eur_rate as rate  # noqa: PLC0415 - Netz nur bei Bedarf

    passed: list[Quote] = []
    rejected: dict[str, str] = {}
    for quote in quotes:
        reason = assess(
            quote, rate=rate,
            min_market_cap_eur=min_market_cap_eur, min_turnover_eur=min_turnover_eur,
        )
        if reason is None:
            passed.append(quote)
        else:
            rejected[quote.instrument.ticker] = reason
    return passed, rejected
