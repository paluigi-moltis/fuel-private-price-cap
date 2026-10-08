"""Export-ready report figures, v2 (larger fonts, no titles, tighter axes).

Same outputs as v1 (1_..7_ prefixed PNGs in output/figures/), restyled:
  a) legend/tick/annotation fonts enlarged; headline titles removed
  b) lines +50% thicker; axis ranges trimmed to the data; x ticks doubled
  c) figs 1-2: aggregate label "Aggregate"
  d) fig 2: excise annotation dropped; hline labels "cap 2.20 EUR/l from
     28 Sep" / "cap 2.261 EUR/l from 6 Oct"; cap-start vline label removed
  e) fig 3: window starts 26 Sep (2 pre-cap days); dashed vline at 28 Sep;
     per-panel hline labels "cap 2.00 EUR/l" / "cap 2.20 EUR/l"; the
     excise vline label becomes "cap 2.261 EUR/l"; panel titles Petrol /
     Diesel only.

Figures 4-7 remain as-is copies of the paper's figures 3, 4, 9, 10.

Run from the repo root:  uv run python adoption/make_report_figs.py
"""
import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault(
    "BROWSER_PATH",
    "/home/ubuntu/.cache/ms-playwright/chromium_headless_shell-1243/"
    "chrome-headless-shell-linux-arm64/chrome-headless-shell",
)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import datetime as dt

import plotly.graph_objects as go
import polars as pl
from plotly.subplots import make_subplots

from fuel_price_cap import config

FIG = config.FIGURES_DIR
ADOPT_FIG = ROOT / "adoption" / "output" / "figures"
ADOPT_TAB = ROOT / "adoption" / "output" / "tables"

CUT = dt.date(2026, 9, 1)
CAP_DATE = dt.date(2026, 9, 28)
EXCISE_STEP = dt.date(2026, 10, 6)
FIG3_CUT = dt.date(2026, 9, 26)  # two days before the cap

FONT = 22   # base font: ticks, legend, annotations
LINE_W = 3  # base 2 -> +50%

GROUP_EN = {"Majors": "Majors", "Large": "Large", "Pompe Bianche": "Independents"}
AGG_EN = "Aggregate"

GROUP_COLORS = {"Majors": "#D62728", "Large": "#1F77B4", "Pompe Bianche": "#7F7F7F"}
AGG_COLOR = "#0B6E4F"


def group_price_chart_en(fuel: str, show_excise_line: bool, stem: str) -> Path:
    prices = pl.read_parquet(config.DATA_DIR / "prices_enriched.parquet")
    tipo = "Stradale"

    def stats(dims: list[str]) -> pl.DataFrame:
        return (
            prices.filter((pl.col("fuel") == fuel) & (pl.col("tipo_impianto") == tipo))
            .filter(pl.col("date") >= CUT)
            .group_by(["date", *dims])
            .agg(mean_prezzo=pl.col("prezzo").mean())
            .sort("date")
        )

    overall = stats([])
    by_group = stats(["group"])

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=overall["date"], y=overall["mean_prezzo"], mode="lines",
            name=AGG_EN, line=dict(color=AGG_COLOR, width=LINE_W + 1, dash="dot"),
        )
    )
    for group in config.GROUP_ORDER:
        s = by_group.filter(pl.col("group") == group)
        if s.height:
            fig.add_trace(
                go.Scatter(
                    x=s["date"], y=s["mean_prezzo"], mode="lines",
                    name=GROUP_EN[group],
                    line=dict(color=GROUP_COLORS[group], width=LINE_W),
                )
            )

    threshold = config.THRESHOLDS[fuel]
    fig.add_hline(
        y=threshold, line_dash="dot", line_color="firebrick",
        annotation_text=f"cap {threshold:.2f} EUR/l from 28 Sep",
        annotation_position="bottom left",
        annotation_font=dict(size=FONT, color="firebrick"),
    )
    if fuel == "Gasolio" and overall["date"].max() >= EXCISE_STEP:
        fig.add_hline(
            y=config.GASOLIO_CAP_AFTER, line_dash="dot", line_color="firebrick",
            annotation_text=f"cap {config.GASOLIO_CAP_AFTER:.3f} EUR/l from 6 Oct",
            annotation_position="bottom left",
            annotation_font=dict(size=FONT, color="firebrick"),
        )
    # vlines carry no text labels (d)
    fig.add_vline(x=CAP_DATE.isoformat(), line_dash="dash", line_color="black")
    if show_excise_line:
        fig.add_vline(x=EXCISE_STEP.isoformat(), line_dash="dash", line_color="black")

    y_lo = overall["mean_prezzo"].min()
    y_hi = overall["mean_prezzo"].max()
    pad = (y_hi - y_lo) * 0.05
    fig.update_layout(
        font=dict(size=FONT),
        margin=dict(l=10, r=30, t=15, b=10),
        template="plotly_white",
        hovermode="x unified",
        width=1400,
        height=620,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0),
    )
    fig.update_xaxes(
        tickformat="%d %b", tickangle=0,
        dtick=7 * 86400000,  # weekly ticks (was ~biweekly -> doubled)
        range=[CUT, overall["date"].max() + dt.timedelta(days=1)],
    )
    fig.update_yaxes(tickformat=".2f", range=[y_lo - pad, y_hi + pad])
    out = FIG / f"{stem}.png"
    fig.write_image(out, scale=2)
    return out


def fig3_adoption_share() -> Path:
    """Item (e): pre-cap days included, cap vline/hline labels, Petrol/Diesel."""
    panel = pl.read_parquet(ADOPT_TAB / "adoption_panel.parquet")
    d = (
        panel.filter(pl.col("date") >= FIG3_CUT)
        .group_by(["date", "fuel"])
        .agg(pl.col("at_cap").mean().alias("share"))
        .sort(["fuel", "date"])
    )

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.10,
        subplot_titles=("Petrol", "Diesel"),
    )
    colors = {"Benzina": "#1f77b4", "Gasolio": "#d62728"}
    for r, fuel in enumerate(["Benzina", "Gasolio"], start=1):
        sub = d.filter(pl.col("fuel") == fuel)
        thr = 2.00 if fuel == "Benzina" else 2.20
        fig.add_trace(
            go.Scatter(
                x=sub["date"], y=sub["share"] * 100, mode="lines+markers",
                line=dict(color=colors[fuel], width=LINE_W), marker=dict(size=9),
                showlegend=False,
            ),
            row=r, col=1,
        )
        fig.add_hline(
            y=thr, line_dash="dot", line_color="firebrick",
            annotation_text=f"cap {thr:.2f} EUR/l",
            annotation_position="right",
            annotation_font=dict(size=FONT, color="firebrick"),
            row=r, col=1,
        )
    fig.add_vline(
        x=CAP_DATE.isoformat(), line_dash="dash", line_color="black",
        annotation_text="28 Sep", annotation_position="top left",
        annotation_font=dict(size=FONT),
        row=1, col=1,
    )
    fig.add_vline(x=EXCISE_STEP.isoformat(), line_dash="dash", line_color="black",
                  row=2, col=1)
    fig.add_annotation(
        xref="x domain", yref="y2 domain", x=0.925, y=0.06, xanchor="right",
        yanchor="bottom", showarrow=False, text="cap 2.261 EUR/l",
        font=dict(size=FONT, color="black"),
    )
    fig.update_xaxes(
        tickformat="%d %b", tickangle=0, dtick=2 * 86400000,
        tickfont=dict(size=FONT),
        range=[FIG3_CUT, d["date"].max() + dt.timedelta(days=1)],
    )
    fig.update_yaxes(ticksuffix="%", tickfont=dict(size=FONT),
                     range=[-2, 80])
    fig.update_layout(
        font=dict(size=FONT), margin=dict(l=10, r=170, t=30, b=10),
        template="plotly_white", width=1500, height=900, showlegend=False,
    )
    out = FIG / "3_adoption_share_daily.png"
    fig.write_image(out, scale=2)
    return out


def copy_fig(src_name: str, stem: str) -> Path:
    out = FIG / f"{stem}.png"
    shutil.copyfile(ADOPT_FIG / src_name, out)
    return out


def main() -> None:
    outs = [
        group_price_chart_en("Benzina", show_excise_line=False,
                             stem="1_benzina_mean_price_brands"),
        group_price_chart_en("Gasolio", show_excise_line=True,
                             stem="2_gasolio_mean_price_brands"),
        fig3_adoption_share(),
        copy_fig("map_adoption_share.png", "4_map_adoption_share"),
        copy_fig("map_pb_adoption_share.png", "5_map_pb_adoption_share"),
        copy_fig("amap_price_post7_ben.png", "6_map_price_oct5_petrol"),
        copy_fig("amap_price_post7_gas.png", "7_map_price_oct5_diesel"),
    ]
    for p in outs:
        print(f"saved {p}")


if __name__ == "__main__":
    main()
