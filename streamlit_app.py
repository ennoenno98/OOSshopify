"""OOS-Dashboard (entgangener Umsatz) — Streamlit-App.

Liest die committeten Modellergebnisse aus results/sku_daily.csv (erzeugt von
scripts/oos_analytics.py) und berechnet jede Ansicht — KPIs, Charts, Rankings,
Episoden — für den im Kalender gewählten Zeitraum. Keine Live-Verbindung zu
Shopify nötig. Deploybar auf Streamlit Community Cloud mit dieser Datei als
Entrypoint.
"""
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

REPO = Path(__file__).parent
RESULTS = REPO / "results"

CATS = ["Physical", "Critically low", "Demand gap", "Suppressed sales (post-OOS)"]
CAT_LABELS_DE = {
    "Physical": "Physisch (Bestand 0)",
    "Critically low": "Kritisch niedrig",
    "Demand gap": "Nachfragelücke",
    "Suppressed sales (post-OOS)": "Gedämpfte Verkäufe (nach OOS)",
    "In stock": "Auf Lager",
    "Pre-launch": "Vor Launch",
    "Discontinued": "Ausgelistet",
}
CATS_DE = [CAT_LABELS_DE[c] for c in CATS]
CAT_COLORS = ["#2a78d6", "#eda100", "#e87ba4", "#008300"]
ACCENT = "#2a78d6"
OOS_CATS = set(CATS)

MONTHS_DE = "['Jan','Feb','Mär','Apr','Mai','Jun','Jul','Aug','Sep','Okt','Nov','Dez']"

st.set_page_config(page_title="OOS – Entgangener Umsatz — Vegavero",
                   page_icon="📉", layout="wide")


def de_int(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


def de_pct(x: float) -> str:
    return f"{x * 100:.1f}".replace(".", ",") + " %"


def check_password() -> bool:
    """App hinter APP_PASSWORD verstecken, wenn das Secret gesetzt ist.

    In Streamlit Cloud setzen (App → Settings → Secrets):
        APP_PASSWORD = "dein-passwort"
    Ohne Secret (z. B. lokal) läuft die App offen.
    """
    try:
        expected = st.secrets.get("APP_PASSWORD", "")
    except st.errors.StreamlitSecretNotFoundError:
        expected = ""  # gar keine Secrets konfiguriert -> App bleibt offen
    if not expected:
        return True
    if st.session_state.get("pw_ok"):
        return True

    def _submit():
        import hmac
        st.session_state["pw_ok"] = hmac.compare_digest(
            st.session_state.get("pw_input", ""), expected)
        st.session_state["pw_input"] = ""  # Passwort nie im State behalten

    st.text_input("Passwort", type="password", key="pw_input",
                  on_change=_submit)
    if st.session_state.get("pw_ok") is False:
        st.error("Falsches Passwort.")
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

st.title("Entgangener Umsatz durch Out-of-Stock — vegavero.com")
st.caption(f"Shopify-Store · Daten {MIN_D.strftime('%d.%m.%Y')} → "
           f"{MAX_D.strftime('%d.%m.%Y')} · Tagesmodell · "
           "Methodik: docs/METHODOLOGY.md")

# ---- Filter: Zeitraum (Kalender) + Granularität -------------------------
fc1, fc2, _ = st.columns([1, 1, 2])
sel = fc1.date_input(
    "Zeitraum", value=(MIN_D, MAX_D), min_value=MIN_D, max_value=MAX_D,
    format="DD.MM.YYYY")
grain = fc2.radio("Granularität", ["Wöchentlich", "Monatlich"],
                  horizontal=True)
if len(sel) != 2:  # Kalender offen, Enddatum noch nicht gewählt
    st.info("Bitte Enddatum im Kalender wählen.")
    st.stop()
start, end = sel

d = daily[(daily["day"].dt.date >= start) & (daily["day"].dt.date <= end)]
if d.empty:
    st.warning("Keine Daten im gewählten Zeitraum.")
    st.stop()

# ---- KPI-Zeile -----------------------------------------------------------
is_oos = d["is_oos"]
live_like = d["live"] | is_oos
exp_all = d.loc[live_like, "expected_revenue"].sum()
exp_oos = d.loc[is_oos, "expected_revenue"].sum()

oos_only = d[is_oos].sort_values(["sku", "day"])
gap = oos_only.groupby("sku")["day"].diff().dt.days.fillna(99)
oos_only = oos_only.assign(episode=(gap > 1).cumsum())
n_episodes = oos_only.groupby(["sku", "episode"]).ngroups

kpis = [
    ("Entgangener Umsatz", f"{de_int(d['lost_revenue'].sum())} €",
     f"{de_int(d['lost_units'].sum())} Einheiten nicht verkauft"),
    ("Realisierter Umsatz", f"{de_int(d['revenue'].sum())} €",
     "Nettoumsatz im Zeitraum"),
    ("OOS-Quote", de_pct(is_oos.sum() / max(int(live_like.sum()), 1)),
     "Anteil aktiver SKU-Tage mit OOS"),
    ("WISR", de_pct(1 - exp_oos / max(exp_all, 1e-9)),
     "umsatzgewichtete Verfügbarkeit"),
    ("Betroffene SKUs",
     str(int(d.loc[d['lost_revenue'] > 0, 'sku'].nunique())),
     f"{n_episodes} OOS-Episoden"),
]
for col, (label, value, sub) in zip(st.columns(5), kpis):
    col.metric(label, value)
    col.caption(sub)

st.divider()

# ---- Zeit-Charts ---------------------------------------------------------
if grain == "Wöchentlich":
    bucket = d["day"].dt.to_period("W-SUN").dt.start_time
    tcol, word = "week", "Woche"
    # deutscher Achsen-Label per Ausdruck: "28. Sep"
    x_axis = alt.Axis(grid=False, labelExpr=(
        f"timeFormat(datum.value, '%d') + '. ' + {MONTHS_DE}[month(datum.value)]"))
else:
    bucket = d["day"].dt.to_period("M").dt.start_time
    tcol, word = "month", "Monat"
    # genau ein Tick pro Monat — Auto-Ticks liegen mittig und doppeln Labels
    x_axis = alt.Axis(grid=False,
                      tickCount={"interval": "month", "step": 1},
                      labelExpr=(f"{MONTHS_DE}[month(datum.value)] + ' ' + "
                                 "timeFormat(datum.value, '%y')"))
db = d.assign(**{tcol: bucket})

st.subheader(f"Entgangener Umsatz pro {word}, nach OOS-Kategorie")
st.caption("Erwartete Nachfrage (λ, gleitender 90-Tage-Schnitt über aktive "
           "Tage) minus tatsächliche Einheiten, bewertet zum gleitenden "
           "Durchschnittsverkaufspreis der SKU.")
long = (db[db["is_oos"]].groupby([tcol, "category"])["lost_revenue"].sum()
        .reset_index())
long["kategorie"] = long["category"].map(CAT_LABELS_DE)
stacked = (
    alt.Chart(long)
    .mark_bar(binSpacing=2, size=24 if grain == "Monatlich" else 10)
    .encode(
        x=alt.X(f"{tcol}:T", title=None, axis=x_axis),
        y=alt.Y("lost_revenue:Q", title="Entgangener Umsatz (€)",
                axis=alt.Axis(format="~s")),
        color=alt.Color("kategorie:N", title=None,
                        scale=alt.Scale(domain=CATS_DE, range=CAT_COLORS),
                        legend=alt.Legend(orient="top")),
        order=alt.Order("kategorie:N"),
        tooltip=[alt.Tooltip(f"{tcol}:T", title=word, format="%d.%m.%Y"),
                 alt.Tooltip("kategorie:N", title="Kategorie"),
                 alt.Tooltip("lost_revenue:Q", title="Entgangen €",
                             format=",.0f")],
    )
    .properties(height=320)
)
st.altair_chart(stacked, use_container_width=True)

st.subheader(f"Gewichtete Verfügbarkeitsquote (WISR), "
             f"{'wöchentlich' if grain == 'Wöchentlich' else 'monatlich'}")
st.caption("Anteil des erwarteten Umsatzes (λ × Preis), der auf Lager war — "
           "ein Stock-out bei einem Topseller wiegt schwerer als bei einem "
           "Langsamdreher.")
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
        tooltip=[alt.Tooltip(f"{tcol}:T", title=word, format="%d.%m.%Y"),
                 alt.Tooltip("wisr:Q", title="WISR", format=".1%"),
                 alt.Tooltip("oos_rate:Q", title="OOS-Quote", format=".1%"),
                 alt.Tooltip("lost:Q", title="Entgangen €", format=",.0f")],
    )
    .properties(height=240)
)
st.altair_chart(wisr, use_container_width=True)

# ---- Tabellen ------------------------------------------------------------
st.subheader("Größte Verlustbringer — SKUs nach entgangenem Umsatz")
top_n = st.slider("Top N", 10, 100, 25, step=5, label_visibility="collapsed")
last = d.sort_values("day").groupby("sku").tail(1).set_index("sku")
sku_tbl = (d.groupby(["sku", "product_title", "variant_title"])
           .agg(lost_revenue=("lost_revenue", "sum"),
                lost_units=("lost_units", "sum"),
                oos_days=("is_oos", "sum"))
           .reset_index())
sku_tbl = sku_tbl[sku_tbl["lost_revenue"] > 0]
sku_tbl["lam"] = sku_tbl["sku"].map(last["lam"])
sku_tbl["stock_now"] = sku_tbl["sku"].map(last["stock"])
sku_tbl["state"] = sku_tbl["sku"].map(last["category"]).map(
    lambda c: CAT_LABELS_DE.get(c, c))
sku_tbl = sku_tbl.sort_values("lost_revenue", ascending=False).head(top_n)
st.dataframe(
    sku_tbl, use_container_width=True, hide_index=True,
    column_config={
        "sku": "SKU",
        "product_title": "Produkt",
        "variant_title": "Variante",
        "lost_revenue": st.column_config.NumberColumn("Entgangen €",
                                                      format="%.0f €"),
        "lost_units": st.column_config.NumberColumn("Entg. Einheiten",
                                                    format="%.0f"),
        "oos_days": "OOS-Tage",
        "lam": st.column_config.NumberColumn("λ/Tag (Periodenende)",
                                             format="%.2f"),
        "stock_now": st.column_config.NumberColumn("Bestand (Periodenende)",
                                                   format="%.0f"),
        "state": "Status (Periodenende)",
    })

st.subheader("Größte OOS-Episoden")
if len(oos_only):
    ep = (oos_only.groupby(["sku", "episode"])
          .agg(product_title=("product_title", "first"),
               start=("day", "min"), end=("day", "max"), days=("day", "count"),
               lost_revenue=("lost_revenue", "sum"),
               main_category=("category",
                              lambda s: s.value_counts().idxmax()))
          .reset_index().drop(columns="episode")
          .sort_values("lost_revenue", ascending=False).head(15))
    ep["main_category"] = ep["main_category"].map(
        lambda c: CAT_LABELS_DE.get(c, c))
    st.dataframe(
        ep, use_container_width=True, hide_index=True,
        column_config={
            "sku": "SKU",
            "product_title": "Produkt",
            "start": st.column_config.DateColumn("Von", format="DD.MM.YYYY"),
            "end": st.column_config.DateColumn("Bis", format="DD.MM.YYYY"),
            "days": "Tage",
            "lost_revenue": st.column_config.NumberColumn("Entgangen €",
                                                          format="%.0f €"),
            "main_category": "Hauptkategorie",
        })
else:
    st.info("Keine OOS-Episoden im gewählten Zeitraum.")

st.caption(
    "Methodik: λ = gleitender 90-Tage-Schnitt der Einheiten pro aktivem Tag "
    "(Tage vor dem Launch und Null-Serien ≥ 7 Tage werden maskiert; λ wird "
    "durch Ausfälle hindurch eingefroren). Ein SKU-Tag gilt als OOS bei "
    "Bestand ≤ 0 (Physisch), Reichweite < 2 Tage (Kritisch niedrig) oder "
    "einem verkaufsfreien Tag zwischen Verkäufen bei λ ≥ 3 (Nachfragelücke); "
    "Episoden bleiben offen, bis Bestand oder Verkäufe nachweislich erholt "
    "sind. Entgangen = max(λ − Einheiten, 0) × gleitender "
    "Durchschnittsverkaufspreis. Verkaufsfreie Tage mit > 15 Tagen "
    "Bestandsreichweite sind normale Nachfrageschwankung und zählen nie. "
    "Archivierte/Draft-Produkte zählen nach ihrem letzten Verkauf nicht "
    "mehr. Episoden am Rand des Zeitraums werden auf den Zeitraum "
    "zugeschnitten. Datenaktualisierung: über Claude neu ziehen, scripts/ "
    "ausführen, pushen. Details: docs/METHODOLOGY.md")
