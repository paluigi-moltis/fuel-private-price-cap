# Panel A: time-to-adoption survival analysis (Cox + AFT), station x fuel.
#
# Duration: days from cap effective date (2026-09-28) to first day with
# effective price <= cap; censored at last day observed for never-adopters.
# Covariates: distance to nearest station, day-0 distance to nearest
# at-cap station, chain size (gestore), population per 1-km cell,
# pre-cap gap vs threshold, brand (bandiera), region (strata option).

.libPaths(c("~/Rlibs", .libPaths()))
suppressPackageStartupMessages({
  library(survival)
  library(data.table)
})

d <- fread("adoption/output/tables/survival_input.csv")
d[, bandiera := factor(bandiera)]
# collapse rare brands into OTHER for stability
tab <- table(d$bandiera)
keep <- names(tab)[tab >= 100]
d[, bandiera_g := fifelse(bandiera %in% keep, as.character(bandiera), "OTHER")]
d[, regione := factor(regione)]

cat("N =", nrow(d), " events =", sum(d$event), "\n")

# 1. Baseline Cox on core covariates
m1 <- coxph(
  Surv(duration, event) ~ nn_dist_km + cap_dist_km_d0 + pop_density_cell +
    pre_gap_vs_cap + n_stations_gestore + fuel,
  data = d, ties = "efron"
)
print(summary(m1))

# 2. + brand
m2 <- coxph(
  Surv(duration, event) ~ nn_dist_km + cap_dist_km_d0 + pop_density_cell +
    pre_gap_vs_cap + n_stations_gestore + fuel + bandiera_g,
  data = d, ties = "efron"
)
print(summary(m2))

# 3. + region (strata: separate baselines per region)
m3 <- coxph(
  Surv(duration, event) ~ nn_dist_km + cap_dist_km_d0 + pop_density_cell +
    pre_gap_vs_cap + n_stations_gestore + fuel + bandiera_g +
    strata(regione),
  data = d, ties = "efron"
)
print(summary(m3))

# 4. Proportional hazards check (m1: continuous covariates only; m2's
#    rare-brand dummies are near-separating and make the zph solve singular)
ph <- cox.zph(m1)
print(ph)

# 5. Accelerated failure time (Weibull) as robustness; +0.5d offset
#    because day-0 adopters give duration = 0 (invalid for AFT)
d[, duration_aft := pmax(duration, 0) + 0.5]
m5 <- survreg(
  Surv(duration_aft, event) ~ nn_dist_km + cap_dist_km_d0 + pop_density_cell +
    pre_gap_vs_cap + n_stations_gestore + fuel + bandiera_g,
  data = d, dist = "weibull"
)
print(summary(m5))

# 6. Firm-level clustering: gestore robust SEs for m2 (same company owns
#    many stations; adoption decisions may correlate within firm)
if (requireNamespace("sandwich", quietly = TRUE)) {
  library(sandwich)
  library(lmtest)
  robust <- coxph(
    Surv(duration, event) ~ nn_dist_km + cap_dist_km_d0 + pop_density_cell +
      pre_gap_vs_cap + n_stations_gestore + fuel + bandiera_g,
    data = d, ties = "efron", robust = TRUE, cluster = gestore
  )
  print(coeftest(robust))
}

# HR plots data export
coefs <- as.data.table(coef(summary(m2)), keep.rownames = "term")
fwrite(coefs, "adoption/output/tables/cox_model2_coefficients.csv")

cat("\nDone.\n")
