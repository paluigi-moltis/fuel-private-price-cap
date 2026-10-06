"""Assemble the analysis panel and the province-level tables.

Outputs:
- adoption_panel.parquet: station x fuel x day with covariates, distances,
  adoption flags (post-cap rows only for flag columns).
- survival_input.csv: station x fuel duration data for R survival models.
- province_dispersion.csv: per province x fuel x phase dispersion stats.
- nonadopter_competitiveness.csv: non-adopter price gap vs provincial
  mean, pre vs post cap.
"""

from __future__ import annotations

import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import config  # noqa: E402


def build() -> None:
    panel = pl.read_parquet(config.STATION_DAY)
    cov = pl.read_parquet(config.STATION_STATIC)
    dist = pl.read_parquet(config.DISTANCES)

    thr = pl.col("fuel").replace_strict(config.THRESHOLDS, return_dtype=pl.Float64)
    panel = panel.with_columns(
        at_cap=(pl.col("prezzo") <= thr),
        post=pl.col("date") >= config.CAP_DATE,
    )
    df = panel.join(cov, on="id_impianto", how="inner").join(
        dist, on=["date", "fuel", "id_impianto"], how="left"
    )

    # first adoption date per station x fuel (at_cap on/after cap date)
    adopt = (
        df.filter(pl.col("post") & pl.col("at_cap"))
        .group_by("id_impianto", "fuel")
        .agg(adopt_date=pl.col("date").min())
    )
    df = df.join(adopt, on=["id_impianto", "fuel"], how="left").with_columns(
        adopted=(pl.col("adopt_date").is_not_null()),
        days_since_cap=(pl.col("date") - config.CAP_DATE).dt.total_days(),
        days_to_adopt=(pl.col("adopt_date") - config.CAP_DATE).dt.total_days(),
    )
    df.select(
        "date",
        "fuel",
        "id_impianto",
        "prezzo",
        "comu_day",
        "at_cap",
        "post",
        "adopt_date",
        "adopted",
        "days_since_cap",
        "days_to_adopt",
        "nn_dist_km",
        "cap_dist_km",
        "bandiera",
        "gestore",
        "n_stations_gestore",
        "Comune",
        "provincia_istat",
        "regione",
        "pop_cell",
        "pop_15_64_cell",
        "occupati_cell",
        "latitude",
        "longitude",
    ).write_parquet(config.ADOPTION_PANEL)

    # ---- survival input (station x fuel level) ----
    surv = (
        df.group_by(  # pre-window covariates need pre rows; group over full frame
            "id_impianto", "fuel"
        )
        .agg(
            adopted=pl.col("adopted").first(),
            days_to_adopt=pl.col("days_to_adopt").first(),
            last_seen=pl.col("date").max(),
            mean_pre_post=pl.col("prezzo").mean(),
            nn_dist_km=pl.col("nn_dist_km").mean(),
            cap_dist_km_d0=pl.col("cap_dist_km")
            .filter(pl.col("days_since_cap") == 0)
            .first(),
            post_days_seen=pl.col("days_since_cap").filter(pl.col("post")).n_unique(),
            cap_dist_km_mean=pl.col("cap_dist_km").mean(),
            bandiera=pl.col("bandiera").first(),
            gestore=pl.col("gestore").first(),
            n_stations_gestore=pl.col("n_stations_gestore").first(),
            comune=pl.col("Comune").first(),
            provincia=pl.col("provincia_istat").first(),
            regione=pl.col("regione").first(),
            pop_cell=pl.col("pop_cell").first(),
            pop_15_64=pl.col("pop_15_64_cell").first(),
            occupati=pl.col("occupati_cell").first(),
            pre_mean=pl.col("prezzo")
            .filter(
                (pl.col("date") >= config.PRE_WINDOW[0])
                & (pl.col("date") <= config.PRE_WINDOW[1])
            )
            .mean(),
        )
        .filter(pl.col("post_days_seen") > 0)  # must be observed post-cap at least once
        .with_columns(
            duration=pl.when(pl.col("adopted"))
            .then(pl.col("days_to_adopt"))
            .otherwise(pl.col("post_days_seen") - 1),
            event=pl.col("adopted").cast(pl.Int8),
            pre_gap_vs_cap=pl.col("pre_mean")
            - pl.col("fuel").replace_strict(config.THRESHOLDS, return_dtype=pl.Float64),
            pop_density_cell=pl.col("pop_cell"),  # pop per 1 km2
        )
        .sort("id_impianto", "fuel")
    )
    surv.write_csv(config.SURVIVAL_INPUT)

    # ---- province dispersion, pre vs post ----
    phases = (
        pl.when(
            (pl.col("date") >= config.PRE_WINDOW[0])
            & (pl.col("date") < config.CAP_DATE)
        )
        .then(pl.lit("pre"))
        .when(pl.col("post"))
        .then(pl.lit("post"))
        .otherwise(None)
        .alias("phase")
    )
    disp = (
        df.with_columns(phases)
        .filter(pl.col("phase").is_not_null())
        .group_by("provincia_istat", "regione", "fuel", "phase")
        .agg(
            n_stations=pl.col("id_impianto").n_unique(),
            n_obs=pl.len(),
            mean=pl.col("prezzo").mean(),
            sd=pl.col("prezzo").std(),
            p10=pl.col("prezzo").quantile(0.10),
            p90=pl.col("prezzo").quantile(0.90),
            iqr=pl.col("prezzo").quantile(0.75) - pl.col("prezzo").quantile(0.25),
            adopter_share=pl.col("at_cap").mean(),
        )
        .with_columns(p90_p10=pl.col("p90") - pl.col("p10"))
        .sort("provincia_istat", "fuel", "phase")
    )
    disp.write_csv(config.PROV_DISPERSION)

    # ---- non-adopter competitiveness vs provincial mean ----
    prov_mean = (
        df.with_columns(phases)
        .filter(pl.col("phase").is_not_null())
        .group_by("provincia_istat", "fuel", "phase", "date")
        .agg(prov_mean_day=pl.col("prezzo").mean())
    )
    comp = (
        df.with_columns(phases)
        .filter(pl.col("phase").is_not_null())
        .join(prov_mean, on=["provincia_istat", "fuel", "phase", "date"], how="left")
        .with_columns(gap_vs_prov=pl.col("prezzo") - pl.col("prov_mean_day"))
        .group_by(
            "id_impianto",
            "fuel",
            "provincia_istat",
            "bandiera",
            "phase",
        )
        .agg(
            adopted=pl.col("adopted").first(),
            gap_mean=pl.col("gap_vs_prov").mean(),
            n_days=pl.len(),
        )
        .group_by("id_impianto", "fuel", "provincia_istat", "bandiera", "adopted")
        .agg(
            gap_pre=pl.col("gap_mean").filter(pl.col("phase") == "pre").first(),
            gap_post=pl.col("gap_mean").filter(pl.col("phase") == "post").first(),
        )
        .with_columns(gap_change=pl.col("gap_post") - pl.col("gap_pre"))
        .sort("id_impianto", "fuel")
    )
    comp.write_csv(config.COMPETITIVENESS)

    print(
        "panel:",
        df.height,
        "| survival:",
        surv.height,
        "| dispersion:",
        disp.height,
        "| comp:",
        comp.height,
    )
    print("adopted share (station x fuel):", surv["adopted"].mean())
    print(
        surv.group_by("fuel")
        .agg(
            n=pl.len(),
            adopt_share=pl.col("adopted").mean(),
            med_days=pl.col("duration").median(),
        )
        .sort("fuel")
    )


if __name__ == "__main__":
    build()
