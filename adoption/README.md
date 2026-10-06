# adoption/ — Cap-adoption drivers: station-level analysis

Station-level study of who adopted Agip Eni's self-imposed price cap
(2026-09-28: Benzina ≤ 2.00, Gasolio ≤ 2.20 EUR/l, Stradale) and how
prices, dispersion and competitiveness evolved. Companion to the main
repo analysis (root README); feeds the paper `paper.tex` → `paper.pdf`.

## Reproducing the paper end-to-end

Requirements: Python ≥ 3.12 with [uv](https://docs.astral.sh/uv/),
R ≥ 4.4, ~2 GB disk, internet access (MIMIT/ISTAT downloads).

```
# 0. Price cache (repo root; needs MongoDB in .env)
uv run fuel-price-cap

# 1. ISTAT inputs: 2026 admin boundaries + 2021 1-km population grid
uv run python adoption/download_istat.py

# 2. Station-day effective-price panel from dtComu (2026-07-01 → 10-05)
uv run python adoption/build_station_day.py

# 3. Covariates: province/region (2026 borders), population, chain size
uv run python adoption/build_station_covariates.py

# 4. Daily distances: nearest station, nearest at-cap station
uv run python adoption/build_distances.py

# 5. Analysis panel, survival input, dispersion/competitiveness tables
uv run python adoption/build_panel.py

# 6. Econometrics (R). Packages: see note below.
Rscript adoption/R/analysis_survival.R     # Cox/AFT, main sample
Rscript adoption/R/analysis_panel.R        # station-FE event study
Rscript adoption/R/revision_samples.R      # 3-sample Cox + LPM (paper tables)

# 7. Figures for the paper
uv run python adoption/revision_analysis.py    # Fig 1 (raw shares) + ES coefs
uv run python adoption/make_maps.py            # province choropleths

# 8. Paper PDF (pdflatex + biber)
cd adoption && pdflatex paper && biber paper && pdflatex paper && pdflatex paper
```

R packages (installed to `~/Rlibs` if not in the system library):

```
Rscript -e 'dir.create("~/Rlibs", showWarnings=FALSE); install.packages(c("survival","data.table","fixest","sandwich","lmtest","zoo"), lib="~/Rlibs")'
```

`data/` holds the downloaded ISTAT/MIMIT raw inputs (zips + extracts,
~28 MB — not committed; step 1 re-creates them). `output/` tables and
figures are regenerable and mostly not committed.

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
- `R/analysis_survival.R` — Cox/AFT time-to-adoption (main sample).
- `R/analysis_panel.R` — daily event study (fixest).
- `R/revision_samples.R` — Cox + LPM on 3 samples (universe / excl.
  Agip Eni+Q8 / Pompe Bianche) → `output/revision_{cox,lpm}.txt`.
- `revision_analysis.py` — Fig 1 raw adoption shares + event-study
  coefficient table.
- `make_maps.py` — province choropleths (all stations, Pompe Bianche).
- `literature/` — reference pool, curated selection, `references.bib`.
- `paper.tex` / `paper.pdf` / `paper_tables.tex` — the paper.

## Key numbers (window 2026-07-01 → 2026-10-05)

- 39,418 station×fuel units; 53.5% adopted within 8 days (median day 4).
- Adoption hazard falls with distance to competitors/adopters, rises
  with population density and chain size; pre-cap gap dominates
  (Cox; holds in all three samples, strongest for Pompe Bianche).
- LPM adoption probability: pre-cap gap and nearest-adopter distance
  are the robust covariates; R² 0.23–0.46 across samples.
- Province IQR widened in 100% of 222 province×fuel cells (~+12 c/l).
- Non-adopters' gap to provincial mean: +1.1 → +5.9 c/l.
