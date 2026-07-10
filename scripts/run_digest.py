"""Digest CLI: inbox pitches -> daily German digest, e-mailed if SMTP is configured.

Usage:
    python scripts/run_digest.py [--db equity_scout.db]

Without SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD/DIGEST_TO the digest is
printed to stdout instead of sent — an unconfigured digest is not an error.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.digest import build_digest, load_smtp_config, send_digest
from equity_scout.evidence.ledger import stats_by_source
from equity_scout.inbox_storage import load_pitches


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    args = parser.parse_args()

    # limit=1000: don't let load_pitches' default cap (100) silently drop open pitches
    # from a DAILY digest; the decided section is scoped to the last 24h instead.
    pitches = load_pitches(args.db, limit=1000)
    now = datetime.now(timezone.utc)
    date_label = now.date().isoformat()
    decided_since = (now - timedelta(hours=24)).isoformat(timespec="seconds")
    text = build_digest(
        pitches,
        date_label=date_label,
        decided_since=decided_since,
        evidence_stats=stats_by_source(args.db),
    )

    config = load_smtp_config(dict(os.environ))
    if config is None:
        print(text)
        print("SMTP not configured — printing digest.")
    else:
        send_digest(config, f"Copilot-Digest {date_label}", text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
