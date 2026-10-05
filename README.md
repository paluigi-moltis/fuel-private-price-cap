# fuel-private-price-cap

Analysis of the private (self-imposed) price cap announced by Italian oil
companies in September 2026, effective **2026-09-28** (included), based on
station-level fuel price data stored in MongoDB.

The pipeline downloads self-service prices (`isSelf = 1`, Benzina / Gasolio,
from 2026-07-01), weekly station snapshots and the excise history; cleans,
enriches and aggregates them; and produces CSV tables plus static Plotly
charts (PNG only) covering cap compliance, price dynamics (gross and net of
taxes) by market group, Tipo Impianto, region and individual Bandiera.

## Usage

```bash
uv sync                     # install dependencies
uv run fuel-price-cap       # full pipeline: download from MongoDB + analyze
uv run fuel-price-cap --cache   # reuse the parquet files already in data/
```

`MONGO_URI` must be defined in `.env` (unless `--cache` is used). The
`fuels` MongoDB database must contain the `prices`, `stations` and `tax`
collections.

Quality checks: `uv run ruff check src/` and `uv run black --check src/`.

## Folder layout

```
src/fuel_price_cap/
  config.py     # constants: window, VAT, thresholds, brand groups, paths
  data.py       # FuelDataRepository (MongoDB -> Polars -> parquet), PriceCleaner
  enrich.py     # BrandGrouper, RegionMapper, StationTimeline, NetPriceCalculator
  analysis.py   # StationStats, CapCompliance, DailyPriceStats
  comu.py       # dtComu parsing/freshness, BrandPriceBreak (per-brand prices)
  plots.py      # PriceChartBuilder (Plotly, static PNG via kaleido)
  main.py       # Pipeline orchestrator (run() executes all stages)

data/           # parquet extracts + static reference CSVs (see below)
output/tables/  # all CSV deliverables
output/figures/ # all charts (static PNG; no HTML)
```

### Data files

| File | Content |
|---|---|
| `data/prices_raw.parquet` | prices as downloaded (date ≥ 2026-07-01, `isSelf=1`, Benzina/Gasolio) |
| `data/prices_clean.parquet` | raw minus 4-sd outliers |
| `data/prices_enriched.parquet` | clean + station attributes (as-of), region, group, net price |
| `data/stations.parquet` | all weekly station snapshots |
| `data/tax.parquet` | excise change dates (EUR per 1000 l) |
| `data/province_region.csv` | 107 province sigle → province name → region |
| `data/brand_groups.csv` | the six explicit brand → group mappings |

### Main outputs

- `output/tables/cap_compliance_daily.csv`, `cap_compliance_period.csv`
  (+ `_region` and `_bandiera` variants): share of observations at or below
  the cap threshold, by fuel × group × Tipo Impianto (× region), and by
  fuel × Bandiera × Tipo Impianto × top-1-Gestore flag. Bandiera columns use
  the **seven-brand view** (see below). All compliance files carry OLAP
  margin rows aggregated over their dimensions, marked with the sentinel
  `"Tutte"` (e.g. `group="Tutte"` = all groups pooled); margin rows sort
  after the detail rows of their cell. In the by-Bandiera files,
  `n_top1_obs` / `share_top1_pct` are cell-level statistics (observations
  run by the brand's top-1 Gestore within that date × fuel × Bandiera ×
  Tipo Impianto cell), repeated on every row of the cell.
- `output/tables/cap_compliance_top1_gestore.csv`: per fuel × Bandiera
  (seven-brand view), how many stations run by the brand's top-1 Gestore
  comply with the cap versus stations run by other operators (counts,
  at-or-below-cap shares and their difference in percentage points).
- `output/tables/net_price_stats_by_group.csv`: net-price stats
  (mean/sd/min/max) with pre/post-cap deltas.
- `output/tables/station_counts_by_*.csv`, `weekly_station_counts.csv`,
  `brand_concentration.csv` (n Gestori, names of the top-1/top-2/top-3
  Gestori, top-1 Gestore station count and share, top-3 Gestore share, HHI
  in [0, 1]). Station counts by Bandiera use the seven-brand view;
  `brand_concentration.csv` covers the six grouped brands.
- `output/tables/dtcomu_capday_agip_eni.csv`: Agip Eni price observations on
  the cap day, cross-tabulated by compliance (≤ cap) and dtComu recency
  bucket (on cap day / within 2 days before / older / missing) — answers
  whether apparent non-compliance is just a stale price communication.
- `output/tables/dtcomu_capday_bandiera.csv`: the same cap-day counts
  (observations, compliant, communication recency) for every brand of the
  seven-brand view.
- `output/tables/postcap_daily_compliance_by_brand.csv`: daily compliance
  per post-cap day × brand, plus the station-level transition counts
  between consecutive post-cap days.
- `output/tables/dtcomu_latest_day_by_comu_day.csv`: observations on the
  latest available day split by whether dtComu is the cap day.
- `output/tables/reference_day_cutoff_benzina_gasolio.csv`: Oct 1 (ISTAT
  inflation reference day) cutoff analysis. The daily extract snapshot
  predates the day's morning communications (zero Oct-1 rows carry
  dtComu = Oct 1), so the table reports the recorded average vs the
  hypothetical average including all same-day communications (visible in
  the Oct-2 data), the number of stations concerned, and their price
  changes — Stradale only, per fuel.
- `output/tables/cap_compliance_capday_region.csv`: cap-day compliance
  (at-or-below share) per region × fuel × Tipo Impianto, sorted by share.
- `output/tables/brand_daily_prices.csv`: daily mean/sd gross price per
  fuel × brand (seven-brand view), full window (2026-07-01 onward).
- `output/tables/brand_price_break.csv`: per fuel × brand, mean gross price
  over the 7 days before the cap vs the cap day, the jump in EUR/l and basis
  points, the distance of the cap-day mean from the threshold, and what
  fraction of the distance to the cap the jump covers.
- `output/tables/outliers_removed.csv`, `bandiera_values_audit.csv`: audits
  (`bandiera_values_audit.csv` is the only table still listing every raw
  Bandiera value).
- `output/figures/`: daily mean ± 1 sd per group (aggregate dotted line),
  one chart per fuel × Tipo Impianto × gross/net × full/zoom window; daily
  at-or-below-cap share by Bandiera and daily brand mean gross price
  (seven-brand view), full window and zoom; ranked horizontal bars of
  cap-day compliance by region (fuel × Tipo Impianto). All charts are static
  PNG; all mark the cap date, and gross price charts also mark the threshold.

## Methodology

- **Price field**: `prezzo`, EUR/litre, self-service only. Each (date ×
  fuel × station) appears at most once in the source, so observations are
  stations.
- **Outliers**: one pass per (date × fuel) cell; observations with
  `|prezzo − mean| > 4 sd` (ddof=1) are dropped. Cells with fewer than 2
  observations are kept untouched. The audit CSV lists every cell with
  removals. Removal rate: **0.97%**.
- **Time-consistent attribution**: station attributes come from *weekly*
  snapshots while prices are *daily*; each price is matched to the latest
  snapshot of the same station up to that day (backward as-of join). Prices
  predating a station's first snapshot (0.07% of rows) use the earliest
  snapshot as fallback. Prices with no station record at all, or whose
  station has no Tipo Impianto, are **dropped** (5,649 rows, 0.16% of clean
  prices, all of the first kind: the source only carries
  Stradale/Autostradale).
- **Groups**: Majors = Agip Eni, Api-Ip, Q8; Large = Esso, Tamoil, Shell;
  Pompe Bianche = everything else (including the literal "Pompe Bianche"
  label and null Bandiere). Matching is exact on a normalized form of the
  label (lowercase, accents/punctuation stripped); every distinct raw
  `Bandiera` value is listed with its assignment in
  `bandiera_values_audit.csv` for review.
- **Seven-brand view**: Bandiera-level tables, reports and charts show the
  six named brands (Agip Eni, Api-Ip, Q8, Esso, Tamoil, Shell) plus a
  single "Pompe Bianche" brand pooling every other Bandiera, including the
  literal "Pompe Bianche" label.
- **Regions**: static sigla → region table (107 sigle; Aosta → Valle
  d'Aosta, Bolzano + Trento → Trentino-Alto Adige/Südtirol). The source
  stores the Napoli sigla "NA" as a missing value: null `Provincia` is
  restored to "NA". Unmatched sigle after the join: 0.
- **Net price**: `net = prezzo / 1.22 − excise(fuel, day)`, with excises in
  EUR/1000 l rescaled to EUR/l and carried forward over a full daily
  calendar (last `application_date ≤ day`). The gasolio excise changed twice
  in the two weeks before the cap (2026-09-18 and 2026-09-26).
- **Cap compliance** (from 2026-09-28, on clean prices): `prezzo <= 2.0`
  (Benzina) and `prezzo <= 2.2` (Gasolio) — a price exactly at the cap does
  not violate a self-imposed cap (in the 2026-09-28 extract no station
  prices exactly at the threshold, so the two definitions coincide). The
  post-cap period in the current extract covers a single day (2026-09-28).
  Compliance
  tables are reported by group and by Bandiera, both sliced by Tipo
  Impianto, together with OLAP margin rows aggregated over any subset of the
  dimensions: an aggregated dimension carries the sentinel value `"Tutte"`
  (e.g. `group="Tutte"` pools all groups for that fuel × Tipo Impianto cell;
  `canonical_name="Tutte"` pools all brands). The by-Bandiera files also
  split every cell by the `gestore_top1` flag, and the dedicated
  `cap_compliance_top1_gestore.csv` report compares compliance of top-1
  operator stations vs the rest (hypothesis: stations directly run by the
  brand's main operator comply faster than independently-operated ones).
- **Top-1 Gestore**: per Bandiera in the seven-brand view, the largest
  Gestore by station count on the latest snapshot (normalized labels, ties
  broken alphabetically); for the merged "Pompe Bianche" brand this is the
  largest independent operator overall. Reported in `brand_concentration.csv`
  (six grouped brands) with its station count and share, and used to flag
  each price row (`gestore_top1` = "top1"/"altri") by comparing the as-of
  Gestore against that anchor.
- **Concentration**: computed on the latest snapshot for the six grouped
  brands only; Gestore labels are normalized before counting. HHI uses
  shares as fractions, so it ranges in [0, 1].
- **Known caveats**: `data_download.py` (the original exploratory script)
  projects `Latitude`/`Longitude`, but the real field names are
  `Latitudine`/`Longitudine`; it is kept untouched for provenance.

## Change Log

- 2026-09-29 — Compliance is now **at or below** the cap (`prezzo <=`
  threshold): a station pricing exactly at the cap does not violate a
  self-imposed cap (no station does in the current extract, so all
  pre-existing counts are unchanged).
- 2026-09-29 — New detailed outputs: dtComu is parsed per price row and
  cap-day observations are split by communication recency
  (`dtcomu_capday_agip_eni.csv` crosstab + `dtcomu_capday_bandiera.csv` for
  all seven brands); new readable regional compliance table
  (`cap_compliance_capday_region.csv`, region × fuel × Tipo Impianto on the
  cap day) with ranked horizontal-bar charts replacing the regional facet
  grids; per-brand daily gross mean prices (`brand_daily_prices.csv`, full
  window + zoom charts by Bandiera) and a pre/post break table
  (`brand_price_break.csv`: 7-day pre-cap mean vs cap day, jump in EUR/l and
  bp, distance to the cap).
- 2026-09-29 — All HTML chart exports removed: figures are static PNG only
  (for print/Web notes); the regional facet-grid price charts are dropped
  with them. `net_price_stats_by_region.csv` is no longer produced (the new
  regional compliance table replaces its role). Rendering needs a Chrome/
  Chromium binary: set `BROWSER_PATH` when kaleido cannot find one (e.g.
  snap-confined Chromium on Ubuntu).
- 2026-09-29 — Implemented the full analysis pipeline (`src/fuel_price_cap/`):
  MongoDB repository with parquet persistence, 4-sd outlier cleaning with
  audit, as-of station attribution, brand grouping with a full Bandiera
  audit, province → region mapping (with the Napoli "NA" restore), daily
  excise calendar and net prices, station counts and Gestore concentration,
  cap compliance tables, national and regional Plotly charts, console
  validation checklist. Added `plotly`, `kaleido`, `numpy` (via
  `plotly[express]`) and dev `ruff`/`black`; console script
  `fuel-price-cap`.
- 2026-09-29 — Prices with no matching station, or whose station lacks a
  Tipo Impianto, are now dropped instead of being bucketed as Pompe
  Bianche / "Altro" (5,649 rows, 0.16% of clean prices). The "Altro"
  bucket no longer exists; station tables likewise exclude untyped
  stations.
- 2026-09-29 — Compliance outputs extended: all cap-compliance files gain
  OLAP `"Tutte"` margin rows over their dimensions; new by-Bandiera
  compliance tables (fuel × Bandiera × Tipo Impianto) split by the
  top-1-Gestore flag, with `n_top1_obs` / `share_top1_pct` on the
  aggregated rows; new `cap_compliance_top1_gestore.csv` report (top-1
  operator vs other operators per Bandiera); `brand_concentration.csv`
  now reports the top-1 Gestore name, station count and share; new daily
  below-cap share charts by Bandiera (six grouped brands + Pompe Bianche
  pooled, full window + zoom).
- 2026-09-29 — Bandiera-level outputs switched to the seven-brand view
  (six named brands + all remaining independents as a single "Pompe
  Bianche" brand) for readability: compliance tables, the top-1 Gestore
  report, station counts by Bandiera and the charts. The top-1 anchor for
  "Pompe Bianche" is the largest independent operator overall.
  `bandiera_values_audit.csv` remains the only table with every raw
  Bandiera value.
- 2026-09-29 — By-Bandiera compliance files: `n_top1_obs` and
  `share_top1_pct` are now cell-level columns filled on every row (they
  previously appeared only on the "Tutte" rows, which also sorted to the
  file bottom, leaving the trailing columns apparently empty); "Tutte"
  margin rows now sort directly after the detail rows of their cell.
  `brand_concentration.csv` additionally names the top-2 and top-3 Gestori
  per brand.
- 2026-09-29 — The generated tables and figures under `output/` are now
  committed to the repository (the raw parquet extracts in `data/` remain
  gitignored and regenerable).
