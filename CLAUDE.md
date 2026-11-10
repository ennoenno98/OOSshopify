# Project instructions

## Which connector for which store

- **Vegavero → Shopify connector (default).** The Shopify connector must stay
  connected to Vegavero (`vegavero.myshopify.com`, www.vegavero.com). Use it
  for all Vegavero store data and for this repo's data refresh.
- **Wowtamins → Matrixify connector (`Matrixify_Wowtmains`).** Do not switch
  the Shopify connector to Wowtamins or any other store to answer a
  Wowtamins question; use Matrixify (and Klar for revenue figures) instead.
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
