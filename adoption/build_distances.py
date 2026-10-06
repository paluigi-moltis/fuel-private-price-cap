"""Daily spatial covariates: distances to nearest competitor / nearest
at-or-below-cap station, per station x fuel x day.

Definitions (fuel-specific, Stradale only):
- nn_dist_km: distance to the nearest OTHER priced station (any price).
- cap_dist_km: distance to the nearest other station whose effective
  price is <= the cap that day ('adopter' reference set). Null on days
  with no adopter within MAX_SEARCH_KM.
- Prices are the dtComu-effective series (see build_station_day), so a
  communication made on day D prices day D.

Distances in EPSG:3035 (LAEA, km). KD-tree per (fuel, day) over the
~19k Stradale stations x 97 days: fast with cKDTree + sparse_radius.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import polars as pl
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).parent))
import config  # noqa: E402

MAX_SEARCH_KM = 50.0


def compute_distances() -> pl.DataFrame:
    panel = pl.read_parquet(config.STATION_DAY)
    cov = pl.read_parquet(config.STATION_STATIC).select(
        "id_impianto", "cell_x", "cell_y"
    )
    panel = panel.join(cov, on="id_impianto", how="inner")

    thresholds = pl.col("fuel").replace_strict(
        config.THRESHOLDS, return_dtype=pl.Float64
    )
    panel = panel.with_columns(at_cap=(pl.col("prezzo") <= thresholds))

    out_parts = []
    for fuel in config.FUELS:
        f = panel.filter(pl.col("fuel") == fuel)
        # merge the two fuels' calendars: iterate days once
        for day in sorted(f["date"].unique().to_list()):
            d = f.filter(pl.col("date") == day).select(
                "id_impianto", "cell_x", "cell_y", "prezzo", "at_cap"
            )
            xy = d.select("cell_x", "cell_y").to_numpy()
            tree = cKDTree(xy)
            # nearest other station (drop self via k=2)
            dd, ii = tree.query(xy, k=2)
            nn_km = dd[:, 1] / 1000.0

            adopters = np.flatnonzero(d["at_cap"].to_numpy())
            if len(adopters) >= 1:
                tree_a = cKDTree(xy[adopters])
                # query k=2: nearest adopter may be the station itself when
                # it is an adopter; pick the first non-self match
                dd_a, ii_a = tree_a.query(xy, k=2)
                idx_first = adopters[ii_a[:, 0]]
                pick_second = idx_first == np.arange(len(xy))
                cap_km = np.where(pick_second, dd_a[:, 1], dd_a[:, 0]) / 1000.0
            else:
                cap_km = np.full(len(xy), np.nan)

            out_parts.append(
                pl.DataFrame(
                    {
                        "date": pl.Series([day] * len(d), dtype=pl.Date),
                        "fuel": pl.Series([fuel] * len(d), dtype=pl.String),
                        "id_impianto": d["id_impianto"],
                        "nn_dist_km": nn_km,
                        "cap_dist_km": cap_km,
                    }
                )
            )
    out = pl.concat(out_parts, how="vertical")
    out = out.with_columns(
        pl.when(pl.col("cap_dist_km") > MAX_SEARCH_KM)
        .then(None)
        .otherwise("cap_dist_km")
        .alias("cap_dist_km")
    )
    return out


if __name__ == "__main__":
    dist = compute_distances()
    dist.write_parquet(config.DISTANCES)
    print("rows:", dist.height)
    print(
        dist.group_by("fuel")
        .agg(
            nn_mean=pl.col("nn_dist_km").mean(),
            cap_mean=pl.col("cap_dist_km").mean(),
            cap_null=pl.col("cap_dist_km").is_null().sum(),
        )
        .sort("fuel")
    )
