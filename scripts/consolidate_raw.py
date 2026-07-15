#!/usr/bin/env python3
"""Consolidate raw ShopifyQL pull results into the two canonical CSVs.

Reads the per-month ShopifyQL JSON results (saved tool-result files plus any
results embedded inline in the session transcript) and writes:

  data/inventory_daily.csv  day, sku, ending_inventory_units, inventory_units_sold
  data/sales_daily.csv      day, sku, net_items_sold, net_sales, gross_sales

Rows with an empty SKU are kept (they represent deleted/unmapped variants) so
totals still reconcile, but the analytics layer ignores them.
"""
import csv
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL_RESULTS = Path(sys.argv[1]) if len(sys.argv) > 1 else None
TRANSCRIPT = Path(sys.argv[2]) if len(sys.argv) > 2 else None


def iter_query_results():
    """Yield parsed {query, columns, rows} dicts from every source."""
    seen_queries = set()
    if TOOL_RESULTS and TOOL_RESULTS.is_dir():
        for f in sorted(TOOL_RESULTS.glob("mcp-Shopify-run-analytics-query-*.txt")):
            try:
                doc = json.loads(f.read_text())
            except json.JSONDecodeError:
                continue
            if doc.get("query") not in seen_queries:
                seen_queries.add(doc["query"])
                yield doc
    if TRANSCRIPT and TRANSCRIPT.is_file():
        # Inline tool results live in transcript lines as JSON strings that
        # contain the same {"query": ..., "rows": ...} document.
        pat = re.compile(r'\{"query":"FROM (?:sales|inventory) [^"]+"')
        for line in TRANSCRIPT.open():
            if '"rowCount"' not in line or '"query":"FROM' not in line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            for text in _strings(entry):
                if not pat.match(text.strip()[:400]) and not text.strip().startswith('{"query":"FROM'):
                    continue
                try:
                    doc = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(doc, dict) and "rows" in doc and doc.get("query") not in seen_queries:
                    seen_queries.add(doc["query"])
                    yield doc


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


def main():
    inv_rows, sales_rows = {}, {}
    for doc in iter_query_results():
        q = doc["query"]
        for row in doc["rows"]:
            key = (row[0], row[1])
            if "GROUP BY product_variant_sku" not in q:
                continue
            if q.startswith("FROM inventory") and "TIMESERIES day" in q:
                inv_rows[key] = row
            elif q.startswith("FROM sales") and "TIMESERIES day" in q and "gross_sales" in q:
                sales_rows[key] = row

    (REPO / "data").mkdir(exist_ok=True)
    with open(REPO / "data/inventory_daily.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["day", "sku", "ending_inventory_units", "inventory_units_sold"])
        for key in sorted(inv_rows):
            w.writerow(inv_rows[key])
    with open(REPO / "data/sales_daily.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["day", "sku", "net_items_sold", "net_sales", "gross_sales"])
        for key in sorted(sales_rows):
            w.writerow(sales_rows[key])

    inv_days = sorted({k[0] for k in inv_rows})
    sales_days = sorted({k[0] for k in sales_rows})
    print(f"inventory: {len(inv_rows)} rows, {inv_days[0]}..{inv_days[-1]}")
    print(f"sales:     {len(sales_rows)} rows, {sales_days[0]}..{sales_days[-1]}")


if __name__ == "__main__":
    main()
