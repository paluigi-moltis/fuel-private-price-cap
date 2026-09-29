"""Analysis: station counts and concentration, cap compliance, daily price stats."""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl

from fuel_price_cap import config
from fuel_price_cap.enrich import normalize_text

_SLICE_ALL = "Tutti"


class StationStats:
    """Station counts and Gestore concentration on the latest snapshot
    (plus weekly counts across all snapshots as a bonus)."""

    def __init__(self, stations: pl.DataFrame) -> None:
        self._stations = stations
        self._latest_date = stations["date"].max()
        self._latest = stations.filter(pl.col("date") == self._latest_date)

    @property
    def latest_date(self) -> object:
        return self._latest_date

    @property
    def latest(self) -> pl.DataFrame:
        return self._latest

    def counts_by_group_tipo(self) -> pl.DataFrame:
        return (
            self._latest.group_by("group", "tipo_impianto")
            .agg(n_stations=pl.len())
            .with_columns(
                share_pct=pl.col("n_stations")
                / pl.col("n_stations").sum().over("tipo_impianto")
                * 100
            )
            .sort("tipo_impianto", "group")
        )

    def counts_by_bandiera_tipo(self) -> pl.DataFrame:
        return (
            self._latest.group_by(
                "group", "canonical_name", "bandiera", "tipo_impianto"
            )
            .agg(n_stations=pl.len())
            .sort(
                "tipo_impianto", "group", "n_stations", descending=[False, False, True]
            )
        )

    def weekly_counts(self) -> pl.DataFrame:
        return (
            self._stations.group_by("date", "group")
            .agg(n_stations=pl.len())
            .sort("date", "group")
        )

    def concentration(self) -> pl.DataFrame:
        """For the six grouped brands only (Majors/Large): number of distinct
        Gestori, top-3 Gestore cumulative share, and HHI over Gestore shares.

        Shares are fractions in [0, 1], so HHI is in [0, 1] as well.
        Computed on the latest snapshot, overall and per Tipo Impianto.
        """
        brands = self._latest.filter(pl.col("group").is_in(config.GROUPED_BRANDS))
        slices = [(_SLICE_ALL, brands)]
        for tipo in config.TIPO_MAIN:
            slices.append((tipo, brands.filter(pl.col("tipo_impianto") == tipo)))
        blocks = [self._concentration_block(frame, label) for label, frame in slices]
        return pl.concat(blocks).sort(
            "canonical_name", "tipo_impianto_slice", descending=[False, False]
        )

    @staticmethod
    def _concentration_block(frame: pl.DataFrame, slice_label: str) -> pl.DataFrame:
        gestori = _normalized_gestori(frame)
        counts = gestori.group_by("canonical_name", "gestore_normalized").agg(
            n_stations=pl.len()
        )
        return (
            counts.group_by("canonical_name")
            .agg(
                n_gestori=pl.len(),
                n_stations=pl.col("n_stations").sum(),
                top3_gestore_share=(
                    pl.col("n_stations").sort(descending=True).head(3).sum()
                    / pl.col("n_stations").sum()
                ),
                hhi=((pl.col("n_stations") / pl.col("n_stations").sum()) ** 2).sum(),
            )
            .with_columns(
                tipo_impianto_slice=pl.lit(slice_label),
                top3_gestore_share=pl.col("top3_gestore_share").round(4),
                hhi=pl.col("hhi").round(4),
            )
            .select(
                "canonical_name",
                "tipo_impianto_slice",
                "n_stations",
                "n_gestori",
                "top3_gestore_share",
                "hhi",
            )
        )


def _normalized_gestori(frame: pl.DataFrame) -> pl.DataFrame:
    """Gestore labels normalized (case/whitespace variants collapse together)."""
    distinct = frame.select(pl.col("gestore").alias("raw")).unique()
    pairs = [
        {"raw": row["raw"], "gestore_normalized": normalize_text(row["raw"])}
        for row in distinct.iter_rows(named=True)
    ]
    lookup = pl.DataFrame(
        pairs, schema={"raw": pl.String, "gestore_normalized": pl.String}
    )
    return frame.join(
        lookup, left_on="gestore", right_on="raw", how="left"
    ).with_columns(pl.col("gestore_normalized").fill_null("(non specificato)"))


class CapCompliance:
    """Share of price observations strictly below the cap threshold
    (Benzina < 2.0 EUR/l, Gasolio < 2.2 EUR/l) from the cap date onward."""

    def __init__(self, prices: pl.DataFrame) -> None:
        self._df = (
            prices.filter(pl.col("date") >= config.CAP_DATE)
            .with_columns(
                threshold=pl.col("fuel").replace_strict(
                    config.THRESHOLDS, return_dtype=pl.Float64
                )
            )
            .with_columns(is_below=pl.col("prezzo") < pl.col("threshold"))
        )

    def daily(self, dims: Sequence[str] = ()) -> pl.DataFrame:
        return (
            self._df.group_by("date", "fuel", *dims)
            .agg(n_obs=pl.len(), n_below=pl.col("is_below").sum())
            .with_columns(pct_below=pl.col("n_below") / pl.col("n_obs") * 100)
            .sort("date", "fuel", *dims)
        )

    def period(self, dims: Sequence[str] = ()) -> pl.DataFrame:
        """Pooled share over the whole post-cap period plus the mean of daily shares."""
        pooled = (
            self._df.group_by("fuel", *dims)
            .agg(n_obs=pl.len(), n_below=pl.col("is_below").sum())
            .with_columns(pct_below_pooled=pl.col("n_below") / pl.col("n_obs") * 100)
        )
        daily_mean = (
            self.daily(dims)
            .group_by("fuel", *dims)
            .agg(pct_below_daily_mean=pl.col("pct_below").mean())
        )
        return pooled.join(daily_mean, on=["fuel", *dims], how="left").sort(
            "fuel", *dims
        )


class DailyPriceStats:
    """Daily mean/sd of gross and net prices, by arbitrary dimensions."""

    @staticmethod
    def daily(prices: pl.DataFrame, dims: Sequence[str] = ()) -> pl.DataFrame:
        return prices.group_by("date", "fuel", *dims).agg(
            n_obs=pl.len(),
            mean_prezzo=pl.col("prezzo").mean(),
            sd_prezzo=pl.col("prezzo").std(ddof=1),
            mean_net_price=pl.col("net_price").mean(),
            sd_net_price=pl.col("net_price").std(ddof=1),
        )

    @staticmethod
    def net_summary(prices: pl.DataFrame, dims: Sequence[str] = ()) -> pl.DataFrame:
        """Mean/sd/min/max of net price per fuel x dims, with pre/post-cap deltas
        (pre = 2026-07-01..cap-1, post = cap date onward) for net and gross."""
        overall = prices.group_by("fuel", *dims).agg(
            n_obs=pl.len(),
            net_mean=pl.col("net_price").mean(),
            net_sd=pl.col("net_price").std(ddof=1),
            net_min=pl.col("net_price").min(),
            net_max=pl.col("net_price").max(),
            gross_mean=pl.col("prezzo").mean(),
        )
        pre = (
            prices.filter(pl.col("date") < config.CAP_DATE)
            .group_by("fuel", *dims)
            .agg(
                net_mean_pre=pl.col("net_price").mean(),
                gross_mean_pre=pl.col("prezzo").mean(),
            )
        )
        post = (
            prices.filter(pl.col("date") >= config.CAP_DATE)
            .group_by("fuel", *dims)
            .agg(
                net_mean_post=pl.col("net_price").mean(),
                gross_mean_post=pl.col("prezzo").mean(),
            )
        )
        keys = ["fuel", *dims]
        return (
            overall.join(pre, on=keys, how="left")
            .join(post, on=keys, how="left")
            .with_columns(
                net_delta_post_pre=pl.col("net_mean_post") - pl.col("net_mean_pre"),
                gross_delta_post_pre=pl.col("gross_mean_post")
                - pl.col("gross_mean_pre"),
            )
            .sort(*keys)
        )
