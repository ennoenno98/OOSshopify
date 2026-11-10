# OOS Lost Revenue Dashboard — vegavero.com

Tracks the revenue lost to out-of-stock products on the Vegavero Shopify
store, per SKU and per week, using the methodology in
[`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).

**Open the dashboard:** [`dashboard/index.html`](dashboard/index.html)
(fully self-contained — download and open in any browser, light & dark mode),
or run the Streamlit app (below).

## Deploying the Streamlit app

`streamlit_app.py` is the same dashboard as a hosted web app. It reads the
committed `results/` files — no Shopify credentials needed; it updates
whenever refreshed data is pushed to this repo.

Run locally:

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Deploy free on [Streamlit Community Cloud](https://share.streamlit.io):
**New app** → select this repo (`ennoenno98/OOSshopify`), branch
`claude/oos-lost-revenue-dashboard-8z8rzj`, main file `streamlit_app.py` →
Deploy. Works with private repos (grant the Streamlit GitHub app access).

### Protecting the app

Two options, combinable:

- **Password gate (built into the app).** In the deployed app go to
  **Settings → Secrets** and add:

  ```toml
  APP_PASSWORD = "choose-a-password"
  ```

  Viewers must enter it before anything renders. Without this secret the
  app runs open (handy for local use; locally you can set it in
  `.streamlit/secrets.toml`, which is gitignored).

- **Private app (Streamlit accounts).** **Settings → Sharing** → make the
  app private and invite viewers by email; they sign in with Google/GitHub.

## How it works

```
data/                      raw extracts from Shopify (committed)
  inventory_daily.csv        day × SKU: ending inventory, units sold
  sales_daily.csv            day × SKU: net items, net & gross sales
  variants.csv               SKU → product title, price, status
scripts/
  oos_analytics.py           the model: λ baselines, OOS categories,
                             episodes, lost revenue  (thresholds at the top)
  build_dashboard.py         renders results/ into dashboard/index.html
  consolidate_raw.py         (one-off) merged the original MCP pulls into data/
results/                     model output (committed)
  sku_daily.csv, weekly.csv, sku_summary.csv, episodes.csv, summary.json
dashboard/index.html         the deliverable
```

Rebuild after changing data or thresholds:

```bash
pip install pandas
python3 scripts/oos_analytics.py      # writes results/
python3 scripts/build_dashboard.py    # writes dashboard/index.html
```

## Refreshing the data

The extracts were pulled through Claude's Shopify MCP connection (ShopifyQL
analytics + Admin API). To refresh, ask Claude to:

1. Re-pull `FROM inventory` and `FROM sales` daily per `product_variant_sku`
   for the months since the last day in `data/*.csv` (queries are month-sized;
   pull through *yesterday* — never include the current partial day),
2. append them to the CSVs (or re-run `consolidate_raw.py` on the new pulls),
3. re-pull the variant list,
4. write the `shopDomain` reported by the Shopify query results into
   `data/last_pull.json`,
5. run `python3 scripts/validate_data.py` — it must pass before anything is
   committed (see below), and
6. re-run the two scripts above.

### Store check (important)

The Shopify connector holds **one store at a time** and can silently point
at a different store (in Oct/Nov 2026 it pointed at the Vanatari store for
three weeks and the refresh committed that store's data). Every refresh must
therefore:

- call `get-shop-info` first and stop unless the store is **Vegavero**
  (`vegavero.myshopify.com`), and
- run `scripts/validate_data.py` before committing. It checks the recorded
  store and that recent days have a normal number of inventory rows, SKU
  sales rows and net sales; a pull from another store fails this check.

## Brands

The app has a brand selector. Vegavero uses the top-level `data/` and
`results/` folders; every other brand lives in `data/<brand>/` and
`results/<brand>/`.

| Brand | Sales source | Inventory history | Model |
| --- | --- | --- | --- |
| Vegavero | Shopify analytics (ShopifyQL) | yes, daily per SKU | all categories |
| Wowtamins | Klar, shop "3.1.2 Wowtamins Shopify D2C" | **none** | sales-gap rules only |

Refreshing Wowtamins: pull `calendar_date × product_sku` from Klar for the
days since `data/wowtamins/last_pull.json` (windows of at most 30 days, the
metrics are listed at the top of `scripts/build_wowtamins_data.py`), save
each result as a JSON file in an empty folder, then

```bash
python3 scripts/build_wowtamins_data.py <folder with the Klar results>
python3 scripts/oos_analytics.py --brand wowtamins
```

Because Wowtamins has no stock data, a day counts as out of stock only when
a SKU that normally sells 3+ units a day sells none (Demand gap), plus the
days until sales recover (Suppressed sales). A variant that was paused or
discontinued on purpose is indistinguishable from a stock-out. The static
`dashboard/index.html` shows Vegavero only.

## Tuning

Every threshold (min demand λ, zero-run mask, days-of-supply cutoffs,
recovery rules, warm-up) is a constant at the top of
`scripts/oos_analytics.py`, documented in the methodology file.
