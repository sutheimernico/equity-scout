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

# v8 sector rotation: the 11 SPDR Select Sector ETFs. Younger funds (XLRE 2015,
# XLC 2018) simply lack history early in a backtest — the rotation strategy skips
# tickers without a full lookback instead of guessing.
SECTOR_ETF_UNIVERSE: list[Instrument] = [
    _etf("XLK", "Technology Select Sector SPDR", "US Sector: Technology"),
    _etf("XLF", "Financial Select Sector SPDR", "US Sector: Financials"),
    _etf("XLV", "Health Care Select Sector SPDR", "US Sector: Health Care"),
    _etf("XLI", "Industrial Select Sector SPDR", "US Sector: Industrials"),
    _etf("XLE", "Energy Select Sector SPDR", "US Sector: Energy"),
    _etf("XLU", "Utilities Select Sector SPDR", "US Sector: Utilities"),
    _etf("XLB", "Materials Select Sector SPDR", "US Sector: Materials"),
    _etf("XLP", "Consumer Staples Select Sector SPDR", "US Sector: Consumer Staples"),
    _etf("XLY", "Consumer Discretionary Select Sector SPDR", "US Sector: Consumer Discretionary"),
    _etf("XLRE", "Real Estate Select Sector SPDR", "US Sector: Real Estate"),
    _etf("XLC", "Communication Services Select Sector SPDR", "US Sector: Communication"),
]
SECTOR_ETF_TICKERS: list[str] = [inst.ticker for inst in SECTOR_ETF_UNIVERSE]

# The panel loaders (backtest/forward/research CLIs) read ETF_TICKERS, so the sector
# funds ride along in the one shared price panel.
ETF_UNIVERSE += SECTOR_ETF_UNIVERSE

ETF_BY_TICKER: dict[str, Instrument] = {inst.ticker: inst for inst in ETF_UNIVERSE}
ETF_TICKERS: list[str] = [inst.ticker for inst in ETF_UNIVERSE]
