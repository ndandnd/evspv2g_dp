# Reserve control and initial energy results

All 48 cases completed and passed independent validation. Reserving as much energy as possible removed all observed shortages in the 24 reserve-controller configurations, at a substantial cost. This establishes a useful controller mechanism, not an economical investment policy or a zero-risk guarantee.

Six fixed SAA24 bus profiles; 2023 forecast climatology; 365 previously inspected 2022 development days; capacities 5/20; common start/end fraction 0/0.5. Routes, generator capacity and required service remain fixed within every paired comparison. Current-slot average solar is assumed observable.

## Empty start with five battery units

All six source profiles are shown. Failure counts are out of 365 days. Cost increases compare reserve against baseline on exactly the dates both are feasible; failed dates remain in shortage statistics.

| Source fit | Seed | Baseline failures 5 units | Baseline failures 20 units | Reserve failures 5 units | Extra cost/day [95% interval] | Matched days |
|---|---:|---:|---:|---:|---:|---:|
| No BESS fit | 11 | 5 | 5 | 0 | 1286.7 [1100.2, 1455.9] | 360 |
| No BESS fit | 29 | 8 | 8 | 0 | 1323.1 [1152.9, 1476.3] | 357 |
| No BESS fit | 47 | 9 | 9 | 0 | 1283.2 [1106.0, 1436.1] | 356 |
| BESS fit | 11 | 11 | 11 | 0 | 1535.5 [1503.7, 1563.6] | 354 |
| BESS fit | 29 | 11 | 11 | 0 | 1539.0 [1509.3, 1566.1] | 354 |
| BESS fit | 47 | 13 | 11 | 0 | 1536.2 [1505.7, 1563.7] | 352 |

With five units and empty start, reserve control costs 29.1–33.7% more on the jointly feasible dates. With twenty units it costs 163.0–181.7% more. Maximizing current reserves can burn extra generation and sacrifice later solar headroom; these aggregate results motivate a bounded reserve target. We have not yet decomposed those two cost mechanisms.

Half-full initial storage reduces baseline failures to zero for the three schedules fitted without BESS, and two for each of the three schedules fitted with BESS, at both capacities. The same half-full state must be restored daily and replenishment is charged. This boundary is a sensitivity assumption; it does not establish that an operational fleet can always begin half full.

All 12 empty-start paired shortage/failure reductions have positive lower descriptive bootstrap endpoints. Six half-full comparisons have no baseline failures; six improve two failures, with zero-containing intervals. The 24 configurations share the same weather year and six related fitted schedules. Their outcomes are not independent replications, and no multiple-comparison correction is claimed.

## Complete treatment table

| Profile | Units | Initial fraction | Controller | Failures | Mean shortage | Conditional cost/day | Feasible days |
|---:|---:|---:|---|---:|---:|---:|---:|
| 11 | 5 | 0.0 | baseline | 5 | 0.036316 | 4002.35 | 360 |
| 11 | 5 | 0.0 | reserve_priority | 0 | 0.000000 | 5366.22 | 365 |
| 11 | 5 | 0.5 | baseline | 0 | 0.000000 | 4499.69 | 365 |
| 11 | 5 | 0.5 | reserve_priority | 0 | 0.000000 | 5315.35 | 365 |
| 11 | 20 | 0.0 | baseline | 5 | 0.036316 | 3553.27 | 360 |
| 11 | 20 | 0.0 | reserve_priority | 0 | 0.000000 | 9971.47 | 365 |
| 11 | 20 | 0.5 | baseline | 0 | 0.000000 | 3783.17 | 365 |
| 11 | 20 | 0.5 | reserve_priority | 0 | 0.000000 | 7887.97 | 365 |
| 14 | 5 | 0.0 | baseline | 8 | 0.066462 | 3923.51 | 357 |
| 14 | 5 | 0.0 | reserve_priority | 0 | 0.000000 | 5373.72 | 365 |
| 14 | 5 | 0.5 | baseline | 0 | 0.000000 | 4473.98 | 365 |
| 14 | 5 | 0.5 | reserve_priority | 0 | 0.000000 | 5322.85 | 365 |
| 14 | 20 | 0.0 | baseline | 8 | 0.070050 | 3486.05 | 357 |
| 14 | 20 | 0.0 | reserve_priority | 0 | 0.000000 | 9948.96 | 365 |
| 14 | 20 | 0.5 | baseline | 0 | 0.000000 | 3762.48 | 365 |
| 14 | 20 | 0.5 | reserve_priority | 0 | 0.000000 | 7915.47 | 365 |
| 17 | 5 | 0.0 | baseline | 9 | 0.047300 | 3994.14 | 356 |
| 17 | 5 | 0.0 | reserve_priority | 0 | 0.000000 | 5410.90 | 365 |
| 17 | 5 | 0.5 | baseline | 0 | 0.000000 | 4474.19 | 365 |
| 17 | 5 | 0.5 | reserve_priority | 0 | 0.000000 | 5360.03 | 365 |
| 17 | 20 | 0.0 | baseline | 9 | 0.047462 | 3551.36 | 356 |
| 17 | 20 | 0.0 | reserve_priority | 0 | 0.000000 | 10056.14 | 365 |
| 17 | 20 | 0.5 | baseline | 0 | 0.000000 | 3769.42 | 365 |
| 17 | 20 | 0.5 | reserve_priority | 0 | 0.000000 | 7972.65 | 365 |
| 21 | 5 | 0.0 | baseline | 11 | 0.024368 | 5270.89 | 354 |
| 21 | 5 | 0.0 | reserve_priority | 0 | 0.000000 | 6903.63 | 365 |
| 21 | 5 | 0.5 | baseline | 2 | 0.012252 | 5386.63 | 363 |
| 21 | 5 | 0.5 | reserve_priority | 0 | 0.000000 | 6852.75 | 365 |
| 21 | 20 | 0.0 | baseline | 11 | 0.021512 | 4356.33 | 354 |
| 21 | 20 | 0.0 | reserve_priority | 0 | 0.000000 | 11558.85 | 365 |
| 21 | 20 | 0.5 | baseline | 2 | 0.005358 | 3192.25 | 363 |
| 21 | 20 | 0.5 | reserve_priority | 0 | 0.000000 | 9495.38 | 365 |
| 24 | 5 | 0.0 | baseline | 11 | 0.023381 | 5270.95 | 354 |
| 24 | 5 | 0.0 | reserve_priority | 0 | 0.000000 | 6907.19 | 365 |
| 24 | 5 | 0.5 | baseline | 2 | 0.012252 | 5385.30 | 363 |
| 24 | 5 | 0.5 | reserve_priority | 0 | 0.000000 | 6856.31 | 365 |
| 24 | 20 | 0.0 | baseline | 11 | 0.021512 | 4356.00 | 354 |
| 24 | 20 | 0.0 | reserve_priority | 0 | 0.000000 | 11562.40 | 365 |
| 24 | 20 | 0.5 | baseline | 2 | 0.002427 | 3192.94 | 363 |
| 24 | 20 | 0.5 | reserve_priority | 0 | 0.000000 | 9498.94 | 365 |
| 27 | 5 | 0.0 | baseline | 13 | 0.029039 | 5257.30 | 352 |
| 27 | 5 | 0.0 | reserve_priority | 0 | 0.000000 | 6900.41 | 365 |
| 27 | 5 | 0.5 | baseline | 2 | 0.009529 | 5395.40 | 363 |
| 27 | 5 | 0.5 | reserve_priority | 0 | 0.000000 | 6849.54 | 365 |
| 27 | 20 | 0.0 | baseline | 11 | 0.024773 | 4358.67 | 354 |
| 27 | 20 | 0.0 | reserve_priority | 0 | 0.000000 | 11555.63 | 365 |
| 27 | 20 | 0.5 | baseline | 2 | 0.007763 | 3192.64 | 363 |
| 27 | 20 | 0.5 | reserve_priority | 0 | 0.000000 | 9492.16 | 365 |

Validation covered 17,520 physical trajectories, all journal/configuration identities and 144 independently constructed oracle LPs. Maximum replay residual 1.95e-14. All oracle cases have zero shortages. Full paired cost, probability, shortage and tail summaries are in validated_results.json and the exported CSVs. Intervals use 2,000 paired circular 14-day block resamples, seed 7291. Zero observed failures and zero-width empirical intervals are not population risk bounds.

Array 133707 and smoke 133695 consumed 2.692778 allocated CPU-hours. Daily solver-call timing totals 5300.19 seconds. Slurm allocated two CPUs to some jobs despite one requested; accounting uses the actual allocation. The separate public-code test 133696 consumed six allocated CPU-seconds. No CG or integer-MIP optimality claim is made by these continuous dispatch tests.

## Next gate

Define a bounded reserve target and compare cost versus shortage at identical capacity and initial conditions. Then test one-hour delayed observations and continuous day-to-day storage before locking the controller for fresh evaluation years. An investment claim subsequently requires matched integer planning on a common route pool, explicit asset amortization and an attained reliability target. Do not expand this maximum-reserve sweep or restart an empty monitor.
