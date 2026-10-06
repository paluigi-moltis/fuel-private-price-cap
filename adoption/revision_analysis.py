"""Revision analyses for the paper (user refinement round 2026-10-06).

Produces:
  output/figures/fig1_raw_adoption_share.png   raw daily at-cap share
  output/figures/map_adoption_share.png        province choropleth, % adopters
  output/figures/map_pb_adoption_share.png     province choropleth, % Pompe Bianche adopters
  output/tables/cox_by_sample.csv              Cox results on 3 samples
  output/tables/lpm_by_sample.csv              LPM full coefficient tables, 3 samples
  output/tables/event_study_coefs.csv          FE event-study coefficients (appendix)
"""
import os

os.environ.setdefault(
    "BROWSER_PATH",
    "/home/ubuntu/.cache/ms-playwright/chromium_headless_shell-1243/"
    "chrome-headless-shell-linux-arm64/chrome-headless-shell",
)

import re

import numpy as np
import polars as pl
import plotly.graph_objects as go
import plotly.express as px

ROOT = os.path.dirname(os.path.abspath(__file__))
TAB = os.path.join(ROOT, "output", "tables")
FIG = os.path.join(ROOT, "output", "figures")
CAP_DATE = pl.date(2026, 9, 28)
END_DATE = pl.date(2026, 10, 5)

p = pl.read_parquet(os.path.join(TAB, "adoption_panel.parquet"))
post = p.filter((pl.col("date") >= CAP_DATE) & (pl.col("date") <= END_DATE))

# ------------------------------------------------------------------ Fig 1
d = (
    post.group_by(["days_since_cap", "fuel"])
    .agg(pl.col("at_cap").mean().alias("share"))
    .sort(["fuel", "days_since_cap"])
)
fuel_names = {"Benzina": "Petrol (Benzina)", "Gasolio": "Diesel (Gasolio)"}
colors = {"Benzina": "#1f77b4", "Gasolio": "#d62728"}
fig = go.Figure()
for fuel in ["Benzina", "Gasolio"]:
    sub = d.filter(pl.col("fuel") == fuel)
    fig.add_trace(
        go.Scatter(
            x=sub["days_since_cap"], y=sub["share"] * 100,
            mode="lines+markers", name=fuel_names[fuel],
            line=dict(color=colors[fuel], width=2.5), marker=dict(size=8),
        )
    )
fig.update_layout(
    title=(
        "Share of stations priced at or below the cap, by days since the cap "
        "(28 Sep 2026 = day 0).<br>Exact daily shares from the dtComu-effective "
        "panel — no model, no uncertainty bands."
    ),
    xaxis_title="Days since cap (0 = 28 Sep 2026)",
    yaxis_title="Stations at or below cap (%)",
    template="plotly_white", width=1400, height=650, font=dict(size=15),
    xaxis=dict(dtick=1),
)
fig.write_image(os.path.join(FIG, "fig1_raw_adoption_share.png"), scale=2)
print("fig1 saved")

# ------------------------------------------------- event-study coefs (appendix)
txt = open(os.path.join(ROOT, "output", "panel_results.txt")).read()
sec = txt.split("===== m1 =====")[1].split("===== m2 =====")[0]
rows = re.findall(
    r"(ev::-?\d+)\s+(-?[\d.]+)\s+([\d.]+)\s+(-?[\d.]+)\s+([\d<.e-]+)\s*(\**)", sec
)
es = pl.DataFrame(
    {
        "event_time": [int(r[0].split("::")[1]) for r in rows],
        "coef": [float(r[1]) for r in rows],
        "se": [float(r[2]) for r in rows],
        "t": [float(r[3]) for r in rows],
        "p": [r[4] for r in rows],
        "stars": [r[5] for r in rows],
    }
).sort("event_time")
es.write_csv(os.path.join(TAB, "event_study_coefs.csv"))
print("event-study coefs:", es.height, "rows;", es["event_time"].to_list())

# ------------------------------------------------------------- samples
# Pompe Bianche = stations with unnamed/blank bandiera (independents)
band = p.select(["id_impianto", "fuel", "bandiera"]).unique()
PB = "Pompe Bianche"
samples = {
    "universe": p,
    "excl_agip_q8": p.filter(~pl.col("bandiera").is_in(["Agip Eni", "Q8"])),
    "pompe_bianche": p.filter(pl.col("bandiera") == PB),
}
for name, df in samples.items():
    u = df.select(["id_impianto", "fuel"]).unique()
    print(f"{name}: {u.height} units, {df.height} rows, "
          f"share adopted {u['adopted'].mean() if 'adopted' in u.columns else 'n/a'}")

# check bandiera values
print("bandiera values:", sorted(p["bandiera"].unique().to_list()))
