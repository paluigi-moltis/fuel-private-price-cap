"""End-to-end pipeline orchestrator for the fuel price cap analysis."""

from __future__ import annotations

import argparse
import os
import warnings

import polars as pl
from dotenv import load_dotenv

from fuel_price_cap import config
from fuel_price_cap.analysis import CapCompliance, DailyPriceStats, StationStats
from fuel_price_cap.data import FuelDataRepository, PriceCleaner
from fuel_price_cap.enrich import (
    BrandGrouper,
    NetPriceCalculator,
    RegionMapper,
    StationTimeline,
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
        self._compliance_tables(enriched)
        self._national_charts(enriched)
        self._regional_outputs(enriched)
        self._validation(prices_raw, prices_clean, outlier_audit, enriched, enrich_meta)

        print(
            f"\nDone. Tables in {config.TABLES_DIR}, figures in {config.FIGURES_DIR}."
        )

    # ------------------------------------------------------------------ #
    # Stage 1: raw data
    # ------------------------------------------------------------------ #
    def _load_raw(self) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
        _banner("Stage 1/8 — raw data (MongoDB -> parquet)")
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
        _banner("Stage 2/8 — reference tables")
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
        _banner("Stage 3/8 — outlier filter (|prezzo - mean| > 4 sd per date x fuel)")
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
        _banner("Stage 4/8 — enrichment (as-of join, region, group, net price)")

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

        stations_enriched = mapper.assign(grouper.assign(stations))
        meta = {**asof_meta, "unmatched_sigle": float(unmatched_sigle)}
        return enriched, stations_enriched, meta

    # ------------------------------------------------------------------ #
    # Stage 5: station tables
    # ------------------------------------------------------------------ #
    @staticmethod
    def _station_tables(stations_enriched: pl.DataFrame) -> None:
        _banner("Stage 5/8 — station counts and Gestore concentration")
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
    def _compliance_tables(enriched: pl.DataFrame) -> None:
        _banner("Stage 6/8 — cap compliance (from 2026-09-28, clean prices)")
        compliance = CapCompliance(enriched)
        daily = compliance.daily(("group", "tipo_impianto"))
        daily.write_csv(config.TABLES["compliance_daily"])
        period = compliance.period(("group", "tipo_impianto"))
        period.write_csv(config.TABLES["compliance_period"])

        enriched_with_region = enriched.filter(pl.col("regione").is_not_null())
        compliance_region = CapCompliance(enriched_with_region)
        daily_region = compliance_region.daily(("regione", "group", "tipo_impianto"))
        daily_region.write_csv(config.TABLES["compliance_daily_region"])
        period_region = compliance_region.period(("regione", "group", "tipo_impianto"))
        period_region.write_csv(config.TABLES["compliance_period_region"])

        post_cap_days = daily["date"].unique().sort().to_list()
        print(f"Post-cap days: {daily['date'].n_unique()} ({post_cap_days})")
        summary = (
            period.group_by("fuel", "group")
            .agg(n_obs=pl.col("n_obs").sum(), n_below=pl.col("n_below").sum())
            .with_columns(pct_below=pl.col("n_below") / pl.col("n_obs") * 100)
            .sort("fuel", "group")
        )
        print(f"Period summary by fuel x group (all Tipo Impianto):\n{summary}")

    # ------------------------------------------------------------------ #
    # Stage 7: national charts + net stats
    # ------------------------------------------------------------------ #
    @staticmethod
    def _national_charts(enriched: pl.DataFrame) -> None:
        _banner("Stage 7/8 — daily price stats and charts (fuel x Tipo Impianto)")
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
        print(f"Written {n_charts} national charts (PNG + HTML) per group")
        print("Net price stats by group (pre = before cap, post = from cap date):")
        print(net_stats)

    # ------------------------------------------------------------------ #
    # Stage 8: regional extension
    # ------------------------------------------------------------------ #
    @staticmethod
    def _regional_outputs(enriched: pl.DataFrame) -> None:
        _banner("Stage 8/8 — regional extension")
        regional_prices = enriched.filter(pl.col("regione").is_not_null())
        by_region = DailyPriceStats.daily(regional_prices, ("regione",))
        net_stats_region = DailyPriceStats.net_summary(
            regional_prices, ("group", "regione", "tipo_impianto")
        )
        net_stats_region.write_csv(config.TABLES["net_stats_region"])

        builder = PriceChartBuilder(config.FIGURES_DIR)
        n_charts = 0
        for fuel in config.FUELS:
            region_slice = by_region.filter(pl.col("fuel") == fuel).sort("date")
            for value_col in ("prezzo", "net_price"):
                builder.regional_price_chart(
                    region_slice, fuel=fuel, value_col=value_col
                )
                n_charts += 1
        regions = by_region["regione"].n_unique()
        print(
            f"Written {n_charts} regional facet charts ({regions} regions) and "
            f"{config.TABLES['net_stats_region'].name} "
            f"({net_stats_region.height:,} rows)"
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
