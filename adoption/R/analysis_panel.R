# Panel B: daily adoption panel with event-study / fixed effects.
#
# Station x fuel x day panel (post-cap). Outcome: at_cap (price <= cap).
# Event time: days_since_cap (-7..+7 in estimates; cap at endpoints).
# Specifications:
#   TWFE: at_cap ~ event_time dummies + station FE + day FE
#   with distance/population interactions to trace spatial diffusion.
# Province dispersion and competitiveness tables are produced in Python
# (build_panel.py); this script focuses on the panel dynamics.

.libPaths(c("~/Rlibs", .libPaths()))
suppressPackageStartupMessages({
  library(data.table)
  library(fixest)
})

d <- fread("adoption/output/tables/adoption_panel.csv")
d <- d[days_since_cap >= -7 & days_since_cap <= 7]  # event-study window
# (pre-cap days up to -7 included so the pre-cap level is identified;
#  -1 is the reference period)
d[, id_fuel := paste(id_impianto, fuel, sep = "_")]
d[, ev := as.integer(pmin(days_since_cap, 7))]
d[, ev := factor(ev, levels = -1:7)]
setorder(d, id_fuel, date)

cat("post rows:", nrow(d), " units:", uniqueN(d$id_fuel), "\n")

# 1. TWFE event study: adoption rate by event time
m1 <- feols(
  at_cap ~ i(ev, ref = -1) | id_fuel,
  data = d, cluster = ~gestore
)
print(summary(m1))
iplot(m1, main = "Adoption rate event study", xlab = "days since cap")
png("adoption/output/figures/event_study_adoption.png", width = 1400, height = 900, res = 150)
iplot(m1, main = "Adoption rate event study", xlab = "days since cap")
dev.off()

# 2. Diffusion: does adoption depend on distance to nearest adopter?
#    interact event time with cap-distance terciles (computed at the cap
#    date, i.e. days_since_cap == 0)
d0 <- d[days_since_cap == 0, .(fuel, id_impianto, cap_dist_km)]
setnames(d0, "cap_dist_km", "cap_dist_km_d0")
d <- d0[d, on = c("fuel", "id_impianto")]  # attach day-0 cap distance
d[, cap_dist_terr := cut(
  cap_dist_km_d0,
  breaks = quantile(cap_dist_km_d0, c(0, 1/3, 2/3, 1), na.rm = TRUE),
  include.lowest = TRUE, labels = c("near", "mid", "far")
)]
m2 <- feols(
  at_cap ~ i(ev, ref = -1) * cap_dist_terr | id_fuel,
  data = d, cluster = ~gestore
)
print(summary(m2))
png("adoption/output/figures/event_study_by_capdist.png", width = 1400, height = 900, res = 150)
iplot(m2, main = "Adoption by distance to nearest adopter (day-0)", xlab = "days since cap")
dev.off()

# 3. Price convergence: gap-to-threshold dynamics for adopters vs not
d[, gap := prezzo - fifelse(fuel == "Benzina", 2.0, 2.2)]
m3 <- feols(
  gap ~ i(ev, ref = -1) * adopted | id_fuel,
  data = d, cluster = ~gestore
)
png("adoption/output/figures/event_study_gap.png", width = 1400, height = 900, res = 150)
iplot(m3, main = "Gap to cap: adopters vs non-adopters", xlab = "days since cap")
dev.off()

# 4. Static panel: covariate effects on daily adoption probability
tab <- table(d$bandiera)
keep <- names(tab)[tab >= 100]
d[, bandiera_g := fifelse(bandiera %in% keep, as.character(bandiera), "OTHER")]
d[, pop_k := pop_cell / 1000]
d[, chain_k := n_stations_gestore / 100]
m4 <- feols(
  at_cap ~ nn_dist_km + cap_dist_km + log1p(pop_k) + chain_k +
    bandiera_g | id_fuel + date,
  data = d, cluster = ~gestore
)
print(summary(m4))

# export
res <- list(m1 = m1, m2 = m2, m4 = m4)
sink("adoption/output/panel_results.txt")
for (nm in names(res)) {
  cat("\n=====", nm, "=====\n")
  print(summary(res[[nm]]))
}
sink()
cat("Done.\n")
