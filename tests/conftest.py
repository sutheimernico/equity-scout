"""Shared fixtures. The wavy panel is session-scoped (built once) since the ML tests reuse it."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from equity_scout.market import PricePanel


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
