"""Export-ready report figures (English labels, numbered prefixes).

Outputs to output/figures/ (main pipeline folder):
  1_benzina_mean_price_brands.png   national benzina Stradale daily mean by
                                    market group + Italy aggregate, no bands,
                                    from 1 Sep, English labels
  2_gasolio_mean_price_brands.png   same for gasolio, plus a dashed vline at
                                    the 6 Oct excise step (label near y-axis)
  3..7_*.png                        copies of the paper's figures 1, 3, 4, 9, 10

Run from the repo root:  uv run python adoption/make_report_figs.py
"""
import os
import shutil
import subprocess
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

from fuel_price_cap import config

FIG = config.FIGURES_DIR
ADOPT_FIG = ROOT / "adoption" / "output" / "figures"

CUT = dt.date(2026, 9, 1)
CAP_DATE = dt.date(2026, 9, 28)
EXCISE_STEP = dt.date(2026, 10, 6)

# Italian -> English label map
GROUP_EN = {
    "Majors": "Majors",
    "Large": "Large",
    "Pompe Bianche": "Independents",
}
AGG_EN = "Italy (all stations)"
FUEL_EN = {"Benzina": "Petrol", "Gasolio": "Diesel"}
TIPO_EN = {"Stradale": "non-motorway", "Autostradale": "motorway"}

GROUP_COLORS = {
    "Majors": "#D62728",
    "Large": "#1F77B4",
    "Pompe Bianche": "#7F7F7F",
}
AGG_COLOR = "#0B6E4F"


def rgba(hex_color: str, alpha: float) -> str:
    v = hex_color.lstrip("#")
    r, g, b = (int(v[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def group_price_chart_en(fuel: str, show_excise_line: bool, stem: str) -> Path:
    prices = pl.read_parquet(config.DATA_DIR / "prices_enriched.parquet")
    tipo = "Stradale"

    def stats(dims: list[str]) -> pl.DataFrame:
        return (
            prices.filter(
                (pl.col("fuel") == fuel) & (pl.col("tipo_impianto") == tipo)
            )
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
            name=AGG_EN, line=dict(color=AGG_COLOR, width=3, dash="dot"),
        )
    )
    for group in config.GROUP_ORDER:
        s = by_group.filter(pl.col("group") == group)
        if s.height:
            fig.add_trace(
                go.Scatter(
                    x=s["date"], y=s["mean_prezzo"], mode="lines",
                    name=GROUP_EN[group],
                    line=dict(color=GROUP_COLORS[group], width=2),
                )
            )

    threshold = config.THRESHOLDS[fuel]
    fig.add_hline(
        y=threshold, line_dash="dot", line_color="firebrick",
        annotation_text=f"cap {threshold:.2f} EUR/l",
        annotation_position="bottom left",
    )
    if fuel == "Gasolio" and overall["date"].max() >= EXCISE_STEP:
        fig.add_hline(
            y=config.GASOLIO_CAP_AFTER, line_dash="dot", line_color="firebrick",
            annotation_text=f"cap {config.GASOLIO_CAP_AFTER:.3f} EUR/l from 6 Oct",
            annotation_position="bottom left",
        )
    fig.add_vline(
        x=CAP_DATE.isoformat(), line_dash="dash", line_color="black",
        annotation_text=f"cap starts {CAP_DATE.isoformat()}",
        annotation_position="top left",
    )
    if show_excise_line:
        fig.add_vline(x=EXCISE_STEP.isoformat(), line_dash="dash",
                      line_color="black")
        fig.add_annotation(
            xref="paper", yref="paper", x=0.015, y=0.955, xanchor="left",
            yanchor="top", showarrow=False,
            text="excise change 6 Oct (cap 2.20 -> 2.261)",
            font=dict(size=12, color="black"),
        )

    fig.update_layout(
        title=(
            f"{FUEL_EN[fuel]} ({tipo_en(tipo)}): daily mean price by market "
            f"group, {CUT.isoformat()} onward"
        ),
        xaxis_title=None,
        yaxis_title="gross price (EUR/l)",
        template="plotly_white",
        hovermode="x unified",
        width=1250,
        height=520,
        legend=dict(orientation="h", yanchor="bottom", y=1.0),
        margin=dict(l=60, r=30, t=80, b=50),
    )
    fig.update_xaxes(
        tickformat="%d %b", tickangle=0,
        range=[CUT, overall["date"].max() + dt.timedelta(days=2)],
    )
    fig.update_yaxes(tickformat=".2f")
    out = FIG / f"{stem}.png"
    fig.write_image(out, scale=2)
    return out


def tipo_en(t: str) -> str:
    return TIPO_EN.get(t, t)


def regen_fig1() -> Path:
    """Re-run make_fig1_v2.py with English-only panel titles (no Italian),
    writing directly to the numbered report name."""
    out = FIG / "3_adoption_share_daily.png"
    env = dict(os.environ, FIG1_OUT=str(out))
    subprocess.run(
        [sys.executable, str(ROOT / "adoption" / "make_fig1_v2.py")],
        check=True, env=env, capture_output=True,
    )
    return out


def copy_fig(src_name: str, stem: str) -> Path:
    src = ADOPT_FIG / src_name
    out = FIG / f"{stem}.png"
    shutil.copyfile(src, out)
    return out


def main() -> None:
    outs = [
        group_price_chart_en("Benzina", show_excise_line=False,
                             stem="1_benzina_mean_price_brands"),
        group_price_chart_en("Gasolio", show_excise_line=True,
                             stem="2_gasolio_mean_price_brands"),
        regen_fig1(),
        copy_fig("map_adoption_share.png", "4_map_adoption_share"),
        copy_fig("map_pb_adoption_share.png", "5_map_pb_adoption_share"),
        copy_fig("amap_price_post7_ben.png", "6_map_price_oct5_petrol"),
        copy_fig("amap_price_post7_gas.png", "7_map_price_oct5_diesel"),
    ]
    for p in outs:
        print(f"saved {p}")


if __name__ == "__main__":
    main()
