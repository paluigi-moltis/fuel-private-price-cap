"""Province choropleth maps: % adopters and % Pompe Bianche adopters."""
import os

os.environ.setdefault(
    "BROWSER_PATH",
    "/home/ubuntu/.cache/ms-playwright/chromium_headless_shell-1243/"
    "chrome-headless-shell-linux-arm64/chrome-headless-shell",
)

import json

import polars as pl
import plotly.express as px
import plotly.graph_objects as go

HERE = os.path.dirname(os.path.abspath(__file__))
TAB = os.path.join(HERE, "output", "tables")
FIG = os.path.join(HERE, "output", "figures")
BORDERS = os.path.join(HERE, "data", "istat_borders", "ProvCM01012026_g",
                       "ProvCM01012026_g_WGS84.shp")

# ---- province adoption rates from the analysis panel --------------------
p = pl.scan_parquet(os.path.join(TAB, "adoption_panel.parquet"))
units = (
    p.group_by(["provincia_istat", "fuel", "id_impianto"])
    .agg(pl.col("adopted").max())
    .group_by(["provincia_istat", "fuel"])
    .agg(pl.col("adopted").mean().alias("share"), pl.len().alias("n"))
    .group_by("provincia_istat")
    .agg(
        ((pl.col("share") * pl.col("n")).sum() / pl.col("n").sum()).alias(
            "share_all"
        ),
        pl.col("n").sum().alias("n"),
    )
    .collect()
)

pb_units = (
    p.filter(pl.col("bandiera") == "Pompe Bianche")
    .group_by(["provincia_istat", "fuel", "id_impianto"])
    .agg(pl.col("adopted").max())
    .group_by(["provincia_istat", "fuel"])
    .agg(pl.col("adopted").mean().alias("share_pb"), pl.len().alias("n_pb"))
    .group_by("provincia_istat")
    .agg(
        ((pl.col("share_pb") * pl.col("n_pb")).sum() / pl.col("n_pb").sum()).alias(
            "share_pb"
        ),
        pl.col("n_pb").sum().alias("n_pb"),
    )
    .collect()
)

prov = units.join(pb_units, on="provincia_istat", how="left")
print(prov.sort("n", descending=True).head(8))
print("provinces:", prov.height,
      "| mean share_all:", round(prov["share_all"].mean(), 3),
      "| mean share_pb:", round(prov["share_pb"].mean(), 3),
      "| provinces with PB:", prov.filter(pl.col("n_pb") > 0).height)

# ---- shapes --------------------------------------------------------------
import shapefile  # pyshp
from pyproj import Transformer

# NOTE: the 2026 ISTAT province layer is UTM32N (EPSG:32632) despite the
# _WGS84 suffix in the filename — reproject to lon/lat for the map.
sf = shapefile.Reader(BORDERS)
_to_wgs84 = Transformer.from_crs("EPSG:32632", "EPSG:4326", always_xy=True)
fields = [f[0] for f in sf.fields[1:]]
geoms = []
for sr in sf.shapeRecords():
    rec = dict(zip(fields, sr.record))
    parts = list(sr.shape.parts) + [len(sr.shape.points)]
    polys = []
    for i in range(len(parts) - 1):
        pts = sr.shape.points[parts[i]:parts[i + 1]]
        if len(pts) >= 3:
            pts_wgs = [_to_wgs84.transform(x, y) for x, y in pts]
            polys.append(pts_wgs)
    geoms.append((rec, polys))
print("province shapes:", len(geoms))

# lons/lats lists per province (multi-polygon as separated traces)
def shape_traces(rec, polys, z, text, colorscale, cmin, cmax, showscale=False):
    raise NotImplementedError  # superseded by geojson approach below

# simpler: build one choropleth trace via geojson
geojson = {"type": "FeatureCollection", "features": []}
ids = []
zmap = {}
for rec, polys in geoms:
    name = rec.get("DEN_PROV") or rec.get("SIGLA") or ""
    # DEN_PROV is '-' for metropolitan cities; prefer SIGLA as the join key
    join_name = rec.get("SIGLA") or name
    fid = str(rec.get("COD_UTS"))
    ids.append(fid)
    row = prov.filter(pl.col("provincia_istat") == join_name)
    if row.height:
        zmap[fid] = row.row(0, named=True)
    feats_polys = []
    for pts in polys:
        ring = [[q[0], q[1]] for q in pts]
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        feats_polys.append([ring])
    geojson["features"].append({
        "type": "Feature",
        "id": fid,
        "properties": {"name": name, "sigla": join_name},
        "geometry": {"type": "MultiPolygon", "coordinates": feats_polys},
    })

prov = prov.with_columns(pl.col("provincia_istat").cast(pl.Utf8))
name2id = {}
for rec, polys in geoms:
    join_name = rec.get("SIGLA") or rec.get("DEN_PROV") or ""
    fid = str(rec.get("COD_UTS"))
    name2id[join_name] = fid
prov = prov.with_columns(
    pl.col("provincia_istat").replace(name2id).alias("fid")
).filter(pl.col("fid").is_not_null())
print("matched provinces:", prov.height)

for tag, col, label, fname in [
    ("all", "share_all",
     "Stations adopting the cap (%)<br><sup>All stations, at or below cap on any day 28 Sep – 5 Oct 2026; station×fuel units</sup>",
     "map_adoption_share.png"),
    ("pb", "share_pb",
     "Pompe Bianche stations adopting the cap (%)<br><sup>Independent stations only (bandiera = Pompe Bianche); station×fuel units</sup>",
     "map_pb_adoption_share.png"),
]:
    sub = prov.filter(pl.col(col).is_not_null())
    sub_pd = sub.with_columns(
        (pl.col(col) * 100).alias("pct")
    ).to_pandas()
    fig = go.Figure(go.Choroplethmap(
        geojson=geojson,
        locations=sub_pd["fid"],
        z=sub_pd["pct"],
        featureidkey="id",
        colorscale="Viridis",
        zmin=0, zmax=100,
        marker_line_width=0.5, marker_line_color="white",
        text=sub_pd["provincia_istat"],
        hovertemplate="%{text}<br>adopting: %{z:.1f}%<extra></extra>",
        colorbar=dict(title="% adopting", thickness=15),
    ))
    fig.update_layout(
        title=dict(text=label, font=dict(size=18)),
        margin=dict(l=0, r=0, t=60, b=0), width=1200, height=1000,
        map=dict(style="carto-positron", center=dict(lat=42.5, lon=12.5),
                 zoom=4.6),
    )
    fig.write_image(os.path.join(FIG, fname), scale=2)
    print("saved", fname, "| provinces plotted:", sub.height,
          "| z range:", round(sub_pd['pct'].min(),1), "-", round(sub_pd['pct'].max(),1))
