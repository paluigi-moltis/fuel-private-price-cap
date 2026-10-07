"""Configuration and shared paths for the cap-adoption analysis.

All scripts in adoption/ import from here. Data conventions follow the
repo's italian-open-data skill notes (MIMIT quirks, dtComu semantics).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

ADOPTION_DIR = Path(__file__).resolve().parent
DATA_DIR = ADOPTION_DIR / "data"
OUT_DIR = ADOPTION_DIR / "output"
R_DIR = ADOPTION_DIR / "R"
for _p in (DATA_DIR, OUT_DIR, OUT_DIR / "tables", OUT_DIR / "figures", R_DIR):
    _p.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- #
# Analysis window
# ---------------------------------------------------------------- #
SERIES_FROM = dt.date(2026, 7, 1)  # requested long window start (user override)
CAP_DATE = dt.date(2026, 9, 28)  # self-imposed cap effective date
PRE_WINDOW = (dt.date(2026, 9, 21), dt.date(2026, 9, 27))  # 7d pre-cap
# Nominal cap thresholds announced by Agip Eni (EUR/l, Stradale self-service).
THRESHOLDS = {"Benzina": 2.00, "Gasolio": 2.20}
# Gasolio cap tracks the excise: the 5 c/l discount removed on 2026-10-06
# (gasolio excise 622.90 -> 672.90 EUR/1000 l, data/tax.parquet) shifts the
# pump-price cap by 0.05 * 1.22 = 6.1 c/l incl. 22% VAT.
GASOLIO_TAX_BACK = dt.date(2026, 10, 6)
GASOLIO_CAP_ADJ = 0.05 * 1.22  # EUR/l
THRESHOLD_BY_DATE = {
    fuel: [
        (dt.date(2026, 9, 28), th),
        (GASOLIO_TAX_BACK, th + (GASOLIO_CAP_ADJ if fuel == "Gasolio" else 0.0)),
    ]
    for fuel, th in THRESHOLDS.items()
}


def cap_threshold(fuel: str, day: dt.date) -> float:
    """Effective cap threshold for a fuel on a given day."""
    steps = THRESHOLD_BY_DATE[fuel]
    eff = steps[0][1]
    for from_d, th in steps:
        if day >= from_d:
            eff = th
    return eff


TIPO_STRADALE = "Stradale"
FUELS = ("Benzina", "Gasolio")

# ---------------------------------------------------------------- #
# Inputs (repo root cache; ../data relative to adoption/)
# ---------------------------------------------------------------- #
_REPO_ROOT = ADOPTION_DIR.parent
PRICES_PARQUET = _REPO_ROOT / "data" / "prices_raw.parquet"  # all dates
STATIONS_PARQUET = _REPO_ROOT / "data" / "stations.parquet"  # weekly anagrafica
ANAGRAFICA_CSV = DATA_DIR / "anagrafica_impianti_attivi.csv"  # MIMIT, has Comune
GRID_CSV = DATA_DIR / "istat_grid" / "GrigliaPop2021_Ind_ITA_CSV.txt"
# NOTE: the 2026 zip extracts WITHOUT a top-level folder (unlike earlier
# vintages) — the four layer dirs sit directly in istat_borders/.
BORDERS_DIR = DATA_DIR / "istat_borders"

# ---------------------------------------------------------------- #
# Outputs
# ---------------------------------------------------------------- #
STATION_DAY = OUT_DIR / "tables" / "station_day_prices.parquet"
STATION_STATIC = OUT_DIR / "tables" / "station_covariates.parquet"
DISTANCES = OUT_DIR / "tables" / "station_day_distances.parquet"
ADOPTION_PANEL = OUT_DIR / "tables" / "adoption_panel.parquet"
SURVIVAL_INPUT = OUT_DIR / "tables" / "survival_input.csv"
PROV_DISPERSION = OUT_DIR / "tables" / "province_dispersion.csv"
COMPETITIVENESS = OUT_DIR / "tables" / "nonadopter_competitiveness.csv"
