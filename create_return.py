#!/usr/bin/env python3
"""
Create an AfterShip return: POST /returns/{version}/returns

Loads .env from this directory (same pattern as aftership-commerce-query).
"""

from __future__ import annotations

import argparse
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


def shopify_numeric_id(gid_or_id: str) -> str:
    s = (gid_or_id or "").strip()
    if not s:
        return ""
    if s.startswith("gid://"):
        return s.rsplit("/", 1)[-1]
    return s


def aftership_store_external_id() -> str:
    explicit = os.environ.get("AFTERSHIP_STORE_EXTERNAL_ID", "").strip()
    if explicit:
        return explicit
    domain = os.environ.get("SHOPIFY_SHOP_DOMAIN", "").strip().lower()
    if not domain:
        return ""
    if domain.endswith(".myshopify.com"):
        return domain[: -len(".myshopify.com")]
    if "." in domain:
        return domain.split(".", 1)[0]
    return domain


def normalize_email(email: str) -> str:
    return email.strip().lower()


def order_emails_rest(order: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    v = order.get("email")
    if isinstance(v, str) and v.strip():
        out.add(normalize_email(v))
    cust = order.get("customer") or {}
    if isinstance(cust, dict):
        v2 = cust.get("email")
        if isinstance(v2, str) and v2.strip():
            out.add(normalize_email(v2))
    return out


def line_returnable_qty(item: dict[str, Any]) -> int:
    for key in ("fulfillable_quantity", "quantity"):
        if key in item and item[key] is not None:
            try:
                q = int(item[key])
            except (TypeError, ValueError):
                continue
            if q > 0:
                return q
    return 0


def _shopify_headers() -> tuple[str, str, dict[str, str]]:
    shop = os.environ.get("SHOPIFY_SHOP_DOMAIN", "").strip()
    token = os.environ.get("SHOPIFY_ADMIN_ACCESS_TOKEN", "").strip()
    ver = os.environ.get("SHOPIFY_API_VERSION", "2024-10").strip()
    if not shop or not token:
        sys.exit("SHOPIFY_SHOP_DOMAIN and SHOPIFY_ADMIN_ACCESS_TOKEN must be set in .env")
    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Access-Token": token,
    }
    return shop, ver, headers


def normalize_shopify_order_name(name: str) -> str:
    s = name.strip()
    if not s.startswith("#"):
        s = f"#{s.lstrip('#')}"
    return s


def fetch_shopify_order(order_id: str) -> dict[str, Any]:
    shop, ver, headers = _shopify_headers()
    url = f"https://{shop}/admin/api/{ver}/orders/{shopify_numeric_id(order_id)}.json"
    r = requests.get(url, headers=headers, timeout=60)
    if r.status_code == 404:
        sys.exit(f"Shopify order not found for id={order_id!r} (HTTP 404)")
    if r.status_code >= 400:
        sys.exit(f"Shopify error HTTP {r.status_code}: {r.text[:800]}")
    body = r.json()
    if not isinstance(body, dict) or "order" not in body:
        sys.exit(f"Unexpected Shopify response: {body!r}")
    return body["order"]


def fetch_shopify_order_by_name(order_name: str) -> dict[str, Any]:
    """Resolve order via GET /orders.json?name=... (REST)."""
    shop, ver, headers = _shopify_headers()
    want = normalize_shopify_order_name(order_name)
    url = f"https://{shop}/admin/api/{ver}/orders.json"
    params = {"status": "any", "limit": 50, "name": want}
    r = requests.get(url, headers=headers, params=params, timeout=60)
    if r.status_code >= 400:
        sys.exit(f"Shopify list orders HTTP {r.status_code}: {r.text[:800]}")
    body = r.json()
    orders = body.get("orders") if isinstance(body, dict) else None
    if not isinstance(orders, list):
        sys.exit(f"Unexpected Shopify list response: {body!r}")
    for o in orders:
        if isinstance(o, dict) and o.get("name") == want:
            return o
    if len(orders) == 1 and isinstance(orders[0], dict):
        return orders[0]
    sys.exit(
        f"No Shopify order matched name={want!r} (got {len(orders)} result(s); try --order-id)."
    )


def build_return_items(
    order: dict[str, Any],
    line_item_ids: list[str],
    skus: list[str],
    reason: str,
    subreason: str | None,
    comment: str | None,
) -> list[dict[str, Any]]:
    items_out: list[dict[str, Any]] = []
    want_ids = {shopify_numeric_id(x) for x in line_item_ids if x.strip()}
    want_skus = {s.strip().lower() for s in skus if s and s.strip()}

    for li in order.get("line_items") or []:
        if not isinstance(li, dict):
            continue
        lid = str(li.get("id") or "")
        sku = (li.get("sku") or "").strip()
        qty = line_returnable_qty(li)
        if qty < 1:
            continue
        if want_ids and shopify_numeric_id(lid) not in want_ids:
            continue
        if want_skus and (not sku or sku.lower() not in want_skus):
            continue
        entry: dict[str, Any] = {
            "external_order_item_id": shopify_numeric_id(lid),
            "intended_return_quantity": qty,
            "return_reason": reason,
            "resolution": "refund",
        }
        if subreason:
            entry["return_subreason"] = subreason
        if comment:
            entry["return_reason_comment"] = comment
        items_out.append(entry)

    return items_out


def summarize_aftership(data: dict[str, Any]) -> dict[str, Any]:
    rma = data.get("rma_number")
    rid = data.get("id")
    approval = data.get("approval_status")
    label_url = None
    docs_url = None
    for sh in data.get("shipments") or []:
        if not isinstance(sh, dict):
            continue
        if not docs_url:
            for key in ("shipping_documents_url", "packing_slip_url"):
                v = sh.get(key)
                if isinstance(v, str) and v.startswith("http"):
                    docs_url = v
                    break
        lab = sh.get("label")
        if isinstance(lab, dict) and not label_url:
            u = lab.get("url")
            if isinstance(u, str) and u.startswith("http"):
                label_url = u
    return {
        "rma_number": str(rma) if rma is not None else None,
        "aftership_return_id": str(rid) if rid is not None else None,
        "approval_status": str(approval) if approval is not None else None,
        "return_label_url": label_url,
        "shipping_documents_url": docs_url,
    }


def main() -> None:
    _load_dotenv()
    here = Path(__file__).resolve().parent

    p = argparse.ArgumentParser(description="Create AfterShip return from Shopify REST order")
    oid = p.add_mutually_exclusive_group(required=True)
    oid.add_argument("--order-id", help="Shopify numeric order id")
    oid.add_argument(
        "--order-name",
        help="Shopify order name, e.g. AWY159901 or #AWY159901 (looked up via REST orders.json)",
    )
    p.add_argument(
        "--line-item-id",
        action="append",
        default=[],
        metavar="ID",
        help="Shopify line item id (repeat for multiple). If omitted with no --sku, all returnable lines.",
    )
    p.add_argument("--sku", action="append", default=[], metavar="SKU", help="Filter by SKU (repeat)")
    p.add_argument("--reason", default="Other")
    p.add_argument("--return-subreason", default=None)
    p.add_argument("--customer-notes", default=None)
    p.add_argument(
        "--refund-destination",
        default=os.environ.get("AFTERSHIP_DEFAULT_REFUND_DESTINATION", "original_payment"),
        choices=("original_payment", "store_credit"),
    )
    p.add_argument(
        "--return-method-type",
        default=os.environ.get("AFTERSHIP_DEFAULT_RETURN_METHOD_TYPE", "retailer_label"),
    )
    p.add_argument("--verify-email", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--output",
        default=str(here / "last_create_return_response.json"),
        help="Write full AfterShip JSON response here",
    )
    args = p.parse_args()

    ver = os.environ.get("AFTERSHIP_RETURNS_API_VERSION", "2026-01").strip()

    if args.order_id:
        order = fetch_shopify_order(args.order_id)
    else:
        order = fetch_shopify_order_by_name(args.order_name or "")
    if args.verify_email:
        if normalize_email(args.verify_email) not in order_emails_rest(order):
            sys.exit(f"Email {args.verify_email!r} does not match Shopify order; aborting.")

    order_ext = shopify_numeric_id(str(order.get("id") or ""))
    store_ext = aftership_store_external_id()
    if not order_ext:
        sys.exit("Shopify order id missing from REST response")
    if not store_ext:
        sys.exit("Set AFTERSHIP_STORE_EXTERNAL_ID or a valid SHOPIFY_SHOP_DOMAIN in .env")

    line_ids = list(args.line_item_id or [])
    skus = list(args.sku or [])
    return_items = build_return_items(
        order,
        line_ids,
        skus if not line_ids else [],
        args.reason,
        args.return_subreason,
        args.customer_notes,
    )
    if not return_items:
        sys.exit("No matching return line items (check ids/SKUs and returnable quantities).")

    body: dict[str, Any] = {
        "order": {
            "external_id": order_ext,
            "store": {"platform": "shopify", "external_id": store_ext},
        },
        "return_items": return_items,
        "refund_destination": args.refund_destination,
        "return_method": {"type": args.return_method_type},
    }

    if args.dry_run:
        result = {
            "shopify_order_id": order_ext,
            "shopify_order_name": order.get("name"),
            "aftership_request_body": body,
        }
        print(json.dumps(result, indent=2))
        return

    key = os.environ.get("AFTERSHIP_API_KEY", "").strip()
    if not key:
        sys.exit("AFTERSHIP_API_KEY is empty in .env (required for POST; use --dry-run to only validate Shopify payload)")

    url = f"https://api.aftership.com/returns/{ver}/returns"
    headers = {"as-api-key": key, "Content-Type": "application/json"}
    r = requests.post(url, headers=headers, json=body, timeout=60)
    out_path = Path(args.output)
    try:
        resp_json = r.json()
    except ValueError:
        resp_json = {"_raw": r.text}
    out_path.write_text(json.dumps(resp_json, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote full response: {out_path}")

    if r.status_code >= 400:
        sys.exit(f"AfterShip HTTP {r.status_code}: {resp_json!r}")

    data = resp_json.get("data") if isinstance(resp_json, dict) else None
    if not isinstance(data, dict):
        sys.exit(f"Unexpected AfterShip response: {resp_json!r}")

    summary = summarize_aftership(data)
    result = {
        **summary,
        "shopify_order_id": order_ext,
        "shopify_order_name": order.get("name"),
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

# -----------------------------------------------------------------------------
# Decagon script tools: assign tool output to a variable literally named ``result``
# (that name is what the runner looks for), e.g. ``result = {"rma_number": "..."}``.
# Do not end the script with only ``print(result)`` as the last line — ``print`` returns
# None → output: null. If Build still shows null, add as the final line: ``return result``.
# Full example: decagon-return-tool/tools/submit_aftership_return.py ends with
# ``result = _execute_tool()`` and ``# return result`` (uncomment return if needed).
# -----------------------------------------------------------------------------
