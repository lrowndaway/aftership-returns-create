# AfterShip Returns — create return (local validation)

End-to-end local check: **Shopify Admin REST** order → **AfterShip Returns** `POST /returns/{version}/returns`, then optional **GET by RMA** to confirm the return exists.

Docs:

- Returns quick start: https://www.aftership.com/docs/returns/quickstart/api-quick-start  
- List returns (filters): https://www.aftership.com/docs/returns/wpx1lk91k5ima-get-returns  

## Setup

```bash
cd actions-runner/processes/aftership-returns-create
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit **`.env`**: set `AFTERSHIP_API_KEY`, Shopify credentials, and (if needed) `AFTERSHIP_STORE_EXTERNAL_ID`.

## Create a return

Either the **numeric Shopify order id** or the **order name** (e.g. `#AWY159901`), plus line selection.

**By order name + SKU:**

```bash
python3 create_return.py \
  --order-name AWY159901 \
  --sku 100634MBLKV1 \
  --reason "Other" \
  --dry-run
```

**By order id + line item id** (same as Decagon metadata / item selector):

```bash
python3 create_return.py \
  --order-id 6695756726456 \
  --line-item-id 15198935580856 \
  --reason "Other" \
  --verify-email "customer@example.com"
```

- **`--verify-email`**: optional; if set, must match the order email on Shopify.  
- **`--dry-run`**: print the AfterShip JSON body only; no POST.  
- **`--sku`**: filter by SKU instead of line item id (omit `--line-item-id`).  
- Omit **`--line-item-id`** / **`--sku`** to include every returnable line (use with care).

Some return reasons (often **`Other`**) require a comment: use **`--customer-notes`** (maps to AfterShip `return_reason_comment`). If AfterShip returns `422` mentioning comments, add that flag.

Full response is written to **`last_create_return_response.json`**.

## Verify an existing return by RMA

```bash
python3 verify_return_by_rma.py RYXCS87M
```

Writes **`last_verify_rma_<RMA>.json`** and prints HTTP status + `meta.message`.

