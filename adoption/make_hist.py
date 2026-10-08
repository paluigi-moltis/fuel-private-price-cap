"""§7 histograms (item 5): distribution of province-level SD and non-adopter
gap, pre vs post cap overlaid in each panel."""
import os

os.environ.setdefault(
    "BROWSER_PATH",
    "/home/ubuntu/.cache/ms-playwright/chromium_headless_shell-1243/"
    "chrome-headless-shell-linux-arm64/chrome-headless-shell",
)

import sys
from pathlib import Path

import polars as pl
import plotly.graph_objects as go
from plotly.subplots import make_subplots

sys.path.insert(0, str(Path(__file__).parent))
import config  # noqa: E402

TAB = str(config.OUT_DIR / "tables")
FIG = str(config.OUT_DIR / "figures")

disp = pl.read_csv(os.path.join(TAB, "province_dispersion.csv"))
sd = (
    disp.drop_nulls("provincia_istat")
    .group_by(["provincia_istat", "phase"])
    .agg(pl.col("sd").mean().alias("sd"))
    .with_columns((pl.col("sd") * 1000).alias("sd_cl"))
)

comp = pl.read_csv(os.path.join(TAB, "nonadopter_competitiveness.csv"))
gap = (
    comp.filter(pl.col("adopted") == False)  # noqa: E712
    .group_by("provincia_istat")
    .agg(pl.col("gap_pre").mean().alias("pre"), pl.col("gap_post").mean().alias("post"))
    .with_columns([(pl.col(c) * 1000).alias(c) for c in ("pre", "post")])
)

fig = make_subplots(rows=2, cols=1, vertical_spacing=0.12,
                    subplot_titles=("Within-province price SD (c/l), by province",
                                    "Non-adopters' gap to the provincial mean (c/l), by province"))
PRE, POST = "#2166ac", "#b2182b"
fig.add_trace(go.Histogram(x=sd.filter(pl.col("phase") == "pre")["sd_cl"],
                           name="pre-cap (21–27 Sep)", marker_color=PRE,
                           opacity=0.65, nbinsx=30), row=1, col=1)
fig.add_trace(go.Histogram(x=sd.filter(pl.col("phase") == "post")["sd_cl"],
                           name="post-cap (28 Sep–7 Oct)", marker_color=POST,
                           opacity=0.65, nbinsx=30), row=1, col=1)
fig.add_trace(go.Histogram(x=gap["pre"], name="pre-cap", marker_color=PRE,
                           opacity=0.65, nbinsx=30, showlegend=False), row=2, col=1)
fig.add_trace(go.Histogram(x=gap["post"], name="post-cap", marker_color=POST,
                           opacity=0.65, nbinsx=30, showlegend=False), row=2, col=1)
fig.update_xaxes(title_text="SD (c/l)", row=1, col=1)
fig.update_xaxes(title_text="gap (c/l)", row=2, col=1)
fig.update_yaxes(title_text="provinces", row=1, col=1)
fig.update_yaxes(title_text="provinces", row=2, col=1)
fig.update_layout(barmode="overlay", template="plotly_white", width=1150,
                  height=820, font=dict(size=15),
                  legend=dict(x=0.72, y=0.98))
fig.write_image(os.path.join(FIG, "fig_dispersion_hist.png"), scale=2)
print("histograms saved:",
      "sd pre med", round(sd.filter(pl.col("phase") == "pre")["sd_cl"].median(), 0),
      "post med", round(sd.filter(pl.col("phase") == "post")["sd_cl"].median(), 0),
      "| gap pre med", round(gap["pre"].median(), 0),
      "post med", round(gap["post"].median(), 0))
