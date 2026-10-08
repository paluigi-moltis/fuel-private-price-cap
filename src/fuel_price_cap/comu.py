"""dtComu communication freshness and brand-level price dynamics."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

import polars as pl

from fuel_price_cap import config


def parse_dt_comu(prices: pl.DataFrame) -> pl.DataFrame:
    """Add ``comu_date`` (date part of the raw ``dt_comu`` communication
    timestamp, format ``dd/mm/YYYY HH:MM:SS``). Null stays null."""
    return prices.with_columns(
        pl.col("dt_comu")
        .str.strptime(pl.Date, "%d/%m/%Y %H:%M:%S", strict=False)
        .alias("comu_date")
    )


class ComuFreshness:
    """Splits cap-day observations by whether the station communicated its
    price recently (dtComu on the cap day itself, or within the last
    ``config.COMU_RECENT_DAYS`` days): a stale communication is a stale
    *price*, and may explain an apparent compliance failure."""

    def __init__(self, prices: pl.DataFrame) -> None:
        self._capday = prices.filter(pl.col("date") == config.CAP_DATE)

    @staticmethod
    def _agg(frame: pl.DataFrame, dims: Sequence[str]) -> pl.DataFrame:
        recent_from = config.CAP_DATE - dt.timedelta(days=config.COMU_RECENT_DAYS)
        keys = [c for c in frame.columns if c in dims]
        flagged = frame.with_columns(
            threshold=config.threshold_expr()
        )
        return flagged.group_by(keys).agg(
            n_obs=pl.len(),
            n_compliant=(pl.col("prezzo") <= pl.col("threshold")).sum(),
            n_comu_capday=(pl.col("comu_date") == config.CAP_DATE).sum(),
            n_comu_recent=(pl.col("comu_date") >= recent_from).sum(),
            n_comu_older=(
                pl.col("comu_date").is_not_null() & (pl.col("comu_date") < recent_from)
            ).sum(),
            n_comu_missing=pl.col("comu_date").is_null().sum(),
        )

    def by_brand(self) -> pl.DataFrame:
        """fuel x canonical_name: compliance and communication recency."""
        frame = self._capday
        return self._agg(frame, ("fuel", "canonical_name")).sort(
            "fuel", "canonical_name"
        )

    @staticmethod
    def _with_buckets(frame: pl.DataFrame) -> pl.DataFrame:
        """Flag compliance and the dtComu recency bucket on cap-day rows."""
        recent_from = config.CAP_DATE - dt.timedelta(days=config.COMU_RECENT_DAYS)
        return frame.with_columns(
            threshold=config.threshold_expr()
        ).with_columns(
            compliant=pl.col("prezzo") <= pl.col("threshold"),
            comu_bucket=pl.when(pl.col("comu_date") == config.CAP_DATE)
            .then(pl.lit("on cap day"))
            .when(
                pl.col("comu_date").is_not_null() & (pl.col("comu_date") >= recent_from)
            )
            .then(pl.lit(f"within {config.COMU_RECENT_DAYS}d before"))
            .when(pl.col("comu_date").is_not_null())
            .then(pl.lit("older"))
            .otherwise(pl.lit("missing")),
        )

    def agip_eni_crosstab(self) -> pl.DataFrame:
        """Agip Eni only: the compliance x communication-recency crosstab
        that answers 'is the low compliance just missing communications?'."""
        frame = self._capday.filter(pl.col("canonical_name") == "Agip Eni")
        return (
            self._with_buckets(frame)
            .group_by("fuel", "compliant", "comu_bucket")
            .agg(n_stations=pl.len())
            .with_columns(
                share_pct=pl.col("n_stations")
                / pl.col("n_stations").sum().over("fuel", "compliant")
                * 100
            )
            .sort("fuel", "compliant", "comu_bucket")
        )

    def agip_eni_capday_detail(self) -> pl.DataFrame:
        """Agip Eni only: one row per fuel x station observed on the cap day,
        with compliance flag, communication recency bucket, raw dtComu
        timestamp and the gap in days between communication and the cap day."""
        frame = self._capday.filter(pl.col("canonical_name") == "Agip Eni")
        return (
            self._with_buckets(frame)
            .with_columns(
                comu_lag_days=(
                    (pl.lit(config.CAP_DATE) - pl.col("comu_date")).dt.total_days()
                ),
                expected_compliant=pl.col("comu_date") >= config.CAP_DATE,
            )
            .select(
                "fuel",
                "id_impianto",
                "compliant",
                "comu_bucket",
                "comu_lag_days",
                "expected_compliant",
                "dt_comu",
                "comu_date",
                "prezzo",
                "threshold",
                "regione",
                "provincia",
                "tipo_impianto",
                "gestore",
            )
            .sort("fuel", "compliant", "comu_lag_days", "id_impianto")
        )

    def agip_eni_capday_summary(self) -> pl.DataFrame:
        """Agip Eni only: compliance by whether the price was communicated
        on the cap day vs earlier.

        Rationale: the cap was drastically lower than the previous day's
        level, so a communication on 2026-09-27 or earlier is expected to be
        non-compliant (it predates the cap decision); only same-day
        communications can be expected to comply.
        """
        frame = self._capday.filter(pl.col("canonical_name") == "Agip Eni")
        return (
            self._with_buckets(frame)
            .with_columns(comu_on_capday=pl.col("comu_date") == config.CAP_DATE)
            .group_by("fuel", "comu_on_capday")
            .agg(
                n_obs=pl.len(),
                n_compliant=(pl.col("prezzo") <= pl.col("threshold")).sum(),
                n_non_compliant=(pl.col("prezzo") > pl.col("threshold")).sum(),
                mean_prezzo=pl.col("prezzo").mean(),
                mean_comu_hour=(
                    pl.col("dt_comu")
                    .str.slice(11, 2)
                    .cast(pl.Int32, strict=False)
                    .mean()
                ),
            )
            .with_columns(pct_compliant=pl.col("n_compliant") / pl.col("n_obs") * 100)
            .sort("fuel", "comu_on_capday")
        )


class BrandPriceBreak:
    """Daily gross mean price per brand plus a pre/post cap-day break table.

    'Pre' is the ``pre_days`` window ending the day before the cap; 'post' is
    the cap day itself (the extract has a single post-cap day). Break points
    are expressed in EUR/l and in basis points of the pre-cap level so brands
    of different price levels are comparable.
    """

    def __init__(
        self,
        prices: pl.DataFrame,
        *,
        pre_days: int = 7,
        brands: Sequence[str] = (),
    ) -> None:
        self._prices = (
            prices.filter(pl.col("canonical_name").is_in(list(brands)))
            if brands
            else prices
        )
        self._pre_days = pre_days
        self._pre_from = config.CAP_DATE - dt.timedelta(days=pre_days)

    def daily(self) -> pl.DataFrame:
        """Full-window daily mean/sd/n per fuel x brand."""
        return (
            self._prices.group_by("date", "fuel", "canonical_name")
            .agg(
                n_obs=pl.len(),
                mean_price=pl.col("prezzo").mean(),
                sd_price=pl.col("prezzo").std(ddof=1),
            )
            .sort("date", "fuel", "canonical_name")
        )

    def break_table(self) -> pl.DataFrame:
        """Per fuel x brand: pre-cap vs cap-day mean price, the jump between
        them, and the distance of the cap-day mean from the cap threshold."""
        daily = self.daily()
        pre = (
            daily.filter(
                (pl.col("date") >= self._pre_from) & (pl.col("date") < config.CAP_DATE)
            )
            .group_by("fuel", "canonical_name")
            .agg(
                mean_price_pre=pl.col("mean_price").mean(),
                n_days_pre=pl.len(),
            )
        )
        post = daily.filter(pl.col("date") == config.CAP_DATE).select(
            "fuel", "canonical_name", pl.col("mean_price").alias("mean_price_capday")
        )
        # cap-day join: the reference date is CAP_DATE itself, which predates
        # the gasolio excise step, so the base threshold mapping is correct.
        threshold = pl.col("fuel").replace_strict(
            config.THRESHOLDS, return_dtype=pl.Float64
        )
        return (
            pre.join(post, on=["fuel", "canonical_name"], how="left")
            .with_columns(
                jump_eur=pl.col("mean_price_capday") - pl.col("mean_price_pre"),
                jump_bp=(pl.col("mean_price_capday") / pl.col("mean_price_pre") - 1)
                * 10_000,
            )
            .with_columns(
                (threshold - pl.col("mean_price_capday")).alias("distance_to_cap_eur"),
                cap_share_of_jump=pl.col("jump_eur")
                / (threshold - pl.col("mean_price_pre")),
            )
            .sort("fuel", "canonical_name")
        )
