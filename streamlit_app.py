"""OOS Lost Revenue dashboard — Streamlit app.

Reads the committed model output in results/ (produced by
scripts/oos_analytics.py); no live Shopify connection needed. Deployable on
Streamlit Community Cloud with this file as the entrypoint.
"""
import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

RESULTS = Path(__file__).parent / "results"

CATS = ["Physical", "Critically low", "Demand gap", "Suppressed sales (post-OOS)"]
CAT_COLORS = ["#2a78d6", "#eda100", "#e87ba4", "#008300"]
ACCENT = "#2a78d6"

st.set_page_config(page_title="OOS Lost Revenue — Vegavero", page_icon="📉",
                   layout="wide")


def check_password() -> bool:
    """Gate the app behind APP_PASSWORD when that secret is configured.

    Set it in Streamlit Cloud (app → Settings → Secrets):
        APP_PASSWORD = "your-password"
    With no secret configured (e.g. running locally), the app stays open.
    """
    expected = st.secrets.get("APP_PASSWORD", "")
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
def load():
    summary = json.loads((RESULTS / "summary.json").read_text())
    weekly = pd.read_csv(RESULTS / "weekly.csv", parse_dates=["week"])
    monthly = pd.read_csv(RESULTS / "monthly.csv", parse_dates=["month"])
    sku = pd.read_csv(RESULTS / "sku_summary.csv")
    episodes = pd.read_csv(RESULTS / "episodes.csv", parse_dates=["start", "end"])
    return summary, weekly, monthly, sku, episodes


summary, weekly, monthly, sku, episodes = load()
T, P = summary["totals"], summary["period"]

st.title("OOS lost revenue — vegavero.com")
st.caption(f"Shopify store · {P['start']} → {P['end']} · daily model · "
           "methodology: docs/METHODOLOGY.md")

# ---- KPI row -----------------------------------------------------------
kpis = [
    ("Lost revenue", f"€{T['lost_revenue']:,.0f}",
     f"{T['lost_units']:,.0f} units not sold"),
    ("Realized revenue", f"€{T['actual_revenue']:,.0f}", "net sales, same period"),
    ("OOS rate", f"{T['oos_rate']*100:.1f}%", "share of live SKU-days"),
    ("WISR", f"{T['wisr']*100:.1f}%", "revenue-weighted in-stock rate"),
    ("SKUs affected", str(T["skus_affected"]), f"{T['episodes']} OOS episodes"),
]
for col, (label, value, sub) in zip(st.columns(5), kpis):
    col.metric(label, value)
    col.caption(sub)

st.divider()

# ---- time charts -------------------------------------------------------
grain = st.radio("Granularity", ["Weekly", "Monthly"], horizontal=True,
                 label_visibility="collapsed")
if grain == "Weekly":
    tdf, tcol = weekly.copy(), "week"
else:
    tdf, tcol = monthly.copy(), "month"

st.subheader(f"Lost revenue per {tcol}, by OOS category")
st.caption("Expected demand (λ, trailing 90-day rate over live days) minus "
           "actual units, valued at each SKU's trailing average selling price.")

long = tdf.melt(id_vars=[tcol], value_vars=[c for c in CATS if c in tdf.columns],
                var_name="category", value_name="lost")
stacked = (
    alt.Chart(long)
    .mark_bar(binSpacing=2)
    .encode(
        x=alt.X(f"{tcol}:T", title=None,
                axis=alt.Axis(format="%b %y" if tcol == "month" else "%d %b",
                              grid=False)),
        y=alt.Y("lost:Q", title="Lost revenue (€)", axis=alt.Axis(format="~s")),
        color=alt.Color("category:N", title=None,
                        scale=alt.Scale(domain=CATS, range=CAT_COLORS),
                        legend=alt.Legend(orient="top")),
        order=alt.Order("category:N"),
        tooltip=[alt.Tooltip(f"{tcol}:T", title=grain[:-2]),
                 alt.Tooltip("category:N"),
                 alt.Tooltip("lost:Q", title="Lost €", format=",.0f")],
    )
    .properties(height=320)
)
st.altair_chart(stacked, use_container_width=True)

st.subheader(f"Weighted in-stock rate (WISR), {grain.lower()}")
st.caption("Share of expected revenue (λ × price) that was in stock — a "
           "stock-out on a big seller hurts more than one on a slow mover.")
wisr = (
    alt.Chart(tdf)
    .mark_area(line={"color": ACCENT, "strokeWidth": 2},
               color=alt.Gradient(gradient="linear",
                                  stops=[alt.GradientStop(color="white", offset=0),
                                         alt.GradientStop(color=ACCENT, offset=1)],
                                  x1=1, x2=1, y1=1, y2=0),
               opacity=0.15)
    .encode(
        x=alt.X(f"{tcol}:T", title=None,
                axis=alt.Axis(format="%b %y" if tcol == "month" else "%d %b",
                              grid=False)),
        y=alt.Y("wisr:Q", title="WISR", scale=alt.Scale(domain=[0, 1]),
                axis=alt.Axis(format="%")),
        tooltip=[alt.Tooltip(f"{tcol}:T", title=grain[:-2]),
                 alt.Tooltip("wisr:Q", title="WISR", format=".1%"),
                 alt.Tooltip("oos_rate:Q", title="OOS rate", format=".1%"),
                 alt.Tooltip("lost_revenue:Q", title="Lost €", format=",.0f")],
    )
    .properties(height=240)
)
st.altair_chart(wisr + wisr.mark_line(color=ACCENT, strokeWidth=2),
                use_container_width=True)

# ---- tables ------------------------------------------------------------
st.subheader("Worst offenders — SKUs ranked by lost revenue")
top_n = st.slider("Show top", 10, 100, 25, step=5, label_visibility="collapsed")
tbl = sku[sku["lost_revenue"] > 0].head(top_n)[
    ["sku", "product_title", "variant_title", "lost_revenue", "lost_units",
     "oos_days", "lam", "stock_now", "category_now"]]
st.dataframe(
    tbl, use_container_width=True, hide_index=True,
    column_config={
        "sku": "SKU",
        "product_title": "Product",
        "variant_title": "Variant",
        "lost_revenue": st.column_config.NumberColumn("Lost €", format="€%.0f"),
        "lost_units": st.column_config.NumberColumn("Lost units", format="%.0f"),
        "oos_days": "OOS days",
        "lam": st.column_config.NumberColumn("λ/day", format="%.2f"),
        "stock_now": st.column_config.NumberColumn("Stock now", format="%.0f"),
        "category_now": "State",
    })

st.subheader("Largest OOS episodes")
ep = episodes.head(15)[["sku", "product_title", "start", "end", "days",
                        "lost_revenue", "main_category"]]
st.dataframe(
    ep, use_container_width=True, hide_index=True,
    column_config={
        "sku": "SKU",
        "product_title": "Product",
        "start": st.column_config.DateColumn("From"),
        "end": st.column_config.DateColumn("To"),
        "days": "Days",
        "lost_revenue": st.column_config.NumberColumn("Lost €", format="€%.0f"),
        "main_category": "Mainly",
    })

st.caption(
    "Method: λ = trailing-90-day units per live day (pre-launch days and "
    "≥7-day zero-runs masked, frozen through outages). A SKU-day is OOS when "
    "stock ≤ 0 (Physical), days-of-supply < 2 (Critically low), or a "
    "zero-sales day enclosed by sales with λ ≥ 3 (Demand gap); episodes "
    "bridge until stock or sales demonstrably recover. "
    "Lost = max(λ − units, 0) × trailing avg selling price. Zero-sale days "
    "with >15 days of stock cover are ordinary demand variation, never "
    "counted. Data refresh: re-pull via Claude, re-run scripts/, push.")
