"""Paper figures refresh (post tax-adjustment data update).

fig1_raw_adoption_share.png — exact daily at-cap share, tax marker.
event_study_by_capdist.png  — exact daily share by day-0 adopter tercile.
fig_prices_daily.png        — daily mean price, all + 5 brands, from Sep 1.
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

sys.path.insert(0, str(Path(__file__).parent))
import config  # noqa: E402

TAB = str(config.OUT_DIR / "tables")
FIG = str(config.OUT_DIR / "figures")
CAP = pl.date(2026, 9, 28)
TAXDAY = pl.date(2026, 10, 6)

p = pl.scan_parquet(os.path.join(TAB, "adoption_panel.parquet"))

# ---------------- fig1: raw daily shares (by fuel) ------------------------
d = (
    p.filter(pl.col("date") >= CAP)
    .group_by(["date", "fuel"])
    .agg(pl.col("at_cap").mean().alias("share"), pl.len().alias("n"))
    .sort(["fuel", "date"])
    .collect()
)
fuel_names = {"Benzina": "Petrol (Benzina)", "Gasolio": "Diesel (Gasolio)"}
colors = {"Benzina": "#1f77b4", "Gasolio": "#d62728"}
fig = go.Figure()
for fuel in ["Benzina", "Gasolio"]:
    sub = d.filter(pl.col("fuel") == fuel)
    fig.add_trace(go.Scatter(
        x=sub["date"], y=sub["share"] * 100,
        mode="lines+markers", name=fuel_names[fuel],
        line=dict(color=colors[fuel], width=2.5), marker=dict(size=7)))
fig.add_vline(x="2026-10-06", line_dash="dot", line_color="#333",
              annotation_text="Gasolio excise +5 c/l<br>(cap threshold +6.1 c/l)",
              annotation_position="top left",
              annotation_font=dict(size=13))
fig.update_layout(
    xaxis_title="Date", yaxis_title="Stations at or below cap (%)",
    template="plotly_white", width=1300, height=620, font=dict(size=15),
    legend=dict(x=0.02, y=0.02))
fig.write_image(os.path.join(FIG, "fig1_raw_adoption_share.png"), scale=2)
print("fig1 saved; last-day shares:",
      d.filter(pl.col("date") == pl.date(2026, 10, 6))
      .select(["fuel", (pl.col("share") * 100).round(1)]).to_dicts())

# ---------------- fig: tercile exact shares -------------------------------
post = p.filter(pl.col("date") >= CAP)
units = (
    p.filter(pl.col("date") == CAP)
    .group_by(["id_impianto", "fuel"])
    .agg(pl.col("cap_dist_km").first())
    .collect()
)
q1, q2 = (units["cap_dist_km"].quantile(q) for q in (1 / 3, 2 / 3))
units = units.with_columns(
    pl.when(pl.col("cap_dist_km") <= q1).then(pl.lit("Near"))
    .when(pl.col("cap_dist_km") <= q2).then(pl.lit("Middle"))
    .otherwise(pl.lit("Far")).alias("tercile")
)
day_terc = (
    post.join(units.lazy().select(["id_impianto", "fuel", "tercile"]),
              on=["id_impianto", "fuel"])
    .group_by(["date", "tercile"])
    .agg(pl.col("at_cap").mean().alias("share"))
    .sort(["tercile", "date"])
)
tc = {"Near": "#1b9e77", "Middle": "#d95f02", "Far": "#7570b3"}
fig = go.Figure()
for t in ["Near", "Middle", "Far"]:
    sub = day_terc.filter(pl.col("tercile") == t).collect()
    fig.add_trace(go.Scatter(
        x=sub["date"], y=sub["share"] * 100, mode="lines+markers",
        name=f"{t} tercile", line=dict(color=tc[t], width=2.5),
        marker=dict(size=6)))
fig.add_vline(x="2026-10-06", line_dash="dot", line_color="#333")
fig.update_layout(
    xaxis_title="Date", yaxis_title="Stations at or below cap (%)",
    template="plotly_white", width=1150, height=600, font=dict(size=15),
    legend=dict(x=0.02, y=0.02))
fig.write_image(os.path.join(FIG, "event_study_by_capdist.png"), scale=2)
print("tercile figure saved; edges:", round(q1, 2), round(q2, 2))
for t in ["Near", "Far"]:
    v = day_terc.filter((pl.col("tercile") == t)
                        & (pl.col("date") == pl.date(2026, 10, 5))).collect()
    print(t, "Oct-5 share:", round(v["share"][0] * 100, 1))

# ---------------- fig: daily mean prices by brand -------------------------
brands = ["Agip Eni", "Q8", "Tamoil", "Api-Ip", "Pompe Bianche"]
sel = p.filter(
    (pl.col("date") >= pl.date(2026, 9, 1))
    & (pl.col("fuel") == "Benzina")
)
daily_all = (
    sel.group_by("date")
    .agg(pl.col("prezzo").mean().alias("v"))
    .with_columns(pl.lit("All stations", dtype=pl.String).alias("b"))
    .select(["date", "b", "v"])
)
daily_brand = (
    sel.filter(pl.col("bandiera").is_in(brands))
    .group_by(["date", "bandiera"])
    .agg(pl.col("prezzo").mean().alias("v"))
    .select([
        "date",
        pl.col("bandiera").cast(pl.String).alias("b"),
        "v",
    ])
)
daily = pl.concat([daily_brand, daily_all]).sort(["b", "date"]).collect()

bc = {"All stations": ("#111111", 3.5),
      "Agip Eni": ("#1b9e77", 2.2), "Q8": ("#d95f02", 2.2),
      "Tamoil": ("#7570b3", 2.2), "Api-Ip": ("#e7298a", 2.2),
      "Pompe Bianche": ("#66a61e", 2.2)}
fig = go.Figure()
for b in ["All stations"] + brands:
    sub = daily.filter(pl.col("b") == b)
    width, dash = (bc[b][1], None) if b != "All stations" else (bc[b][1], "dot")
    fig.add_trace(go.Scatter(
        x=sub["date"], y=sub["v"], mode="lines", name=b,
        line=dict(color=bc[b][0], width=width, dash=dash)))
fig.add_vline(x="2026-09-28", line_dash="dash", line_color="#d62728",
              annotation_text="Voluntary cap starts", annotation_position="top left")
fig.add_vline(x="2026-10-06", line_dash="dot", line_color="#333",
              annotation_text="Gasolio excise +5 c/l", annotation_position="top left")
fig.update_layout(
    xaxis_title="Date", yaxis_title="Mean price (EUR/l, petrol/Benzina)",
    template="plotly_white", width=1300, height=650, font=dict(size=15),
    legend=dict(x=0.01, y=0.98))
fig.write_image(os.path.join(FIG, "fig_prices_daily.png"), scale=2)
print("daily price figure saved")
