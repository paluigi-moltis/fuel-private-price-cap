# Who Adopts a Price Cap? The Diffusion of Agip Eni's Self-Imposed Cap across Italian Fuel Retailers

*Working paper — draft skeleton with computed results, [date: 2026-10-06]*

## 1. Introduction

On 28 September 2026 Agip Eni unilaterally imposed a cap on its motor-fuel
prices (2.00 EUR/l Benzina, 2.20 EUR/l Gasolio, self-service, Stradale
network), announced as a two-month measure against speculators. Within
days the Italian market saw the largest synchronised price communication
wave on record: 9,192 stations (Benzina) communicated on 1 October alone,
led by competitor chains cutting 10–17 c/l.

This paper asks who adopts the cap — i.e. whose effective price is at or
below the threshold — and why. We build a station-level panel from
communication-level data (dtComu), which reconstructs the *effective*
daily price path of every Stradale station independently of the daily
extract's snapshot timing (a source of measurement bias we document: the
extract taken before the morning communication wave misdates adoptions
by 1–3 days, and on ISTAT reference days overstates the market average
by up to 4 c/l).

We combine: (i) survival models of time-to-adoption; (ii) a daily panel
event study around the cap date; (iii) province-level price-dispersion
analysis; (iv) competitiveness of non-adopters relative to their
provincial market.

**Headline findings** (station×fuel units, N = 39,418, window
2026-07-01 → 2026-10-05):

1. Adoption is fast and massive but incomplete: 53.5% of stations price
   at or below the cap within 8 days (median adoption: day 4).
2. Adoption follows a spatial diffusion gradient — the hazard of
   adopting falls ~9% per km of distance to the nearest priced station
   and ~2% per km to the nearest at-cap station on the cap date.
3. Firm size matters: each additional station of the same Gestore raises
   the adoption hazard; chains move network-wide (the Q8 wave: 1,902
   stations in one morning).
4. Pre-cap price position is the dominant predictor: stations already
   within ~15 c/l of the threshold adopt almost immediately (HR 0.015
   per EUR/l of gap).
5. The cap polarised the market: province-level within-day dispersion
   (IQR) widened in **100% of 222 province×fuel cells** (Gasolio IQR
   +12.1 c/l on average), because a mass of adopters sits at the cap
   while a non-adopter tail holds above it.
6. Non-adopters became relatively more expensive: their gap to the
   provincial mean rose from +1.1 to +5.9 c/l — a competitive position
   that worsened mechanically with every neighbour adopting.

## 2. Institutional background and related literature

- *Institutional setting*: MIMIT price-communication obligation
  (dtComu semantics; daily extracts; the 8am cutoff and its biases —
  documented in the repo's skill notes and in §3.2).
- *Fuel price cycles and asymmetry*: Eckert (2013) survey; Lewis &
  Noel (2011) on Edgewater-style retail oligopolies.
- *Monopoly/oligopoly pricing under price ceilings*:_introductory_
  theory predicts ceiling-induced price uniformity at the cap when
  demand is inelastic and the binding cap sits below the collusive
  level; our data show partial uniformity plus a non-adopter tail.
- *Spatial price linkages in retail fuel*: German-Pfaff (RRB literature),
  Pennerstorfer et al. (2019) on spatial competition and market structure.
- *Diffusion of pricing decisions*: entry/exit and strategic complementarity
  literature; cap adoption as a discrete strategic choice with local
  spillovers — the survival framework connects to duration models in IO.
- *Italian fuel-market studies*: ABF/AGCM enforcement reports; the
  "speculator" debate of 2026 (news coverage to be cited).

**Contribution**: first station-level, communication-based measurement of
a self-imposed cap's diffusion; evidence that a unilateral cap triggers
competitor matching with a clear spatial gradient; documentation that
reference-day sampling bias (ISTAT 1/11/21) can be material (3.5–4.1 c/l).

## 3. Data

### 3.1 Sources

| Source | Content | Unit |
|---|---|---|
| MIMIT prezzi (daily extracts, in MongoDB) | price communications: idImpianto, fuel, prezzo, dtComu | communication |
| MIMIT anagrafica | Gestore, Bandiera, Tipo Impianto, coordinates, Comune | station |
| ISTAT Griglia Popolazione 2021 | population per 1-km cell (EPSG:3035) | cell |
| ISTAT Limiti 01-01-2026 | province/region polygons (UTM 32N→WGS84) | polygon |

### 3.2 From communications to effective prices

Each dtComu is a price *event*; the station's price on day D is the last
communication with comu_day ≤ D. This avoids the extract snapshot bias:
- the daily extract dates day-D prices before the 00:00–08:00
  communication wave (0 same-day communications survive into the day-D
  extract on Oct 1; 1,314 into the Oct-4 extract — timing varies);
- on ISTAT reference days this biases recorded averages upward by
  3.5–4.1 c/l when a wave lands on the reference day (Oct 1 2026, measured).

### 3.3 Sample

- Stradale stations only (autostradale excluded: different market).
- Benzina + Gasolio, 2026-07-01 → 2026-10-05 (97 days).
- 39,418 station×fuel units; 3.8M station-day rows.
- Coordinates harmonised (WGS84); 2 broken-coordinate stations dropped
  from the grid join; 53 stations (0.2%) without province assignment kept
  with missing province.

### 3.4 Variables

- `adopted` / duration: first post-cap day with effective price ≤ cap
  (2.00/2.20); censored at last observation (Oct 5).
- `nn_dist_km`: distance to nearest other priced station (same fuel), km.
- `cap_dist_km(d)`: distance to nearest station at-or-below cap on day d.
- `pop_density_cell`: census population of the containing 1-km cell.
- `n_stations_gestore`: national chain size of the Gestore.
- `pre_gap_vs_cap`: mean price Sept 21–27 minus cap.
- `bandiera` (brand), `regione`, `provincia_istat`.

## 4. Descriptive findings

- Adoption share by day: 19.3% (day 0, station-FE event-study estimate)
  rising to 51.2% (day 7); jump on day 3–4 = the Q8/Tamoil/Api-Ip wave.
- Agip Eni's own compliance: 24.9% on cap day (communication lags) →
  98.4–98.6% by Oct 5 (their prices sit 0.8–0.9 c/l below the cap).
- Brands on Oct 5 (Benzina, at-or-below-cap share): Agip Eni 98.4%,
  Q8 87.2%, Tamoil 62.4%, Api-Ip 42.8%, Pompe Bianche 25.2%, Esso 24.2%,
  Shell 11.6% — mean prices order identically (two-tier market).

## 5. Who adopts? Survival analysis

(Cox proportional hazards; station×fuel units; gestore-clustered
uncertainty; full tables in `output/survival_results.txt`.)

| Covariate | HR (m1) | HR (m2, +brand) | Interpretation |
|---|---|---|---|
| nn_dist_km | 0.912 | 0.938 | farther from competitors → slower adoption |
| cap_dist_km (day 0) | 0.983 | 0.974 | nearer an adopter → faster adoption |
| pop_density_cell | 1.00001*** | — | denser cells adopt faster |
| pre_gap_vs_cap | 0.015 | 0.024 | dominating effect |
| n_stations_gestore | 1.0007 | 1.0004 | chain size → faster |
| fuel (Gasolio) | n.s. | n.s. | same dynamics both fuels |
| brand dummies | — | dominant | Q8/Agip Eni fastest; white labels slowest |

Weibull AFT and gestore-clustered estimates agree (sign and
significance). PH assumption holds for the continuous spec.

## 6. Market dynamics: event study

(TWFE panel, station FE; reference = day −1; figures in
`output/figures/event_study_*.png`.)

- `at_cap` rises 0.19 → 0.51 over 8 days; no anticipatory movement
  before day 0 (announcement-effect estimated −0.003, n.s.).
- Diffusion gradient: by day 4, near-adopter tercile adoption 58.4%
  vs 34.8% far tercile — consistent with local strategic
  complementarities, not just brand-level national decisions.
- Gap-to-cap for eventual adopters collapses to ~0 from day 0;
  non-adopters' gap *widens* — polarisation, not convergence.

## 7. Territorial dispersion and competitiveness

- Province IQR widened in every one of 222 province×fuel cells
  (Benzina +12.7 c/l, Gasolio +12.1 c/l on average): the cap created a
  bimodal distribution (mass at cap + non-adopter tail).
- Non-adopters' competitiveness vs provincial mean: +1.1 c/l pre,
  +5.9 c/l post (+4.8 c/l deterioration).
- Welfare reading: consumers near adopters gain; the dispersion
  increase implies larger consumer-search gains from comparison
  shopping, and heterogeneous pass-through across territory.

## 8. Discussion and policy conclusions

1. A unilateral, temporary cap achieved partial market-wide matching
   within days — mostly via competitor chains' network-wide decisions
   and local spillovers — leaving ~46% of stations (many Pompe Bianche/
   independents) above the cap.
2. Adoption correlates with density, chain size and proximity — i.e.
   the cap spread along urban, organised-firm corridors; rural/independent
   stations retained above-cap prices, so consumer gains are
   geographically uneven.
3. Measurement: official statistics sampling reference days against
   8am-cut extracts can mis-measure reference-day prices by 3–4 c/l;
   communication-based reconstruction (this paper's approach) is the
   robust alternative.
4. Caveats: adoption ≠ compliance enforcement; temporary cap may induce
   strategic pricing around expiry; coordinates quality and brand
   classification inherited from MIMIT data.

## 9. Reproducibility

All results regenerate from:
```
uv run fuel-price-cap            # refresh MongoDB cache
uv run python adoption/build_station_day.py
uv run python adoption/build_station_covariates.py
uv run python adoption/build_distances.py
uv run python adoption/build_panel.py
Rscript adoption/R/analysis_survival.R
Rscript adoption/R/analysis_panel.R
```
Data: MIMIT open data (IODL 2.0), ISTAT census grid & 2026 borders.
