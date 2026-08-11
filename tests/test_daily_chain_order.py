"""Daily chain step order: delivery before cosmetics.

`insights` costs ~90 s per title over 30 titles (measured 2026-08-11) and only fills a
display cache that nothing else in the chain reads. As the SECOND step it made the other
ten wait out its 12-minute cap every day. It now runs last, so a cap that fires there
costs no pitch, no booking and no resolution — see daily_copilot.sh's comment.
"""
from __future__ import annotations

from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
CHAIN = REPO_DIR / "scripts" / "daily_copilot.sh"

# Every step whose output someone actually receives or that writes the ledger/books.
DELIVERY_STEPS = (
    "step radar",
    "step earnings",
    "step evidence",
    "step fscore",
    "step notify",
    "step score_watchlist",
    "step resolve_predictions",
    "step resolve_evidence",
    "step resolve_events",
    "step lanes",
    "step digest",
)


def _text() -> str:
    return CHAIN.read_text()


def test_insights_runs_after_every_delivery_step():
    text = _text()
    insights_at = text.index("step insights")
    for step in DELIVERY_STEPS:
        assert text.index(step) < insights_at, f"{step} must not wait on insights"


def test_insights_carries_its_own_wider_cap():
    """A 30-title run does not fit the chain-wide 12 min, and raising the chain-wide cap
    would hand every other step a budget it has no reason to have."""
    text = _text()
    assert 'STEP_TIMEOUT="${EQUITY_SCOUT_INSIGHTS_TIMEOUT:-' in text
    # The override sits directly before the step it applies to, not somewhere above the
    # chain — otherwise a later-added step would silently inherit the wide cap.
    override_at = text.index('STEP_TIMEOUT="${EQUITY_SCOUT_INSIGHTS_TIMEOUT:-')
    assert override_at < text.index("step insights")
    for step in DELIVERY_STEPS:
        assert text.index(step) < override_at, f"{step} would inherit the insights cap"
