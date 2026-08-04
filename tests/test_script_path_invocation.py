"""Sibling-script imports must survive path-style invocation.

`python scripts/run_notify.py` (how daily_copilot.sh / nightly_train.sh start the chain)
puts scripts/ on sys.path, NOT the repo root — so a bare `from scripts.run_digest import ...`
raises ModuleNotFoundError. That regression silenced every Telegram pitch between
2026-07-21 and 2026-08-04 (notify aborted, chain logged FAILED and continued) and left the
Auto-Depot's regime gate permanently at "unknown" (run_autotrader swallowed it in an
except). Both callsites now anchor the repo root before importing a sibling; these tests
run in a subprocess because the pytest process already has the repo root on sys.path
(pyproject's pythonpath = ["."]) and would therefore pass either way.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_DIR / "scripts"


def test_notify_reaches_past_its_sibling_import(tmp_path: Path) -> None:
    """A real path-style run with an empty DB: it must fail on the MISSING WATCHLIST
    (the honest next step), not on the import that precedes it."""
    result = subprocess.run(
        [sys.executable, "scripts/run_notify.py", "--db", str(tmp_path / "empty.db"),
         "--inbox-only"],
        cwd=REPO_DIR, capture_output=True, text=True, timeout=120,
    )
    assert "No module named 'scripts'" not in result.stderr
    assert "No watchlist found" in result.stderr


def test_autotrader_regime_collector_resolves_its_sibling_import(tmp_path: Path) -> None:
    """Load run_autotrader exactly as a path-style start does (scripts/ on sys.path, repo
    root absent — cwd is tmp_path so `python -c`'s implicit cwd entry cannot help) and call
    the regime collector. fetch_year_closes is stubbed to None so no network is touched:
    every signal is unknown, so the collector legitimately returns None — what must NOT
    happen is the import failing and the gate degrading silently."""
    probe = f"""
import sys
sys.path.insert(0, {str(SCRIPTS_DIR)!r})
import importlib.util
import equity_scout.charts
equity_scout.charts.fetch_year_closes = lambda ticker: None  # no network in tests
spec = importlib.util.spec_from_file_location(
    "run_autotrader", {str(SCRIPTS_DIR / "run_autotrader.py")!r}
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print("REGIME:", mod._collect_regime_level(None))
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=tmp_path, capture_output=True, text=True, timeout=120,
    )
    assert "No module named 'scripts'" not in result.stderr, result.stderr
    assert "REGIME:" in result.stdout, result.stderr
