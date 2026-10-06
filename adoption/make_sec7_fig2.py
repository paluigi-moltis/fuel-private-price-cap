"""§7 figure 2: non-adopter vs adopter competitiveness gap
(pre/post provincial-mean gap, unit-level distributions)."""
import os

os.environ.setdefault(
    "BROWSER_PATH",
    "/home/ubuntu/.cache/ms-playwright/chromium_headless_shell-1243/"
    "chrome-headless-shell-linux-arm64/chrome-headless-shell",
)

import polars as pl
import plotly.graph_objects as go

HERE = os.path.dirname(os.path.abspath(__file__))
TAB = os.path.join(HERE, "output", "tables")
FIG = os.path.join(HERE, "output", "figures")

comp = pl.read_csv(os.path.join(TAB, "nonadopter_competitiveness.csv"))
na = comp.filter(pl.col("adopted") == False)  # noqa: E712
ad = comp.filter(pl.col("adopted") == True)  # noqa: E712
print("non-adopters:", na.height, "| adopters:", ad.height)
print("non-adopter mean gap pre/post (c/l):",
      round(na["gap_pre"].mean() * 1000, 1), round(na["gap_post"].mean() * 1000, 1))
print("adopter mean gap pre/post (c/l):",
      round(ad["gap_pre"].mean() * 1000, 1), round(ad["gap_post"].mean() * 1000, 1))

fig = go.Figure()
groups = [
    ("Non-adopters, pre", na["gap_pre"] * 1000, "#7570b3", "dash"),
    ("Non-adopters, post", na["gap_post"] * 1000, "#7570b3", "solid"),
    ("Adopters, pre", ad["gap_pre"] * 1000, "#1b9e77", "dash"),
    ("Adopters, post", ad["gap_post"] * 1000, "#1b9e77", "solid"),
]
for name, vals, color, dash in groups:
    fig.add_trace(go.Histogram(
        x=vals.to_numpy(), name=name, histnorm="probability",
        xbins=dict(start=-150, end=150, size=5),
        marker_color=color, opacity=0.45 if dash == "dash" else 0.8,
        bingroup=1))
fig.update_layout(
    barmode="overlay",
    xaxis_title="Gap to provincial daily mean (c/l)",
    yaxis_title="Share of stations",
    template="plotly_white", width=1000, height=600, font=dict(size=15),
    legend=dict(x=0.98, y=0.98, xanchor="right"))
fig.write_image(os.path.join(FIG, "competitiveness_gap.png"), scale=2)
print("saved competitiveness_gap.png")
