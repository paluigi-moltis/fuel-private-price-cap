"""Build the station-day price panel from dtComu (communication) semantics.

Problem: the repo's daily extract (`date`-keyed prices) snapshots the
market before each day's 00:00-08:00 communication wave, so a station's
"price on day D" may reflect a communication made days earlier. Any
adoption analysis keyed to the cap date would then misdate adoptions by
1-3 days.

Fix: treat each price communication (dtComu) as the atomic event. For
every station x fuel, sort communications by dtComu; the station's price
in force on day D is the last communication with comu_date <= D. This
reconstructs the *effective* price path at daily granularity regardless
of when the extractor happened to snapshot it.

Inputs: repo parquet cache (prices_raw: one row per extract date x fuel
x station with dt_comu; duplicated communications across extract dates
are collapsed by keeping max dtComu per (station, fuel, prezzo?) — in
fact per (station, fuel, dtComu) since the same communication repeats
until replaced).
"""

from __future__ import annotations

import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import config  # noqa: E402


def load_communications() -> pl.DataFrame:
    """Unique price communications per (station, fuel), Sept window onward.

    The same communication appears on consecutive extract dates until the
    operator sends a new one; deduplicate on (id_impianto, fuel, dt_comu,
    prezzo) keeping the first extract date it was seen in.
    """
    prices = pl.read_parquet(config.PRICES_PARQUET).filter(
        pl.col("date") >= config.SERIES_FROM
    )
    comms = (
        prices.with_columns(
            comu_at=pl.col("dt_comu").str.strptime(
                pl.Datetime, "%d/%m/%Y %H:%M:%S", strict=False
            )
        )
        .filter(pl.col("comu_at").is_not_null())
        .group_by("id_impianto", "fuel", "comu_at")
        .agg(
            prezzo=pl.col("prezzo").max(),  # identical across repeats
            first_seen=pl.col("date").min(),
        )
        .sort("id_impianto", "fuel", "comu_at")
    )
    return comms


def build_station_day() -> pl.DataFrame:
    """Station x fuel x day effective price, from SERIES_FROM to latest.

    Strategy: explode the communication history to a daily calendar via
    join_asof per (station, fuel). Then restrict to the union calendar of
    days on which the station was present in any extract (so stations
    that close / stop reporting are not silently carried forward at
    stale prices forever).
    """
    comms = load_communications()

    # calendar of extract dates (defines the days a station was 'alive')
    (
        pl.read_parquet(config.PRICES_PARQUET, columns=["date"])
        .filter(pl.col("date") >= config.SERIES_FROM)
        .unique()
        .sort("date")
    )

    # full day x alive-pair calendar, then ONE global asof join
    alive_pairs = (
        pl.read_parquet(config.PRICES_PARQUET, columns=["date", "fuel", "id_impianto"])
        .filter(pl.col("date") >= config.SERIES_FROM)
        .unique()
    )
    first_comm = comms.group_by("id_impianto", "fuel").agg(
        first_comu=pl.col("comu_at").min()
    )
    cal = (
        alive_pairs.join(first_comm, on=["id_impianto", "fuel"], how="inner")
        # no price in force before the station's first in-window communication
        .filter(pl.col("date") >= pl.col("first_comu").dt.date())
        .select("date", "fuel", "id_impianto")
        .sort("date")
    )
    comms_day = comms.with_columns(comu_day=pl.col("comu_at").dt.date())
    panel = cal.join_asof(
        comms_day,
        left_on="date",
        right_on="comu_day",
        by=["id_impianto", "fuel"],
        strategy="backward",
    )

    # days is now unused at frame level; keep for clarity of the range
    panel = panel.with_columns(
        compliance_at_cap=pl.when(pl.col("date") >= config.CAP_DATE)
        .then(pl.col("prezzo") <= pl.col("fuel").replace_strict(config.THRESHOLDS))
        .otherwise(None)
    )
    return panel
