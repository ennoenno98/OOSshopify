# Project instructions

## Which connector for which store

- **Vegavero → Shopify connector (default).** The Shopify connector must stay
  connected to Vegavero (`vegavero.myshopify.com`, www.vegavero.com). Use it
  for all Vegavero store data and for this repo's data refresh.
- **Wowtamins → Matrixify connector (`Matrixify_Wowtmains`) and Klar.** Do
  not switch the Shopify connector to Wowtamins or any other store to answer
  a Wowtamins question.
  - Sales and revenue per SKU and day: Klar, shop "3.1.2 Wowtamins Shopify
    D2C" (this is what the dashboard's Wowtamins series is built from, see
    `scripts/build_wowtamins_data.py`).
  - Store objects (products, current stock, single orders): Matrixify. Two
    limits found in Nov 2026: an export job is capped at 10,000 orders on the
    store's Matrixify plan, and the export file host `app.matrixify.app` is
    blocked by this environment's network policy, so files cannot be
    downloaded here. Do not try to route around the block; report it.
  - Neither source has daily inventory history. Wowtamins stock-outs are
    inferred from sales gaps only.
- Never call the Shopify `switch-shop` tool unless the user explicitly asks
  to change the connected store.

## Before any Shopify data pull

The Shopify connector holds one store at a time and can silently point at a
different one (in Oct/Nov 2026 it pointed at the Vanatari store for three
weeks and the refresh committed that store's data).

1. Call `get-shop-info` first. If the store is not Vegavero, stop, change
   nothing, and tell the user.
2. After pulling, write the `shopDomain` from the query results into
   `data/last_pull.json`.
3. Run `python3 scripts/validate_data.py`. Commit and push only if it passes.

Refresh steps are in `README.md` ("Refreshing the data").
