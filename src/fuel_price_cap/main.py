"""End-to-end pipeline orchestrator for the fuel price cap analysis."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import warnings

import polars as pl
from dotenv import load_dotenv

from fuel_price_cap import config
from fuel_price_cap.analysis import (
    CapCompliance,
    DailyPriceStats,
    StationStats,
    attach_top1_share,
    top1_compliance_report,
)
from fuel_price_cap.comu import (
    BrandPriceBreak,
    ComuFreshness,
    parse_dt_comu,
)
from fuel_price_cap.data import FuelDataRepository, PriceCleaner
from fuel_price_cap.enrich import (
    BrandGrouper,
    NetPriceCalculator,
    RegionMapper,
    StationTimeline,
    brand_view,
)
from fuel_price_cap.plots import PriceChartBuilder


class Pipeline:
    """Runs every analysis stage in order and writes all deliverables."""

    def __init__(self, use_cache: bool = False) -> None:
        self.use_cache = use_cache

    def run(self) -> None:
        for directory in (config.DATA_DIR, config.TABLES_DIR, config.FIGURES_DIR):
            directory.mkdir(parents=True, exist_ok=True)

        prices_raw, stations, tax = self._load_raw()
        self._write_reference_tables()

        prices_clean, outlier_audit = self._clean(prices_raw)
        enriched, stations_enriched, enrich_meta = self._enrich(
            prices_clean, stations, tax
        )

        self._station_tables(stations_enriched)
        self._compliance_tables(enriched, stations_enriched)
        self._national_charts(enriched)
        self._regional_outputs(enriched)
        self._comu_and_brand_outputs(enriched)
        self._validation(prices_raw, prices_clean, outlier_audit, enriched, enrich_meta)

        print(
            f"\nDone. Tables in {config.TABLES_DIR}, figures in {config.FIGURES_DIR}."
        )

    # ------------------------------------------------------------------ #
    # Stage 1: raw data
    # ------------------------------------------------------------------ #
    def _load_raw(self) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
        _banner("Stage 1/9 — raw data (MongoDB -> parquet)")
        if self.use_cache:
            paths = (
                config.PRICES_RAW_PATH,
                config.STATIONS_PATH,
                config.TAX_PATH,
            )
            missing = [p for p in paths if not p.exists()]
            if missing:
                msg = (
                    "--cache given but parquet file(s) missing: "
                    f"{[str(p) for p in missing]}. Run once without --cache."
                )
                raise SystemExit(msg)
            print("Loading cached parquet files from data/ ...")
            frames = (
                pl.read_parquet(config.PRICES_RAW_PATH),
                pl.read_parquet(config.STATIONS_PATH),
                pl.read_parquet(config.TAX_PATH),
            )
        else:
            print("Downloading prices, stations and tax from MongoDB ...")
            frames_data = FuelDataRepository().fetch_all()
            frames = (
                frames_data["prices"],
                frames_data["stations"],
                frames_data["tax"],
            )
            frames[0].write_parquet(config.PRICES_RAW_PATH)
            frames[1].write_parquet(config.STATIONS_PATH)
            frames[2].write_parquet(config.TAX_PATH)
            print(f"Saved {config.PRICES_RAW_PATH.name}, stations.parquet, tax.parquet")

        prices, stations, tax = frames
        fuels = prices["fuel"].unique().sort().to_list()
        print(
            f"prices: {prices.height:,} rows | {prices['date'].min()} → "
            f"{prices['date'].max()} | fuels: {fuels}"
        )
        print(
            f"stations: {stations.height:,} snapshot rows | "
            f"{stations['id_impianto'].n_unique():,} distinct stations | "
            f"{stations['date'].n_unique()} weekly snapshots "
            f"({stations['date'].min()} → {stations['date'].max()})"
        )
        first_tax = tax["application_date"].min()
        print(f"tax: {tax.height} excise change dates from {first_tax}")
        return prices, stations, tax

    @staticmethod
    def _write_reference_tables() -> None:
        _banner("Stage 2/9 — reference tables")
        RegionMapper.write_reference_csv(str(config.PROVINCE_REGION_PATH))
        BrandGrouper.write_reference_csv(str(config.BRAND_GROUPS_PATH))
        print(
            f"Written {config.PROVINCE_REGION_PATH.name} (107 sigle) and "
            f"{config.BRAND_GROUPS_PATH.name} (6 mapped brands)"
        )

    # ------------------------------------------------------------------ #
    # Stage 3: cleaning
    # ------------------------------------------------------------------ #
    @staticmethod
    def _clean(prices_raw: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
        _banner("Stage 3/9 — outlier filter (|prezzo - mean| > 4 sd per date x fuel)")
        clean, audit = PriceCleaner().clean(prices_raw)
        clean.write_parquet(config.PRICES_CLEAN_PATH)
        audit.write_csv(config.TABLES["outliers"])
        removed = audit["n_removed"].sum()
        share = removed / prices_raw.height * 100
        print(
            f"{prices_raw.height:,} raw -> {clean.height:,} clean "
            f"({removed:,} removed, {share:.3f}%) -> {config.PRICES_CLEAN_PATH.name}"
        )
        if audit.height:
            print(
                "Worst day/fuel cells:\n"
                f"{audit.sort('share_removed_pct', descending=True).head(5)}"
            )
        return clean, audit

    # ------------------------------------------------------------------ #
    # Stage 4: enrichment
    # ------------------------------------------------------------------ #
    @staticmethod
    def _enrich(
        prices_clean: pl.DataFrame, stations: pl.DataFrame, tax: pl.DataFrame
    ) -> tuple[pl.DataFrame, pl.DataFrame, dict[str, float]]:
        _banner("Stage 4/9 — enrichment (as-of join, region, group, net price)")

        attributed, asof_meta = StationTimeline().attribute(prices_clean, stations)
        print(
            f"as-of join: {asof_meta['fallback_rows']:,.0f} rows "
            f"({asof_meta['fallback_share_pct']:.2f}%) backfilled with the earliest "
            f"snapshot; dropped {asof_meta['dropped_rows']:,.0f} rows "
            f"({asof_meta['dropped_share_pct']:.2f}%) without a station "
            f"({asof_meta['no_station_rows']:,.0f}) or without Tipo Impianto "
            f"({asof_meta['missing_tipo_rows']:,.0f})"
        )

        grouper = BrandGrouper()
        enriched = grouper.assign(attributed)

        mapper = RegionMapper()
        enriched = mapper.assign(enriched)
        unmatched_sigle = enriched.filter(
            pl.col("regione").is_null() & pl.col("provincia").is_not_null()
        ).height

        enriched, net_meta = NetPriceCalculator().enrich(enriched, tax)
        enriched.write_parquet(config.PRICES_ENRICHED_PATH)
        print(
            f"province join: {unmatched_sigle} unmatched rows (expected 0); "
            f"tax calendar: {net_meta['null_excise_rows']} rows without excise, "
            f"{net_meta['null_net_price_rows']} without net price"
        )

        audit = grouper.audit(stations)
        audit.write_csv(config.TABLES["bandiera_audit"])
        grouped_stations = audit.filter(pl.col("group").is_in(config.GROUPED_BRANDS))[
            "bandiera"
        ].n_unique()
        print(
            f"bandiera audit: {audit.height} distinct raw values "
            f"({grouped_stations} matched to the 6 grouped brands) -> "
            f"{config.TABLES['bandiera_audit'].name}"
        )

        # seven-brand view for every station-level table downstream: the raw
        # Bandiera detail is preserved in bandiera_values_audit.csv only
        stations_enriched = brand_view(mapper.assign(grouper.assign(stations)))
        meta = {**asof_meta, "unmatched_sigle": float(unmatched_sigle)}
        return enriched, stations_enriched, meta

    # ------------------------------------------------------------------ #
    # Stage 5: station tables
    # ------------------------------------------------------------------ #
    @staticmethod
    def _station_tables(stations_enriched: pl.DataFrame) -> None:
        _banner("Stage 5/9 — station counts and Gestore concentration")
        stats = StationStats(stations_enriched)
        print(f"Latest snapshot used for counts: {stats.latest_date}")

        by_group = stats.counts_by_group_tipo()
        by_group.write_csv(config.TABLES["station_group"])
        by_bandiera = stats.counts_by_bandiera_tipo()
        by_bandiera.write_csv(config.TABLES["station_bandiera"])
        weekly = stats.weekly_counts()
        weekly.write_csv(config.TABLES["weekly_counts"])
        concentration = stats.concentration()
        concentration.write_csv(config.TABLES["concentration"])

        totals = (
            by_group.group_by("group").agg(n=pl.col("n_stations").sum()).sort("group")
        )
        print(f"Stations by group (latest snapshot, all Tipo Impianto):\n{totals}")
        concentration_overall = concentration.filter(
            pl.col("tipo_impianto_slice") == "Tutti"
        )
        print(f"\nGestore concentration (six grouped brands):\n{concentration_overall}")

    # ------------------------------------------------------------------ #
    # Stage 6: cap compliance
    # ------------------------------------------------------------------ #
    @staticmethod
    def _compliance_tables(
        enriched: pl.DataFrame, stations_enriched: pl.DataFrame
    ) -> None:
        _banner("Stage 6/9 — cap compliance (from 2026-09-28, clean prices)")
        # seven-brand view everywhere in this stage (six named brands plus
        # all remaining independents as a single "Pompe Bianche" brand)
        comp_prices = brand_view(enriched)
        top1_gestori = StationStats(stations_enriched).top1_gestori()

        compliance = CapCompliance(comp_prices)
        daily = compliance.daily_with_aggregates(("group", "tipo_impianto"))
        daily.write_csv(config.TABLES["compliance_daily"])
        period = compliance.period(("group", "tipo_impianto"))
        period.write_csv(config.TABLES["compliance_period"])

        _print_compliance_summary(daily, period)

        compliance_bandiera = CapCompliance(comp_prices, top1_gestori=top1_gestori)
        dims_bandiera = ("canonical_name", "tipo_impianto", "gestore_top1")
        daily_bandiera = compliance_bandiera.daily_with_aggregates(dims_bandiera)
        daily_bandiera = attach_top1_share(
            daily_bandiera, keys=("date", "fuel"), dims=dims_bandiera[:2]
        )
        daily_bandiera.write_csv(config.TABLES["compliance_daily_bandiera"])
        period_bandiera = compliance_bandiera.period(dims_bandiera)
        period_bandiera = attach_top1_share(
            period_bandiera, keys=("fuel",), dims=dims_bandiera[:2]
        )
        period_bandiera.write_csv(config.TABLES["compliance_period_bandiera"])

        top1_report = top1_compliance_report(period_bandiera)
        top1_report.write_csv(config.TABLES["compliance_top1"])
        print(
            f"Top-1 Gestore compliance report: {top1_report.height} fuel x brand "
            f"rows -> {config.TABLES['compliance_top1'].name}"
        )
        _print_top1_hypothesis(top1_report)
        _check_aggregate_rows(daily, comp_prices)

        enriched_with_region = comp_prices.filter(pl.col("regione").is_not_null())
        compliance_region = CapCompliance(enriched_with_region)
        daily_region = compliance_region.daily_with_aggregates(
            ("regione", "group", "tipo_impianto")
        )
        daily_region.write_csv(config.TABLES["compliance_daily_region"])
        period_region = compliance_region.period(("regione", "group", "tipo_impianto"))
        period_region.write_csv(config.TABLES["compliance_period_region"])

        daily_plot = CapCompliance(
            brand_view(enriched, name="plot_bandiera"), from_date=None
        ).daily(("plot_bandiera",))
        builder = PriceChartBuilder(config.FIGURES_DIR)
        n_charts = 0
        for fuel in config.FUELS:
            fuel_slice = daily_plot.filter(pl.col("fuel") == fuel)
            for zoom in (False, True):
                builder.compliance_share_chart(fuel_slice, fuel=fuel, zoom=zoom)
                n_charts += 1
        print(
            f"Written {n_charts} compliance-share charts by Bandiera "
            "(full window + zoom)"
        )

    # ------------------------------------------------------------------ #
    # Stage 7: national charts + net stats
    # ------------------------------------------------------------------ #
    @staticmethod
    def _national_charts(enriched: pl.DataFrame) -> None:
        _banner("Stage 7/9 — daily price stats and charts (fuel x Tipo Impianto)")
        by_group = DailyPriceStats.daily(enriched, ("tipo_impianto", "group"))
        overall = DailyPriceStats.daily(enriched, ("tipo_impianto",))
        net_stats = DailyPriceStats.net_summary(enriched, ("group",))
        net_stats.write_csv(config.TABLES["net_stats_group"])

        builder = PriceChartBuilder(config.FIGURES_DIR)
        n_charts = 0
        for fuel in config.FUELS:
            for tipo in config.TIPO_MAIN:
                group_slice = by_group.filter(
                    (pl.col("fuel") == fuel) & (pl.col("tipo_impianto") == tipo)
                ).sort("date")
                overall_slice = overall.filter(
                    (pl.col("fuel") == fuel) & (pl.col("tipo_impianto") == tipo)
                ).sort("date")
                for value_col in ("prezzo", "net_price"):
                    for zoom in (False, True):
                        builder.group_price_chart(
                            group_slice,
                            overall_slice,
                            fuel=fuel,
                            tipo=tipo,
                            value_col=value_col,
                            zoom=zoom,
                        )
                        n_charts += 1
        print(f"Written {n_charts} national charts per group (PNG)")
        print("Net price stats by group (pre = before cap, post = from cap date):")
        print(net_stats)

    # ------------------------------------------------------------------ #
    # Stage 8: regional extension
    # ------------------------------------------------------------------ #
    @staticmethod
    def _regional_outputs(enriched: pl.DataFrame) -> None:
        _banner("Stage 8/9 — regional extension (post-cap compliance by region)")
        regional_prices = brand_view(enriched.filter(pl.col("regione").is_not_null()))
        post_cap = regional_prices.filter(pl.col("date") >= config.CAP_DATE)
        by_region = (
            post_cap.group_by("regione", "fuel", "tipo_impianto")
            .agg(
                n_obs=pl.len(),
                n_at_or_below=(
                    pl.col("prezzo")
                    <= pl.col("fuel").replace_strict(
                        config.THRESHOLDS, return_dtype=pl.Float64
                    )
                ).sum(),
            )
            .with_columns(
                pct_at_or_below=pl.col("n_at_or_below") / pl.col("n_obs") * 100
            )
            .sort("fuel", "tipo_impianto", "pct_at_or_below")
        )
        by_region.write_csv(config.TABLES["compliance_region_capday"])

        builder = PriceChartBuilder(config.FIGURES_DIR)
        n_charts = 0
        for fuel in config.FUELS:
            for tipo in config.TIPO_MAIN:
                builder.regional_compliance_chart(
                    by_region.filter(
                        (pl.col("fuel") == fuel) & (pl.col("tipo_impianto") == tipo)
                    ),
                    fuel=fuel,
                    tipo=tipo,
                )
                n_charts += 1
        print(
            f"Written {n_charts} ranked regional compliance bars and "
            f"{config.TABLES['compliance_region_capday'].name} "
            f"({by_region.height} rows)"
        )

    # ------------------------------------------------------------------ #
    # Stage 9: dtComu freshness + brand price break
    # ------------------------------------------------------------------ #
    @staticmethod
    def _comu_and_brand_outputs(enriched: pl.DataFrame) -> None:
        _banner("Stage 9/9 — dtComu freshness and brand price break")
        prices = parse_dt_comu(brand_view(enriched))
        unparsed = prices.filter(
            pl.col("dt_comu").is_not_null() & pl.col("comu_date").is_null()
        ).height
        if unparsed:
            print(f"WARNING: {unparsed} rows with unparsable dt_comu")

        fresh = ComuFreshness(prices)
        by_brand = fresh.by_brand()
        by_brand.write_csv(config.TABLES["dtcomu_capday_bandiera"])
        crosstab = fresh.agip_eni_crosstab()
        crosstab.write_csv(config.TABLES["dtcomu_capday"])
        detail = fresh.agip_eni_capday_detail()
        detail.write_csv(config.TABLES["dtcomu_capday_detail"])
        summary = fresh.agip_eni_capday_summary()
        summary.write_csv(config.TABLES["dtcomu_capday_summary"])
        agip = by_brand.filter(pl.col("canonical_name") == "Agip Eni")
        print("Agip Eni on cap day (compliance = at or below the cap):")
        print(
            agip.select(
                "fuel",
                "n_obs",
                "n_compliant",
                "n_comu_capday",
                "n_comu_recent",
                "n_comu_older",
            )
        )
        print("Agip Eni cap day, by communication day (cap day vs earlier):")
        print(summary)
        n_detail = detail.height
        print(
            f"Station-level detail: {n_detail:,} rows -> "
            f"{config.TABLES['dtcomu_capday_detail'].name}"
        )

        post_cap = prices.filter(pl.col("date") >= config.CAP_DATE)
        n_post_days = post_cap["date"].n_unique()
        if n_post_days > 1:
            latest = post_cap["date"].max()
            latest_rows = post_cap.filter(pl.col("date") == latest)
            thr = pl.col("fuel").replace_strict(
                config.THRESHOLDS, return_dtype=pl.Float64
            )
            latest_flags = latest_rows.with_columns(
                compliant=pl.col("prezzo") <= thr,
                comu_28=pl.col("comu_date") == config.CAP_DATE,
                comu_same=pl.col("comu_date") == latest,
            )
            compliance_by_day = (
                post_cap.with_columns(compliant=pl.col("prezzo") <= thr)
                .group_by("date", "fuel", "canonical_name")
                .agg(
                    n_obs=pl.len(),
                    n_compliant=pl.col("compliant").sum(),
                )
                .with_columns(pct=pl.col("n_compliant") / pl.col("n_obs") * 100)
                .sort("date", "fuel", "canonical_name")
            )
            compliance_by_day.write_csv(config.TABLES["postcap_daily"])
            print(
                f"Post-cap daily compliance by brand -> "
                f"{config.TABLES['postcap_daily'].name}"
            )
            print(
                compliance_by_day.filter(
                    (pl.col("canonical_name") == "Agip Eni")
                    & (pl.col("date") == latest)
                )
            )
            by_comu_day = (
                latest_flags.group_by("fuel", "comu_28")
                .agg(
                    n_obs=pl.len(),
                    n_compliant=pl.col("compliant").sum(),
                    n_comu_same=pl.col("comu_same").sum(),
                )
                .with_columns(pct=pl.col("n_compliant") / pl.col("n_obs") * 100)
                .sort("fuel", "comu_28")
            )
            by_comu_day.write_csv(config.TABLES["dtcomu_day2"])
            print(
                f"Latest post-cap day by communication day -> "
                f"{config.TABLES['dtcomu_day2'].name}"
            )
            print(by_comu_day)

            # Reference-day cutoff analysis (ISTAT 1/11/21 inflation days).
            # The daily extract snapshot predates that day's morning price
            # communications: rows dated Oct 1 never carry dtComu = Oct 1.
            # Counterfactual: replace each station's recorded price with its
            # post-cutoff communication (dtComu = reference day, first
            # visible in the next day's data).
            ref_day = dt.date(2026, 10, 1)
            ref_next = dt.date(2026, 10, 2)
            stradale = prices.filter(pl.col("tipo_impianto") == config.TIPO_STRADALE)
            ref_rows = []
            for fuel in config.FUELS:
                d_ref = stradale.filter(pl.col("date") == ref_day).filter(fuel=fuel)
                d_next = stradale.filter(pl.col("date") == ref_next).filter(fuel=fuel)
                ref_prev = ref_day - dt.timedelta(days=1)
                d_prev = stradale.filter(pl.col("date") == ref_prev).filter(fuel=fuel)
                late = d_next.filter(pl.col("comu_date") == ref_day).select(
                    "id_impianto", pl.col("prezzo").alias("p_new")
                )
                prev = d_ref.select("id_impianto", pl.col("prezzo").alias("p_prev"))
                prev0 = (
                    d_prev.select("id_impianto", pl.col("prezzo").alias("p_prev0"))
                    .join(late, on="id_impianto", how="semi")
                    .join(prev, on="id_impianto", how="anti")
                )
                late = (
                    late.join(prev, on="id_impianto", how="left")
                    .join(prev0, on="id_impianto", how="left")
                    .with_columns(
                        p_old=pl.coalesce("p_prev", "p_prev0"),
                        in_ref_data=pl.col("p_prev").is_not_null(),
                    )
                )
                changed = late.filter(pl.col("p_new") != pl.col("p_old"))
                hyp = d_ref.join(
                    late.select("id_impianto", "p_new"), on="id_impianto", how="left"
                ).with_columns(p=pl.coalesce("p_new", "prezzo"))
                ref_rows.append(
                    {
                        "fuel": fuel,
                        "n_ref_rows": d_ref.height,
                        "mean_recorded": d_ref["prezzo"].mean(),
                        "n_comu_ref_day": late.height,
                        "n_comu_ref_day_in_data": late.filter("in_ref_data").height,
                        "n_comu_absent": late.filter(~pl.col("in_ref_data")).height,
                        "n_changed_price": changed.height,
                        "mean_hypothetical": hyp["p"].mean(),
                        "delta_eur_l": hyp["p"].mean() - d_ref["prezzo"].mean(),
                        "mean_old_price_changers": changed["p_old"].mean(),
                        "mean_new_price_changers": changed["p_new"].mean(),
                    }
                )
            ref_table = pl.DataFrame(ref_rows)
            ref_table.write_csv(config.TABLES["reference_day"])
            print(
                f"Reference-day cutoff analysis ({ref_day}) -> "
                f"{config.TABLES['reference_day'].name}"
            )
            print(ref_table)

        brands = (
            "Agip Eni",
            "Api-Ip",
            "Q8",
            "Esso",
            "Tamoil",
            "Shell",
            config.GROUP_WHITE,
        )
        brk = BrandPriceBreak(prices, pre_days=7, brands=brands)
        daily = brk.daily()
        daily.write_csv(config.TABLES["brand_prices_daily"])
        break_table = brk.break_table()
        break_table.write_csv(config.TABLES["brand_prices_break"])

        builder = PriceChartBuilder(config.FIGURES_DIR)
        n_charts = 0
        for fuel in config.FUELS:
            fuel_slice = daily.filter(pl.col("fuel") == fuel)
            for zoom in (False, True):
                builder.brand_price_chart(fuel_slice, fuel=fuel, zoom=zoom)
                n_charts += 1
        print(f"Break table (pre = {config.CAP_WEEK_FROM}..cap-1 mean, cap day):")
        print(
            break_table.select(
                "fuel",
                "canonical_name",
                "mean_price_pre",
                "mean_price_capday",
                "jump_eur",
                "jump_bp",
                "distance_to_cap_eur",
            )
        )
        print(
            f"Written {n_charts} brand price charts, "
            f"{config.TABLES['brand_prices_daily'].name} and "
            f"{config.TABLES['brand_prices_break'].name}"
        )

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    @staticmethod
    def _validation(
        prices_raw: pl.DataFrame,
        prices_clean: pl.DataFrame,
        outlier_audit: pl.DataFrame,
        enriched: pl.DataFrame,
        meta: dict[str, float],
    ) -> None:
        _banner("Validation checklist")
        expected_drop = prices_raw.height - prices_clean.height
        audit_sum = outlier_audit["n_removed"].sum()
        print(
            f"[{'OK' if expected_drop == audit_sum else 'FAIL'}] outlier audit sums "
            f"match: raw - clean = {expected_drop:,}, audit sum = {audit_sum:,} "
            f"({audit_sum / prices_raw.height * 100:.3f}% of raw)"
        )
        attributed_share = 100 - meta["dropped_share_pct"]
        print(
            f"[{'OK' if attributed_share > 99.5 else 'WARN'}] as-of attribution: "
            f"{attributed_share:.3f}% of clean prices kept, all with station "
            f"attributes and Tipo Impianto ({meta['dropped_rows']:,.0f} rows dropped; "
            f"fallback share {meta['fallback_share_pct']:.2f}%)"
        )
        print(
            f"[{'OK' if meta['unmatched_sigle'] == 0 else 'FAIL'}] province join: "
            f"{meta['unmatched_sigle']:.0f} unmatched rows"
        )
        null_net = enriched.filter(pl.col("net_price").is_null()).height
        net_flag = "OK" if null_net == 0 else "FAIL"
        print(f"[{net_flag}] net price defined on all rows: {null_net} nulls")
        max_prezzo = enriched["prezzo"].max()
        min_prezzo = enriched["prezzo"].min()
        print(
            f"[{'OK' if min_prezzo > 1.0 and max_prezzo < 3.0 else 'WARN'}] sanity "
            f"prezzo in (1, 3) EUR/l: min = {min_prezzo:.3f}, max = {max_prezzo:.3f}"
        )
        net_above = enriched.filter(pl.col("net_price") >= pl.col("prezzo")).height
        gross_flag = "OK" if net_above == 0 else "FAIL"
        print(f"[{gross_flag}] net < gross price on all rows: {net_above} violations")
        group_totals = (
            enriched.filter(pl.col("date") == enriched["date"].max())
            .group_by("group")
            .agg(n=pl.col("id_impianto").n_unique())
        )
        print("Distinct stations by group on the last price day:")
        print(group_totals.sort("group"))


def _banner(title: str) -> None:
    print(f"\n{'=' * 74}\n{title}\n{'=' * 74}", flush=True)


def _print_compliance_summary(daily: pl.DataFrame, period: pl.DataFrame) -> None:
    post_cap_days = daily["date"].unique().sort().to_list()
    print(f"Post-cap days: {daily['date'].n_unique()} ({post_cap_days})")
    detail = period.filter(
        (pl.col("group") != config.AGG_SENTINEL)
        & (pl.col("tipo_impianto") != config.AGG_SENTINEL)
    )
    summary = (
        detail.group_by("fuel", "group")
        .agg(n_obs=pl.col("n_obs").sum(), n_below=pl.col("n_below").sum())
        .with_columns(pct_below=pl.col("n_below") / pl.col("n_obs") * 100)
        .sort("fuel", "group")
    )
    print(f"Period summary by fuel x group (all Tipo Impianto):\n{summary}")


def _print_top1_hypothesis(top1_report: pl.DataFrame) -> None:
    """Lag hypothesis at a glance: post-cap compliance of stations run by the
    brand's top-1 Gestore vs any other operator (seven-brand view)."""
    print("Top-1 Gestore vs other operators (post-cap pooled, all Tipo Impianto):")
    print(top1_report)


def _check_aggregate_rows(daily: pl.DataFrame, enriched: pl.DataFrame) -> None:
    """Integrity check: a 'Tutte' margin row must equal the pooled detail.

    Both sides are compared per single day: the 'Tutte' margin row of a
    (date, fuel, tipo) cell pools over the remaining dimensions only, so
    the direct count must be taken for that same day — summing over all
    post-cap days would double-count once more than one day exists.
    """
    margin = daily.filter(
        (pl.col("group") == config.AGG_SENTINEL)
        & (pl.col("tipo_impianto") == config.TIPO_STRADALE)
        & (pl.col("fuel") == config.FUELS[0])
        & (pl.col("date") == config.CAP_DATE)
    )
    direct = enriched.filter(
        (pl.col("date") == config.CAP_DATE)
        & (pl.col("tipo_impianto") == config.TIPO_STRADALE)
        & (pl.col("fuel") == config.FUELS[0])
    ).height
    margin_n = margin["n_obs"][0] if margin.height else None
    ok = margin_n == direct
    print(
        f"[{'OK' if ok else 'FAIL'}] aggregate rows: 'Tutte' margin n_obs == "
        f"pooled detail ({margin_n} vs {direct})"
    )


def main() -> None:
    # both as-of join inputs are explicitly sorted by date beforehand
    warnings.filterwarnings(
        "ignore",
        message="Sortedness of columns cannot be checked",
        category=UserWarning,
    )
    parser = argparse.ArgumentParser(
        description="Fuel price cap analysis pipeline (cap effective 2026-09-28)."
    )
    parser.add_argument(
        "--cache",
        action="store_true",
        help="reuse parquet files in data/ instead of downloading from MongoDB",
    )
    args = parser.parse_args()

    load_dotenv()
    if not args.cache and not os.environ.get("MONGO_URI"):
        raise SystemExit("MONGO_URI is not set: configure it in .env")

    Pipeline(use_cache=args.cache).run()


if __name__ == "__main__":
    main()
