# Nested 24-to-64 scenario experiment — validated results

Validated 2026-09-12T05:55:41.488472+00:00. Jobs 951353/951354/951692: all 75 scheduler stages completed, including 27 MIP policies and 45 development-year evaluations. The three deterministic mean policies and their five evaluations were authenticated and reused from wave 7.

**Increasing the sample size does not give a consistent improvement across methods and arms.** V2G+BESS SAA retains its matched deterministic cost advantage and zero failures on the 365 development days; the additional saving from 64 rather than 24 scenarios is modest and its paired intervals include zero for all three seeds. No-BESS SAA reliability improves in these runs, but the incumbents remain time-limited and one seed buys reliability at a substantial conditional cost increase. More scenarios do not remove the mismatch between full-day training recourse and causal dispatch.

This is a bounded development sensitivity check, not a new holdout or a population reliability guarantee. Training is 2023; evaluation is 2022. The frozen 2024/2025 study was not retuned or rerun.

## Main V2G+BESS SAA comparison

Current-solar forecast; all 365 days are feasible for each policy in this table. The unchanged matched deterministic mean costs 3,412.91 per day. Positive savings favor 64 scenarios. Costs are model monetary units per day.

| Seed | SAA24 cost/day | SAA64 cost/day | Saving: 24 → 64 (95% interval) | Saving: mean → 64 (95% interval) | SAA64 mean-cost 95% interval |
|---|---:|---:|---|---|---|
| 11 | 3,162.41 | 3,155.51 | 6.90 [-19.30, 38.59] | 257.41 [144.81, 367.87] | [2,247.43, 4,080.58] |
| 29 | 3,163.78 | 3,155.34 | 8.44 [-18.58, 41.07] | 257.57 [145.17, 368.73] | [2,247.36, 4,080.52] |
| 47 | 3,174.03 | 3,155.52 | 18.50 [-7.75, 49.28] | 257.39 [145.01, 368.44] | [2,247.71, 4,080.42] |

The SAA64 costs differ by less than 0.2/day across these three seeds. That is descriptive stability for this configuration and evaluation year, not proof of sample-size convergence or a guarantee about future weather.

## Reliability and cost tradeoffs across all methods

Current-solar forecast for BESS arms; monthly forecast for no BESS, where storage forecast adaptation is absent. Each slash-separated triplet is seeds 11 / 29 / 47. A failed day requires positive emergency energy in replay; its incomplete operating cost is not treated as a feasible total cost.

| Arm | Method | Failed days with 24 scenarios | Failed days with 64 scenarios |
|---|---|---|---|
| Solar + BESS | SAA | 2 / 2 / 3 | 3 / 2 / 3 |
| Solar + BESS | Minimax | 4 / 8 / 8 | 6 / 5 / 10 |
| Solar + BESS | Minimax + tie | 3 / 5 / 5 | 11 / 5 / 3 |
| V2G, no BESS | SAA | 6 / 8 / 9 | 5 / 6 / 0 |
| V2G, no BESS | Minimax | 0 / 0 / 0 | 0 / 0 / 0 |
| V2G, no BESS | Minimax + tie | 0 / 0 / 0 | 0 / 0 / 0 |
| V2G + BESS | SAA | 0 / 0 / 0 | 0 / 0 / 0 |
| V2G + BESS | Minimax | 8 / 7 / 9 | 12 / 6 / 7 |
| V2G + BESS | Minimax + tie | 4 / 4 / 4 | 4 / 4 / 4 |

- No-BESS SAA seed 47 goes from 9 failed days to zero, while costing 414.33 more per day on the 356 dates feasible under both policies (95% interval for the cost increase: 365.79–468.63). It is not an unqualified dominance result. Seeds 11 and 29 still fail 5 and 6 days.
- Minimax has zero no-BESS failures for both sample sizes but does not ensure zero failures with causal BESS dispatch. Its robustness applies to sampled full-day recourse, not every future causal trajectory.
- Expected-cost tie-breaking is also not a reliability guarantee: solar+BESS seed 11 goes from 3 to 11 failed days. Tiny numerical cost differences, including near-zero intervals, should not be promoted as operational improvements.

## Solver budget and certificate scope

| No-BESS SAA seed | 24-scenario finite-pool gap | 64-scenario finite-pool gap | Status |
|---|---:|---:|---|
| 11 | 1.445% | 1.951% | Time limit with validated incumbent, both sizes |
| 29 | 1.722% | 1.830% | Time limit with validated incumbent, both sizes |
| 47 | 2.408% | 3.000% | Time limit with validated incumbent, both sizes |

Actual allocation: **2.609 CPU-hours**, including preparation, MIPs and evaluation. Native MIP calls total **2847.44 seconds** (0.791 hours). The largest observed native total is 900.093s under a requested 900s limit. CPUTimeRAW reflects allocated CPUs × elapsed time, not measured busy CPU; some scheduler allocations have two CPUs despite a one-CPU request. MaxRSS was not available in the parent-job accounting extract.

All 24 remaining final MIPs report native optimal status within the requested 1e-6 relative tolerance. All nine tie-break primary gaps are 0.0; their second solve minimizes sampled mean cost under primary incumbent + 1e-5. Keep primary worst-cost bounds and conditional secondary mean-cost bounds separate. Native vectors and rounded deployed commitments were both checked; replayed training values are included because rounding can change objectives slightly.

The experiments share frozen pools of 313 / 1,919 / 419 columns within the three respective arms. They do not prove full-route integer optimality. The unresolved SAA gaps confound a claim about the exact sample-size optima: this comparison is between the policies returned under matched requested budgets.

## What to try next

| Priority | Action | Evidence it should produce | Stop condition |
|---|---|---|---|
| 1 | Consolidate the completed algorithm review into an isolated candidate: column/reconstruction validation and sparse scenario templates, followed by a persistent LP master. | Exact matrix/physical/objective parity and total assembly/LP/pricing time on a fixed easy/difficult panel. The review already measured 2.35–4.33× faster assembly in a local prototype. | Reject any certificate mismatch or speedup that vanishes in total runtime. |
| 2 | Separate no-BESS MIP search quality from statistical sample quality using the same frozen pools and a predeclared larger-budget diagnostic. | Incumbents and lower bounds versus elapsed time for the three difficult seeds; paired reliability/cost after improvement. Record this as a new campaign before submission. | Do not call a time-limited incumbent gap a weakness of the stochastic optimum. |
| 3 | Formalize adaptive charging at observed station arrival, with committed trip service and forecast-history nonanticipativity. | A small extensive-form/rolling-horizon control comparison against the existing fixed-profile baseline. | Reject gains that require observing unrevealed future weather or changing the required service. |
| 4 | Use public code selectively; defer a full branch-and-price tree until root-pool MIP/enrichment evidence justifies it. | Reproducible small author benchmark and a mapped V2G formulation before claiming reusable performance. | Do not transplant charge-only dominance or bounds into V2G without proof. |

No new jobs were launched during this validation. No active release, EVSP–DR campaign, route pool or held-out weather selection changed. See the [completed code review](../../code_review_20260912/README.md) and its source-linked public-code and DR-transfer tables.

## Validation and statistical interpretation

- Authenticated release, input/configuration identities, pool hashes, source baseline hashes and nested dates: each 64-day sample begins with exactly its former 24 days.
- Checked 54 saved native vectors, 1,728 independently constructed fixed-policy training LPs, selected truck-profile replay, all 16,425 daily physical trajectories and hash-chain entries, and 135 predetermined independent full-day oracle solves.
- Frozen paired circular block bootstrap: 14 days, 2,000 resamples, seed 7291. Intervals condition on a selected policy and one observed weather year; weather and seed replicates are not independent observed years. Empirical all-zero failure intervals are not population risk bounds.
- Cost comparisons below use exactly the jointly feasible dates and report that denominator. Full-year means and distributions are only reported if all 365 days are feasible. Failures and shortage are always retained.

## Complete paired sample-size table

Positive savings and positive failure-rate reduction favor 64 scenarios. Failure reduction intervals are percentage points. All methods, seeds and forecast variants are included.

| Arm | Method | Seed | Forecast | Failed days 24 → 64 | Failure-rate reduction 95% interval (pp) | Joint feasible days | Saving/day (95% interval) |
|---|---|---:|---|---|---|---:|---|
| Solar + BESS | SAA | 11 | Monthly | 2 → 3 | [-0.82, 0.00] | 362 | 17.41 [-12.76, 52.35] |
| Solar + BESS | SAA | 11 | Current solar | 2 → 3 | [-0.82, 0.00] | 362 | 14.66 [-13.69, 47.85] |
| Solar + BESS | Minimax | 11 | Monthly | 10 → 12 | [-1.37, 0.00] | 353 | 20.86 [10.06, 33.77] |
| Solar + BESS | Minimax | 11 | Current solar | 4 → 6 | [-1.92, 0.55] | 358 | 21.21 [9.39, 35.28] |
| Solar + BESS | Minimax + tie | 11 | Monthly | 3 → 12 | [-4.66, -0.55] | 353 | 3.15 [-3.07, 9.95] |
| Solar + BESS | Minimax + tie | 11 | Current solar | 3 → 11 | [-4.11, -0.55] | 354 | -2.31 [-6.76, 1.83] |
| Solar + BESS | SAA | 29 | Monthly | 3 → 3 | [0.00, 0.00] | 362 | -1.18 [-3.14, 0.46] |
| Solar + BESS | SAA | 29 | Current solar | 2 → 2 | [0.00, 0.00] | 363 | -0.02 [-2.10, 2.18] |
| Solar + BESS | Minimax | 29 | Monthly | 12 → 6 | [0.27, 3.29] | 353 | -8.32 [-27.71, 11.80] |
| Solar + BESS | Minimax | 29 | Current solar | 8 → 5 | [0.00, 1.64] | 356 | -25.06 [-41.71, -10.08] |
| Solar + BESS | Minimax + tie | 29 | Monthly | 9 → 6 | [-0.55, 2.47] | 355 | 9.68 [-4.14, 24.59] |
| Solar + BESS | Minimax + tie | 29 | Current solar | 5 → 5 | [-0.82, 0.82] | 359 | -5.19 [-11.48, 0.42] |
| Solar + BESS | SAA | 47 | Monthly | 3 → 3 | [0.00, 0.00] | 362 | 0.26 [-0.06, 0.69] |
| Solar + BESS | SAA | 47 | Current solar | 3 → 3 | [0.00, 0.00] | 362 | 0.09 [-0.37, 0.54] |
| Solar + BESS | Minimax | 47 | Monthly | 11 → 11 | [0.00, 0.00] | 354 | 2.89 [-4.61, 10.42] |
| Solar + BESS | Minimax | 47 | Current solar | 8 → 10 | [-1.37, 0.00] | 355 | 6.29 [2.57, 10.25] |
| Solar + BESS | Minimax + tie | 47 | Monthly | 6 → 3 | [0.00, 1.92] | 359 | -1.55 [-10.35, 6.80] |
| Solar + BESS | Minimax + tie | 47 | Current solar | 5 → 3 | [0.00, 1.37] | 360 | 2.29 [-1.96, 6.93] |
| V2G, no BESS | SAA | 11 | Monthly | 6 → 5 | [0.00, 0.82] | 359 | -5.00 [-24.32, 11.71] |
| V2G, no BESS | Minimax | 11 | Monthly | 0 → 0 | [0.00, 0.00] | 365 | 0.00 [-0.00, 0.00] |
| V2G, no BESS | Minimax + tie | 11 | Monthly | 0 → 0 | [0.00, 0.00] | 365 | 0.00 [-0.00, 0.00] |
| V2G, no BESS | SAA | 29 | Monthly | 8 → 6 | [-0.55, 1.64] | 356 | -1.75 [-15.39, 12.97] |
| V2G, no BESS | Minimax | 29 | Monthly | 0 → 0 | [0.00, 0.00] | 365 | 35.17 [24.14, 45.98] |
| V2G, no BESS | Minimax + tie | 29 | Monthly | 0 → 0 | [0.00, 0.00] | 365 | 0.00 [-0.00, 0.00] |
| V2G, no BESS | SAA | 47 | Monthly | 9 → 0 | [0.55, 4.66] | 356 | -414.33 [-468.63, -365.79] |
| V2G, no BESS | Minimax | 47 | Monthly | 0 → 0 | [0.00, 0.00] | 365 | 52.84 [28.59, 78.80] |
| V2G, no BESS | Minimax + tie | 47 | Monthly | 0 → 0 | [0.00, 0.00] | 365 | 45.58 [24.81, 67.70] |
| V2G + BESS | SAA | 11 | Monthly | 2 → 2 | [0.00, 0.00] | 363 | 9.77 [-17.86, 43.40] |
| V2G + BESS | SAA | 11 | Current solar | 0 → 0 | [0.00, 0.00] | 365 | 6.90 [-19.30, 38.59] |
| V2G + BESS | Minimax | 11 | Monthly | 8 → 12 | [-2.19, -0.27] | 353 | -13.61 [-23.21, -4.32] |
| V2G + BESS | Minimax | 11 | Current solar | 8 → 12 | [-2.19, -0.27] | 353 | -14.95 [-24.33, -6.08] |
| V2G + BESS | Minimax + tie | 11 | Monthly | 6 → 6 | [0.00, 0.00] | 359 | -0.00 [-0.00, -0.00] |
| V2G + BESS | Minimax + tie | 11 | Current solar | 4 → 4 | [0.00, 0.00] | 361 | -0.00 [-0.00, -0.00] |
| V2G + BESS | SAA | 29 | Monthly | 1 → 1 | [0.00, 0.00] | 364 | 9.74 [-17.99, 42.64] |
| V2G + BESS | SAA | 29 | Current solar | 0 → 0 | [0.00, 0.00] | 365 | 8.44 [-18.58, 41.07] |
| V2G + BESS | Minimax | 29 | Monthly | 11 → 7 | [0.00, 2.74] | 354 | -91.09 [-117.35, -65.36] |
| V2G + BESS | Minimax | 29 | Current solar | 7 → 6 | [0.00, 0.82] | 358 | -67.11 [-97.38, -40.06] |
| V2G + BESS | Minimax + tie | 29 | Monthly | 6 → 6 | [0.00, 0.00] | 359 | -0.01 [-0.01, -0.00] |
| V2G + BESS | Minimax + tie | 29 | Current solar | 4 → 4 | [0.00, 0.00] | 361 | -0.01 [-0.01, -0.00] |
| V2G + BESS | SAA | 47 | Monthly | 1 → 2 | [-0.82, 0.00] | 363 | 20.67 [-6.93, 53.16] |
| V2G + BESS | SAA | 47 | Current solar | 0 → 0 | [0.00, 0.00] | 365 | 18.50 [-7.75, 49.28] |
| V2G + BESS | Minimax | 47 | Monthly | 9 → 11 | [-1.92, 0.55] | 353 | 8.22 [2.84, 14.69] |
| V2G + BESS | Minimax | 47 | Current solar | 9 → 7 | [0.00, 1.37] | 356 | 9.00 [3.51, 15.47] |
| V2G + BESS | Minimax + tie | 47 | Monthly | 6 → 6 | [0.00, 0.00] | 359 | -0.00 [-0.00, -0.00] |
| V2G + BESS | Minimax + tie | 47 | Current solar | 4 → 4 | [0.00, 0.00] | 361 | -0.00 [-0.00, -0.00] |

Full costs/shortage quantiles, all intervals, primary/secondary bounds, native and rounded residuals, training costs, source hashes and budgets: [validated_results.json](validated_results.json). Editable exports: [paired comparisons](paired_comparisons.csv), [evaluation statistics](evaluation_statistics.csv), [policy budgets](policy_budgets.csv). Validator: validate_sample64.py (original research artifact `diagnostics/validate_sample64.py`; not included in this export).
