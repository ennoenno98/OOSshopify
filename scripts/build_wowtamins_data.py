#!/usr/bin/env python3
"""Merge Klar pulls into the Wowtamins sales series (data/wowtamins/).

Wowtamins has no ShopifyQL access in this project (the Shopify connector
stays on Vegavero), so its daily sales per SKU come from Klar:

    shop        "3.1.2 Wowtamins Shopify D2C"   (B2B excluded)
    report      revenue_and_profit
    dimensions  calendar_date, product_sku
    metrics     gross_items, net_items, gross_revenue, net_revenue,
                shipping_revenue, tax_value
    windows     <= 30 days each (500-row limit per query)

Usage:
    python3 scripts/build_wowtamins_data.py <dir with Klar result JSON files>

Each file is one query result as returned by the Klar connector. Rows are
merged into data/wowtamins/sales_daily.csv (day + sku, newest pull wins), so
a refresh only needs the days since the last pull.

Columns written (same shape as the Vegavero series):
    net_items_sold  = gross_items: units ordered that day. Demand is what the
                      model needs; a later return does not undo it.
    net_sales       = net_revenue minus the shipping share, i.e. after
                      discounts, returns and VAT, without shipping — the
                      closest Klar equivalent of Shopify "net sales".
    gross_sales     = the same before returns.

Klar days are UTC; German midnight falls 1-2 hours earlier. Irrelevant for
day-level stock-out detection, but daily totals differ slightly from Shopify.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "data" / "wowtamins"

# Inserts and flyers ride along in orders at ~0 EUR; they are not products.
MIN_REVENUE_PER_ITEM = 1.0

# Display names (the store renamed products from German to English in Oct 2026;
# SKUs stayed the same). Unknown SKUs fall back to the SKU itself.
NAMES = {
    "SKU-WT-WKCZ": ("Kids Complete Gummies", "sugar-free"),
    "SKU-WT-WKC": ("Kids Complete Gummies", "with sugar"),
    "SKU-WT-WTCZ": ("Teens Complete Gummies", "sugar-free"),
    "SKU-WT-WEGZ": ("Iron Gummies", "sugar-free"),
    "SKU-WT-WO3Z": ("Omega-3 Gummies", "sugar-free"),
    "SKU-WT-WO3": ("Omega-3 Gummies", "with sugar"),
    "SKU-WT-WMGz": ("Magnesium Gummies", "sugar-free"),
    "SKU-WT-WVD": ("Vitamin D3 + K2 Gummies", ""),
    "SKU-WT-WKMz": ("Kids Multi Gummies", "sugar-free"),
    "SKU-WT-WIG": ("Immun Gummies", ""),
    "SKU-WT-WKPz": ("Kids Probio Sticks", "sugar-free"),
    "SKU-WT-WB12": ("Vitamin B12 Spray", ""),
    "SKU-WT-WKCZ-BIO360": ("Kids Complete (BIO360)", "sugar-free"),
    "SKU-WT-WKC-BIO360": ("Kids Complete (BIO360)", "with sugar"),
}
FIELDS = ["day", "sku", "net_items_sold", "net_sales", "gross_sales"]


def read_pulls(folder: Path) -> dict[tuple[str, str], dict]:
    rows: dict[tuple[str, str], dict] = {}
    files = sorted(p for p in folder.iterdir() if p.suffix in (".json", ".txt"))
    if not files:
        raise SystemExit(f"no Klar result files in {folder}")
    for f in files:
        doc = json.loads(f.read_text())
        if doc.get("group_by") != ["calendar_date", "product_sku"]:
            continue
        if doc.get("truncated"):
            raise SystemExit(f"{f.name}: result was truncated at the row limit "
                             "— pull a shorter window")
        for r in doc["rows"]:
            rows[(r["calendar_date"], r["product_sku"] or "")] = r
    return rows


def to_sales(r: dict) -> dict:
    gross_rev = r["gross_revenue"] or 0.0
    # share of the tax-inclusive amount that is not VAT
    ex_vat = 1 - (r["tax_value"] or 0.0) / gross_rev if gross_rev else 1.0
    shipping_net = (r["shipping_revenue"] or 0.0) * ex_vat
    return {
        "day": r["calendar_date"],
        "sku": r["product_sku"] or "",
        "net_items_sold": int(r["gross_items"] or 0),
        "net_sales": round((r["net_revenue"] or 0.0) - shipping_net, 2),
        "gross_sales": round(gross_rev * ex_vat - shipping_net, 2),
    }


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    new = {k: to_sales(r) for k, r in read_pulls(Path(sys.argv[1])).items()}

    OUT.mkdir(parents=True, exist_ok=True)
    sales_path = OUT / "sales_daily.csv"
    merged: dict[tuple[str, str], dict] = {}
    if sales_path.exists():
        with open(sales_path) as f:
            for row in csv.DictReader(f):
                merged[(row["day"], row["sku"])] = row
    merged.update(new)

    # drop inserts/flyers: SKUs that earn (almost) nothing per item overall
    items: dict[str, float] = {}
    revenue: dict[str, float] = {}
    for (_, sku), row in merged.items():
        items[sku] = items.get(sku, 0) + float(row["net_items_sold"])
        revenue[sku] = revenue.get(sku, 0) + float(row["net_sales"])
    products = {s for s in items
                if s and items[s] > 0 and revenue[s] / items[s] >= MIN_REVENUE_PER_ITEM}
    dropped = sorted(set(items) - products)

    with open(sales_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for key in sorted(merged):
            if key[1] in products:
                w.writerow({k: merged[key][k] for k in FIELDS})

    with open(OUT / "variants.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sku", "product_title", "variant_title", "current_price", "status"])
        for sku in sorted(products):
            title, variant = NAMES.get(sku, (sku, ""))
            price = round(revenue[sku] / items[sku], 2)  # avg net price, fallback only
            w.writerow([sku, title, variant, price, "ACTIVE"])

    days = sorted({k[0] for k in merged if k[1] in products})
    (OUT / "last_pull.json").write_text(json.dumps(
        {"source": "Klar · 3.1.2 Wowtamins Shopify D2C", "pulled_through": days[-1]},
        indent=2) + "\n")
    print(f"{sales_path.relative_to(REPO)}: {days[0]} .. {days[-1]}, "
          f"{len(products)} SKUs, {sum(1 for k in merged if k[1] in products)} rows")
    print("dropped non-product SKUs:", ", ".join(dropped) or "none")


if __name__ == "__main__":
    main()
