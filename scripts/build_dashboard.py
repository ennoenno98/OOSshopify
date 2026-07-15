#!/usr/bin/env python3
"""Render results/ into a self-contained HTML dashboard (dashboard/index.html).

No external assets: all CSS/JS inline, charts drawn as SVG by a small inline
script from an embedded JSON payload. Re-run after oos_analytics.py.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
RESULTS = REPO / "results"
OUT = REPO / "dashboard" / "index.html"

CATS = ["Physical", "Critically low", "Demand gap", "Suppressed sales (post-OOS)"]


def _series(df: pd.DataFrame, key: str) -> list[dict]:
    out = []
    for _, r in df.iterrows():
        out.append({
            "t": r[key].strftime("%Y-%m-%d"),
            "cats": [round(float(r.get(c, 0) or 0), 2) for c in CATS],
            "lost": round(float(r["lost_revenue"]), 2),
            "actual": round(float(r["actual_revenue"]), 2),
            "wisr": round(float(r["wisr"]), 4),
            "oos_rate": round(float(r["oos_rate"]), 4),
            "skus_oos": int(r["skus_oos"]),
        })
    return out


def payload() -> dict:
    summary = json.loads((RESULTS / "summary.json").read_text())
    weekly = pd.read_csv(RESULTS / "weekly.csv", parse_dates=["week"])
    monthly = pd.read_csv(RESULTS / "monthly.csv", parse_dates=["month"])
    sku = pd.read_csv(RESULTS / "sku_summary.csv")
    episodes = pd.read_csv(RESULTS / "episodes.csv")

    top_sku = []
    for _, r in sku[sku["lost_revenue"] > 0].head(25).iterrows():
        top_sku.append({
            "sku": r["sku"], "title": r["product_title"], "variant": r["variant_title"],
            "lost": round(float(r["lost_revenue"]), 2),
            "units": round(float(r["lost_units"]), 0),
            "days": int(r["oos_days"]),
            "lam": round(float(r["lam"]), 2) if pd.notna(r["lam"]) else None,
            "stock": None if pd.isna(r["stock_now"]) else int(r["stock_now"]),
            "state": r["category_now"],
        })

    eps = []
    for _, r in episodes.head(15).iterrows():
        eps.append({
            "sku": r["sku"], "title": r["product_title"],
            "start": r["start"][:10], "end": r["end"][:10], "days": int(r["days"]),
            "lost": round(float(r["lost_revenue"]), 2), "cat": r["main_category"],
        })

    return {"summary": summary,
            "series": {"weekly": _series(weekly, "week"),
                       "monthly": _series(monthly, "month")},
            "topSku": top_sku, "episodes": eps,
            "generated": date.today().isoformat()}


HTML = r"""<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OOS Lost Revenue — Vegavero</title>
<style>
  .viz-root {
    color-scheme: light;
    --surface-1:#fcfcfb; --page:#f9f9f7;
    --ink-1:#0b0b0b; --ink-2:#52514e; --ink-3:#898781;
    --grid:#e1e0d9; --baseline:#c3c2b7; --border:rgba(11,11,11,.10);
    --s1:#2a78d6; --s2:#008300; --s3:#e87ba4; --s4:#eda100;
    --accent:#2a78d6; --dim:#c3c2b7;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) .viz-root {
      color-scheme: dark;
      --surface-1:#1a1a19; --page:#0d0d0d;
      --ink-1:#ffffff; --ink-2:#c3c2b7; --ink-3:#898781;
      --grid:#2c2c2a; --baseline:#383835; --border:rgba(255,255,255,.10);
      --s1:#3987e5; --s2:#008300; --s3:#d55181; --s4:#c98500;
      --accent:#3987e5; --dim:#52514e;
    }
  }
  :root[data-theme="dark"] .viz-root {
    color-scheme: dark;
    --surface-1:#1a1a19; --page:#0d0d0d;
    --ink-1:#ffffff; --ink-2:#c3c2b7; --ink-3:#898781;
    --grid:#2c2c2a; --baseline:#383835; --border:rgba(255,255,255,.10);
    --s1:#3987e5; --s2:#008300; --s3:#d55181; --s4:#c98500;
    --accent:#3987e5; --dim:#52514e;
  }
  .viz-root { font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    background: var(--page); color: var(--ink-1); margin: 0; padding: 24px;
    min-height: 100vh; box-sizing: border-box; }
  .wrap { max-width: 1060px; margin: 0 auto; }
  h1 { font-size: 22px; margin: 0 0 2px; font-weight: 650; }
  .sub { color: var(--ink-2); font-size: 13px; margin-bottom: 20px; }
  h2 { font-size: 15px; font-weight: 650; margin: 28px 0 4px; }
  .note { color: var(--ink-2); font-size: 12.5px; margin: 0 0 10px; max-width: 76ch; }
  .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px,1fr));
    gap: 10px; margin: 18px 0; }
  .tile { background: var(--surface-1); border: 1px solid var(--border);
    border-radius: 10px; padding: 12px 14px; }
  .tile .lbl { font-size: 12px; color: var(--ink-2); margin-bottom: 4px; }
  .tile .val { font-size: 24px; font-weight: 600; }
  .tile.hero .val { font-size: 40px; }
  .tile .sub2 { font-size: 11.5px; color: var(--ink-3); margin-top: 3px; }
  .filters { display: flex; align-items: center; gap: 12px; margin: 22px 0 0; }
  .seg { display: inline-flex; border: 1px solid var(--border); border-radius: 8px;
    overflow: hidden; background: var(--surface-1); }
  .seg button { font: inherit; font-size: 12.5px; padding: 6px 14px; border: 0;
    background: transparent; color: var(--ink-2); cursor: pointer; }
  .seg button + button { border-left: 1px solid var(--border); }
  .seg button[aria-pressed="true"] { background: var(--accent); color: #fff;
    font-weight: 600; }
  .seg button:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  .card { background: var(--surface-1); border: 1px solid var(--border);
    border-radius: 10px; padding: 14px 16px; margin-bottom: 8px; }
  .legend { display: flex; gap: 16px; flex-wrap: wrap; font-size: 12px;
    color: var(--ink-2); margin: 2px 0 8px; }
  .legend span { display: inline-flex; align-items: center; gap: 6px; }
  .sw { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
  svg { display: block; width: 100%; height: auto; }
  svg text { font-family: inherit; }
  .tt { position: fixed; pointer-events: none; background: var(--surface-1);
    border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px;
    font-size: 12px; color: var(--ink-1); box-shadow: 0 4px 14px rgba(0,0,0,.18);
    opacity: 0; transition: opacity .08s; z-index: 10; max-width: 260px; }
  .tt .t { font-weight: 600; margin-bottom: 4px; }
  .tt .row { display: flex; justify-content: space-between; gap: 14px;
    color: var(--ink-2); }
  .tt .row b { color: var(--ink-1); font-weight: 600; }
  .tblwrap { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; font-size: 12.5px; }
  th { text-align: left; color: var(--ink-2); font-weight: 600; padding: 6px 10px;
    border-bottom: 1px solid var(--baseline); white-space: nowrap; }
  td { padding: 6px 10px; border-bottom: 1px solid var(--grid); vertical-align: top; }
  td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; }
  .muted { color: var(--ink-3); }
  .pill { font-size: 11px; padding: 1px 8px; border-radius: 999px;
    border: 1px solid var(--border); color: var(--ink-2); white-space: nowrap; }
  footer { color: var(--ink-3); font-size: 11.5px; margin: 26px 0 6px;
    max-width: 86ch; line-height: 1.5; }
</style>
<div class="viz-root"><div class="wrap">
  <h1>OOS lost revenue — vegavero.com</h1>
  <div class="sub" id="sub"></div>
  <div class="kpis" id="kpis"></div>

  <div class="filters">
    <div class="seg" role="group" aria-label="Time granularity">
      <button id="segW" aria-pressed="true">Weekly</button>
      <button id="segM" aria-pressed="false">Monthly</button>
    </div>
  </div>

  <h2 id="h-lost">Lost revenue per week, by OOS category</h2>
  <p class="note">Estimated revenue not earned because products were out of
  stock: expected demand (&lambda;, trailing 90-day rate over live days) minus
  actual units, valued at each SKU's trailing average selling price. Zero-sale
  days on SKUs with ample stock cover are treated as ordinary demand variation
  and never counted.</p>
  <div class="card">
    <div class="legend" id="legend1"></div>
    <div id="chart1"></div>
  </div>

  <h2 id="h-wisr">Weighted in-stock rate (WISR), weekly</h2>
  <p class="note">Share of expected revenue (&lambda; &times; price) that was
  in stock — a stock-out on a big seller hurts more than one on a slow mover.</p>
  <div class="card"><div id="chart2"></div></div>

  <h2>Worst offenders — SKUs ranked by lost revenue</h2>
  <div class="card tblwrap"><table id="tblSku"></table></div>

  <h2>Largest OOS episodes</h2>
  <div class="card tblwrap"><table id="tblEp"></table></div>

  <footer id="foot"></footer>
</div><div class="tt" id="tt"></div></div>
<script>
const D = __DATA__;
const CATS = ["Physical","Critically low","Demand gap","Suppressed sales (post-OOS)"];
const CSS = n => getComputedStyle(document.querySelector('.viz-root')).getPropertyValue(n).trim();
const COLS = () => [CSS('--s1'), CSS('--s4'), CSS('--s3'), CSS('--s2')];
const eur = v => "€" + Math.round(v).toLocaleString("en-US");
const eurK = v => v >= 1000000 ? "€" + (v/1e6).toFixed(2) + "M"
  : v >= 100000 ? "€" + (v/1000).toFixed(0) + "k"
  : v >= 10000 ? "€" + (v/1000).toFixed(1) + "k" : eur(v);
const pct = v => (v*100).toFixed(1) + "%";
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

let grain = "weekly";
const pts = () => D.series[grain];
const tickLabel = t => grain === "monthly"
  ? MON[+t.slice(5,7)-1] + " " + t.slice(2,4)
  : t.slice(5);
const bucketName = t => grain === "monthly"
  ? MON[+t.slice(5,7)-1] + " " + t.slice(0,4)
  : "Week of " + t;

// ---- header + KPI row
const T = D.summary.totals, P = D.summary.period;
document.getElementById("sub").textContent =
  `Shopify store · ${P.start} → ${P.end} · daily model · data pulled ${D.generated}`;
const kpis = [
  ["Lost revenue", eurK(T.lost_revenue), `${Math.round(T.lost_units).toLocaleString()} units not sold`, true],
  ["Realized revenue", eurK(T.actual_revenue), "net sales, same period"],
  ["OOS rate", pct(T.oos_rate), "share of live SKU-days flagged OOS"],
  ["WISR", pct(T.wisr), "revenue-weighted in-stock rate"],
  ["SKUs affected", T.skus_affected, `${T.episodes} OOS episodes`],
];
document.getElementById("kpis").innerHTML = kpis.map(([l,v,s,hero]) =>
  `<div class="tile${hero?" hero":""}"><div class="lbl">${l}</div><div class="val">${v}</div><div class="sub2">${s||""}</div></div>`).join("");

// ---- tooltip helpers
const tt = document.getElementById("tt");
function showTT(html, x, y) {
  tt.innerHTML = html; tt.style.opacity = 1;
  const w = tt.offsetWidth, h = tt.offsetHeight;
  tt.style.left = Math.min(x + 14, innerWidth - w - 8) + "px";
  tt.style.top  = Math.max(8, Math.min(y - h - 12, innerHeight - h - 8)) + "px";
}
const hideTT = () => tt.style.opacity = 0;

// ---- chart 1: stacked columns
function chart1() {
  const data = pts(), cols = COLS();
  document.getElementById("legend1").innerHTML = CATS.map((c,i) =>
    `<span><span class="sw" style="background:${cols[i]}"></span>${c}</span>`).join("");
  const W = 1000, H = 300, m = {t:16, r:8, b:34, l:52};
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const n = data.length;
  const band = iw / n, bw = Math.min(24, Math.max(6, band - 6));
  const max = Math.max(...data.map(w => w.lost)) * 1.08;
  const y = v => m.t + ih * (1 - v / max);
  let s = "";
  const step = niceStep(max, 4);
  for (let v = 0; v <= max; v += step) {
    s += `<line x1="${m.l}" x2="${W-m.r}" y1="${y(v)}" y2="${y(v)}" stroke="var(--grid)" stroke-width="1"/>`;
    s += `<text x="${m.l-8}" y="${y(v)+4}" text-anchor="end" font-size="11" fill="var(--ink-3)">${v>=1000?(v/1000)+"k":v}</text>`;
  }
  s += `<line x1="${m.l}" x2="${W-m.r}" y1="${y(0)}" y2="${y(0)}" stroke="var(--baseline)" stroke-width="1"/>`;
  const every = Math.ceil(n / 12);
  data.forEach((w, i) => {
    const x = m.l + i * band + (band - bw) / 2;
    let acc = 0;
    w.cats.forEach((v, k) => {
      if (v <= 0) return;
      const y1 = y(acc + v), h = y(acc) - y(acc + v);
      acc += v;
      const gap = Math.min(2, h);        // 2px surface gap between segments
      const isTop = Math.abs(acc - w.lost) < 1e-6;
      const r = isTop ? Math.min(4, bw/2, h) : 0;
      s += `<path d="${topRounded(x, y1 + (isTop?0:gap), bw, Math.max(0.5, h - gap), r)}" fill="${cols[k]}"/>`;
    });
    s += `<rect data-i="${i}" x="${m.l + i*band}" y="${m.t}" width="${band}" height="${ih}" fill="transparent"/>`;
    if (i % every === 0)
      s += `<text x="${x+bw/2}" y="${H-12}" text-anchor="middle" font-size="11" fill="var(--ink-3)">${tickLabel(w.t)}</text>`;
  });
  const el = document.getElementById("chart1");
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Lost revenue stacked by category">${s}</svg>`;
  el.querySelector("svg").addEventListener("mousemove", e => {
    const t = e.target.closest("[data-i]"); if (!t) { hideTT(); return; }
    const w = data[+t.dataset.i];
    showTT(`<div class="t">${bucketName(w.t)}</div>` +
      CATS.map((c,k) => w.cats[k] > 0 ? `<div class="row"><span>${c}</span><b>${eur(w.cats[k])}</b></div>` : "").join("") +
      `<div class="row"><span>Total lost</span><b>${eur(w.lost)}</b></div>` +
      `<div class="row"><span>Realized</span><b>${eur(w.actual)}</b></div>` +
      `<div class="row"><span>SKUs OOS</span><b>${w.skus_oos}</b></div>`, e.clientX, e.clientY);
  });
  el.querySelector("svg").addEventListener("mouseleave", hideTT);
}
function topRounded(x, y, w, h, r) {
  if (r <= 0) return `M${x},${y} h${w} v${h} h${-w} Z`;
  return `M${x},${y+r} a${r},${r} 0 0 1 ${r},${-r} h${w-2*r} a${r},${r} 0 0 1 ${r},${r} v${h-r} h${-w} Z`;
}
function niceStep(max, target) {
  const raw = max / target, p = Math.pow(10, Math.floor(Math.log10(raw)));
  for (const k of [1,2,2.5,5,10]) if (k*p >= raw) return k*p;
  return 10*p;
}

// ---- chart 2: WISR line
function chart2() {
  const data = pts();
  const W = 1000, H = 220, m = {t:14, r:56, b:30, l:52};
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const n = data.length;
  const x = i => m.l + (n === 1 ? iw/2 : i * iw / (n-1));
  const y = v => m.t + ih * (1 - v);
  let s = "";
  for (const v of [0, .25, .5, .75, 1]) {
    s += `<line x1="${m.l}" x2="${W-m.r}" y1="${y(v)}" y2="${y(v)}" stroke="var(--grid)" stroke-width="1"/>`;
    s += `<text x="${m.l-8}" y="${y(v)+4}" text-anchor="end" font-size="11" fill="var(--ink-3)">${v*100}%</text>`;
  }
  const ptsStr = data.map((w,i) => `${x(i)},${y(w.wisr)}`).join(" ");
  s += `<polygon points="${m.l},${y(0)} ${ptsStr} ${x(n-1)},${y(0)}" fill="var(--accent)" opacity="0.1"/>`;
  s += `<polyline points="${ptsStr}" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
  const last = data[n-1];
  s += `<circle cx="${x(n-1)}" cy="${y(last.wisr)}" r="4.5" fill="var(--accent)" stroke="var(--surface-1)" stroke-width="2"/>`;
  s += `<text x="${x(n-1)+10}" y="${y(last.wisr)+4}" font-size="12" font-weight="600" fill="var(--ink-1)">${pct(last.wisr)}</text>`;
  const every = Math.ceil(n / 12);
  data.forEach((w,i) => {
    if (i % every === 0)
      s += `<text x="${x(i)}" y="${H-10}" text-anchor="middle" font-size="11" fill="var(--ink-3)">${tickLabel(w.t)}</text>`;
  });
  s += `<line id="ch2x" y1="${m.t}" y2="${m.t+ih}" stroke="var(--baseline)" stroke-width="1" opacity="0"/>`;
  const el = document.getElementById("chart2");
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Weighted in-stock rate over time">${s}</svg>`;
  const svg = el.querySelector("svg"), cross = svg.querySelector("#ch2x");
  svg.addEventListener("mousemove", e => {
    const r = svg.getBoundingClientRect();
    const mx = (e.clientX - r.left) * W / r.width;
    const i = Math.max(0, Math.min(n-1, Math.round((mx - m.l) / (iw/Math.max(n-1,1)))));
    cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i));
    cross.setAttribute("opacity", 1);
    const w = data[i];
    showTT(`<div class="t">${bucketName(w.t)}</div>
      <div class="row"><span>WISR</span><b>${pct(w.wisr)}</b></div>
      <div class="row"><span>OOS rate</span><b>${pct(w.oos_rate)}</b></div>
      <div class="row"><span>Lost revenue</span><b>${eur(w.lost)}</b></div>`, e.clientX, e.clientY);
  });
  svg.addEventListener("mouseleave", () => { cross.setAttribute("opacity", 0); hideTT(); });
}

// ---- grain toggle
function setGrain(g) {
  grain = g;
  document.getElementById("segW").setAttribute("aria-pressed", g === "weekly");
  document.getElementById("segM").setAttribute("aria-pressed", g === "monthly");
  const word = g === "weekly" ? "week" : "month";
  document.getElementById("h-lost").textContent = `Lost revenue per ${word}, by OOS category`;
  document.getElementById("h-wisr").textContent = `Weighted in-stock rate (WISR), ${g}`;
  chart1(); chart2();
}
document.getElementById("segW").addEventListener("click", () => setGrain("weekly"));
document.getElementById("segM").addEventListener("click", () => setGrain("monthly"));

// ---- tables
function tables() {
  document.getElementById("tblSku").innerHTML =
    `<tr><th>SKU</th><th>Product</th><th class="n">Lost €</th><th class="n">Lost units</th>
     <th class="n">OOS days</th><th class="n">&lambda;/day</th><th class="n">Stock now</th><th>State</th></tr>` +
    D.topSku.map(r => `<tr><td class="muted">${esc(r.sku)}</td>
      <td>${esc(r.title)} <span class="muted">· ${esc(r.variant)}</span></td>
      <td class="n"><b>${eur(r.lost)}</b></td><td class="n">${r.units.toLocaleString()}</td>
      <td class="n">${r.days}</td><td class="n">${r.lam ?? "–"}</td>
      <td class="n">${r.stock === null ? "–" : r.stock.toLocaleString()}</td>
      <td><span class="pill">${esc(r.state)}</span></td></tr>`).join("");
  document.getElementById("tblEp").innerHTML =
    `<tr><th>SKU</th><th>Product</th><th>From</th><th>To</th><th class="n">Days</th>
     <th class="n">Lost €</th><th>Mainly</th></tr>` +
    D.episodes.map(r => `<tr><td class="muted">${esc(r.sku)}</td><td>${esc(r.title)}</td>
      <td>${r.start}</td><td>${r.end}</td><td class="n">${r.days}</td>
      <td class="n"><b>${eur(r.lost)}</b></td><td><span class="pill">${esc(r.cat)}</span></td></tr>`).join("");
}

document.getElementById("foot").innerHTML =
  `Method: &lambda; = trailing-90-day units per live day (pre-launch days and
  &ge;7-day zero-runs masked, frozen through outages). A SKU-day is OOS when
  stock &le; 0 (Physical), days-of-supply &lt; 2 (Critically low), or a
  zero-sales day enclosed by sales with &lambda; &ge; 3 (Demand gap); episodes
  bridge until stock or sales demonstrably recover. Lost = max(&lambda; &minus;
  units, 0) &times; trailing avg selling price. Zero-sale days with &gt;15 days
  of stock cover are ordinary demand variation, never counted. Archived/draft
  products stop counting after their last sale. Deliberate-throttle and
  ad-signal rules from the Amazon model are not applied (no per-SKU ad data in
  scope). Full write-up: docs/METHODOLOGY.md · engine: scripts/oos_analytics.py`;

chart1(); chart2(); tables();
const mq = matchMedia("(prefers-color-scheme: dark)");
mq.addEventListener?.("change", () => { chart1(); chart2(); });
new MutationObserver(() => { chart1(); chart2(); })
  .observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
</script>
"""


def main():
    data = payload()
    html = HTML.replace("__DATA__", json.dumps(data))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html)
    print(f"wrote {OUT} ({OUT.stat().st_size/1024:.0f} kB)")


if __name__ == "__main__":
    main()
