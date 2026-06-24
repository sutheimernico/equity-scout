"""Shared constants. Honesty guardrails live here so every surface reuses them."""

DISCLAIMER = (
    "equity-scout is a local research assistant. It does NOT provide investment advice "
    "and makes no performance promises. Factor screens are well-studied but do not reliably "
    "beat the market. Free data (yfinance) is unofficial and may be incomplete, especially "
    "outside the US. LLM theses are context-bounded interpretations, never price forecasts."
)

DEFAULT_DB_PATH = "equity_scout.db"
DEFAULT_UNIVERSE_PATH = "data/universe_v1.csv"
