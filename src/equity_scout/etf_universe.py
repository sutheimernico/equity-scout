"""The fixed multi-asset ETF basket the allocation strategies trade on.

Tickers chosen to match the source strategies (GEM uses SPY/VEU/IEF/BIL; DAA canary uses VWO/BND;
Permanent Portfolio uses SPY/TLT/BIL/GLD) and to be reliably available on yfinance (all US-listed).
Asset class is stored in `Instrument.sector`. This is a separate concern from the stock factor-funnel
universe — these strategies allocate across asset classes, they don't pick single stocks.
"""
from __future__ import annotations

from equity_scout.models import Instrument


def _etf(ticker: str, name: str, asset_class: str) -> Instrument:
    return Instrument(ticker, name, "US", "US", "USD", asset_class)


ETF_UNIVERSE: list[Instrument] = [
    _etf("SPY", "SPDR S&P 500", "US Equity"),
    _etf("VEU", "Vanguard FTSE All-World ex-US", "Intl Equity"),
    _etf("VWO", "Vanguard Emerging Markets", "EM Equity"),
    _etf("IEF", "iShares 7-10Y Treasury", "Treasury (Intermediate)"),
    _etf("TLT", "iShares 20+Y Treasury", "Treasury (Long)"),
    _etf("BND", "Vanguard Total Bond Market", "Aggregate Bond"),
    _etf("BIL", "SPDR 1-3 Month T-Bill", "Cash"),
    _etf("GLD", "SPDR Gold Shares", "Gold"),
    _etf("DBC", "Invesco DB Commodity", "Commodities"),
    _etf("VNQ", "Vanguard Real Estate", "REIT"),
]

ETF_BY_TICKER: dict[str, Instrument] = {inst.ticker: inst for inst in ETF_UNIVERSE}
ETF_TICKERS: list[str] = [inst.ticker for inst in ETF_UNIVERSE]
