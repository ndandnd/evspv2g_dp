# Frozen 2024–2025 weather validation

Validated 12 September 2026. The current-solar controller substantially reduces the earlier forecast problem, but does not establish zero weather risk. V2G+BESS SAA has zero failed days in 2024 and one failed day per seed in 2025. Minimax is more reliable for V2G without BESS in most tested cases, but this does not extend uniformly to BESS operation.

All 100 cases completed. Independent checks passed for source, configuration, code and weather hashes; daily hash chains and date coverage; all 36,550 physical trajectories; and 300 predetermined full-day dispatch LP checks. Emergency energy is diagnostic unmet supply: any positive shortage above tolerance counts as a failure of the original model.

Counts below use monthly plus current-solar forecasts for BESS and monthly forecasts without BESS. Trip profiles and asset decisions were fitted on 2023 only. Each triplet is seeds 11 / 29 / 47, not three independent weather years. The single deterministic mean baseline uses an older, unmatched route pool and is secondary evidence.

| Configuration | Policy | Failed days, 2024 / 366 | Failed days, 2025 / 365 |
|---|---|---:|---:|
| Charge-only + BESS | SAA24 | 2 / 2 / 2 | 6 / 4 / 6 |
| Charge-only + BESS | Minimax24 | 9 / 13 / 10 | 11 / 12 / 12 |
| Charge-only + BESS | Reduction 24→8 | 2 / 2 / 1 | 5 / 5 / 5 |
| Charge-only + BESS | Mean (unmatched pool) | 1 | 5 |
| V2G, no BESS | SAA24 | 9 / 12 / 10 | 13 / 13 / 12 |
| V2G, no BESS | Minimax24 | 0 / 0 / 0 | 0 / 2 / 0 |
| V2G, no BESS | Reduction 24→8 | 9 / 13 / 19 | 13 / 15 / 17 |
| V2G, no BESS | Mean (unmatched pool) | 111 | 106 |
| V2G + BESS | SAA24 | 0 / 0 / 0 | 1 / 1 / 1 |
| V2G + BESS | Minimax24 | 8 / 7 / 11 | 9 / 10 / 13 |
| V2G + BESS | Reduction 24→8 | 1 / 0 / 2 | 1 / 0 / 2 |
| V2G + BESS | Mean (unmatched pool) | 0 | 0 |

For V2G+BESS SAA in 2024, mean daily costs across seeds are 3545.12, 3544.34 and 3549.41 in the benchmark cost units. Seed 11’s 95% block-bootstrap interval is [2638.46, 4442.06]. In 2025 each seed fails 1/365 days (0.274%); the corresponding empirical block interval is [0%, 0.822%]. An unconditional finite mean cost is not reported for a policy-year with any infeasible day.

The full machine-readable table contains all 100 cases and both forecasts, cost quantiles and intervals when the whole year is feasible, shortage distributions, failure intervals, and paired forecast comparisons. Conditional cost savings explicitly retain the jointly feasible-day denominator. The bootstrap uses 2,000 circular 14-day blocks with seed 7291, separately by year. Intervals are conditional on these weather years and fixed fitted policies; a degenerate [0, 0] bootstrap interval for zero observed failures is not a population risk bound.

Actual scheduler allocation was 2.915 CPU-hours; recorded daily evaluation work totals 2.411 solver-call wall-hours. Requested one CPU per task, but accounting allocated two to some jobs; the former number uses actual AllocCPUS. The earlier source MIP pool gaps reach 3.000%. These are finite-pool results, not proofs for all integer routes.

Weather is the verified Open-Meteo BestMatch benchmark, fixed UTC−7, using the original endpoint-hour indexing. Current-slot average solar is assumed observed at dispatch. This is not a validated physical start-hour/DST deployment study or a homogeneous ERA5 station record.

Next controlled comparison: [matched deterministic/minimax tie-break protocol](../../campaigns/weather_fair_policy_wave7/PROTOCOL.md). It uses 2023 fitting and 2022 development only, with no alteration of this frozen 100-case holdout. No causal conclusion that SAA dominates deterministic planning is justified by the unmatched means above.

Evidence: [full results](holdout_results.json), accounting (original research artifact `snapshots/holdout_validation/accounting.psv`; not included in this export), validation script (original research artifact `diagnostics/validate_holdout.py`; not included in this export), [independent literature review](../../REVIEW.md), [original holdout protocol](../../weather_validation/FROZEN_HOLDOUT_PROTOCOL.md).
