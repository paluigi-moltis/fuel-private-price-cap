"""CRS harmonization for the adoption analysis.

Single source of truth for coordinate reference systems:

- Storage / interchange: EPSG:4326 (WGS84 lon/lat) — MIMIT station
  coordinates and ISTAT border shapefiles are natively WGS84.
- Metric computation (distances in km, areas): EPSG:3035
  (ETRS89-LAEA Europe) — the CRS of the ISTAT/Eurostat 1-km population
  grid (grid IDs encode 3035 south-west cell corners). Equal-area, so
  distances are accurate enough (sub-0.1% scale distortion over Italy)
  and grid cells are exactly 1 km2.

Every loader in this module returns data already in one of these two
CRSs; nothing else may invent a projection.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import polars as pl
import pyproj

sys.path.insert(0, str(Path(__file__).parent))
import config  # noqa: E402
from shapely.geometry import Point

WGS84 = pyproj.CRS.from_epsg(4326)
LAEA = pyproj.CRS.from_epsg(3035)
_TO_LAEA = pyproj.Transformer.from_crs(WGS84, LAEA, always_xy=True).transform
_TO_WGS84 = pyproj.Transformer.from_crs(LAEA, WGS84, always_xy=True).transform

_GRID_ID_RE = re.compile(r"CRS3035RES1000mN(?P<n>\d+)E(?P<e>\d+)")


def lonlat_to_laea(lon: float, lat: float) -> tuple[float, float]:
    return _TO_LAEA(lon, lat)


def laea_to_lonlat(x: float, y: float) -> tuple[float, float]:
    return _TO_WGS84(x, y)


def grid_id_to_cell_center(grid_id: str) -> tuple[float, float] | None:
    """ISTAT grid id -> (x, y) of the cell CENTER in EPSG:3035.

    Ids look like 'CRS3035RES1000mN1386000E4558000' and encode the
    south-west corner of a 1-km cell; the center is corner + 500 m.
    """
    m = _GRID_ID_RE.match(grid_id)
    if m is None:
        return None
    return int(m["e"]) + 500.0, int(m["n"]) + 500.0


def load_population_grid() -> pl.DataFrame:
    """ISTAT 2021 census population grid, one row per 1-km cell.

    Columns: cell_x, cell_y (EPSG:3035, cell centers), lon, lat
    (EPSG:4326, cell centers), pop_tot and census breakdowns.
    """
    frame = pl.read_csv(
        config.GRID_CSV, separator=";", encoding="utf-8-lossy"
    ).with_columns(pl.col("GRD_ID").str.strip_chars())
    cells = [grid_id_to_cell_center(g) for g in frame["GRD_ID"]]
    xy = pl.DataFrame(
        cells,
        schema={"x": pl.Float64, "y": pl.Float64},
        orient="row",
    )
    out = pl.concat([frame.drop("GRD_ID", "CNTR_ID"), xy], how="horizontal").rename(
        {
            "x": "cell_x",
            "y": "cell_y",
            "Pop_Tot": "pop_tot",
            "Pop_0_15": "pop_0_15",
            "Pop_15_64": "pop_15_64",
            "Pop_oltre_65": "pop_65p",
            "Occupati": "occupati",
        }
    )
    # cell centers -> WGS84 for reference/plotting
    lons, lats = zip(
        *(
            laea_to_lonlat(x, y)
            for x, y in zip(out["cell_x"], out["cell_y"], strict=False)
        ),
        strict=True,
    )
    return out.with_columns(pl.Series("lon", lons), pl.Series("lat", lats))


def load_stations_laea(stations: pl.DataFrame) -> pl.DataFrame:
    """Add cell_x/cell_y (EPSG:3035) columns to a stations frame.

    Input must have latitude/longitude in WGS84 decimal degrees.
    Rows with missing or out-of-bbox coordinates are dropped (skill
    notes: bbox lat 35-47.5, lon 6-19; broken coords exist upstream).
    """
    good = stations.filter(
        pl.col("latitude").is_between(35.0, 47.5)
        & pl.col("longitude").is_between(6.0, 19.0)
    )
    xy = [
        lonlat_to_laea(lon, lat)
        for lon, lat in zip(good["longitude"], good["latitude"], strict=True)
    ]
    return good.with_columns(
        pl.Series("cell_x", [c[0] for c in xy]),
        pl.Series("cell_y", [c[1] for c in xy]),
    )


def nearest_population_cell(
    stations_laea: pl.DataFrame, grid: pl.DataFrame
) -> pl.DataFrame:
    """Attach population of the containing/nearest 1-km cell per station.

    Because station coordinates carry ~5 decimal places and cells are
    1 km, nearest-cell == containing cell for all well-placed stations;
    nearest is used so coastal/misplaced stations still get a value,
    together with the snap distance (a large snap flags bad geocodes).
    """
    from scipy.spatial import cKDTree

    tree = cKDTree(grid.select("cell_x", "cell_y").to_numpy())
    d, idx = tree.query(stations_laea.select("cell_x", "cell_y").to_numpy())
    cells = grid.select("pop_tot", "pop_0_15", "pop_15_64", "pop_65p", "occupati")[
        idx
    ].to_numpy()
    cell_xy = grid.select("cell_x", "cell_y").to_numpy()[idx]
    cell_lons, cell_lats = zip(*(laea_to_lonlat(x, y) for x, y in cell_xy), strict=True)
    return stations_laea.with_columns(
        pl.Series("pop_cell", cells[:, 0]),
        pl.Series("pop_0_15_cell", cells[:, 1]),
        pl.Series("pop_15_64_cell", cells[:, 2]),
        pl.Series("pop_65p_cell", cells[:, 3]),
        pl.Series("occupati_cell", cells[:, 4]),
        pl.Series("cell_snap_km", d / 1000.0),
        pl.Series("cell_lon", cell_lons),
        pl.Series("cell_lat", cell_lats),
    )


def point_in_province(
    lon: float, lat: float, prov_geoms: dict[str, object]
) -> str | None:
    """Point-in-polygon lookup against prepared province geometries."""
    p = Point(lon, lat)
    for sigla, geom in prov_geoms.items():
        if geom.covers(p):
            return sigla
    return None
