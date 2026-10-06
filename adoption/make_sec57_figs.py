"""§5 fig: adoption rate by distance-to-nearest-day-0-adopter tercile
(daily, exact shares — replaced the old FE-interaction plot).
§7 figs: province dispersion (IQR pre vs post) and non-adopter
competitiveness gap distribution."""
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
CAP = pl.date(2026, 9, 28)
END = pl.date(2026, 10, 5)

p = pl.scan_parquet(os.path.join(TAB, "adoption_panel.parquet"))
post = p.filter((pl.col("date") >= CAP) & (pl.col("date") <= END))

# ---------------- fig: terciles of distance to nearest day-0 adopter ------
d0 = post.filter(pl.col("days_since_cap") == 0)
units = (
    p.group_by(["id_impianto", "fuel"])
    .agg(pl.col("cap_dist_km").first().alias("cap_dist_km"))
    .collect()
)
q1, q2 = units["cap_dist_km"].quantile(1 / 3), units["cap_dist_km"].quantile(2 / 3)
units = units.with_columns(
    pl.when(pl.col("cap_dist_km") <= q1).then(pl.lit("Near"))
    .when(pl.col("cap_dist_km") <= q2).then(pl.lit("Middle"))
    .otherwise(pl.lit("Far")).alias("tercile")
)
day_terc = (
    post.join(units.select(["id_impianto", "fuel", "tercile"]).lazy(),
              on=["id_impianto", "fuel"])
    .group_by(["days_since_cap", "tercile"])
    .agg(pl.col("at_cap").mean().alias("share"))
    .sort(["tercile", "days_since_cap"])
)
colors = {"Near": "#1b9e77", "Middle": "#d95f02", "Far": "#7570b3"}
fig = go.Figure()
for t in ["Near", "Middle", "Far"]:
    sub = day_terc.filter(pl.col("tercile") == t).collect()
    fig.add_trace(go.Scatter(
        x=sub["days_since_cap"], y=sub["share"] * 100,
        mode="lines+markers", name=f"{t} tercile",
        line=dict(color=colors[t], width=2.5), marker=dict(size=7)))
fig.update_layout(
    xaxis_title="Days since cap (0 = 28 Sep 2026)",
    yaxis_title="Stations at or below cap (%)",
    template="plotly_white", width=1150, height=600, font=dict(size=15),
    xaxis=dict(dtick=1))
fig.write_image(os.path.join(FIG, "event_study_by_capdist.png"), scale=2)
print("tercile edges (km):", round(q1, 2), round(q2, 2))
for t in ["Near", "Far"]:
    v = day_terc.filter((pl.col("tercile") == t) & (pl.col("days_since_cap") == 4)).collect()
    print(t, "day-4 share:", round(v["share"][0] * 100, 1))

# ---------------- fig: dispersion (province IQR pre vs post) --------------
disp = pl.read_csv(os.path.join(TAB, "province_dispersion.csv"))
print("dispersion cols:", disp.columns)
