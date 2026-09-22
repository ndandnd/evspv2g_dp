# Seasonal/current-solar forecast comparison — 11 September 2026

All36cases completed. Daily journal chains, source policy/pool hashes, status identities, independent replay residuals and oracle equality to wave4 passed. Each policy uses the same365dates in reused2022development data. Seeds11/29/47 are separate trained policies, not independent weather years.

| Arm/method | Annual forecast failures | Monthly failures | Monthly + current solar failures |
|---|---|---|---|
|Solar+BESS SAA|34/38/35|2/3/3|2/2/3|
|Solar+BESS minimax|13/14/12|10/12/11|4/8/8|
|Solar+BESS reduced|31/35/34|2/3/2|2/2/2|
|V2G+BESS SAA|18/19/14|2/2/1|0/0/0|
|V2G+BESS minimax|17/17/17|8/11/9|8/7/9|
|V2G+BESS reduced|18/22/20|1/2/1|0/0/0|

All36variants reduced observed failed days versus annual climatology;33paired14-day block95%intervals excludezero in the beneficial direction. For SAA V2G+BESS with current-solar updates, paired reductions are4.93%,5.21%,3.84%, with intervals[1.64,8.77]%,[1.64,9.32]%,[1.10,6.86]%. These intervals are conditional on policies and this development year. Zero observed failures is no unseen-event guarantee. Monthly/current-solar is not uniformly superior to monthly alone in all metrics; retain all outcomes rather than selecting a winning variant perseed.

[Full failure, shortage and conditional cost distributions, paired intervals and hashes](forecast_results.json). Emergency energy denotes original-model failure, not feasible cheap supply. Cost comparisons use jointly feasible dates and explicitly report their denominators. Recorded per-day solver time sums3396.71seconds; scoped Slurm accounting (original research artifact `snapshots/20260911_1421/slurm_accounting.psv`; not included in this export) provides actual elapsed/allocation records. No new MIP or optimality certificate is created.

Interpretation: much of the first causal controller's failure was forecast misspecification; this is insufficient motivation for RL. Freeze both simple forecast variants and all policies for new-year evaluation.

Weather audit corrected the source label: an explicit ERA5 query did not reproduce the first training week (max discrepancy148W/m²), whereas default Best Match at fixedUTC−7 reproduced all8760training values exactly. [Audit result](../../weather_validation/training_audit_result.json). Open-Meteo documents Best Match as a combination of products and radiation as averaged over the preceding hour: [official API documentation](https://open-meteo.com/en/docs/historical-weather-api). Retain endpoint-hour benchmark indexing explicitly; do not describe this as validated DST-aware operations or homogeneous ERA5/station observations.

A [100-case protocol](../../weather_validation/FROZEN_HOLDOUT_PROTOCOL.md) was frozen before2024/2025downloads. New years passed complete-hour/no-null/nonnegative-value QA with raw and CSV hashes. Both forecast variants and all methods retained; deterministic baselines are secondary because their source pools differ. Results will be new-year benchmark validation, not a repair of the manuscript's physical clock convention.
