"""Fig 1 v2: two stacked panels — petrol (no tax line) and gasolio (tax line).

Item 2 of the fourth revision round: the dotted Oct-6 excise line applies to
gasolio only, so the fuel panels are split instead of overlaid.
"""
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
CAP = pl.date(2026, 9, 28)

p = pl.scan_parquet(os.path.join(TAB, "adoption_panel.parquet"))
d = (
    p.filter(pl.col("date") >= CAP)
    .group_by(["date", "fuel"])
    .agg(pl.col("at_cap").mean().alias("share"))
    .sort(["fuel", "date"])
    .collect()
)

fig = make_subplots(
    rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
    subplot_titles=("Petrol (Benzina) — cap 2.00 EUR/l",
                    "Diesel (Gasolio) — cap 2.20, then 2.261 EUR/l from 6 Oct"),
)
colors = {"Benzina": "#1f77b4", "Gasolio": "#d62728"}
for r, fuel in enumerate(["Benzina", "Gasolio"], start=1):
    sub = d.filter(pl.col("fuel") == fuel)
    fig.add_trace(
        go.Scatter(x=sub["date"], y=sub["share"] * 100, mode="lines+markers",
                   line=dict(color=colors[fuel], width=2.5), marker=dict(size=7),
                   showlegend=False),
        row=r, col=1)

# tax line only in the gasolio (bottom) panel
fig.add_vline(x="2026-10-06", line_dash="dot", line_color="#333", row=2, col=1,
              annotation_text="Gasolio excise +5 c/l<br>(cap +6.1 c/l)",
              annotation_position="top left", annotation_font=dict(size=13))

fig.update_yaxes(title_text="At or below cap (%)", range=[15, 75], row=1, col=1)
fig.update_yaxes(title_text="At or below cap (%)", range=[15, 75], row=2, col=1)
fig.update_xaxes(title_text="Date", row=2, col=1)
fig.update_layout(template="plotly_white", width=1150, height=820,
                  font=dict(size=15), margin=dict(t=60))
fig.write_image(os.path.join(FIG, "fig1_raw_adoption_share.png"), scale=2)
print("fig1 v2 saved; final-day:",
      d.filter(pl.col("date") == pl.date(2026, 10, 7))
      .select(["fuel", (pl.col("share") * 100).round(1)]).to_dicts())
