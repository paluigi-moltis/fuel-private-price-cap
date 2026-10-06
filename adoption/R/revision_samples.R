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
  # drop occupati per editorial decision: highly collinear with population
  if (length(unique(x$bandiera_g)) > 1) {
    form <- adopted ~ nn_dist_km + cap_dist_km_d0 + pop_density_cell +
      pre_gap_vs_cap + n_stations_gestore + fuel +
      bandiera_g + regione
  } else {
    form <- adopted ~ nn_dist_km + cap_dist_km_d0 + pop_density_cell +
      pre_gap_vs_cap + n_stations_gestore + fuel + regione
  }
  m <- lm(form, data = x)
  library(sandwich); library(lmtest)
  co <- coeftest(m, vcov = vcovCL, cluster = ~ gestore)
  print(co)
  r2 <- summary(m)$r.squared
  r2adj <- summary(m)$adj.r.squared
  cat(sprintf("\nN = %d, R2 = %.4f, adj. R2 = %.4f\n", nobs(m), r2, r2adj))
}
sink()

# ---------------------------------------------------------------- Diagnostics
# Appendix: VIF for continuous covariates (LPM, universe sample),
# scaled Schoenfeld residual tests (PH) for the Cox models.
sink("output/revision_diagnostics.txt")
for (s in names(SAMPLES)) {
  cat("\n\n==================================================\n")
  cat("SAMPLE:", s, "\n")
  cat("==================================================\n")

  # -- LPM diagnostics
  x <- prep(data.table::copy(SAMPLES[[s]](d)))
  x[, adopted := as.integer(adopted == "true" | adopted == "True" |
                            adopted == "TRUE" | adopted == TRUE)]
  x[, fuel := factor(fuel)]
  x[, regione := factor(regione)]
  x <- x[!is.na(regione)]
  if (length(unique(x$bandiera_g)) > 1) {
    form <- adopted ~ nn_dist_km + cap_dist_km_d0 + pop_density_cell +
      pre_gap_vs_cap + n_stations_gestore + fuel +
      bandiera_g + regione
  } else {
    form <- adopted ~ nn_dist_km + cap_dist_km_d0 + pop_density_cell +
      pre_gap_vs_cap + n_stations_gestore + fuel + regione
  }
  m <- lm(form, data = x)
  cat("\n--- LPM: VIF on continuous covariates (1/(1-R2) aux regressions) ---\n")
  cont <- c("nn_dist_km", "cap_dist_km_d0", "pop_density_cell",
            "pre_gap_vs_cap", "n_stations_gestore")
  x[, pop_density_cell := as.numeric(pop_density_cell)]
  x[, n_stations_gestore := as.numeric(n_stations_gestore)]
  for (v in cont) {
    others <- setdiff(cont, v)
    aux <- lm(as.formula(paste0("`", v, "` ~ ",
                                paste(others, collapse = " + "))), data = x)
    r2v <- summary(aux)$r.squared
    cat(sprintf("VIF(%s) = %.2f  (R2aux = %.3f)\n", v, 1/(1 - r2v), r2v))
  }
  cat("\n--- LPM: residual checks ---\n")
  r <- resid(m, type = "pearson")
  cat(sprintf("mean residual: %.4f | sd: %.4f\n", mean(r), sd(r)))
  # RESET
  lmtest::resettest(m, power = 2:3)
  print(lmtest::resettest(m, power = 2:3))
  cat("\n--- LPM: Breaugh calibration (mean pred vs actual) ---\n")
  cat(sprintf("mean predicted: %.4f | actual share: %.4f\n",
              mean(predict(m, type = "response")), mean(x$adopted)))

  # -- Cox diagnostics
  xc <- prep(data.table::copy(SAMPLES[[s]](d)))
  cat("\n--- Cox (m_a): PH test (scaled Schoenfeld, cox.zph) ---\n")
  ma <- coxph(Surv(duration, event) ~ nn_dist_km + cap_dist_km_d0 +
                pop_density_cell + pre_gap_vs_cap + n_stations_gestore +
                fuel, data = xc, ties = "efron", cluster = gestore)
  zp <- survival::cox.zph(ma, transform = "km")
  print(zp)
  cat("\n--- Cox (m_a): martingale-residual functional form check ---\n")
  # crude: correlation of martingale residuals with each continuous covariate
  mr <- resid(ma, type = "martingale")
  mf <- model.frame(ma)
  for (v in cont) {
    val <- as.numeric(mf[[v]])
    ok <- !is.na(val) & !is.na(mr)
    cat(sprintf("cor(martingale, %s) = %.3f\n", v, cor(mr[ok], val[ok])))
  }
  # condition number of covariate correlation matrix
  cm <- cor(xc[, ..cont], use = "pairwise.complete.obs")
  ev <- eigen(cm, only.values = TRUE)$values
  cat(sprintf("\ncondition number of covariate correlation matrix: %.1f\n",
              max(ev) / min(ev)))
  cat("\n--- covariate correlation matrix ---\n")
  print(round(cm, 3))
}
sink()
cat("done: output/revision_cox.txt, output/revision_lpm.txt, output/revision_diagnostics.txt\n")
