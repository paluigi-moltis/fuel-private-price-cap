# adoption/ — Cap-adoption drivers: station-level analysis

Station-level study of who adopted Agip Eni's self-imposed price cap
(2026-09-28: Benzina ≤ 2.00, Gasolio ≤ 2.20 EUR/l, Stradale) and how
prices, dispersion and competitiveness evolved. Companion to the main
repo analysis (root README); feeds the draft paper `paper_draft.md`.

## Layout

- `config.py` — paths, analysis window, thresholds.
- `download_istat.py` — ISTAT inputs (2026 borders, 2021 population grid).
- `crs.py` — CRS harmonization (WGS84 storage, EPSG:3035 metric work;
  2026 borders are UTM 32N despite the `_WGS84` filename).
- `build_station_day.py` — dtComu-effective station-day price panel
  (immune to the daily extract's pre-08:00 snapshot bias).
- `build_station_covariates.py` — geography, population, chain size.
- `build_distances.py` — daily nearest-station / nearest-adopter distances.
- `build_panel.py` — analysis panel + survival input + province tables.
- `R/analysis_survival.R` — Panel A: Cox/AFT time-to-adoption.
- `R/analysis_panel.R` — Panel B: daily event study (fixest).
- `output/` — tables, figures, R logs; `paper_draft.md` — the paper.

## Run order

```
uv run fuel-price-cap                     # repo root: refresh price cache
uv run python adoption/download_istat.py
uv run python adoption/build_station_day.py
uv run python adoption/build_station_covariates.py
uv run python adoption/build_distances.py
uv run python adoption/build_panel.py
Rscript adoption/R/analysis_survival.R    # needs ~/Rlibs (survival, data.table)
Rscript adoption/R/analysis_panel.R       # needs ~/Rlibs (fixest)
```

`data/` holds the downloaded ISTAT/MIMIT raw inputs (zips + extracts,
~28 MB — not committed). R packages install with:
`Rscript -e 'install.packages(c("survival","data.table","fixest","sandwich","lmtest"), lib="~/Rlibs")'`.

## Key numbers (window 2026-07-01 → 2026-10-05)

- 39,418 station×fuel units; 53.5% adopted within 8 days (median day 4).
- Adoption hazard falls with distance to competitors/adopters, rises
  with population density and chain size; pre-cap gap dominates.
- Province IQR widened in 100% of 222 province×fuel cells (~+12 c/l).
- Non-adopters' gap to provincial mean: +1.1 → +5.9 c/l.
