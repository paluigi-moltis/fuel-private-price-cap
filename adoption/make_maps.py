"""Province choropleth maps (v3).

(a) adoption maps, stacked vertically at full text width, large legend fonts;
(b) section-7 choropleths:
    - non-adopter gap to provincial mean, pre and post cap;
    - province price SD, pre and post cap (SD replaced IQR as the
      dispersion measure).
Colour scales cut to the true min/max of each map.
"""
import os

os.environ.setdefault(
    "BROWSER_PATH",
    "/home/ubuntu/.cache/ms-playwright/chromium_headless_shell-1243/"
    "chrome-headless-shell-linux-arm64/chrome-headless-shell",
)

import polars as pl
import plotly.graph_objects as go
import shapefile  # pyshp
from pyproj import Transformer

HERE = os.path.dirname(os.path.abspath(__file__))
TAB = os.path.join(HERE, "output", "tables")
FIG = os.path.join(HERE, "output", "figures")
BORDERS = os.path.join(HERE, "data", "istat_borders", "ProvCM01012026_g",
                       "ProvCM01012026_g_WGS84.shp")

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
    name = rec.get("DEN_PROV") or rec.get("SIGLA") or ""
    # DEN_PROV is '-' for metropolitan cities; prefer SIGLA as the join key
    join_name = rec.get("SIGLA") or name
    fid = str(rec.get("COD_UTS"))
    name2id[join_name] = fid
    parts = list(sr.shape.parts) + [len(sr.shape.points)]
    feats_polys = []
    for i in range(len(parts) - 1):
        pts = sr.shape.points[parts[i]:parts[i + 1]]
        if len(pts) >= 3:
            pts_wgs = [_to_wgs84.transform(x, y) for x, y in pts]
            ring = [[q[0], q[1]] for q in pts_wgs]
            if ring[0] != ring[-1]:
                ring.append(ring[0])
            feats_polys.append([ring])
    geojson["features"].append({
        "type": "Feature",
        "id": fid,
        "properties": {"name": name, "sigla": join_name},
        "geometry": {"type": "MultiPolygon", "coordinates": feats_polys},
    })
print("province shapes:", len(geojson["features"]))


def choropleth(fid, z, zmin, zmax, fname, cb_title, fmt=".1f",
               tickfont=22, width=1150, height=1350):
    fig = go.Figure(go.Choroplethmap(
        geojson=geojson, locations=fid, z=z, featureidkey="id",
        colorscale="Viridis", zmin=zmin, zmax=zmax,
        marker_line_width=0.4, marker_line_color="white",
        hovertemplate="%{z:" + fmt + "}<extra></extra>",
        colorbar=dict(
            title=dict(text=cb_title, side="right"),
            thickness=16, len=0.72, tickfont=dict(size=tickfont),
            ticklen=6, outlinewidth=0),
    ))
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0), width=width, height=height,
        map=dict(style="white-bg", center=dict(lat=41.4, lon=12.6),
                 zoom=4.5),
    )
    fig.write_image(os.path.join(FIG, fname), scale=2)
    print("saved", fname, "| z:", round(zmin, 1), "-", round(zmax, 1))


def attach_fid(df):
    return (
        df.with_columns(pl.col("provincia_istat").cast(pl.Utf8)
                        .replace(name2id).alias("fid"))
        .filter(pl.col("fid").is_not_null())
    )


# ==== (b1) non-adopter gap to provincial mean, pre/post ===================
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
               fname, "c/l")

# ==== (b2) province SD pre/post ===========================================
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
               float(g["pcl"].max()), fname, "c/l")

# ==== (a) adoption maps ===================================================
p = pl.scan_parquet(os.path.join(TAB, "adoption_panel.parquet"))


def prov_rates(filter_expr, col):
    q = p
    if filter_expr is not None:
        q = q.filter(filter_expr)
    return (
        q.group_by(["provincia_istat", "fuel", "id_impianto"])
        .agg(pl.col("adopted").max())
        .group_by(["provincia_istat", "fuel"])
        .agg(pl.col("adopted").mean().alias("share"), pl.len().alias("n"))
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
    zmin, zmax = float(sub_pd["pct"].min()), float(sub_pd["pct"].max())
    choropleth(sub_pd["fid"], sub_pd["pct"], zmin, zmax, fname, "%",
               tickfont=24)
