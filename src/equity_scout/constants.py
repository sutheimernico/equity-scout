"""Shared constants. Honesty guardrails live here so every surface reuses them."""

DISCLAIMER = (
    "equity-scout ist ein lokaler Recherche-Assistent. Es ist KEINE Anlageberatung und gibt "
    "keine Performance-Versprechen. Faktor-Screens sind gut erforscht, schlagen den Markt aber "
    "nicht zuverlässig. Die kostenlosen Daten (yfinance) sind inoffiziell und können lückenhaft "
    "sein, besonders außerhalb der USA. LLM-Einschätzungen sind kontextgebundene Interpretationen, "
    "niemals Kursprognosen."
)

DEFAULT_DB_PATH = "equity_scout.db"
DEFAULT_UNIVERSE_PATH = "data/universe_combined.csv"  # the full ~530-stock global universe
DEFAULT_FORWARD_DB_PATH = "forward_paper.db"  # forward paper-trading track record (Strang B)
