"""All province choropleths (v4): tight Italy zoom, horizontal colorbar
below the map (readable, not rotated), pairs stacked 2 per PDF page.

Outputs (size tuned so two figures fill one A4 text page):
  map_adoption_share.png, map_pb_adoption_share.png        (fig 2-3)
  map_sd_pre.png, map_sd_post.png                          (fig 5-6)
  map_gap_pre.png, map_gap_post.png                        (fig 7-8)
  appendix: amap_price_pre_{ben,gas}.png, amap_price_post7_{ben,gas}.png,
            amap_gapadoption_{ben,gas}.png, amap_adopt7_{ben,gas}.png
"""
import os

os.environ.setdefault(
    "BROWSER_PATH",
    "/home/ubuntu/.cache/ms-playwright/chromium_headless_shell-1243/"
    "chrome-headless-shell-linux-arm64/chrome-headless-shell",
)

import datetime as dt
import sys
from pathlib import Path

import polars as pl
import plotly.graph_objects as go
import shapefile  # pyshp
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).parent))
import config  # noqa: E402

TAB = str(config.OUT_DIR / "tables")
FIG = str(config.OUT_DIR / "figures")
BORDERS = str(config.DATA_DIR / "istat_borders" / "ProvCM01012026_g"
              / "ProvCM01012026_g_WGS84.shp")
CAP = config.CAP_DATE
D7 = CAP + dt.timedelta(days=7)  # 2026-10-05 = "7 days after the cap"

# ---- shapes --------------------------------------------------------------
# NOTE: the 2026 ISTAT province layer is UTM32N (EPSG:32632) despite the
# _WGS84 suffix in the filename — reproject to lon/lat for the map.
sf = shapefile.Reader(BORDERS)
_to_wgs84 = Transformer.from_crs("EPSG:32632", "EPSG:4326", always_xy=True)
fields = [f[0] for f in sf.fields[1:]]
geojson = {"type": "FeatureCollection", "features": []}
name2id = {}
for sr in sf.shapeRecords():
    rec = dict(zip(fields, sr.record))
    join_name = rec.get("SIGLA") or rec.get("DEN_PROV") or ""
    fid = str(rec.get("COD_UTS"))
    name2id[join_name] = fid
    parts = list(sr.shape.parts) + [len(sr.shape.points)]
    feats = []
    for i in range(len(parts) - 1):
        pts = sr.shape.points[parts[i]:parts[i + 1]]
        if len(pts) >= 3:
            ring = [[x, y] for x, y in
                    (_to_wgs84.transform(x, y) for x, y in pts)]
            if ring[0] != ring[-1]:
                ring.append(ring[0])
            feats.append([ring])
    geojson["features"].append({
        "type": "Feature", "id": fid,
        "properties": {"name": rec.get("DEN_PROV", ""), "sigla": join_name},
        "geometry": {"type": "MultiPolygon", "coordinates": feats},
    })
print("province shapes:", len(geojson["features"]))

LON0, LON1, LAT0, LAT1 = 6.6, 18.65, 35.4, 47.1  # tight Italy bbox


def choropleth(fid, z, zmin, zmax, fname, cb_title, fmt=".1f"):
    """Tight-zoom map, horizontal colorbar underneath (horizontal ticks)."""
    fig = go.Figure(go.Choroplethmap(
        geojson=geojson, locations=fid, z=z, featureidkey="id",
        colorscale="Viridis", zmin=zmin, zmax=zmax,
        marker_line_width=0.4, marker_line_color="white",
        hovertemplate="%{z:" + fmt + "}<extra></extra>",
        colorbar=dict(
            title=dict(text=cb_title, side="top"),
            orientation="h", thickness=14, len=0.5,
            x=0.5, xanchor="center", y=-0.015, yanchor="top",
            tickfont=dict(size=20), ticklen=4, outlinewidth=0),
    ))
    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=95), width=1400, height=840,
        map=dict(
            style="white-bg",
            center=dict(lat=41.4, lon=12.55),
            zoom=4.75,
        ),
    )
    fig.write_image(os.path.join(FIG, fname), scale=2)
    print("saved", fname, "| z:", round(float(zmin), 1), "-",
          round(float(zmax), 1))


def attach_fid(df):
    return (
        df.with_columns(pl.col("provincia_istat").cast(pl.Utf8)
                        .replace(name2id).alias("fid"))
        .filter(pl.col("fid").is_not_null())
    )


p = pl.scan_parquet(os.path.join(TAB, "adoption_panel.parquet"))

# ==== (a) adoption maps ===================================================
def prov_rates(filter_expr, col):
    q = p.filter(pl.col("date") >= CAP)
    if filter_expr is not None:
        q = q.filter(filter_expr)
    return (
        q.group_by(["provincia_istat", "fuel", "id_impianto"])
        .agg(pl.col("at_cap").max())
        .group_by(["provincia_istat", "fuel"])
        .agg(pl.col("at_cap").mean().alias("share"), pl.len().alias("n"))
        .group_by("provincia_istat")
        .agg(((pl.col("share") * pl.col("n")).sum() / pl.col("n").sum())
             .alias(col), pl.col("n").sum().alias("n"))
        .collect()
    )


prov = attach_fid(
    prov_rates(None, "share_all").join(
        prov_rates(pl.col("bandiera") == "Pompe Bianche", "share_pb"),
        on="provincia_istat", how="left")
)
print("matched provinces:", prov.height)
for col, fname in [("share_all", "map_adoption_share.png"),
                   ("share_pb", "map_pb_adoption_share.png")]:
    sub = prov.filter(pl.col(col).is_not_null())
    sub_pd = sub.with_columns((pl.col(col) * 100).alias("pct")).to_pandas()
    choropleth(sub_pd["fid"], sub_pd["pct"],
               float(sub_pd["pct"].min()), float(sub_pd["pct"].max()),
               fname, "% adopting")

# ==== SD pre/post =========================================================
disp = pl.read_csv(os.path.join(TAB, "province_dispersion.csv"))
sd = attach_fid(
    disp.drop_nulls("provincia_istat")
    .group_by(["provincia_istat", "phase"])
    .agg(pl.col("sd").mean().alias("sd"))
    .pivot(index="provincia_istat", on="phase", values="sd")
)
for phase, fname in [("pre", "map_sd_pre.png"), ("post", "map_sd_post.png")]:
    g = sd.with_columns((pl.col(phase) * 1000).alias("pcl"))
    choropleth(g["fid"], g["pcl"], float(g["pcl"].min()),
               float(g["pcl"].max()), fname, "SD (c/l)")

# ==== non-adopter gap pre/post ============================================
comp = pl.read_csv(os.path.join(TAB, "nonadopter_competitiveness.csv"))
na = comp.filter(pl.col("adopted") == False)  # noqa: E712
for col, fname in [("gap_pre", "map_gap_pre.png"),
                   ("gap_post", "map_gap_post.png")]:
    g = attach_fid(
        na.with_columns((pl.col(col) * 1000).alias("pcl"))
        .group_by("provincia_istat")
        .agg(pl.col("pcl").mean().alias("v"))
    )
    choropleth(g["fid"], g["v"], float(g["v"].min()), float(g["v"].max()),
               fname, "gap (c/l)")

# ==== appendix maps: benzina / gasolio x 4 measures =======================
print("--- appendix maps ---")
pre = p.filter((pl.col("date") >= config.PRE_WINDOW[0])
               & (pl.col("date") <= config.PRE_WINDOW[1]))
d7 = p.filter((pl.col("date") >= CAP) & (pl.col("date") <= D7))
post = p.filter(pl.col("date") >= CAP)

for fuel, tag in [("Benzina", "ben"), ("Gasolio", "gas")]:
    # 1. average provincial price the day before the cap (27 Sep)
    m = attach_fid(
        pre.filter((pl.col("fuel") == fuel)
                   & (pl.col("date") == config.PRE_WINDOW[1]))
        .group_by("provincia_istat")
        .agg(pl.col("prezzo").mean().alias("v"))
        .collect()
    )
    choropleth(m["fid"], m["v"], float(m["v"].min()), float(m["v"].max()),
               f"amap_price_pre_{tag}.png", "EUR/l", ".3f")

    # 2. average provincial price, cap + 7 days (28 Sep - 5 Oct)
    m = attach_fid(
        d7.filter(pl.col("fuel") == fuel)
        .group_by("provincia_istat")
        .agg(pl.col("prezzo").mean().alias("v"))
        .collect()
    )
    choropleth(m["fid"], m["v"], float(m["v"].min()), float(m["v"].max()),
               f"amap_price_post7_{tag}.png", "EUR/l", ".3f")

    # 3. post-cap average price gap: non-adopters minus adopters
    g = (
        post.filter(pl.col("fuel") == fuel)
        .group_by(["provincia_istat", "adopted"])
        .agg(pl.col("prezzo").mean().alias("m"))
        .collect()
        .pivot(on="adopted", index="provincia_istat", values="m")
        .drop_nulls(["false", "true"])
        .with_columns(((pl.col("false") - pl.col("true")) * 1000)
                      .alias("gap"))
    )
    m = attach_fid(g)
    choropleth(m["fid"], m["gap"], float(m["gap"].min()),
               float(m["gap"].max()), f"amap_gapadoption_{tag}.png",
               "non-adopt − adopt (c/l)")

    # 4. % of cap adopters 7 days after the cap
    m = attach_fid(
        d7.filter(pl.col("fuel") == fuel)
        .group_by(["provincia_istat", "id_impianto"])
        .agg(pl.col("at_cap").max().alias("a"))
        .group_by("provincia_istat")
        .agg(pl.col("a").mean().alias("share"))
        .with_columns((pl.col("share") * 100).alias("pct"))
        .collect()
    )
    choropleth(m["fid"], m["pct"], float(m["pct"].min()),
               float(m["pct"].max()), f"amap_adopt7_{tag}.png", "% adopting")
