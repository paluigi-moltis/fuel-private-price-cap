# The 2026-09-28 private price cap: day-one compliance

*Italy's major oil companies self-imposed a pump-price cap effective 2026-09-28 (included): 2.00 €/l for Benzina, 2.20 €/l for Gasolio (self-service). This note measures day-one compliance on the MIMIT station-level extract of 2026-09-28 (~24k stations, self-service only, 4-sd outlier-cleaned). A station complies when its price is at or below the cap.*

## 1. Compliance is low — but communication, not refusal, is the bottleneck

On the cap day, **Agip Eni complied on 24.9% of Benzina and 25.3% of Gasolio price observations** (956/3,835 and 971/3,834). But compliance tracks almost perfectly with *when the price was last communicated* (`dtComu`):

| Last communication | Benzina: n | compliant | Gasolio: n | compliant |
|---|---|---|---|---|
| on 09-28 (same day) | 932 | **94.4%** | 966 | **91.6%** |
| 09-27 or earlier | 2,903 | **2.6%** | 2,868 | **3.0%** |

Same-day communications cluster at **00:00–07:00** (mean ~06:20) — a coordinated early-morning update. Stations that did not re-communicate kept their pre-cap price, which was set under the old (higher) level and is almost never compliant. In other words: the ~25% compliance rate is essentially the *share of stations reached by the same-morning update*, not the share willing to comply. Had all stations communicated on the 28th at the same-day cohort's observed compliance rate (~94%), day-one compliance would have been ≈ 94%, not 25%.

The 133 same-day communicators that were nevertheless non-compliant (52 Benzina + 81 Gasolio) are **laggards of the same rollout, not holdouts**: they also communicated in the early-morning window (00–07 h), but transmitted old-level prices (mean 2.15 €/l Benzina vs 2.00 for the compliant cohort), scattered across regions and mostly *Stradale* — consistent with price files that reached a small share of stations after their automated morning communication.

## 2. Compliance differs sharply by region

Benzina/Stradale compliance spans a factor of ~8: from 1.6% in Valle d'Aosta and 2.2% in Sardegna to 12.9% in Friuli-Venezia Giulia, 8.4% in Lazio and 8.2% in Abruzzo (national median ≈ 5%).

![Cap-day compliance by region](output/figures/cap_compliance_capday_region_benzina_stradale.png)

## 3. A visible break in prices — but only for Agip Eni

Daily brand means over the week before the cap show a clean break on 09-28, and only for the brand that announced it:

![Daily mean Benzina price by brand](output/figures/brand_mean_price_benzina_zoom.png)

Agip Eni Benzina dropped **−3.8 c/l (−179 bp)** against its 7-day pre-cap mean (2.149 → 2.111 €/l), closing ~26% of the distance to the cap; Gasolio shows the analogous move once the 09-26 excise hike (+5 c/l) is accounted for. Every other brand (Api-Ip, Q8, Esso, Tamoil, Shell, Pompe Bianche) was flat or drifted *away* from the cap (Benzina ±0.4 c/l; Gasolio +3.4…+4.0 c/l, pure excise pass-through). Note also the frozen 09-26/27 prices: stations barely communicated over the weekend before the cap.

## Data & method

- Source: MIMIT open-data *prezzi praticati* via MongoDB (prices 2026-07-01 → 09-28, weekly station snapshots); self-service only; 0.97% outlier removal.
- Compliance: `prezzo ≤ cap` on the 09-28 extract; brand view = 6 named brands + pooled independents ("Pompe Bianche").
- All numbers and figures: [fuel-private-price-cap](https://github.com/paluigi/fuel-private-price-cap), PR #1 — tables `dtcomu_capday_*`, `cap_compliance_capday_region`, `brand_price_break`.

*Caveat: one post-cap day only; Autostradale cells are small; dtComu reflects the last communication, so a station could have re-priced at the pump without communicating.*
