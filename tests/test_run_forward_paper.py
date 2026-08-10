"""Runner: the ML-bots' stock panel load path must be gap-tolerant (R3 follow-up).

Nightly forward_paper runs WITH --refresh and therefore WRITES data/prices/ml_bots_panel.csv;
run_autotrader runs right after it WITHOUT --refresh and just reads that snapshot back. If this
load path still trims to the common range (load_etf_panel -> clean_panel), a single young
watchlist ticker truncates every other stock's history in the SAVED file — R3's combined_panel
fix in run_autotrader.py (commit b01ab1f) then reads pre-trimmed data anyway, no matter how
gap-tolerant its own loader is.
"""
from __future__ import annotations

import sys

import pandas as pd

from equity_scout.data.etf_panel import clean_columns
from equity_scout.strategies.base import TargetWeight

import scripts.run_forward_paper as runner


def test_stock_panel_for_bots_survives_a_young_ticker(monkeypatch) -> None:
    old_index = pd.bdate_range("2024-01-02", periods=500)  # ~2 years
    young_index = old_index[-10:]  # joined 10 trading days ago
    raw = pd.DataFrame(index=old_index)
    raw["OLD"] = 100.0
    raw["YOUNG"] = float("nan")
    raw.loc[young_index, "YOUNG"] = 50.0

    def fake_load_etf_panel(tickers, **kwargs):  # noqa: ANN001, ANN201
        # The stock-bot panel must NOT be routed through here — this loader still applies the
        # destructive common-range trim (dropna(how="any") over ALL bot tickers).
        raise AssertionError("stock panel must use load_price_history, not load_etf_panel")

    monkeypatch.setattr(runner, "load_etf_panel", fake_load_etf_panel)
    monkeypatch.setattr(runner, "load_price_history", lambda tickers, **kwargs: clean_columns(raw))

    panel = runner.stock_panel_for_bots(["OLD", "YOUNG"], start="2007-01-01", refresh=False)

    assert panel.closes["OLD"].notna().sum() == len(old_index)  # full history kept, not trimmed
    young = panel.closes["YOUNG"]
    assert young.notna().sum() == len(young_index)  # young ticker's own short history present
    assert young.isna().sum() == len(old_index) - len(young_index)  # gap tolerated, not dropped


class _Strategy:
    """Canned strategy: fixed targets, or raises on decide() to simulate a crashing sleeve."""

    def __init__(self, name: str, weights: dict[str, float] | None = None, raises: bool = False) -> None:
        self.name = name
        self._weights = weights or {}
        self._raises = raises

    def decide(self, as_of, market):  # noqa: ANN001, ANN201 - Strategy protocol
        if self._raises:
            raise RuntimeError("boom")
        return [TargetWeight(t, w) for t, w in self._weights.items()]


class _FakeBot(_Strategy):
    """Like _Strategy, but pre-flagged `ready` (bots gate on a promoted champion, not decide())."""

    ready = True


def test_main_isolates_a_crashing_strategy_and_still_advances_the_others(
    monkeypatch, tmp_path, wavy_panel, capsys,
) -> None:
    """One rule sleeve's decide() blowing up must not take the healthy sleeves' advance down
    with it (same isolation contract as run_train_entry_all's per-preset try/except)."""
    good = _Strategy("Good Sleeve", weights={"SPY": 1.0})
    bad = _Strategy("Bad Sleeve", raises=True)

    monkeypatch.setattr(runner, "load_etf_panel", lambda tickers, **kw: wavy_panel)
    monkeypatch.setattr(runner, "default_strategies", lambda: [bad, good])
    monkeypatch.setattr(runner, "load_latest_watchlist", lambda db: None)
    monkeypatch.setattr(
        sys, "argv",
        ["run_forward_paper.py", "--db", str(tmp_path / "forward.db"),
         "--main-db", str(tmp_path / "main.db")],
    )

    runner.main()

    out = capsys.readouterr().out
    assert "Bad Sleeve fehlgeschlagen: boom" in out
    assert "Good Sleeve" in out  # the healthy sleeve still advanced and reported its status


def test_main_isolates_a_crashing_bot_and_still_advances_the_other(
    monkeypatch, tmp_path, wavy_panel, capsys,
) -> None:
    """Mirrors the rule-strategy isolation: one ML bot's crash must not skip the other bot."""
    long_bot = _FakeBot("ML Long Bot", raises=True)
    short_bot = _FakeBot("ML Short Bot")

    monkeypatch.setattr(runner, "load_etf_panel", lambda tickers, **kw: wavy_panel)
    monkeypatch.setattr(runner, "default_strategies", lambda: [])
    monkeypatch.setattr(runner, "load_latest_watchlist", lambda db: None)
    monkeypatch.setattr(runner, "stock_panel_for_bots", lambda tickers, **kw: wavy_panel)
    monkeypatch.setattr(
        runner.MLLongStrategy, "from_registry", classmethod(lambda cls, db_path, **kw: long_bot),
    )
    monkeypatch.setattr(
        runner.MLShortStrategy, "from_registry", classmethod(lambda cls, db_path, **kw: short_bot),
    )
    monkeypatch.setattr(
        sys, "argv",
        ["run_forward_paper.py", "--db", str(tmp_path / "forward.db"),
         "--main-db", str(tmp_path / "main.db")],
    )

    runner.main()

    out = capsys.readouterr().out
    assert "ML Long Bot fehlgeschlagen: boom" in out
    assert "ML Short Bot" in out
