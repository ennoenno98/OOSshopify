"""OOS Lost Revenue dashboard — Streamlit app.

Reads the committed model output in results/sku_daily.csv (produced by
scripts/oos_analytics.py) and computes every view — KPIs, charts, rankings,
episodes — for the period selected in the slicer. No live Shopify connection
needed. Deployable on Streamlit Community Cloud with this file as entrypoint.
"""
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

REPO = Path(__file__).parent
RESULTS = REPO / "results"

CATS = ["Physical", "Critically low", "Demand gap", "Suppressed sales (post-OOS)"]
CAT_COLORS = ["#2a78d6", "#eda100", "#e87ba4", "#008300"]
ACCENT = "#2a78d6"
OOS_CATS = set(CATS)

st.set_page_config(page_title="OOS Lost Revenue — Vegavero", page_icon="📉",
                   layout="wide")


def check_password() -> bool:
    """Gate the app behind APP_PASSWORD when that secret is configured.

    Set it in Streamlit Cloud (app → Settings → Secrets):
        APP_PASSWORD = "your-password"
    With no secret configured (e.g. running locally), the app stays open.
    """
    try:
        expected = st.secrets.get("APP_PASSWORD", "")
    except st.errors.StreamlitSecretNotFoundError:
        expected = ""  # no secrets configured at all -> app stays open
    if not expected:
        return True
    if st.session_state.get("pw_ok"):
        return True

    def _submit():
        import hmac
        st.session_state["pw_ok"] = hmac.compare_digest(
            st.session_state.get("pw_input", ""), expected)
        st.session_state["pw_input"] = ""  # never keep the password around

    st.text_input("Password", type="password", key="pw_input",
                  on_change=_submit)
    if st.session_state.get("pw_ok") is False:
        st.error("Wrong password.")
    st.stop()


check_password()


@st.cache_data
def load() -> pd.DataFrame:
    daily = pd.read_csv(RESULTS / "sku_daily.csv", parse_dates=["day"])
    meta = pd.read_csv(REPO / "data" / "variants.csv").set_index("sku")
    daily["expected_revenue"] = (daily["lam"].fillna(0)
                                 * daily["trail_price"].fillna(0))
    daily["is_oos"] = daily["category"].isin(OOS_CATS)
    daily["product_title"] = daily["sku"].map(meta["product_title"]).fillna("")
    daily["variant_title"] = daily["sku"].map(meta["variant_title"]).fillna("")
    return daily


daily = load()
MIN_D, MAX_D = daily["day"].min().date(), daily["day"].max().date()

st.title("OOS lost revenue — vegavero.com")
st.caption(f"Shopify store · data {MIN_D} → {MAX_D} · daily model · "
           "methodology: docs/METHODOLOGY.md")

# ---- filters: period picker + granularity ------------------------------
fc1, fc2, _ = st.columns([1, 1, 2])
sel = fc1.date_input(
    "Period", value=(MIN_D, MAX_D), min_value=MIN_D, max_value=MAX_D,
    format="DD.MM.YYYY")
grain = fc2.radio("Granularity", ["Weekly", "Monthly"], horizontal=True)
if len(sel) != 2:  # calendar open, end date not picked yet
    st.info("Pick an end date in the calendar.")
    st.stop()
start, end = sel

d = daily[(daily["day"].dt.date >= start) & (daily["day"].dt.date <= end)]
if d.empty:
    st.warning("No data in the selected period.")
    st.stop()

# ---- KPI row ------------------------------------------------------------
is_oos = d["is_oos"]
live_like = d["live"] | is_oos
exp_all = d.loc[live_like, "expected_revenue"].sum()
exp_oos = d.loc[is_oos, "expected_revenue"].sum()

oos_only = d[is_oos].sort_values(["sku", "day"])
gap = oos_only.groupby("sku")["day"].diff().dt.days.fillna(99)
oos_only = oos_only.assign(episode=(gap > 1).cumsum())
n_episodes = oos_only.groupby(["sku", "episode"]).ngroups

kpis = [
    ("Lost revenue", f"€{d['lost_revenue'].sum():,.0f}",
     f"{d['lost_units'].sum():,.0f} units not sold"),
    ("Realized revenue", f"€{d['revenue'].sum():,.0f}", "net sales, same period"),
    ("OOS rate", f"{is_oos.sum() / max(int(live_like.sum()), 1) * 100:.1f}%",
     "share of live SKU-days"),
    ("WISR", f"{(1 - exp_oos / max(exp_all, 1e-9)) * 100:.1f}%",
     "revenue-weighted in-stock rate"),
    ("SKUs affected",
     str(int(d.loc[d['lost_revenue'] > 0, 'sku'].nunique())),
     f"{n_episodes} OOS episodes"),
]
for col, (label, value, sub) in zip(st.columns(5), kpis):
    col.metric(label, value)
    col.caption(sub)

st.divider()

# ---- time charts --------------------------------------------------------
if grain == "Weekly":
    bucket = d["day"].dt.to_period("W-SUN").dt.start_time
    tcol = "week"
    # one tick per week is too dense over a year; let vega thin them out,
    # day-of-month in the label keeps every tick unique
    x_axis = alt.Axis(format="%d %b", grid=False)
else:
    bucket = d["day"].dt.to_period("M").dt.start_time
    tcol = "month"
    # exactly one tick per month — auto ticks land mid-month and repeat labels
    x_axis = alt.Axis(format="%b %y", grid=False,
                      tickCount={"interval": "month", "step": 1})
db = d.assign(**{tcol: bucket})

st.subheader(f"Lost revenue per {tcol}, by OOS category")
st.caption("Expected demand (λ, trailing 90-day rate over live days) minus "
           "actual units, valued at each SKU's trailing average selling price.")
long = (db[db["is_oos"]].groupby([tcol, "category"])["lost_revenue"].sum()
        .reset_index())
stacked = (
    alt.Chart(long)
    .mark_bar(binSpacing=2, size=24 if grain == "Monthly" else 10)
    .encode(
        x=alt.X(f"{tcol}:T", title=None, axis=x_axis),
        y=alt.Y("lost_revenue:Q", title="Lost revenue (€)",
                axis=alt.Axis(format="~s")),
        color=alt.Color("category:N", title=None,
                        scale=alt.Scale(domain=CATS, range=CAT_COLORS),
                        legend=alt.Legend(orient="top")),
        order=alt.Order("category:N"),
        tooltip=[alt.Tooltip(f"{tcol}:T", title=grain[:-2]),
                 alt.Tooltip("category:N"),
                 alt.Tooltip("lost_revenue:Q", title="Lost €", format=",.0f")],
    )
    .properties(height=320)
)
st.altair_chart(stacked, use_container_width=True)

st.subheader(f"Weighted in-stock rate (WISR), {grain.lower()}")
st.caption("Share of expected revenue (λ × price) that was in stock — a "
           "stock-out on a big seller hurts more than one on a slow mover.")
lb = db[db["live"] | db["is_oos"]]
wisr_df = lb.groupby(tcol).apply(
    lambda g: pd.Series({
        "wisr": 1 - (g.loc[g["is_oos"], "expected_revenue"].sum()
                     / max(g["expected_revenue"].sum(), 1e-9)),
        "oos_rate": g["is_oos"].mean(),
        "lost": g["lost_revenue"].sum(),
    }), include_groups=False).reset_index()
wisr = (
    alt.Chart(wisr_df)
    .mark_area(line={"color": ACCENT, "strokeWidth": 2},
               color=ACCENT, opacity=0.12)
    .encode(
        x=alt.X(f"{tcol}:T", title=None, axis=x_axis),
        y=alt.Y("wisr:Q", title="WISR", scale=alt.Scale(domain=[0, 1]),
                axis=alt.Axis(format="%")),
        tooltip=[alt.Tooltip(f"{tcol}:T", title=grain[:-2]),
                 alt.Tooltip("wisr:Q", title="WISR", format=".1%"),
                 alt.Tooltip("oos_rate:Q", title="OOS rate", format=".1%"),
                 alt.Tooltip("lost:Q", title="Lost €", format=",.0f")],
    )
    .properties(height=240)
)
st.altair_chart(wisr, use_container_width=True)

# ---- tables --------------------------------------------------------------
st.subheader("Worst offenders — SKUs ranked by lost revenue")
top_n = st.slider("Show top", 10, 100, 25, step=5, label_visibility="collapsed")
last = d.sort_values("day").groupby("sku").tail(1).set_index("sku")
sku_tbl = (d.groupby(["sku", "product_title", "variant_title"])
           .agg(lost_revenue=("lost_revenue", "sum"),
                lost_units=("lost_units", "sum"),
                oos_days=("is_oos", "sum"))
           .reset_index())
sku_tbl = sku_tbl[sku_tbl["lost_revenue"] > 0]
sku_tbl["lam"] = sku_tbl["sku"].map(last["lam"])
sku_tbl["stock_now"] = sku_tbl["sku"].map(last["stock"])
sku_tbl["state"] = sku_tbl["sku"].map(last["category"])
sku_tbl = sku_tbl.sort_values("lost_revenue", ascending=False).head(top_n)
st.dataframe(
    sku_tbl, use_container_width=True, hide_index=True,
    column_config={
        "sku": "SKU",
        "product_title": "Product",
        "variant_title": "Variant",
        "lost_revenue": st.column_config.NumberColumn("Lost €", format="€%.0f"),
        "lost_units": st.column_config.NumberColumn("Lost units", format="%.0f"),
        "oos_days": "OOS days",
        "lam": st.column_config.NumberColumn("λ/day (period end)", format="%.2f"),
        "stock_now": st.column_config.NumberColumn("Stock (period end)",
                                                   format="%.0f"),
        "state": "State (period end)",
    })

st.subheader("Largest OOS episodes")
if len(oos_only):
    ep = (oos_only.groupby(["sku", "episode"])
          .agg(product_title=("product_title", "first"),
               start=("day", "min"), end=("day", "max"), days=("day", "count"),
               lost_revenue=("lost_revenue", "sum"),
               main_category=("category",
                              lambda s: s.value_counts().idxmax()))
          .reset_index().drop(columns="episode")
          .sort_values("lost_revenue", ascending=False).head(15))
    st.dataframe(
        ep, use_container_width=True, hide_index=True,
        column_config={
            "sku": "SKU",
            "product_title": "Product",
            "start": st.column_config.DateColumn("From"),
            "end": st.column_config.DateColumn("To"),
            "days": "Days",
            "lost_revenue": st.column_config.NumberColumn("Lost €",
                                                          format="€%.0f"),
            "main_category": "Mainly",
        })
else:
    st.info("No OOS episodes in the selected period.")

st.caption(
    "Method: λ = trailing-90-day units per live day (pre-launch days and "
    "≥7-day zero-runs masked, frozen through outages). A SKU-day is OOS when "
    "stock ≤ 0 (Physical), days-of-supply < 2 (Critically low), or a "
    "zero-sales day enclosed by sales with λ ≥ 3 (Demand gap); episodes "
    "bridge until stock or sales demonstrably recover. "
    "Lost = max(λ − units, 0) × trailing avg selling price. Zero-sale days "
    "with >15 days of stock cover are ordinary demand variation, never "
    "counted. Episodes touching the period edges are clipped to the period. "
    "Data refresh: re-pull via Claude, re-run scripts/, push.")
