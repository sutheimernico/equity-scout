"""Investierbarkeitsfilter — beide Datenfallen, die die Live-Messung am 2026-08-27 zeigte."""
from __future__ import annotations

from equity_scout.liquidity import (
    MIN_MARKET_CAP_EUR,
    REASON_ILLIQUID,
    REASON_NO_DATA,
    REASON_SMALL,
    assess,
    filter_investable,
    market_cap_eur,
)
from equity_scout.models import Instrument, Quote

RATES = {"USD": 0.92, "GBP": 1.17, "GBp": 0.0117, "INR": 0.0103, "JPY": 0.0058}


def rate(currency: str | None) -> float | None:
    return RATES.get(currency or "")


def _quote(ticker: str, *, currency: str, cap: float | None, volume: float | None, price: float | None) -> Quote:
    return Quote(
        instrument=Instrument(ticker, ticker, "X", "US", currency, "Tech"),
        trailing_pe=None, price_to_book=None, return_on_equity=None,
        profit_margins=None, revenue_growth=None, earnings_growth=None,
        momentum_6m=0.1, price=price, market_cap=cap, avg_volume=volume,
    )


def test_a_nano_cap_is_rejected_with_its_number() -> None:
    """EHLD stand am 2026-08-27 auf Platz 2 der Watchlist: 27 Mio $, 4 071 Stück am Tag."""
    reason = assess(_quote("EHLD", currency="USD", cap=27_567_056, volume=4_071, price=9.79), rate=rate)
    assert reason is not None and REASON_SMALL in reason and "25 Mio €" in reason  # 0,92 EUR/USD im Test, live 0,88


def test_a_large_liquid_name_passes() -> None:
    assert assess(_quote("MSFT", currency="USD", cap=3.7e12, volume=39e6, price=503.5), rate=rate) is None


def test_british_market_cap_is_read_as_pounds_not_pence() -> None:
    """yfinance mischt die Einheiten: `price` in Pence, `marketCap` in Pfund. Ohne diese
    Unterscheidung fliegt easyJet (5 Mrd £) als 59-Mio-Klitsche raus."""
    easyjet = _quote("EZJ.L", currency="GBp", cap=5_042_811_904, volume=8_576_324, price=674.6)
    assert market_cap_eur(easyjet, rate) > 5e9
    assert assess(easyjet, rate=rate) is None


def test_a_missing_market_cap_falls_back_to_turnover() -> None:
    """Ageas hat bei yfinance keinen Börsenwert, aber 19 Mio € Tagesumsatz — fail-closed
    hätte einen der wenigen wirklich handelbaren Titel der Liste geworfen."""
    ageas = _quote("AGS.BR", currency="EUR", cap=None, volume=259_493, price=73.7)
    assert assess(ageas, rate=rate) is None


def test_the_turnover_fallback_carries_a_surcharge() -> None:
    """Ohne Börsenwert fehlt der Größencheck, also muss der Umsatz mehr leisten: 1,5 Mio €
    reichen mit Börsenwert, ohne ihn nicht."""
    thin = _quote("GLU", currency="USD", cap=None, volume=84_000, price=19.4)  # ~1,5 Mio €
    reason = assess(thin, rate=rate)
    assert reason is not None and REASON_ILLIQUID in reason
    with_cap = _quote("GLU", currency="USD", cap=2e9, volume=84_000, price=19.4)
    assert assess(with_cap, rate=rate) is None


def test_no_data_at_all_is_rejected_not_waved_through() -> None:
    assert assess(_quote("X", currency="USD", cap=None, volume=None, price=None), rate=rate) == REASON_NO_DATA


def test_a_big_but_thinly_traded_name_is_rejected() -> None:
    """Größe allein reicht nicht: ein 2-Mrd-Titel mit 800 Tsd € Umsatz bewegt sich bei
    jeder Order."""
    reason = assess(_quote("ETO", currency="USD", cap=2e9, volume=31_765, price=31.67), rate=rate)
    assert reason is not None and REASON_ILLIQUID in reason


def test_euro_names_need_no_fx_lookup() -> None:
    """`eur_rate` gibt für EUR None zurück (= „nichts umzurechnen"). Wer das als
    „unbekannt" liest, wirft jeden Euro-Titel raus."""
    def no_rates(currency: str | None) -> float | None:
        return None

    assert assess(_quote("SAP.DE", currency="EUR", cap=2e11, volume=1e6, price=200.0), rate=no_rates) is None


def test_a_failed_fx_lookup_does_not_disqualify_a_stock() -> None:
    """Der Wechselkurs kommt aus derselben gedrosselten Quelle wie alles andere. Fällt er
    aus, ist das ein Infrastrukturproblem — kein Befund über den Titel. Ohne diese
    Unterscheidung hätte EIN fehlgeschlagener FX-Abruf mitten im Wochenlauf das GESAMTE
    Universum aussortiert (gefunden 2026-08-27, als der parallel laufende Scout Yahoo
    drosselte und die Pipeline-Tests rot wurden)."""
    assert assess(
        _quote("X.ZZ", currency="ZZZ", cap=1e12, volume=1e9, price=100.0), rate=lambda c: None
    ) is None


def test_no_numbers_at_all_is_still_a_rejection() -> None:
    """Fail-open gilt NUR für die Umrechnung. Wer gar keine Rohwerte hat, bleibt draußen —
    sonst wäre der Filter für genau die dünnen Titel abgeschaltet, für die er da ist."""
    assert assess(
        _quote("X.ZZ", currency="ZZZ", cap=None, volume=None, price=None), rate=lambda c: None
    ) == REASON_NO_DATA


def test_filter_investable_reports_every_rejection() -> None:
    quotes = [
        _quote("BIG", currency="USD", cap=5e9, volume=2e6, price=50.0),
        _quote("TINY", currency="USD", cap=1e7, volume=1e3, price=5.0),
    ]
    passed, rejected = filter_investable(quotes, rate=rate)
    assert [q.instrument.ticker for q in passed] == ["BIG"]
    assert "TINY" in rejected and str(MIN_MARKET_CAP_EUR / 1e6).startswith("300")


# --- Cache-Übergang: die Falle, die den nächsten Wochenlauf leer gemacht hätte ---------

def test_a_pre_filter_cache_row_is_refetched_not_replayed(tmp_path) -> None:
    """Der Wochenlauf serviert Quotes bis zu 7 Tage aus dem Cache. Zeilen aus der Zeit vor
    dem Investierbarkeitsfilter kennen `market_cap` gar nicht — würden sie ausgeliefert,
    fiele eine ganze Woche lang JEDER Titel durch den Filter und die Watchlist wäre leer.
    """
    from equity_scout.data.cache import CachedProvider, QuoteCache, is_stale_schema

    cache = QuoteCache(str(tmp_path / "cache.db"))
    # So sah eine Zeile vor dem 2026-08-27 aus: alle alten Felder, keine neuen.
    old_row = {
        "trailing_pe": 15.0, "price_to_book": 2.0, "return_on_equity": 0.2,
        "profit_margins": 0.1, "revenue_growth": 0.05, "earnings_growth": 0.05,
        "momentum_6m": 0.1, "volatility_6m": 0.01, "price": 100.0,
        "high_52w_proximity": 0.9,
    }
    assert is_stale_schema(old_row) is True
    cache.put("MSFT", old_row, "2026-08-27")

    fetched: list[str] = []

    class _Inner:
        def fetch_quote(self, instrument: Instrument) -> Quote:
            fetched.append(instrument.ticker)
            return _quote("MSFT", currency="USD", cap=3e12, volume=39e6, price=500.0)

    provider = CachedProvider(_Inner(), cache, run_date="2026-08-27", max_age_days=7)
    quote = provider.fetch_quote(Instrument("MSFT", "Microsoft", "X", "US", "USD", "Tech"))
    assert fetched == ["MSFT"] and quote.market_cap == 3e12

    # Und die frisch geschriebene Zeile wird beim nächsten Mal wieder aus dem Cache bedient.
    fetched.clear()
    provider.fetch_quote(Instrument("MSFT", "Microsoft", "X", "US", "USD", "Tech"))
    assert fetched == []


def test_a_name_yfinance_has_no_cap_for_is_not_refetched_forever(tmp_path) -> None:
    """Schlüssel vorhanden, Wert None = „gemessen, gibt es nicht". Das ist keine veraltete
    Zeile — sonst würde genau der Titel jeden Lauf neu abgefragt, für den es nichts gibt."""
    from equity_scout.data.cache import is_stale_schema

    assert is_stale_schema({"market_cap": None, "avg_volume": None}) is False
