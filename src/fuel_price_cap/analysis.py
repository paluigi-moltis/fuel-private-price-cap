"""Analysis: station counts and concentration, cap compliance, daily price stats."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from itertools import combinations

import polars as pl

from fuel_price_cap import config
from fuel_price_cap.enrich import normalize_text, normalized_mapping

_SLICE_ALL = "Tutti"


class StationStats:
    """Station counts and Gestore concentration on the latest snapshot
    (plus weekly counts across all snapshots as a bonus).

    Stations without a Tipo Impianto are excluded, mirroring the price-level
    convention of dropping prices that cannot be attributed to a typed
    station (none exist in the current data: the source only carries
    Stradale/Autostradale)."""

    def __init__(self, stations: pl.DataFrame) -> None:
        self._stations = stations.filter(pl.col("tipo_impianto").is_not_null())
        self._latest_date = self._stations["date"].max()
        self._latest = self._stations.filter(pl.col("date") == self._latest_date)

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
        # seven-brand view (see enrich.brand_view); the raw Bandiera detail
        # lives in bandiera_values_audit.csv
        return (
            self._latest.group_by("group", "canonical_name", "tipo_impianto")
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

    def top1_gestori(self) -> pl.DataFrame:
        """Largest Gestore (normalized label) per brand on the latest
        snapshot, with its station count. Anchors the ``gestore_top1``
        compliance split."""
        gestori = _normalized_gestori(self._latest)
        counts = gestori.group_by("canonical_name", "gestore_normalized").agg(
            n_stations=pl.len()
        )
        return counts.group_by("canonical_name").agg(
            top1_gestore=pl.col("gestore_normalized")
            .sort_by(["n_stations", "gestore_normalized"], descending=[True, False])
            .first(),
            n_stations_top1=pl.col("n_stations").max(),
        )

    def concentration(self) -> pl.DataFrame:
        """For the six grouped brands only (Majors/Large): number of distinct
        Gestori, top-1 and top-3 Gestore shares, and HHI over Gestore shares.

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
        # gestori ranked by station count (ties broken alphabetically);
        # slice().first() yields null when the brand has fewer operators
        ranked_gestori = pl.col("gestore_normalized").sort_by(
            ["n_stations", "gestore_normalized"], descending=[True, False]
        )
        return (
            counts.group_by("canonical_name")
            .agg(
                n_gestori=pl.len(),
                n_stations=pl.col("n_stations").sum(),
                top1_gestore=ranked_gestori.first(),
                top2_gestore=ranked_gestori.slice(1, 1).first(),
                top3_gestore=ranked_gestori.slice(2, 1).first(),
                n_stations_top1=pl.col("n_stations").max(),
                top3_gestore_share=(
                    pl.col("n_stations").sort(descending=True).head(3).sum()
                    / pl.col("n_stations").sum()
                ),
                hhi=((pl.col("n_stations") / pl.col("n_stations").sum()) ** 2).sum(),
            )
            .with_columns(
                tipo_impianto_slice=pl.lit(slice_label),
                top1_gestore_share=(
                    pl.col("n_stations_top1") / pl.col("n_stations")
                ).round(4),
                top3_gestore_share=pl.col("top3_gestore_share").round(4),
                hhi=pl.col("hhi").round(4),
            )
            .select(
                "canonical_name",
                "tipo_impianto_slice",
                "n_stations",
                "n_gestori",
                "top1_gestore",
                "top2_gestore",
                "top3_gestore",
                "n_stations_top1",
                "top1_gestore_share",
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
    """Share of price observations at or below the self-imposed cap
    (Benzina <= 2.0 EUR/l, Gasolio <= 2.2 EUR/l): pricing exactly at the
    cap does not violate it.

    ``from_date`` bounds the window (default: the cap date, included);
    ``None`` keeps the full period. When ``top1_gestori`` (from
    ``StationStats.top1_gestori``) is given, rows carry a ``gestore_top1``
    flag: "top1" when the station's Gestore is the brand's largest operator,
    "altri" otherwise.
    """

    def __init__(
        self,
        prices: pl.DataFrame,
        from_date: dt.date | None = config.COMPLIANCE_FROM,
        top1_gestori: pl.DataFrame | None = None,
    ) -> None:
        base = (
            prices if from_date is None else prices.filter(pl.col("date") >= from_date)
        )
        flagged = base.with_columns(
            threshold=pl.col("fuel").replace_strict(
                config.THRESHOLDS, return_dtype=pl.Float64
            )
        ).with_columns(is_below=pl.col("prezzo") <= pl.col("threshold"))
        if top1_gestori is not None:
            flagged = self._flag_gestore_top1(flagged, top1_gestori)
        self._df = flagged

    @staticmethod
    def _flag_gestore_top1(
        frame: pl.DataFrame, top1_gestori: pl.DataFrame
    ) -> pl.DataFrame:
        normalized = normalized_mapping(frame, "gestore")
        return (
            frame.join(normalized, left_on="gestore", right_on="raw", how="left")
            .join(
                top1_gestori.select("canonical_name", "top1_gestore"),
                on="canonical_name",
                how="left",
            )
            .with_columns(
                gestore_top1=pl.when(pl.col("normalized") == pl.col("top1_gestore"))
                .then(pl.lit("top1"))
                .otherwise(pl.lit("altri"))
            )
            .drop("normalized", "top1_gestore")
        )

    def daily(self, dims: Sequence[str] = ()) -> pl.DataFrame:
        return (
            self._df.group_by("date", "fuel", *dims)
            .agg(n_obs=pl.len(), n_below=pl.col("is_below").sum())
            .with_columns(pct_below=pl.col("n_below") / pl.col("n_obs") * 100)
            .sort("date", "fuel", *dims)
        )

    def daily_with_aggregates(self, dims: Sequence[str] = ()) -> pl.DataFrame:
        """Daily shares plus OLAP margins: for every subset of ``dims``,
        additional rows aggregated over that subset, with the aggregated
        dimensions set to ``"Tutte"``."""
        return _add_aggregate_rows(self.daily(dims), dims)

    def period(self, dims: Sequence[str] = ()) -> pl.DataFrame:
        """Pooled share over the window plus the mean of daily shares,
        computed on the daily frame including its aggregate rows."""
        daily_frame = self.daily_with_aggregates(dims)
        pooled = (
            daily_frame.group_by("fuel", *dims)
            .agg(n_obs=pl.col("n_obs").sum(), n_below=pl.col("n_below").sum())
            .with_columns(pct_below_pooled=pl.col("n_below") / pl.col("n_obs") * 100)
        )
        daily_mean = daily_frame.group_by("fuel", *dims).agg(
            pct_below_daily_mean=pl.col("pct_below").mean()
        )
        joined = pooled.join(daily_mean, on=["fuel", *dims], how="left")
        return _sort_details_first(joined, keys=("fuel",), dims=dims)


def _dim_subsets(dims: Sequence[str]) -> list[tuple[str, ...]]:
    """All non-empty subsets of ``dims``, in a deterministic order."""
    return [
        subset
        for size in range(1, len(dims) + 1)
        for subset in combinations(dims, size)
    ]


def _add_aggregate_rows(daily: pl.DataFrame, dims: Sequence[str]) -> pl.DataFrame:
    """Append OLAP margin rows to a daily compliance frame: for each subset
    of ``dims``, rows pooled over that subset with the dimension set to
    ``"Tutte"`` (counts summed, ``pct_below`` recomputed). Margin rows sort
    after the detail rows of their cell."""
    frames = [daily]
    for subset in _dim_subsets(dims):
        keep = [d for d in dims if d not in subset]
        margins = (
            daily.group_by("date", "fuel", *keep)
            .agg(
                n_obs=pl.col("n_obs").sum(),
                n_below=pl.col("n_below").sum(),
            )
            .with_columns(pct_below=pl.col("n_below") / pl.col("n_obs") * 100)
            .with_columns(pl.lit(config.AGG_SENTINEL).alias(d) for d in subset)
            .select(daily.columns)
        )
        frames.append(margins)
    return _sort_details_first(pl.concat(frames), keys=("date", "fuel"), dims=dims)


def _sort_details_first(
    frame: pl.DataFrame, keys: Sequence[str], dims: Sequence[str]
) -> pl.DataFrame:
    """Sort by the key and dimension columns with ``"Tutte"`` margins last
    within each cell (instead of scattered or block-appended at file level)."""
    helpers = [
        pl.when(pl.col(d) == config.AGG_SENTINEL)
        .then(pl.lit("\uffff"))
        .otherwise(pl.col(d))
        .alias(f"__sort_{d}")
        for d in dims
    ]
    helper_names = [f"__sort_{d}" for d in dims]
    return frame.with_columns(helpers).sort(*keys, *helper_names).drop(helper_names)


def _olap_sum(
    frame: pl.DataFrame,
    *,
    keys: Sequence[str],
    dims: Sequence[str],
    value_col: str,
    out_name: str,
) -> pl.DataFrame:
    """``frame`` at the most detailed grain (``keys`` + ``dims``, one row per
    cell with ``value_col``), plus margin rows over every subset of ``dims``
    with the value summed and the dimension set to ``"Tutte"``."""
    base = frame.select(*keys, *dims, pl.col(value_col).alias(out_name))
    frames = [base]
    for subset in _dim_subsets(dims):
        keep = [d for d in dims if d not in subset]
        margins = (
            frame.group_by(*keys, *keep)
            .agg(pl.col(value_col).sum().alias(out_name))
            .with_columns(pl.lit(config.AGG_SENTINEL).alias(d) for d in subset)
            .select(*base.columns)
        )
        frames.append(margins)
    return pl.concat(frames)


def attach_top1_share(
    frame: pl.DataFrame, keys: Sequence[str], dims: Sequence[str]
) -> pl.DataFrame:
    """Add cell-level ``n_top1_obs`` and ``share_top1_pct`` columns to a
    compliance frame (daily or period grain): the number and share of
    observations in each cell whose Gestore is the brand's top-1 operator.

    The two values describe the cell (keys x dims), so they are repeated on
    every row of the cell — including the "top1"/"altri" detail rows and the
    margins — and no row is left with empty trailing columns. ``keys`` are
    the non-dimension key columns (("date", "fuel") for daily frames,
    ("fuel",) for period frames); ``dims`` are the bandiera dimensions.
    Top-1 counts are OLAP-summed so they align with every margin cell,
    including the pooled ``canonical_name="Tutte"`` rows.
    """
    # only detailed-grain rows: the frame already carries margin rows, and
    # _olap_sum rebuilds the margins itself from the detail
    detailed_top1 = frame.filter(
        (pl.col("gestore_top1") == "top1")
        & ~pl.any_horizontal([pl.col(d) == config.AGG_SENTINEL for d in dims])
    )
    top1_counts = _olap_sum(
        detailed_top1,
        keys=keys,
        dims=dims,
        value_col="n_obs",
        out_name="n_top1_obs",
    )
    cell_totals = frame.filter(pl.col("gestore_top1") == config.AGG_SENTINEL).select(
        *keys, *dims, "n_obs"
    )
    cell_stats = (
        cell_totals.join(top1_counts, on=[*keys, *dims], how="left")
        # two separate with_columns: the share must see the zero-filled count
        .with_columns(n_top1_obs=pl.col("n_top1_obs").fill_null(0))
        .with_columns(share_top1_pct=pl.col("n_top1_obs") / pl.col("n_obs") * 100)
        .select(*keys, *dims, "n_top1_obs", "share_top1_pct")
    )
    # left join keeps the frame's existing (sentinel-aware) row order
    return frame.join(cell_stats, on=[*keys, *dims], how="left")


def top1_compliance_report(period_bandiera: pl.DataFrame) -> pl.DataFrame:
    """Wide per-Bandiera comparison of post-cap compliance between stations
    run by the brand's top-1 Gestore and stations run by any other operator.

    Input: a period-grain bandiera compliance frame with the ``gestore_top1``
    split (all Tipo Impianto pooled). Output: one row per fuel x brand with
    observation counts, below-cap counts and shares for both operator
    classes, plus the share difference in percentage points.
    """
    detail = period_bandiera.filter(
        (pl.col("tipo_impianto") == config.AGG_SENTINEL)
        & (pl.col("gestore_top1") != config.AGG_SENTINEL)
        & (pl.col("canonical_name") != config.AGG_SENTINEL)
    )
    top1 = detail.filter(pl.col("gestore_top1") == "top1").select(
        "fuel",
        "canonical_name",
        n_top1_obs=pl.col("n_obs"),
        n_top1_below=pl.col("n_below"),
        pct_below_top1=pl.col("pct_below_pooled"),
    )
    altri = detail.filter(pl.col("gestore_top1") == "altri").select(
        "fuel",
        "canonical_name",
        n_altri_obs=pl.col("n_obs"),
        n_altri_below=pl.col("n_below"),
        pct_below_altri=pl.col("pct_below_pooled"),
    )
    return (
        top1.join(altri, on=["fuel", "canonical_name"], how="full", coalesce=True)
        .with_columns(
            # null when the brand has no station of that operator class
            delta_top1_altri_pp=pl.col("pct_below_top1") - pl.col("pct_below_altri")
        )
        .sort(
            "fuel",
            "delta_top1_altri_pp",
            descending=[False, True],
            nulls_last=True,
        )
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
