"""Build static station covariates: geography, population, chain size.

Outputs one row per station (id_impianto) with:
- WGS84 lon/lat and EPSG:3035 x/y (harmonized CRS layer)
- comune (from MIMIT anagrafica), provincia (from 2026 ISTAT borders,
  point-in-polygon; MIMIT sigle mapped via the skill synonym table),
  regione (from borders)
- population covariates from the ISTAT 1-km grid (containing cell)
- gestore chain size (# stations of the same gestore, national)
- bandiera (raw + seven-brand canonical via repo config)
"""

from __future__ import annotations

import sys
from pathlib import Path

import polars as pl
import pyproj
import shapefile  # pyshp
from crs import WGS84
from shapely.geometry import Point, shape
from shapely.ops import transform as shp_transform
from shapely.prepared import prep

sys.path.insert(0, str(Path(__file__).parent))
import config  # noqa: E402
from crs import (  # noqa: E402
    load_population_grid,
    load_stations_laea,
    nearest_population_cell,
)

# MIMIT provincia sigle -> ISTAT SIGLA set (skill synonym table)
SYNONYMS = {
    "SU": {"VS", "CI", "CA"},
    "ROMA": {"RM"},
    "SS": {"SS", "OT"},
    "NU": {"NU", "OG", "OT"},
    "CA": {"CA", "SU"},
    "OLBIA TEMPIO": {"OT"},
    "GALLURA NORD-EST SARDEGNA": {"OT"},
    "MEDIO CAMPIDANO": {"VS"},
    "CARBONIA IGLESIAS": {"CI"},
}


def load_anagrafica() -> pl.DataFrame:
    """Latest MIMIT anagrafica with Comune; one row per station."""
    rows: list[list[str]] = []
    with open(config.ANAGRAFICA_CSV, encoding="utf-8", errors="replace") as f:
        header = None
        for line in f:
            if line.startswith("Estrazione del "):
                continue
            if header is None:
                header = line.strip().split("|")
                continue
            parts = line.rstrip("\n").split("|")
            if len(parts) < len(header):
                continue
            rows.append(parts[: len(header)])
    frame = pl.DataFrame(rows, schema=header, orient="row")
    return frame.select(
        pl.col("idImpianto").cast(pl.Int64).alias("id_impianto"),
        "Gestore",
        "Bandiera",
        "Tipo Impianto",
        "Comune",
        "Provincia",
        pl.col("Latitudine").cast(pl.Float64, strict=False).alias("latitude"),
        pl.col("Longitudine").cast(pl.Float64, strict=False).alias("longitude"),
    )


def load_province_shapes():
    """ISTAT 2026 province polygons, prepared, keyed by SIGLA; plus regions.

    CRS gotcha (verified): despite the `_WGS84` suffix, the 2026
    generalizzata layers are projected in WGS84 / UTM zone 32N
    (EPSG:32632) — the .prj says PROJCS[WGS_1984_UTM_Zone_32N...] and
    the coordinates are meters. Polygons are brought back to WGS84
    lon/lat here so station points (4326) can be tested directly.
    Verified: under 32632->4326 all province test points hit their own
    province; any other reading (33N, raw) fails.
    """
    base = config.BORDERS_DIR
    _to_wgs84 = pyproj.Transformer.from_crs(
        pyproj.CRS.from_epsg(32632), WGS84, always_xy=True
    ).transform

    sf = shapefile.Reader(str(base / "ProvCM01012026_g" / "ProvCM01012026_g_WGS84"))
    fields = [f[0] for f in sf.fields[1:]]
    i_sigla = fields.index("SIGLA")
    i_codreg = fields.index("COD_REG")

    sf_reg = shapefile.Reader(str(base / "Reg01012026_g" / "Reg01012026_g_WGS84"))
    reg_fields = [f[0] for f in sf_reg.fields[1:]]
    i_regcode = reg_fields.index("COD_REG")
    i_regname = reg_fields.index("DEN_REG")
    code_to_region = {r[i_regcode]: r[i_regname] for r in sf_reg.records()}

    prov = {}
    prov_region = {}
    for rec, sr in zip(sf.records(), sf.shapes(), strict=True):
        sigla = rec[i_sigla]
        if sigla in prov:  # one row per province; guard anyway
            continue
        prov[sigla] = prep(shp_transform(_to_wgs84, shape(sr.__geo_interface__)))
        prov_region[sigla] = code_to_region[rec[i_codreg]]
    return prov, prov_region


def build_station_covariates() -> pl.DataFrame:
    ana = load_anagrafica().filter(pl.col("Tipo Impianto") == config.TIPO_STRADALE)
    grid = load_population_grid()
    st = load_stations_laea(ana)
    st = nearest_population_cell(st, grid)

    prov_geoms, prov_region = load_province_shapes()
    siglas = list(prov_geoms.keys())
    assigned = []
    regions = []
    for lon, lat, declared in zip(
        st["longitude"], st["latitude"], st["Provincia"], strict=True
    ):
        target = None
        cands = SYNONYMS.get(declared, {declared})
        # fast path: check declared (or synonyms) first
        for s in cands:
            if s in prov_geoms and prov_geoms[s].covers(Point(lon, lat)):
                target = s
                break
        if target is None:  # brute-force scan (data-entry drift)
            for s in siglas:
                if prov_geoms[s].covers(Point(lon, lat)):
                    target = s
                    break
        assigned.append(target)
        regions.append(prov_region.get(target) if target else None)
    st = st.with_columns(
        pl.Series("provincia_istat", assigned),
        pl.Series("regione", regions),
    )

    # gestore chain size over priced stations (any fuel), latest anagrafica
    chain = (
        st.group_by("Gestore")
        .agg(n_stations_gestore=pl.len())
        .rename({"Gestore": "gestore"})
    )
    out = st.rename(
        {
            "Bandiera": "bandiera",
            "Provincia": "provincia_mimit",
            "Gestore": "gestore",
        }
    )
    out = out.join(chain, on="gestore", how="left")
    return out


if __name__ == "__main__":
    cov = build_station_covariates()
    cov.write_parquet(config.STATION_STATIC)
    n_assigned = cov["provincia_istat"].is_not_null().sum()
    share = n_assigned / cov.height
    print(f"stations: {cov.height}, provincia assigned: {n_assigned} ({share:.1%})")
    print(
        f"cell snap > 0.71km (likely bad geocode): {(cov['cell_snap_km'] > 0.71).sum()}"
    )
    print(
        cov.select(
            "id_impianto",
            "bandiera",
            "Comune",
            "provincia_istat",
            "regione",
            "pop_cell",
            "n_stations_gestore",
        ).head(5)
    )
