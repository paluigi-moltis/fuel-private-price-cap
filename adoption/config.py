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
THRESHOLDS = {"Benzina": 2.00, "Gasolio": 2.20}  # EUR/l, self-service

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
