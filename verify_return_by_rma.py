#!/usr/bin/env python3
"""
GET AfterShip return by RMA: /returns/{version}/returns/rma/{rma}

Loads .env from this directory.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

import requests

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore


def _load_dotenv() -> None:
    if load_dotenv is None:
        return
    here = Path(__file__).resolve().parent
    p = here / ".env"
    if p.is_file():
        load_dotenv(p)


def main() -> None:
    _load_dotenv()
    here = Path(__file__).resolve().parent

    p = argparse.ArgumentParser(description="GET AfterShip return by RMA")
    p.add_argument("rma", help="RMA code, e.g. RYXCS87M")
    p.add_argument(
        "--output",
        default=None,
        help="Write JSON here (default: last_verify_rma_<RMA>.json in this folder)",
    )
    args = p.parse_args()

    key = os.environ.get("AFTERSHIP_API_KEY", "").strip()
    if not key:
        sys.exit("AFTERSHIP_API_KEY is empty in .env")

    ver = os.environ.get("AFTERSHIP_RETURNS_API_VERSION", "2026-01").strip()
    rma = args.rma.strip()
    enc = quote(rma, safe="")
    url = f"https://api.aftership.com/returns/{ver}/returns/rma/{enc}"
    r = requests.get(
        url,
        headers={"as-api-key": key, "Content-Type": "application/json"},
        timeout=60,
    )
    try:
        body = r.json()
    except ValueError:
        body = {"_raw": r.text}

    out = args.output or str(here / f"last_verify_rma_{rma}.json")
    Path(out).write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    print(f"HTTP {r.status_code}")
    meta = body.get("meta") if isinstance(body, dict) else {}
    if isinstance(meta, dict) and meta.get("message"):
        print(meta.get("message"))
    print(f"Wrote: {out}")


if __name__ == "__main__":
    main()
