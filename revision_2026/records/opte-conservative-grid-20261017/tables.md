## Grid mapping of every energy quantity (true kWh -> grid kWh)

| step | rule | capacity | charge per block | discharge per block | task | deadheads | start / end / minimum SoC |
|---|---|---|---|---|---|---|---|
| 25 (exact25) | nearest | 700 -> 700 | 175 -> 175 | 175 -> 175 | 200 -> 200 | 50 -> 50, 100 -> 100 | 700 / 700 / 0 |
| 50 (cons50) | conservative | 700 -> 700 | 175 -> 150 | 175 -> 150 | 200 -> 200 | 50 -> 50, 100 -> 100 | 700 / 700 / 0 |
| 20 (cons20) | conservative | 700 -> 700 | 175 -> 160 | 175 -> 160 | 200 -> 200 | 50 -> 60, 100 -> 100 | 700 / 700 / 0 |
| 20 (near20) | nearest | 700 -> 700 | 175 -> 160 | 175 -> 160 | 200 -> 200 | 50 -> 40, 100 -> 100 | 700 / 700 / 0 |
| 10 (cons10) | conservative | 700 -> 700 | 175 -> 170 | 175 -> 170 | 200 -> 200 | 50 -> 50, 100 -> 100 | 700 / 700 / 0 |
| 10 (rate160_10) | conservative | 700 -> 700 | 160 -> 160 | 160 -> 160 | 200 -> 200 | 50 -> 50, 100 -> 100 | 700 / 700 / 0 |

## LP value relative to the exact value (frozen DP, 25 kWh), six bases

| arm | step kWh | block limit used kWh | LP vs exact, min .. max (%) | route columns replayed | physically infeasible | LP-support columns infeasible / support | columns that stop charging when full | real SoC below grid SoC (events) | CG s, 6 bases |
|---|---|---|---|---|---|---|---|---|---|
| frozen25 | 25 | 175 | +0.000 .. +0.000 | n/a (frozen DP keeps no trace) | | | | | 77.6 |
| exact25 | 25 | 175 | +0.000 .. +0.000 | 2817 | 0 | 0 / 806 | 0 | n/a | 159.0 |
| cons25 | 25 | 175 | +0.000 .. +0.000 | 2817 | 0 | 0 / 806 | 0 | 0 | 78.1 |
| cons50 | 50 | 150 | +0.647 .. +0.802 | 2841 | 0 | 0 / 811 | 0 | 0 | 72.1 |
| cons10 | 10 | 170 | +0.156 .. +0.450 | 3133 | 0 | 0 / 810 | 0 | 0 | 111.0 |
| cons20 | 20 | 160 | +11.054 .. +16.404 | 2475 | 0 | 0 / 813 | 1715 | 0 | 96.3 |
| near20 | 20 | 160 | -4.614 .. -2.777 | 2920 | 2160 | 804 / 804 | 0 | n/a | 78.8 |
| rate160_10 | 10 | 160 | +0.461 .. +0.619 | 3059 | 0 | 0 / 810 | 0 | 0 | 106.0 |

## Per base: 20 kWh conservative in detail

| n | seed | exact LP (25 kWh) | cons 20 LP | % | same routes, paying only for energy stored (re-solved LP) | % | trucks in LP exact / cons | fossil kWh in LP exact / cons | nearest 20 LP (% , infeasible routes in LP support) | 10 kWh grid with 160 kWh limit (%) |
|---|---|---|---|---|---|---|---|---|---|---|
| 60 | 0 | 3,553.787 | 4,136.742 | +16.40 | 3,907.360 | +9.95 | 20.00 / 20.04 | 5,300 / 6,800 | -4.19, 58/58 | +0.51 |
| 120 | 0 | 9,578.541 | 10,764.800 | +12.38 | 10,285.967 | +7.39 | 29.22 / 36.81 | 19,755 / 22,580 | -3.29, 129/129 | +0.60 |
| 200 | 0 | 17,709.761 | 19,729.225 | +11.40 | 18,930.057 | +6.89 | 51.19 / 54.13 | 38,480 / 43,200 | -2.90, 205/205 | +0.60 |
| 60 | 1 | 3,712.836 | 4,123.247 | +11.05 | 3,897.647 | +4.98 | 16.00 / 20.00 | 5,400 / 6,800 | -4.61, 60/60 | +0.46 |
| 120 | 1 | 9,532.465 | 10,805.720 | +13.36 | 10,334.956 | +8.42 | 34.41 / 37.25 | 19,403 / 22,400 | -3.09, 136/136 | +0.62 |
| 200 | 1 | 17,663.161 | 19,836.100 | +12.30 | 19,029.273 | +7.73 | 52.57 / 56.50 | 38,207 / 43,200 | -2.78, 216/216 | +0.62 |

## Restricted route MIP (integer), exact 25 kWh pool vs conservative 20 kWh pool

Gurobi, cold, truck columns only, Threads 1, Seed 0, MIPGap 1e-6, 600 s. Both values are restricted-pool heuristics (price-and-branch), not proven integer optima of the full model.

| n | seed | exact LP | MIP exact 25 (status, trucks, s) | MIP cons 20 (status, trucks, s) | MIP cons20 vs MIP exact (%) | MIP cons20 vs exact LP (%) | MIP cons 20, routes booked at stored energy (%) vs MIP exact | MIP-selected cons20 routes infeasible / selected | selected routes that stop when full | stored energy not drawn, kWh |
|---|---|---|---|---|---|---|---|---|---|---|
| 60 | 0 | 3,553.787 | 3,599.362 (optimal, 19, 0.3) | 4,221.275 (optimal, 21, 0.8) | +17.28 | +18.78 | +10.91 (optimal) | 0 / 21 | 20 | 600 |
| 120 | 0 | 9,578.541 | 10,022.887 (optimal, 33, 171.2) | 10,981.575 (optimal, 38, 66.1) | +9.56 | +14.65 | +4.81 (optimal) | 0 / 38 | 35 | 1220 |
| 200 | 0 | 17,709.761 | 18,722.263 (time_limit, 63, 600.2) | 20,697.320 (time_limit, 63, 600.1) | +10.55 | +16.87 | +5.87 (time_limit) | 0 / 63 | 47 | 1940 |
| 60 | 1 | 3,712.836 | 3,770.062 (optimal, 17, 0.4) | 4,152.320 (optimal, 20, 0.4) | +10.14 | +11.84 | +4.30 (optimal) | 0 / 20 | 20 | 600 |
| 120 | 1 | 9,532.465 | 9,725.163 (optimal, 36, 177.9) | 11,099.543 (optimal, 40, 40.5) | +14.13 | +16.44 | +9.28 (optimal) | 0 / 40 | 36 | 1180 |
| 200 | 1 | 17,663.161 | 18,322.375 (time_limit, 57, 600.1) | 20,633.385 (time_limit, 63, 600.1) | +12.61 | +16.82 | +8.05 (time_limit) | 0 / 63 | 51 | 1980 |

## Checks

- missing_runs: []
- errors: []
- all_converged_priced_out: True
- max_artificial_mass: 0.0
- exact25_minus_frozen25_max_abs: 0.0
- cons25_minus_frozen25_max_abs: 0.0
- max_abs_diff_vs_15oct_sweep: 0.0
- conservative_lp_at_or_above_exact: True
- resolved_executed_at_or_above_exact: True
- lp_master_checks_ok: True
- mip_exact_master_checks_ok: True
- lp_obj_recomputed_max_abs_diff: 2.546585164964199e-11
