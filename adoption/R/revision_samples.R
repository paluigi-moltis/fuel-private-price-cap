# Revision analyses: Cox + LPM on three samples
#   S1 universe, S2 excl. Agip Eni + Q8, S3 Pompe Bianche only.
# Outputs: output/revision_cox.txt, output/revision_lpm.txt
.libPaths(c("~/Rlibs", .libPaths()))
suppressMessages({
  library(survival); library(data.table)
})

d <- as.data.table(read.csv("output/tables/survival_input.csv",
                            stringsAsFactors = FALSE))
d[, bandiera := as.character(bandiera)]
d[, is_pb := bandiera == "Pompe Bianche"]
SAMPLES <- list(
  S1_universe       = function(x) x,
  S2_excl_agip_q8   = function(x) x[!(bandiera %in% c("Agip Eni", "Q8"))],
  S3_pompe_bianche  = function(x) x[bandiera == "Pompe Bianche"]
)

# brand grouping: >=100 obs kept, else OTHER (within sample)
prep <- function(x) {
  x[, bandiera_g := bandiera]
  tab <- x[, .N, by = bandiera_g]
  rare <- tab[N < 100, bandiera_g]
  x[bandiera_g %in% rare, bandiera_g := "OTHER"]
  # drop singleton-factor levels that would break the PH/AFT fits
  x
}

cat("\n========== SAMPLE SIZES ==========\n")
for (s in names(SAMPLES)) {
  x <- SAMPLES[[s]](d)
  cat(sprintf("%s: N units = %d, events = %d, share = %.3f\n",
              s, nrow(x), sum(x$event), mean(x$event)))
}

# ---------------------------------------------------------------- Cox
sink("output/revision_cox.txt")
for (s in names(SAMPLES)) {
  x <- prep(data.table::copy(SAMPLES[[s]](d)))
  cat("\n\n==================================================\n")
  cat("SAMPLE:", s, "\n")
  cat("==================================================\n")
  # m_a: continuous core (no brand)
  ma <- coxph(Surv(duration, event) ~ nn_dist_km + cap_dist_km_d0 +
                pop_density_cell + pre_gap_vs_cap + n_stations_gestore +
                fuel, data = x, ties = "efron",
              cluster = gestore)
  print(summary(ma))
  # m_b: + brand
  if (length(unique(x$bandiera_g)) > 2) {
    mb <- coxph(Surv(duration, event) ~ nn_dist_km + cap_dist_km_d0 +
                  pop_density_cell + pre_gap_vs_cap + n_stations_gestore +
                  fuel + bandiera_g, data = x, ties = "efron",
                cluster = gestore)
    print(summary(mb))
  } else {
    cat("\n(brand dummies skipped: <3 levels in this sample)\n")
  }
}
sink()

# ---------------------------------------------------------------- LPM
# adoption probability ~ full covariate set (OLS, gestore-clustered SE)
sink("output/revision_lpm.txt")
for (s in names(SAMPLES)) {
  x <- prep(data.table::copy(SAMPLES[[s]](d)))
  x[, adopted := as.integer(adopted == "true" | adopted == "True" |
                            adopted == "TRUE" | adopted == TRUE)]
  x[, fuel := factor(fuel)]
  x[, regione := factor(regione)]
  x <- x[!is.na(regione)]
  cat("\n\n==================================================\n")
  cat("SAMPLE:", s, "\n")
  cat("==================================================\n")
  # full set incl. region FE; brand too (within-sample >=100 rule).
  # In S3 (single brand) drop the brand term entirely.
  if (length(unique(x$bandiera_g)) > 1) {
    form <- adopted ~ nn_dist_km + cap_dist_km_d0 + pop_density_cell +
      occupati + pre_gap_vs_cap + n_stations_gestore + fuel +
      bandiera_g + regione
  } else {
    form <- adopted ~ nn_dist_km + cap_dist_km_d0 + pop_density_cell +
      occupati + pre_gap_vs_cap + n_stations_gestore + fuel + regione
  }
  m <- lm(form, data = x)
  library(sandwich); library(lmtest)
  co <- coeftest(m, vcov = vcovCL, cluster = ~ gestore)
  print(co)
  cat(sprintf("\nN = %d, R2 = %.4f\n", nobs(m), summary(m)$r.squared))
}
sink()
cat("done: output/revision_cox.txt, output/revision_lpm.txt\n")
