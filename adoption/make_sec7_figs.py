"""§7 figures: dispersion (IQR pre vs post per province) and
non-adopter competitiveness gap distribution."""
import os

os.environ.setdefault(
    "BROWSER_PATH",
    "/home/ubuntu/.cache/ms-playwright/chromium_headless_shell-1243/"
    "chrome-headless-shell-linux-arm64/chrome-headless-shell",
)

import polars as pl
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = os.path.dirname(os.path.abspath(__file__))
TAB = os.path.join(HERE, "output", "tables")
FIG = os.path.join(HERE, "output", "figures")

# ---------------- dispersion: IQR pre vs post scatter ---------------------
disp = pl.read_csv(os.path.join(TAB, "province_dispersion.csv"))
wide = (
    disp.pivot(index=["provincia_istat", "fuel"], on="phase", values="iqr")
    .rename({"pre": "iqr_pre", "post": "iqr_post"})
)
print("cells:", wide.height, "| post>pre:", (wide["iqr_post"] > wide["iqr_pre"]).sum())
fuel_style = {"Benzina": ("#1f77b4", "circle"), "Gasolio": ("#d62728", "diamond")}
fig = go.Figure()
for fuel, (color, sym) in fuel_style.items():
    sub = wide.filter(pl.col("fuel") == fuel)
    fig.add_trace(go.Scatter(
        x=sub["iqr_pre"] * 1000, y=sub["iqr_post"] * 1000,
        mode="markers", name=fuel, marker=dict(color=color, symbol=sym,
                                               size=8, opacity=0.75)))
lim = [0, max(wide["iqr_post"].max(), wide["iqr_pre"].max()) * 1000 * 1.05]
fig.add_trace(go.Scatter(x=lim, y=lim, mode="lines", showlegend=False,
                         line=dict(dash="dash", color="gray")))
fig.update_layout(
    xaxis_title="Pre-cap province IQR (c/l, 21–27 Sep)",
    yaxis_title="Post-cap province IQR (c/l, 28 Sep–5 Oct)",
    template="plotly_white", width=800, height=700, font=dict(size=15))
fig.write_image(os.path.join(FIG, "dispersion_scatter.png"), scale=2)
print("saved dispersion_scatter.png")

# ------------- competitiveness: non-adopter gap pre vs post ---------------
comp = pl.read_csv(os.path.join(TAB, "nonadopter_competitiveness.csv"))
print("comp cols:", comp.columns, "| rows:", comp.height)
