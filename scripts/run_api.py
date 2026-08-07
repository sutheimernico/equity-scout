"""Serve the dashboard read-API (v12 M1: optional LAN bind behind DASH_TOKEN)."""
from __future__ import annotations

import argparse
import os

import uvicorn

from equity_scout.api import create_app

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="equity_scout.db")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1",
                    help="Bind address. 0.0.0.0 exposes the dashboard on the LAN and "
                         "REQUIRES DASH_TOKEN in the environment (fail-closed).")
    args = ap.parse_args()
    if args.host not in LOOPBACK_HOSTS and not os.environ.get("DASH_TOKEN"):
        raise SystemExit(
            "Refusing to bind non-loopback without DASH_TOKEN set — the dashboard has a "
            "write endpoint and stays private. Set DASH_TOKEN in .env (see README "
            "'Handy-Cockpit') and retry."
        )
    uvicorn.run(create_app(args.db, warm_model=True), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
