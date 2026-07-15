#!/usr/bin/env python3
"""OOS Lost Revenue analytics for the Vegavero Shopify store.

Shopify port of the Amazon OOS methodology (see docs/METHODOLOGY.md).
Computes, per SKU x day:

  * lambda      - expected demand rate (trailing-90d units per LIVE day)
  * category    - Physical / Critically low / Demand gap / Suppressed sales
                  (post-OOS) / Listing blocked / (in stock)
  * lost_units  - max(lambda - units, 0) on OOS days
  * lost_revenue- lost_units x trailing avg selling price

and rolls up weekly totals, per-SKU totals, OOS episodes, OOS rate and WISR.

All thresholds live below and are the single place to tune the model.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------- thresholds
MIN_DEMAND = 3.0        # lambda (units/day) below which a zero-sales day carries no signal
BASELINE_WINDOW = 90    # trailing window (live days) for lambda
BASELINE_MIN_DAYS = 14  # minimum live days before lambda is trusted
ZERO_RUN_MASK = 7       # >= this many consecutive zero-sales days = outage, masked from lambda
SHIP_WINDOW = 28        # trailing window for avg daily units used in reach (days-of-supply)
OOS_DOS = 2.0           # reach below this = "Critically low" (own warehouse: ~pick-pack buffer)
BLOCKED_MIN_REACH = 15.0  # units=0 with reach above this = listing problem, not stock-out
RECOVERY_DOS = 7.0      # episode stays open until reach climbs back above this band
RECOVERY_SALES_FRAC = 0.5  # ... or sales recover to >= this fraction of lambda
RECEIPT_MIN_FRAC = 2.0  # inbound restock counts as meaningful when >= this x lambda
PRICE_WINDOW = 90       # trailing window for avg selling price per unit
WARMUP_DAYS = 28        # first days of history are baseline warm-up, never scored

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
RESULTS = REPO / "results"

CAT_IN_STOCK = "In stock"
CAT_PHYSICAL = "Physical"
CAT_CRITICAL = "Critically low"
CAT_DEMAND_GAP = "Demand gap"
CAT_SUPPRESSED = "Suppressed sales (post-OOS)"
CAT_BLOCKED = "Listing blocked"
CAT_PRELAUNCH = "Pre-launch"
CAT_DISCONTINUED = "Discontinued"
OOS_CATS = {CAT_PHYSICAL, CAT_CRITICAL, CAT_DEMAND_GAP, CAT_SUPPRESSED}


def load_panel() -> tuple[pd.DataFrame, pd.DataFrame]:
    inv = pd.read_csv(DATA / "inventory_daily.csv", parse_dates=["day"])
    sales = pd.read_csv(DATA / "sales_daily.csv", parse_dates=["day"])
    variants = pd.read_csv(DATA / "variants.csv").fillna({"sku": ""})
    inv = inv[inv["sku"].notna() & (inv["sku"] != "")]
    sales = sales[sales["sku"].notna() & (sales["sku"] != "")]

    days = pd.date_range(inv["day"].min(), inv["day"].max(), freq="D")
    skus = sorted(set(inv["sku"]) | set(sales["sku"]))
    idx = pd.MultiIndex.from_product([skus, days], names=["sku", "day"])

    panel = pd.DataFrame(index=idx)
    panel = panel.join(inv.set_index(["sku", "day"])[
        ["ending_inventory_units", "inventory_units_sold"]])
    panel = panel.join(sales.set_index(["sku", "day"])[
        ["net_items_sold", "net_sales", "gross_sales"]])

    # Inventory level: forward-fill within SKU (report omits some SKU-days);
    # before the first observation the level is unknown -> NaN (never "0").
    panel["stock"] = panel.groupby(level="sku")["ending_inventory_units"].ffill()
    # Units: no sales row means zero units that day. Returns can push net
    # negative; demand is floored at 0 (a return day is not negative demand).
    panel["units"] = panel["net_items_sold"].fillna(0).clip(lower=0)
    panel["revenue"] = panel["net_sales"].fillna(0.0)
    return panel.reset_index(), variants


def _mask_baseline_days(g: pd.DataFrame) -> pd.DataFrame:
    """Flag pre-launch days and long zero-runs; both are excluded from lambda."""
    sold = g["units"] > 0
    g["pre_launch"] = ~sold.cummax()  # before first-ever sale

    zero = (g["units"] == 0) & ~g["pre_launch"]
    run_id = (zero != zero.shift()).cumsum()
    run_len = zero.groupby(run_id).transform("size")
    g["long_zero_run"] = zero & (run_len >= ZERO_RUN_MASK)
    g["live"] = ~g["pre_launch"] & ~g["long_zero_run"]
    return g


def _rates(g: pd.DataFrame) -> pd.DataFrame:
    """lambda, reach and trailing price for one SKU (already day-sorted)."""
    live_units = g["units"].where(g["live"])
    lam = live_units.rolling(BASELINE_WINDOW, min_periods=BASELINE_MIN_DAYS).mean()
    g["lam"] = lam.ffill()  # frozen through outages at the last live rate

    ship = live_units.rolling(SHIP_WINDOW, min_periods=7).mean().ffill()
    g["reach"] = g["stock"] / ship.clip(lower=0.1)
    g.loc[g["stock"].isna(), "reach"] = np.nan

    pos = g["units"] > 0
    rev90 = g["revenue"].where(pos).rolling(PRICE_WINDOW, min_periods=1).sum()
    unit90 = g["units"].where(pos).rolling(PRICE_WINDOW, min_periods=1).sum()
    g["trail_price"] = (rev90 / unit90.replace(0, np.nan)).ffill()
    return g


def _categorize(g: pd.DataFrame) -> pd.DataFrame:
    """Daily category flags + episode bridging, one SKU at a time."""
    n = len(g)
    cat = np.array([CAT_IN_STOCK] * n, dtype=object)
    units = g["units"].to_numpy(float)
    stock = g["stock"].to_numpy(float)
    reach = g["reach"].to_numpy(float)
    lam = g["lam"].to_numpy(float)
    live = g["live"].to_numpy(bool)
    pre = g["pre_launch"].to_numpy(bool)

    sold_idx = np.flatnonzero(units > 0)
    last_sale = sold_idx[-1] if len(sold_idx) else -1

    demand_ok = ~np.isnan(lam) & (lam >= MIN_DEMAND)
    known_stock = ~np.isnan(stock)

    # Min-demand gates only the zero-sales signals (Demand gap / Blocked);
    # a physical or critically-low day is OOS at any demand rate.
    physical = known_stock & (stock <= 0) & ~pre & ~np.isnan(lam)
    critical = known_stock & ~physical & ~pre & ~np.isnan(lam) & ~np.isnan(reach) & (reach < OOS_DOS)
    blocked = (units == 0) & ~pre & demand_ok & ~np.isnan(reach) & (reach > BLOCKED_MIN_REACH)
    # Demand gap: zero-sales day enclosed by sales (not the discontinued tail),
    # for a SKU whose expected rate makes a zero anomalous.
    enclosed = np.arange(n) <= last_sale
    demand_gap = (units == 0) & enclosed & ~pre & demand_ok & ~physical & ~critical & ~blocked

    cat[blocked] = CAT_BLOCKED
    cat[demand_gap] = CAT_DEMAND_GAP
    cat[critical] = CAT_CRITICAL
    cat[physical] = CAT_PHYSICAL
    cat[pre] = CAT_PRELAUNCH

    # --- episode bridging: an OOS episode stays open until stock demonstrably
    # recovers (meaningful inbound receipt, reach back above the recovery band,
    # or sales back to >= half the effective rate).
    inbound = np.zeros(n)
    if n > 1:
        delta = np.diff(stock, prepend=stock[0])
        sold_today = np.nan_to_num(g["inventory_units_sold"].to_numpy(float))
        inbound = np.maximum(delta + sold_today, 0)  # receipts net of sales

    in_episode = False
    for i in range(n):
        if cat[i] in (CAT_PHYSICAL, CAT_CRITICAL, CAT_DEMAND_GAP):
            in_episode = True
            continue
        if not in_episode or cat[i] in (CAT_PRELAUNCH, CAT_BLOCKED):
            in_episode = False if cat[i] == CAT_PRELAUNCH else in_episode
            continue
        l = lam[i] if not np.isnan(lam[i]) else 0.0
        recovered = (
            inbound[i] >= RECEIPT_MIN_FRAC * max(l, 1.0)
            or (not np.isnan(reach[i]) and reach[i] >= RECOVERY_DOS)
            or units[i] >= RECOVERY_SALES_FRAC * l
        )
        if recovered:
            in_episode = False
        else:
            cat[i] = CAT_SUPPRESSED if units[i] > 0 else CAT_DEMAND_GAP

    g["category"] = cat
    return g


def compute() -> dict:
    panel, variants = load_panel()
    panel = panel.sort_values(["sku", "day"])
    parts = []
    for _, g in panel.groupby("sku", sort=False):
        g = g.reset_index(drop=True)
        g = _mask_baseline_days(g)
        g = _rates(g)
        g = _categorize(g)
        parts.append(g)
    df = pd.concat(parts, ignore_index=True)

    meta = variants.set_index("sku")

    # Warm-up: don't score the first weeks of history — baselines (lambda,
    # reach, price) are still forming and misread as outages.
    warmup_end = df["day"].min() + pd.Timedelta(days=WARMUP_DAYS)
    df.loc[(df["day"] < warmup_end) &
           df["category"].isin(OOS_CATS | {CAT_BLOCKED}), "category"] = CAT_IN_STOCK

    # Discontinued tail: a product that is no longer ACTIVE (archived, draft,
    # unlisted) was deliberately delisted — its zero-stock tail after the last
    # sale is not lost revenue.
    df["status"] = df["sku"].map(meta["status"]).fillna("ACTIVE")
    last_sale_day = df[df["units"] > 0].groupby("sku")["day"].max()
    tail = (df["status"] != "ACTIVE") & (df["day"] > df["sku"].map(last_sale_day))
    df.loc[tail & df["category"].isin(OOS_CATS | {CAT_BLOCKED}), "category"] = CAT_DISCONTINUED

    df["current_price"] = df["sku"].map(meta["current_price"])
    df["trail_price"] = df["trail_price"].fillna(df["current_price"])

    is_oos = df["category"].isin(OOS_CATS)
    df["lost_units"] = np.where(is_oos, (df["lam"] - df["units"]).clip(lower=0), 0.0)
    df["lost_revenue"] = df["lost_units"] * df["trail_price"].fillna(0)
    df["unrealized_revenue"] = np.where(
        df["category"] == CAT_BLOCKED, df["lam"].fillna(0) * df["trail_price"].fillna(0), 0.0)
    df["expected_revenue"] = df["lam"].fillna(0) * df["trail_price"].fillna(0)

    RESULTS.mkdir(exist_ok=True)
    keep = ["sku", "day", "units", "revenue", "stock", "lam", "reach",
            "trail_price", "live", "category", "lost_units", "lost_revenue",
            "unrealized_revenue"]
    df[keep].to_csv(RESULTS / "sku_daily.csv", index=False, float_format="%.4f")

    episodes = build_episodes(df, meta)
    episodes.to_csv(RESULTS / "episodes.csv", index=False, float_format="%.2f")
    return summarize(df, episodes, meta)


def build_episodes(df: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    d = df[df["category"].isin(OOS_CATS)].copy()
    if d.empty:
        return pd.DataFrame(columns=["sku", "start", "end", "days", "lost_units", "lost_revenue"])
    d = d.sort_values(["sku", "day"])
    gap = d.groupby("sku")["day"].diff().dt.days.fillna(99)
    d["episode"] = (gap > 1).cumsum()
    ep = d.groupby(["sku", "episode"]).agg(
        start=("day", "min"), end=("day", "max"), days=("day", "count"),
        lost_units=("lost_units", "sum"), lost_revenue=("lost_revenue", "sum"),
        main_category=("category", lambda s: s.value_counts().idxmax()),
    ).reset_index().drop(columns="episode")
    ep["product_title"] = ep["sku"].map(meta["product_title"])
    return ep.sort_values("lost_revenue", ascending=False)


def summarize(df: pd.DataFrame, episodes: pd.DataFrame, meta: pd.DataFrame) -> dict:
    is_oos = df["category"].isin(OOS_CATS)
    live_like = df["live"] | is_oos  # OOS days count as live exposure

    # Weekly rollup (ISO weeks, keyed by Monday)
    df["week"] = df["day"].dt.to_period("W-SUN").dt.start_time
    wk = df.groupby("week").agg(
        lost_revenue=("lost_revenue", "sum"),
        lost_units=("lost_units", "sum"),
        unrealized_revenue=("unrealized_revenue", "sum"),
        actual_revenue=("revenue", "sum"),
    )
    wk_cat = (df[is_oos].groupby(["week", "category"])["lost_revenue"].sum()
              .unstack(fill_value=0.0).reindex(wk.index, fill_value=0.0))
    wk_oos = df[live_like].groupby("week").apply(
        lambda g: pd.Series({
            "oos_rate": g["category"].isin(OOS_CATS).mean(),
            "wisr": 1 - (g.loc[g["category"].isin(OOS_CATS), "expected_revenue"].sum()
                         / max(g["expected_revenue"].sum(), 1e-9)),
            "skus_oos": g.loc[g["category"].isin(OOS_CATS), "sku"].nunique(),
        }), include_groups=False)
    weekly = wk.join(wk_cat).join(wk_oos).reset_index()

    # Per-SKU rollup
    sku = df.groupby("sku").agg(
        lost_revenue=("lost_revenue", "sum"),
        lost_units=("lost_units", "sum"),
        unrealized_revenue=("unrealized_revenue", "sum"),
        oos_days=("category", lambda s: s.isin(OOS_CATS).sum()),
        blocked_days=("category", lambda s: (s == CAT_BLOCKED).sum()),
        actual_revenue=("revenue", "sum"),
    )
    last = df.sort_values("day").groupby("sku").tail(1).set_index("sku")
    sku["lam"] = last["lam"]
    sku["stock_now"] = last["stock"]
    sku["reach_now"] = last["reach"]
    sku["category_now"] = last["category"]
    sku["product_title"] = meta["product_title"]
    sku["variant_title"] = meta["variant_title"]
    sku = sku.sort_values("lost_revenue", ascending=False).reset_index()

    live_days = int(live_like.sum())
    oos_days = int(is_oos.sum())
    exp_rev = df.loc[live_like, "expected_revenue"].sum()
    exp_rev_oos = df.loc[is_oos, "expected_revenue"].sum()

    summary = {
        "period": {"start": str(df["day"].min().date()), "end": str(df["day"].max().date())},
        "totals": {
            "lost_revenue": round(float(df["lost_revenue"].sum()), 2),
            "lost_units": round(float(df["lost_units"].sum()), 1),
            "unrealized_revenue": round(float(df["unrealized_revenue"].sum()), 2),
            "actual_revenue": round(float(df["revenue"].sum()), 2),
            "oos_rate": round(oos_days / max(live_days, 1), 4),
            "wisr": round(1 - exp_rev_oos / max(exp_rev, 1e-9), 4),
            "skus_affected": int((sku["lost_revenue"] > 0).sum()),
            "episodes": len(episodes),
        },
        "by_category": {
            c: round(float(df.loc[df["category"] == c, "lost_revenue"].sum()), 2)
            for c in sorted(OOS_CATS)
        },
    }
    weekly.to_csv(RESULTS / "weekly.csv", index=False, float_format="%.2f")
    sku.to_csv(RESULTS / "sku_summary.csv", index=False, float_format="%.2f")
    (RESULTS / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    s = compute()
    print(json.dumps(s, indent=2))
