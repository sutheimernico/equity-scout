"""Serve the dashboard read-API."""
from __future__ import annotations

import argparse

import uvicorn

from equity_scout.api import create_app


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="equity_scout.db")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    uvicorn.run(create_app(args.db), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
