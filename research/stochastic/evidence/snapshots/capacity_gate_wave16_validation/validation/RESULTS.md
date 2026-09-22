# Capacity gate wave 16 validation

Status: **validated_complete**. 24/24 cases complete; 8760 daily records inspected.

Fixed reconstructed routes and assets within pairs; both full-day foresight; empty-cyclic BESS; 2022 development; no investment or causal optimum.

All source/identity/journal/summary checks passed. Nb=0 matches wave 15 on 1460 days; minimum-shortage and tied-shortage operating-cost nesting passed for 7300 adjacent-capacity day pairs.

| Policy | Nb | Fixed/adaptive failures | Joint days | Saving/day [95% calendar-block interval] | Saving % | Fixed/adaptive all-day costs |
|---|---:|---:|---:|---|---:|---|
| 10 | 0 | 100/0 | 265 | 65.51 [33.15, 105.08] | 1.58 | — / 4,808.81 |
| 10 | 1 | 31/0 | 334 | 36.19 [16.09, 62.16] | 0.84 | — / 4,643.45 |
| 10 | 2 | 1/0 | 364 | 19.03 [8.17, 33.90] | 0.42 | — / 4,482.95 |
| 10 | 5 | 0/0 | 365 | 5.95 [1.98, 11.66] | 0.15 | 4,038.25 / 4,032.30 |
| 10 | 10 | 0/0 | 365 | 2.29 [1.15, 3.94] | 0.07 | 3,438.96 / 3,436.66 |
| 10 | 20 | 0/0 | 365 | 1.23 [0.84, 1.72] | 0.03 | 3,662.44 / 3,661.20 |
| 11 | 0 | 6/0 | 359 | 185.73 [156.50, 220.19] | 3.81 | — / 4,790.12 |
| 11 | 1 | 0/0 | 365 | 89.26 [64.01, 118.05] | 1.90 | 4,705.18 / 4,615.91 |
| 11 | 2 | 0/0 | 365 | 75.73 [51.13, 102.16] | 1.67 | 4,526.31 / 4,450.59 |
| 11 | 5 | 0/0 | 365 | 61.85 [36.82, 88.63] | 1.53 | 4,045.77 / 3,983.91 |
| 11 | 10 | 0/0 | 365 | 25.95 [13.72, 40.78] | 0.76 | 3,398.73 / 3,372.77 |
| 11 | 20 | 0/0 | 365 | 2.99 [1.94, 4.42] | 0.08 | 3,605.38 / 3,602.39 |
| 14 | 0 | 8/0 | 357 | 193.82 [156.32, 237.57] | 3.99 | — / 4,790.12 |
| 14 | 1 | 2/0 | 363 | 79.50 [57.08, 105.33] | 1.71 | — / 4,615.91 |
| 14 | 2 | 0/0 | 365 | 63.75 [44.87, 84.74] | 1.41 | 4,514.34 / 4,450.59 |
| 14 | 5 | 0/0 | 365 | 46.14 [28.28, 65.58] | 1.14 | 4,030.05 / 3,983.91 |
| 14 | 10 | 0/0 | 365 | 10.84 [5.08, 17.73] | 0.32 | 3,383.62 / 3,372.77 |
| 14 | 20 | 0/0 | 365 | 1.73 [1.38, 2.17] | 0.05 | 3,604.12 / 3,602.39 |
| 17 | 0 | 9/0 | 356 | 232.44 [202.40, 264.17] | 4.76 | — / 4,790.12 |
| 17 | 1 | 1/0 | 364 | 158.98 [125.20, 194.03] | 3.34 | — / 4,615.91 |
| 17 | 2 | 0/0 | 365 | 139.00 [102.46, 177.34] | 3.03 | 4,589.59 / 4,450.59 |
| 17 | 5 | 0/0 | 365 | 121.85 [83.28, 162.73] | 2.97 | 4,105.76 / 3,983.91 |
| 17 | 10 | 0/0 | 365 | 88.29 [58.75, 119.03] | 2.55 | 3,461.07 / 3,372.77 |
| 17 | 20 | 0/0 | 365 | 75.56 [49.87, 101.62] | 2.05 | 3,677.95 / 3,602.39 |

Costs are conditional on the stated joint support unless all-day costs are shown. Intervals resample calendar dates before conditioning, using 14-day circular blocks and 2,000 replicates by default. Policies share the same development weather; seeds are not independent test populations. This does not establish causal gains, an optimal investment frontier or original-route recovery. The gap between fixed and adaptive optima need not be monotone in capacity.
