"""Shared constants. Honesty guardrails live here so every surface reuses them."""

DISCLAIMER = (
    "equity-scout ist ein lokaler Recherche-Assistent. Es ist KEINE Anlageberatung und gibt "
    "keine Performance-Versprechen. Faktor-Screens sind gut erforscht, schlagen den Markt aber "
    "nicht zuverlässig. Die kostenlosen Daten (yfinance) sind inoffiziell und können lückenhaft "
    "sein, besonders außerhalb der USA. LLM-Einschätzungen sind kontextgebundene Interpretationen, "
    "niemals Kursprognosen."
)

# One-line variant for space-constrained surfaces (Telegram pitches, digest footer).
SHORT_DISCLAIMER = "Keine Anlageberatung."

# Structural caveats about the ML entry model pipeline (plan v7 strand C, task C4). These are
# facts about how the pipeline is built, not per-model metrics, so they stay constant regardless
# of registry/champion state — surfaced in /api/model so the report is honest about limits that
# a metric alone would not reveal.
MODEL_CAVEATS = [
    # engine.py::run_backtest defaults to rebalance="ME" (month-end); the forward/live path
    # (forward_paper.py::advance_account) calls strategy.decide() fresh on every cron run
    # (run_forward_paper.py, weekdays) — i.e. de facto daily. Backtest metrics do not carry
    # over 1:1 to live performance because the two paths trade at different frequencies.
    "Der Backtest rebalanciert monatlich (Monatsende), der Forward-/Live-Pfad täglich — "
    "Backtest-Renditen sind daher nicht 1:1 auf den Live-Betrieb übertragbar.",
    # run_train_entry.py::_resolve_tickers trains on today's watchlist (load_latest_watchlist),
    # backfilled from --start (default 2007-01-01) — tickers that were delisted/dropped since
    # then never enter the training panel, so the universe is survivorship-biased.
    "Das ML-Trainingsuniversum ist die heutige Watchlist, zurückgerechnet ab 2007 — historisch "
    "rausgefallene/delistete Titel fehlen (Survivorship-Bias), die OOS-Kennzahlen sind dadurch "
    "tendenziell optimistisch.",
]

DEFAULT_DB_PATH = "equity_scout.db"
DEFAULT_UNIVERSE_PATH = "data/universe_combined.csv"  # the full ~1200-stock global universe
DEFAULT_FORWARD_DB_PATH = "forward_paper.db"  # forward paper-trading track record (Strang B)
DEFAULT_CACHE_DB_PATH = "equity_scout_cache.db"  # read-through quote cache (key figures)

# Frozen persistence keys: these strings live in forward/autotrader DB rows — never rename.
ML_SLEEVE_NAMES = ("ML Long Bot", "ML Short Bot")
