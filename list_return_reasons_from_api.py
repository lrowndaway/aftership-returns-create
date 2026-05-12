#!/usr/bin/env python3
"""
AfterShip Returns does not expose a public "list configured return reasons" endpoint.
This script calls GET /returns (paginated) and prints distinct return_reason / return_subreason
values seen on historical return line items — useful to match exact API strings.

Loads .env from this directory (same keys as create_return.py).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

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


def _api_key() -> str:
    for k in (
        "AFTERSHIP_RETURNS_STAGING_API_KEY",
        "AFTERSHIP_API_KEY",
    ):
        v = os.environ.get(k, "").strip()
        if v:
            return v
    return ""


def _harvest_from_return(ret: dict[str, Any], out: set[tuple[str, str | None]]) -> None:
    for item in ret.get("return_items") or []:
        if not isinstance(item, dict):
            continue
        rr = item.get("return_reason")
        if rr is None or not str(rr).strip():
            continue
        rs = item.get("return_subreason")
        rs_s = str(rs).strip() if rs is not None and str(rs).strip() else None
        out.add((str(rr).strip(), rs_s))


def main() -> None:
    _load_dotenv()
    key = _api_key()
    if not key:
        sys.exit("Set AFTERSHIP_API_KEY or AFTERSHIP_RETURNS_STAGING_API_KEY in .env")

    ver = os.environ.get("AFTERSHIP_RETURNS_API_VERSION", "2026-01").strip()
    max_pages = int(os.environ.get("AFTERSHIP_LIST_REASONS_MAX_PAGES", "5"))
    limit = min(50, int(os.environ.get("AFTERSHIP_LIST_REASONS_LIMIT", "50")))

    base = f"https://api.aftership.com/returns/{ver}/returns"
    headers = {"as-api-key": key, "Content-Type": "application/json"}

    pairs: set[tuple[str, str | None]] = set()
    for page in range(1, max_pages + 1):
        r = requests.get(
            base,
            headers=headers,
            params={"page": page, "limit": limit},
            timeout=60,
        )
        if r.status_code >= 400:
            sys.exit(f"AfterShip HTTP {r.status_code}: {r.text[:800]}")
        try:
            body = r.json()
        except ValueError:
            sys.exit(f"Non-JSON response: {r.text[:500]}")

        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            break
        returns = data.get("returns") or []
        if not isinstance(returns, list) or not returns:
            break

        for entry in returns:
            if isinstance(entry, dict):
                _harvest_from_return(entry, pairs)

        pagination = data.get("pagination") if isinstance(data, dict) else None
        if isinstance(pagination, dict):
            total_pages = pagination.get("total_pages") or pagination.get("totalPages")
            if isinstance(total_pages, int) and page >= total_pages:
                break

    if not pairs:
        print(
            "No return_reason values found in recent GET /returns pages.\n"
            "Either there are no returns yet, or the list payload shape differs — "
            "inspect one return with verify_return_by_rma.py.",
        )
        return

    print(
        "Distinct (return_reason, return_subreason) from recent returns "
        f"(up to {max_pages} page(s), limit={limit}):\n",
    )
    for reason, sub in sorted(pairs, key=lambda x: (x[0].lower(), x[1] or "")):
        line = json.dumps({"return_reason": reason, "return_subreason": sub}, ensure_ascii=False)
        print(line)


if __name__ == "__main__":
    main()
