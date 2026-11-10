#!/usr/bin/env python3
"""Gate for the data refresh: fail loudly instead of committing bad data.

Run after appending a pull and BEFORE oos_analytics.py / committing:

    python3 scripts/validate_data.py            # validates data/
    python3 scripts/validate_data.py <dir>      # validates another data dir

Checks
  1. data/last_pull.json names the expected store (EXPECTED_STORE). The
     refresh must write the `shopDomain` reported by the Shopify query
     results into that file — the connector holds one store at a time and
     can silently point at a different one.
  2. No missing days, and every recent day has a normal number of inventory
     rows, SKU sales rows and net sales compared with the preceding weeks.
     A pull from another store shows up here even if (1) was skipped.

Exit code 0 = OK, 1 = do not commit.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

EXPECTED_STORE = "vegavero.myshopify.com"
RECENT_DAYS = 35        # window that gets checked
BASELINE_DAYS = 56      # preceding window the recent days are compared with
MIN_INV_ROWS_FRAC = 0.8   # inventory rows per day vs baseline median
MIN_SALES_ROWS_FRAC = 0.4  # SKU sales rows per day vs baseline median
MIN_NET_SALES_FRAC = 0.25  # net sales per day vs baseline median


def main() -> int:
    data = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "data"
    problems: list[str] = []

    marker = data / "last_pull.json"
    if not marker.exists():
        problems.append(f"{marker.name} missing — the refresh must record the store it pulled from")
    else:
        store = json.loads(marker.read_text()).get("shopDomain")
        if store != EXPECTED_STORE:
            problems.append(f"last pull came from '{store}', expected '{EXPECTED_STORE}'")

    inv = pd.read_csv(data / "inventory_daily.csv", parse_dates=["day"])
    sal = pd.read_csv(data / "sales_daily.csv", parse_dates=["day"])
    last = inv["day"].max()
    days = pd.date_range(inv["day"].min(), last, freq="D")

    per_day = pd.DataFrame(index=days)
    per_day["inv_rows"] = inv.groupby("day").size().reindex(days).fillna(0)
    named = sal[sal["sku"].notna() & (sal["sku"] != "")]
    per_day["sales_rows"] = named.groupby("day").size().reindex(days).fillna(0)
    per_day["net_sales"] = sal.groupby("day")["net_sales"].sum().reindex(days).fillna(0)

    recent = per_day.iloc[-RECENT_DAYS:]
    base = per_day.iloc[-(RECENT_DAYS + BASELINE_DAYS):-RECENT_DAYS]
    limits = {
        "inv_rows": (MIN_INV_ROWS_FRAC, "inventory rows"),
        "sales_rows": (MIN_SALES_ROWS_FRAC, "SKU sales rows"),
        "net_sales": (MIN_NET_SALES_FRAC, "net sales"),
    }
    for col, (frac, label) in limits.items():
        floor = frac * base[col].median()
        bad = recent[recent[col] < floor]
        if len(bad):
            sample = ", ".join(f"{d.date()} ({v:.0f})" for d, v in bad[col].head(5).items())
            problems.append(
                f"{len(bad)} recent day(s) with too few {label} "
                f"(< {floor:.0f}, normal ≈ {base[col].median():.0f}): {sample}"
                + (" …" if len(bad) > 5 else ""))

    if sal["day"].max() != last:
        problems.append(f"sales end {sal['day'].max().date()} but inventory ends {last.date()}")

    if problems:
        print("DATA VALIDATION FAILED — do not commit:")
        for p in problems:
            print("  -", p)
        return 1
    print(f"data OK: {EXPECTED_STORE}, through {last.date()}, "
          f"{int(recent['inv_rows'].median())} inventory rows/day, "
          f"€{recent['net_sales'].median():,.0f} median net sales/day")
    return 0


if __name__ == "__main__":
    sys.exit(main())
