"""PDF report of the current dashboard view (brand, period, granularity).

Pure matplotlib (PdfPages, vector output) so the hosted app needs no extra
system packages. Figures are built with matplotlib.figure.Figure directly,
never pyplot — pyplot's global state is not safe across Streamlit sessions.
"""
from __future__ import annotations

import io
from datetime import date

import matplotlib
import matplotlib.dates as mdates
import matplotlib.lines
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure
from matplotlib.patches import FancyBboxPatch
from matplotlib.ticker import FuncFormatter

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.font_manager import FontProperties

matplotlib.rcParams["pdf.fonttype"] = 42  # embed real fonts, keep text selectable
FONT = "DejaVu Sans"  # ships with matplotlib: same output on every machine

PAGE_W, PAGE_H = 8.27, 11.69          # A4 portrait, inches
MARGIN = 0.6
CONTENT_W = PAGE_W - 2 * MARGIN

INK, INK_2, INK_3 = "#0b0b0b", "#52514e", "#898781"
GRID, BASELINE, TILE = "#e1e0d9", "#c3c2b7", "#f6f5f1"
ACCENT = "#2a78d6"


class _Page:
    """One A4 page with a y-cursor measured in inches from the top."""

    def __init__(self, pdf: PdfPages, footer: str):
        self.pdf, self.footer = pdf, footer
        self.n = 0
        self._new()

    def _new(self):
        self.fig = Figure(figsize=(PAGE_W, PAGE_H))
        self._renderer = FigureCanvasAgg(self.fig).get_renderer()
        self.n += 1
        self.y = MARGIN
        self.fig.text(MARGIN / PAGE_W, 0.35 / PAGE_H, self.footer, fontsize=6.5,
                      color=INK_3, va="bottom", fontfamily=FONT)
        self.fig.text(1 - MARGIN / PAGE_W, 0.35 / PAGE_H, f"Page {self.n}",
                      fontsize=6.5, color=INK_3, va="bottom", ha="right",
                      fontfamily=FONT)

    def flush(self):
        self.pdf.savefig(self.fig)

    def new_page(self):
        self.flush()
        self._new()

    def room(self) -> float:
        return PAGE_H - MARGIN - 0.25 - self.y

    def need(self, inches: float):
        if self.room() < inches:
            self.new_page()

    # -- primitives (x, y, w, h in inches from the top-left corner) ----------
    def text(self, x, y, s, **kw):
        kw.setdefault("va", "top")
        kw.setdefault("color", INK)
        kw.setdefault("fontfamily", FONT)
        self.fig.text(x / PAGE_W, 1 - y / PAGE_H, s, **kw)

    def width(self, s: str, fontsize: float, weight="normal") -> float:
        """Rendered width of a string in inches."""
        w, _, _ = self._renderer.get_text_width_height_descent(
            s, FontProperties(family=FONT, size=fontsize, weight=weight), False)
        return w / self.fig.dpi

    def fit(self, s: str, width_in: float, fontsize: float) -> str:
        """Truncate with an ellipsis so the text stays inside its column."""
        if self.width(s, fontsize) <= width_in:
            return s
        while len(s) > 1 and self.width(s + "…", fontsize) > width_in:
            s = s[:-1]
        return s.rstrip(" ·") + "…"

    def wrap(self, s: str, width_in: float, fontsize: float) -> list[str]:
        """Break a paragraph into lines no wider than width_in."""
        lines, cur = [], ""
        for word in s.split():
            trial = f"{cur} {word}".strip()
            if cur and self.width(trial, fontsize) > width_in:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        return lines + [cur] if cur else lines

    def hline(self, x0, x1, y, color=GRID, lw=0.5):
        self.fig.add_artist(matplotlib.lines.Line2D(
            [x0 / PAGE_W, x1 / PAGE_W], [1 - y / PAGE_H] * 2,
            color=color, lw=lw, transform=self.fig.transFigure))

    def axes(self, x, y, w, h):
        return self.fig.add_axes([x / PAGE_W, 1 - (y + h) / PAGE_H,
                                  w / PAGE_W, h / PAGE_H])

    def box(self, x, y, w, h, color=TILE):
        self.fig.add_artist(FancyBboxPatch(
            (x / PAGE_W, 1 - (y + h) / PAGE_H), w / PAGE_W, h / PAGE_H,
            boxstyle="round,pad=0,rounding_size=0.006", fc=color, ec="none",
            transform=self.fig.transFigure))


def _style_axes(ax):
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)
    ax.tick_params(colors=INK_3, labelsize=7, length=0, labelfontfamily=FONT)
    ax.grid(axis="y", color=GRID, lw=0.5)
    ax.set_axisbelow(True)


def _date_axis(ax, grain: str, buckets):
    if grain == "Monthly":
        # one label per month, centred under its bar (thinned on long ranges)
        months = sorted(pd.DatetimeIndex(buckets).unique())
        months = months[::max(1, -(-len(months) // 15))]
        ax.set_xticks([m + _mid(grain) for m in months],
                      [m.strftime("%b %y") for m in months])
    else:
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=11))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m.%y"))


def _plot_box(page: _Page, height: float):
    return MARGIN + 0.42, page.y, CONTENT_W - 0.95, height


def _mid(grain: str) -> pd.Timedelta:
    """Offset from a bucket's first day to its middle."""
    return pd.Timedelta(days=15 if grain == "Monthly" else 3)


def _lost_chart(page: _Page, lost: pd.DataFrame, bucket: str, grain: str,
                cats: list[str], colors: list[str], xlim, height=2.5):
    page.text(MARGIN, page.y, f"Lost revenue per {bucket}, by OOS category",
              fontsize=10.5, fontweight="bold")
    page.y += 0.24
    present = [c for c in cats if c in set(lost["category"])]
    if lost.empty:
        page.text(MARGIN, page.y + 0.1, "No out-of-stock days in this period.",
                  fontsize=8.5, color=INK_2)
        page.y += 0.5
        return
    # legend row: swatch + label in text ink, only categories that occur
    x = MARGIN
    for c in present:
        page.box(x, page.y + 0.015, 0.09, 0.09, color=colors[cats.index(c)])
        page.text(x + 0.13, page.y, c, fontsize=7.5, color=INK_2)
        x += 0.13 + page.width(c, 7.5) + 0.25
    page.y += 0.22

    ax = page.axes(*_plot_box(page, height))
    pivot = (lost.pivot_table(index=bucket, columns="category",
                              values="lost_revenue", aggfunc="sum")
             .reindex(columns=present).fillna(0.0).sort_index())
    width = 20 if grain == "Monthly" else 5.2          # days
    offset = _mid(grain)
    bottom = pd.Series(0.0, index=pivot.index)
    for c in present:
        ax.bar(pivot.index + offset, pivot[c], width=width, bottom=bottom,
               color=colors[cats.index(c)], edgecolor="white", linewidth=0.6)
        bottom += pivot[c]
    _style_axes(ax)
    _date_axis(ax, grain, pivot.index)
    ax.yaxis.set_major_formatter(FuncFormatter(
        lambda v, _: f"€{v / 1000:g}k" if v >= 1000 else f"€{v:g}"))
    ax.set_ylim(0, bottom.max() * 1.1 if bottom.max() > 0 else 1)
    ax.set_xlim(*xlim)
    page.y += height + 0.4


def _wisr_chart(page: _Page, wisr: pd.DataFrame, bucket: str, grain: str,
                xlim, height=1.7):
    page.text(MARGIN, page.y, f"Weighted in-stock rate (WISR), {grain.lower()}",
              fontsize=10.5, fontweight="bold")
    page.y += 0.3
    if wisr.empty:
        page.text(MARGIN, page.y + 0.1, "No live SKU-days in this period.",
                  fontsize=8.5, color=INK_2)
        page.y += 0.5
        return
    ax = page.axes(*_plot_box(page, height))
    w = wisr.sort_values(bucket)
    x = w[bucket] + _mid(grain)
    ax.fill_between(x, w["wisr"], color=ACCENT, alpha=0.12, lw=0)
    ax.plot(x, w["wisr"], color=ACCENT, lw=1.6,
            solid_joinstyle="round", solid_capstyle="round")
    ax.plot([x.iloc[-1]], [w["wisr"].iloc[-1]], "o", ms=5, color=ACCENT,
            mec="white", mew=1.2, clip_on=False)
    ax.annotate(f"{w['wisr'].iloc[-1] * 100:.1f}%", (x.iloc[-1], w["wisr"].iloc[-1]),
                xytext=(7, 0), textcoords="offset points", va="center",
                fontsize=8, fontweight="bold", color=INK, fontfamily=FONT,
                annotation_clip=False)
    _style_axes(ax)
    _date_axis(ax, grain, w[bucket])
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v * 100:.0f}%"))
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_xlim(*xlim)
    page.y += height + 0.4


def _table(page: _Page, title: str, columns: list[tuple[str, float, str]],
           rows: list[list[str]], fontsize=7.2, row_h=0.19):
    """columns: (header, width fraction, 'l'|'r'). Flows across pages."""
    def pad(x):  # left-aligned columns keep clear of the column before them
        return 0.0 if x == MARGIN else 0.08

    def header():
        page.text(MARGIN, page.y, title if page.y_title_first else f"{title} (continued)",
                  fontsize=10.5, fontweight="bold")
        page.y_title_first = False
        page.y += 0.3
        x = MARGIN
        for name, frac, align in columns:
            w = frac * CONTENT_W
            page.text(x + (w - 0.06 if align == "r" else pad(x)), page.y, name,
                      fontsize=fontsize, color=INK_2, fontweight="bold",
                      ha="right" if align == "r" else "left")
            x += w
        page.y += row_h
        page.hline(MARGIN, MARGIN + CONTENT_W, page.y - 0.045, color=BASELINE, lw=0.7)

    page.need(0.3 + row_h * 4)
    page.y_title_first = True
    header()
    if not rows:
        page.text(MARGIN, page.y + 0.03, "None in this period.", fontsize=8, color=INK_2)
        page.y += 0.4
        return
    for r in rows:
        if page.room() < row_h:
            page.new_page()
            header()
        x = MARGIN
        for (name, frac, align), cell in zip(columns, r):
            w = frac * CONTENT_W
            page.text(x + (w - 0.06 if align == "r" else pad(x)), page.y + 0.025,
                      cell if align == "r"
                      else page.fit(cell, w - 0.08 - pad(x), fontsize),
                      fontsize=fontsize,
                      ha="right" if align == "r" else "left")
            x += w
        page.y += row_h
        page.hline(MARGIN, MARGIN + CONTENT_W, page.y - 0.02)
    page.y += 0.3


def _num(v, fmt="{:,.0f}", empty="–") -> str:
    return empty if pd.isna(v) else fmt.format(v)


def build_pdf(*, site: str, source: str, note: str | None, start: date,
              end: date, grain: str, kpis: list[tuple[str, str, str]],
              lost: pd.DataFrame, wisr: pd.DataFrame, bucket: str,
              skus: pd.DataFrame, episodes: pd.DataFrame | None,
              cats: list[str], colors: list[str], method: str) -> bytes:
    """Render the report and return the PDF bytes."""
    d = "%d.%m.%Y"
    period = f"{start.strftime(d)} – {end.strftime(d)}"
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        page = _Page(pdf, f"OOS lost revenue · {site} · {period} · "
                          f"generated {date.today().strftime(d)}")
        # ---- header
        page.text(MARGIN, page.y, f"OOS lost revenue — {site}",
                  fontsize=17, fontweight="bold")
        page.y += 0.36
        page.text(MARGIN, page.y, f"{period} · {grain.lower()} view · {source}",
                  fontsize=8.5, color=INK_2)
        page.y += 0.3
        if note:
            lines = page.wrap(note, CONTENT_W - 0.2, 7.2)
            h = 0.15 * len(lines) + 0.14
            page.box(MARGIN, page.y, CONTENT_W, h, color="#eaf2fc")
            page.text(MARGIN + 0.1, page.y + 0.07, "\n".join(lines),
                      fontsize=7.2, color="#1c4f91", linespacing=1.35)
            page.y += h + 0.18

        # ---- KPI tiles: label, value, sub-line
        gap, n = 0.1, len(kpis)
        w = (CONTENT_W - gap * (n - 1)) / n
        for i, (label, value, sub) in enumerate(kpis):
            x = MARGIN + i * (w + gap)
            page.box(x, page.y, w, 0.86)
            page.text(x + 0.1, page.y + 0.09, label, fontsize=7.2, color=INK_2)
            page.text(x + 0.1, page.y + 0.28, value,
                      fontsize=14 if i == 0 else 12.5, fontweight="bold")
            page.text(x + 0.1, page.y + 0.57,
                      "\n".join(page.wrap(sub, w - 0.18, 6)[:2]),
                      fontsize=6, color=INK_3, linespacing=1.3)
        page.y += 0.86 + 0.35

        # ---- charts
        buckets = pd.concat([lost[bucket], wisr[bucket]])
        xlim = (None, None) if buckets.empty else (
            buckets.min() - pd.Timedelta(days=2),
            buckets.max() + pd.Timedelta(days=31 if grain == "Monthly" else 7))
        _lost_chart(page, lost, bucket, grain, cats, colors, xlim)
        _wisr_chart(page, wisr, bucket, grain, xlim)

        # ---- tables
        page.new_page()
        sku_rows = [[
            r.sku, f"{r.product_title} · {r.variant_title}" if r.variant_title
            else r.product_title,
            _num(r.lost_revenue, "€{:,.0f}"), _num(r.lost_units), _num(r.oos_days),
            _num(r.lam, "{:.2f}"), _num(r.stock_now), r.state,
        ] for r in skus.itertuples()]
        _table(page, f"Worst offenders — top {len(sku_rows)} SKUs by lost revenue", [
            ("SKU", 0.13, "l"), ("Product", 0.29, "l"), ("Lost €", 0.09, "r"),
            ("Lost units", 0.09, "r"), ("OOS days", 0.09, "r"),
            ("λ/day", 0.07, "r"), ("Stock", 0.08, "r"), ("State (period end)", 0.16, "l"),
        ], sku_rows)

        ep_rows = [] if episodes is None else [[
            r.sku, r.product_title, r.start.strftime(d), r.end.strftime(d),
            _num(r.days), _num(r.lost_revenue, "€{:,.0f}"), r.main_category,
        ] for r in episodes.itertuples()]
        _table(page, "Largest OOS episodes", [
            ("SKU", 0.13, "l"), ("Product", 0.28, "l"), ("From", 0.1, "l"),
            ("To", 0.1, "l"), ("Days", 0.06, "r"), ("Lost €", 0.09, "r"),
            ("Mainly", 0.24, "l"),
        ], ep_rows)

        # ---- method note
        lines = page.wrap(method.removeprefix("Method: "), CONTENT_W, 6.6)
        page.need(0.14 * len(lines) + 0.3)
        page.text(MARGIN, page.y, "Method", fontsize=8, fontweight="bold", color=INK_2)
        page.y += 0.2
        page.text(MARGIN, page.y, "\n".join(lines), fontsize=6.6, color=INK_3,
                  linespacing=1.4)
        page.flush()
    return buf.getvalue()
