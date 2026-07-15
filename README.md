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
Deploy. Works with private repos (grant the Streamlit GitHub app access);
set the app itself to private if only your team should see it.

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
3. re-pull the variant list, and
4. re-run the two scripts above.

## Tuning

Every threshold (min demand λ, zero-run mask, days-of-supply cutoffs,
recovery rules, warm-up) is a constant at the top of
`scripts/oos_analytics.py`, documented in the methodology file.
