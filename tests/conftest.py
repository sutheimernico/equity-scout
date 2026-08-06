"""Shared fixtures. The wavy panel is session-scoped (built once) since the ML tests reuse it."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from equity_scout.market import PricePanel


@pytest.fixture(autouse=True)
def _no_broker_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may reach the broker.

    `run_session` defaults to `feed="alpaca"` since 2026-08-06 and only falls back to the
    simulated path when the key is ABSENT. The shell chains source `.env`, so a test run
    started from one of them would otherwise place real (paper) orders and corrupt a track
    record. Tests that exercise the broker path set the key themselves and fake the HTTP calls.
    """
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET_KEY", raising=False)


@pytest.fixture(scope="session")
def wavy_panel() -> PricePanel:
    """~10y up-trending market with volatility waves so the primary signal turns on/off and labels
    vary — long enough for purged walk-forward to produce out-of-sample bets."""
    n = 2600
    idx = pd.bdate_range("2008-01-01", periods=n)
    base = np.array([1.0003**i * (1 + 0.18 * np.sin(i / 70.0)) for i in range(n)])
    cols = {
        t: list(100.0 * base * (1 + 0.02 * np.sin(np.arange(n) / 90.0 + off)))
        for off, t in enumerate(["SPY", "VEU", "VWO", "VNQ"])
    }
    cols["BIL"] = list(100.0 * 1.00005 ** np.arange(n))
    return PricePanel(pd.DataFrame(cols, index=idx))
