"""Configuration constants for the fuel price cap analysis."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
TABLES_DIR = PROJECT_ROOT / "output" / "tables"
FIGURES_DIR = PROJECT_ROOT / "output" / "figures"

DB_NAME = "fuels"

# value used in compliance tables for rows that aggregate over a dimension
AGG_SENTINEL = "Tutte"

# --- Analysis window -------------------------------------------------------
PRICES_FROM = dt.date(2026, 7, 1)
TAX_FROM = dt.date(2026, 5, 1)
CAP_DATE = dt.date(2026, 9, 28)  # self-imposed cap, effective date included
ZOOM_FROM = dt.date(2026, 9, 14)  # pre/post-cap focus window for charts
CAP_WEEK_FROM = dt.date(2026, 9, 21)  # week before the cap (brand comparison)

# --- Compliance rule --------------------------------------------------------
# A station complies when its price is at or below the self-imposed cap:
# pricing exactly at the cap does not violate it. From the cap date (included).
COMPLIANCE_FROM = CAP_DATE
# days before the cap date whose dtComu still counts as 'recent'
COMU_RECENT_DAYS = 2

FUELS: tuple[str, ...] = ("Benzina", "Gasolio")

# --- Price rules -----------------------------------------------------------
VAT_RATE = 0.22  # prezzo = (net + excise) * (1 + VAT)
THRESHOLDS: dict[str, float] = {"Benzina": 2.0, "Gasolio": 2.2}  # gross EUR/l

# Gasolio cap tracks the excise calendar: D.L. 162/2026 removed the remaining
# 5 c/l discount on 2026-10-06 (622.90 -> 672.90 EUR/1000 l), so the cap rises
# by 5 * 1.22 = 6.1 c/l incl. VAT (2.200 -> 2.261). Benzina is unaffected.
GASOLIO_EXCISE_STEP = dt.date(2026, 10, 6)
GASOLIO_CAP_AFTER = 2.261  # gross EUR/l from GASOLIO_EXCISE_STEP (included)


def cap_threshold(fuel: str, day: dt.date) -> float:
    """Gross EUR/l cap for `fuel` effective on `day` (excise-aware)."""
    if fuel == "Gasolio" and day >= GASOLIO_EXCISE_STEP:
        return GASOLIO_CAP_AFTER
    return THRESHOLDS[fuel]


def threshold_expr(date_col: str = "date") -> pl.Expr:
    """Polars expression: per-row cap threshold keyed on fuel and date."""
    thr = pl.col("fuel").replace_strict(THRESHOLDS, return_dtype=pl.Float64)
    return (
        pl.when((pl.col("fuel") == "Gasolio") & (pl.col(date_col) >= GASOLIO_EXCISE_STEP))
        .then(pl.lit(GASOLIO_CAP_AFTER))
        .otherwise(thr)
    )


# --- Outlier rule: one pass, per (date x fuel) cell -------------------------
SD_CUTOFF = 4.0
MIN_CELL_SIZE = 2  # ddof=1 std needs >= 2 observations

# --- Brand groups ----------------------------------------------------------
GROUP_MAJORS = "Majors"
GROUP_LARGE = "Large"
GROUP_WHITE = "Pompe Bianche"
GROUP_ORDER: tuple[str, ...] = (GROUP_MAJORS, GROUP_LARGE, GROUP_WHITE)
GROUPED_BRANDS = (GROUP_MAJORS, GROUP_LARGE)
AGGREGATE_LABEL = "Italia (tutte)"

# normalized bandiera -> (canonical display name, group)
BRAND_GROUPS: dict[str, tuple[str, str]] = {
    "agip eni": ("Agip Eni", GROUP_MAJORS),
    "api ip": ("Api-Ip", GROUP_MAJORS),
    "q8": ("Q8", GROUP_MAJORS),
    "esso": ("Esso", GROUP_LARGE),
    "tamoil": ("Tamoil", GROUP_LARGE),
    "shell": ("Shell", GROUP_LARGE),
}

# --- Tipo impianto ---------------------------------------------------------
TIPO_STRADALE = "Stradale"
TIPO_AUTOSTRADALE = "Autostradale"
TIPO_MAIN: tuple[str, ...] = (TIPO_STRADALE, TIPO_AUTOSTRADALE)

# --- Deliverable paths -----------------------------------------------------
PRICES_RAW_PATH = DATA_DIR / "prices_raw.parquet"
PRICES_CLEAN_PATH = DATA_DIR / "prices_clean.parquet"
PRICES_ENRICHED_PATH = DATA_DIR / "prices_enriched.parquet"
STATIONS_PATH = DATA_DIR / "stations.parquet"
TAX_PATH = DATA_DIR / "tax.parquet"
PROVINCE_REGION_PATH = DATA_DIR / "province_region.csv"
BRAND_GROUPS_PATH = DATA_DIR / "brand_groups.csv"

TABLES = {
    "outliers": TABLES_DIR / "outliers_removed.csv",
    "bandiera_audit": TABLES_DIR / "bandiera_values_audit.csv",
    "station_group": TABLES_DIR / "station_counts_by_group_tipo.csv",
    "station_bandiera": TABLES_DIR / "station_counts_by_bandiera_tipo.csv",
    "weekly_counts": TABLES_DIR / "weekly_station_counts.csv",
    "concentration": TABLES_DIR / "brand_concentration.csv",
    "compliance_daily": TABLES_DIR / "cap_compliance_daily.csv",
    "compliance_period": TABLES_DIR / "cap_compliance_period.csv",
    "compliance_daily_bandiera": TABLES_DIR / "cap_compliance_daily_bandiera.csv",
    "compliance_period_bandiera": TABLES_DIR / "cap_compliance_period_bandiera.csv",
    "compliance_top1": TABLES_DIR / "cap_compliance_top1_gestore.csv",
    "compliance_daily_region": TABLES_DIR / "cap_compliance_daily_region.csv",
    "compliance_period_region": TABLES_DIR / "cap_compliance_period_region.csv",
    "net_stats_group": TABLES_DIR / "net_price_stats_by_group.csv",
    "net_stats_region": TABLES_DIR / "net_price_stats_by_region.csv",
    "dtcomu_capday": TABLES_DIR / "dtcomu_capday_agip_eni.csv",
    "dtcomu_capday_bandiera": TABLES_DIR / "dtcomu_capday_bandiera.csv",
    "dtcomu_capday_detail": TABLES_DIR / "dtcomu_capday_agip_eni_detail.csv",
    "dtcomu_capday_summary": TABLES_DIR / "dtcomu_capday_agip_eni_by_comu_day.csv",
    "compliance_region_capday": TABLES_DIR / "cap_compliance_capday_region.csv",
    "postcap_daily": TABLES_DIR / "postcap_daily_compliance_by_brand.csv",
    "dtcomu_day2": TABLES_DIR / "dtcomu_latest_day_by_comu_day.csv",
    "reference_day": TABLES_DIR / "reference_day_cutoff_benzina_gasolio.csv",
    "brand_prices_daily": TABLES_DIR / "brand_daily_prices.csv",
    "brand_prices_break": TABLES_DIR / "brand_price_break.csv",
}
