"""Digest CLI: inbox pitches -> daily German digest, e-mailed if SMTP is configured.

Usage:
    python scripts/run_digest.py [--db equity_scout.db]

Without SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD/DIGEST_TO the digest is
printed to stdout instead of sent — an unconfigured digest is not an error.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.digest import build_digest, load_smtp_config, send_digest
from equity_scout.inbox_storage import load_pitches


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    args = parser.parse_args()

    pitches = load_pitches(args.db)
    date_label = datetime.now(timezone.utc).date().isoformat()
    text = build_digest(pitches, date_label=date_label)

    config = load_smtp_config(dict(os.environ))
    if config is None:
        print(text)
        print("SMTP not configured — printing digest.")
    else:
        send_digest(config, f"Copilot-Digest {date_label}", text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
