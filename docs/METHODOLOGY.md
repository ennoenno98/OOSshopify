# OOS Lost Revenue — Shopify Methodology

_How this dashboard estimates the revenue lost to out-of-stocks on the
vegavero.com Shopify store. Source of truth: `scripts/oos_analytics.py`.
This is the Shopify port of the Amazon OOS methodology; deviations from the
original are listed at the end._

---

## 1. The question

For every SKU, on every day, we observe **units sold** (Shopify sales
analytics) and **stock on hand** (Shopify inventory analytics). Lost revenue
is:

> **Lost = what the SKU *would* have sold − what it *actually* sold**, on days
> we judge it was out of stock, valued in €.

Everything is computed at **SKU × day**, then rolled up weekly for display.
There is a single stock pool (the store's own fulfilment), so no regional
split applies.

---

## 2. Expected demand (λ) — the counterfactual baseline

```
λ = trailing-90-day average units per LIVE day
```

- **Live days only.** Two kinds of day are excluded from the baseline:
  - **pre-launch days** (before the SKU's first-ever sale);
  - **long zero-runs** (≥ 7 consecutive zero-sales days — an outage or a
    hidden listing, not sales noise) — otherwise λ would decay through the
    stock-out and a long outage would eventually value itself at ≈ 0.
- **Frozen through the outage.** With those days masked, λ is carried forward
  at the last live rate, so a multi-week stock-out keeps its pre-outage rate.
- **Short scattered zeros still count**, so a slow mover keeps its true low
  rate and its ordinary no-sale days are not mistaken for stock-outs.
- λ needs at least 14 live days before it is trusted; the first 28 days of
  history are a **warm-up** and are never scored.

### The Poisson intuition
Under Poisson the chance of a zero-sales day is `P(0) = e^(−λ)`. A zero-sales
day only counts as a demand-gap stock-out when **λ ≥ 3 units/day**
(`MIN_DEMAND`) — the ~5 % cutoff. Below that, zeros carry no signal.

---

## 3. When is a day "out of stock"?

A SKU-day is flagged OOS if **any** of these hold:

1. **Physical** — ending inventory ≤ 0. (Applies at any demand rate.)
2. **Critically low** — reach (days-of-supply) below **2 days** (`OOS_DOS`):
   effectively out even before the balance hits zero.
3. **Demand gap** — units = 0 on a day *enclosed by sales* (not a pre-launch
   or discontinued tail), for a SKU whose λ ≥ 3.

**Reach** = current stock ÷ trailing-28-day average daily units (live days).

### Episodes don't break on a blip
An OOS **episode stays open** until stock demonstrably recovers:
- a meaningful inbound restock (day-over-day stock increase net of sales,
  scaled to demand: ≥ 2×λ), **or**
- reach climbs back above **7 days**, **or**
- sales recover to **≥ ½ of λ**.

Bridged days that still carry some sales are labelled *Suppressed sales
(post-OOS)*, distinct from a true zero-sales *Demand gap*.

---

## 4. What is deliberately NOT counted as lost

| Category | Rule | Booked as |
| --- | --- | --- |
| **Ample-stock zero day** | units = 0 with **reach > 15 days** (`BLOCKED_MIN_REACH`) and λ ≥ 3. This store has no listing suppression, so a no-sale day with plenty of stock is ordinary demand variation (bulk/lumpy sellers, weekends) — the guard exists so such days can never be misread as demand gaps. | Nothing — ordinary in-stock day |
| **Discontinued** | Product status is not ACTIVE (archived/draft/unlisted) and the day is after the SKU's last sale. A deliberate delisting is not lost revenue. | Excluded entirely |
| **Warm-up** | First 28 days of history — baselines still forming. | Excluded entirely |

**Category priority per day:** Physical → Critically low → Demand gap.
Flags are mutually exclusive; no day is double-counted.

---

## 5. Valuing the lost units

On each OOS day:

```
lost_units   = max( λ − units_sold , 0 )
lost_revenue = lost_units × trailing-90d avg selling price per unit
```

- **Price** is the SKU's own trailing-90-day net revenue ÷ units over days
  with sales (falls back to the current catalog price when a SKU has no sales
  history yet), so the valuation reflects that SKU's real realized economics,
  discounts included.
- Returns can push a day's net units negative; demand is floored at 0.

---

## 6. Rolled-up metrics

- **OOS rate** — share of live SKU-days flagged OOS.
- **WISR** (Weighted In-Stock Rate) — % of time in stock, weighted by each
  SKU's **expected revenue** (λ × avg price), so a stock-out on a big seller
  hurts the score more than one on a slow mover.

---

## 7. Data sources & honest caveats

- **Shopify analytics (ShopifyQL)** → `data/inventory_daily.csv` (daily ending
  inventory + units sold per SKU) and `data/sales_daily.csv` (daily net items,
  net & gross sales per SKU). History begins 2025-09-01 (earlier data is not
  tracked in this store's analytics).
- **Shopify Admin API** → `data/variants.csv` (SKU → product, price, status).
- The newest day is an intra-day partial and is never pulled (extracts run
  through *yesterday*).
- Shopify inventory can go negative when overselling is enabled; those days
  are Physical OOS, but actual units sold still offset the loss
  (`λ − units`), so the estimate self-corrects.
- Sales rows with an empty SKU (deleted variants, custom items) are excluded.
- Real sales are more variable than pure Poisson (weekends, promos, bulk/B2B
  orders). SKUs that sell in infrequent bulk spikes have inflated λ between
  spikes; the ample-stock guard keeps their ordinary no-sale days out of the
  loss totals.

## Deviations from the Amazon original

| Original (Amazon) | Here (Shopify) | Why |
| --- | --- | --- |
| Valued in CM3 and revenue | **Revenue only** | Chosen at design time; Shopify has no CM3 |
| EU / GB regional pools | Single pool | One store, one fulfilment network |
| Cooling-down / Heating-up categories (ad-cut & price throttles) | **Dropped** | Requires per-SKU ad spend; deliberately out of scope |
| Positioned run-rate (promo uplift replaces λ) | **Dropped** | Part of the throttle logic above |
| "Listing blocked" bucket (unrealized revenue) | **Downgraded to a guard** — such days are booked as ordinary in-stock days | This store has no listing suppression; the pattern is bulk/lumpy demand |
| Country split of lost units | Not applicable | Single storefront |
| Reach thresholds EU 4d / GB 12d | **2 days** | Own warehouse: no cross-border transfer lag |
| FBA Inventory Ledger receipts | Inferred from day-over-day stock delta net of sales | Shopify analytics has no receipts table |
| Discontinued handling implicit in ledger | Explicit non-ACTIVE-status rule | Archived listings linger in Shopify data |

All thresholds live at the top of `scripts/oos_analytics.py`.
