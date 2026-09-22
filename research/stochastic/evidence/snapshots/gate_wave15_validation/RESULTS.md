# Gate wave 15 results: value of vehicle-side charging adaptivity, and stronger deterministic baselines

Launched 17 September 2026 22:13 EDT, complete by 19 September. Protocol: `campaigns/gate_oracle_wave15/PROTOCOL.md`. Code: `gate_wave15/`. All 48 oracle cases, 54 MIPs and 108 evaluations completed; total allocation about 2.9 CPU-hours (0.51 oracle including the duplicate array, 1.76 MIP, 0.63 evaluation). Every oracle case reproduced the wave-7 fixed-profile oracle exactly when the truck variables were pinned (first three days of each case), and the adaptive oracle never exceeded the fixed one in shortage or cost on any day. Development data only (2023 fitting, 2022 evaluation); perfect-information oracles, not causal policies. Causal evaluation of the selected baselines is in `gate_causal_wave15` (see addendum below when complete).

## A. Fixed-profile versus fixed-skeleton adaptive-charging oracle (2022, 365 days)

| Arm | Plan | Cap | Fixed failures | Adaptive failures | Fixed cost (joint days) | Adaptive cost (joint days) | Saving/day [95% block CI] | Saving % |
|---|---|---|---|---|---|---|---|---|
| Solar + BESS | mean | 0.8 | 0 | 0 | 3,497.67 | 3,497.36 | 0.31 [0.03, 0.78] | 0.01 |
| Solar + BESS | SAA24 (3 seeds) | 0.8 | 0 | 0 | 3,142–3,158 | 3,142–3,158 | 0.01–0.02 | 0.00 |
| V2G + BESS | mean | 0.8 | 0 | 0 | 3,341.68 | 3,340.02 | 1.65 [0.16, 3.87] | 0.05 |
| V2G + BESS | SAA24 (3 seeds) | 0.8 | 0 | 0 | 3,094–3,098 | 3,094–3,098 | 0.03–0.04 | 0.00 |
| V2G, no BESS | mean | 0.8 | 100 | 0 | 4,140.50 (265 d) | 4,074.99 (265 d) | 65.51 [32.52, 106.83] | 1.58 |
| V2G, no BESS | SAA24 seed 11 | 0.8 | 6 | 0 | 4,879.72 (359 d) | 4,694.00 | 185.73 [155.08, 219.35] | 3.81 |
| V2G, no BESS | SAA24 seed 29 | 0.8 | 8 | 0 | 4,854.87 (357 d) | 4,661.05 | 193.82 [155.64, 236.67] | 3.99 |
| V2G, no BESS | SAA24 seed 47 | 0.8 | 9 | 0 | 4,885.58 (356 d) | 4,653.14 | 232.44 [202.21, 264.10] | 4.76 |

All-day adaptive-oracle cost in the no-BESS arm at cap 0.8 (zero failures for every plan): mean plan 4,808.81; SAA24 4,790.12 for all three seeds. Caps 1.0 and uncapped give the same pattern (BESS arms 0.00–0.05%, no-BESS 3.7–4.6% for SAA, 2.2% for the mean plan). Full table: `oracle_rows.json`, `campaigns/gate_oracle_wave15/cases/*/days.jsonl`.

Reading: with stationary storage available at the tested price (36/day per 700 kWh unit, 18–23 units bought), full-information adaptive vehicle charging is worth nothing; the BESS already absorbs the weather. When the fleet is the only storage, adaptive charging removes every failure and saves 3.7–4.8% of daily cost for SAA plans, and turns the mean-day plan from 100 failed days into zero. Even then the no-BESS fleet costs about 50% more per day than fleet plus BESS.

## B. Deterministic baselines and matched capacity (frozen wave-7 pools, cap 0.8, 900 s Gurobi)

Selection of the monthly plan uses 2023 only (lowest fixed-oracle cost among plans with zero 2023 failures). 2022 fixed-oracle mean cost, all 365 days feasible unless stated:

| Arm | Annual-mean plan | Selected month (2023 rule) | SAA24 seeds 11 / 29 / 47 | SAA vs selected month | Best month in 2022 hindsight |
|---|---|---|---|---|---|
| Solar + BESS | 3,497.67 (Nb 20) | April: 3,149.72 (Nb 22) | 3,157.85 / 3,144.71 / 3,142.33 | −0.26% / +0.16% / +0.23% | April 3,149.72 |
| V2G + BESS | 3,341.68 (Nb 18) | August: 3,095.08 (Nb 20) | 3,094.52 / 3,096.17 / 3,098.46 | +0.02% / −0.04% / −0.11% | April 3,085.85 |

Matched-capacity controls (2022 fixed-oracle cost):

| Arm | Control | Nb | Cost | Comment |
|---|---|---|---|---|
| Solar + BESS | mean plan, Nb forced to 22 / 23 | 22 / 23 | 3,267.91 / 3,296.49 | recovers about two thirds of the mean-to-SAA gap |
| Solar + BESS | SAA24 (3 seeds), Nb forced to 20 | 20 | 3,232.78 / 3,229.21 / 3,228.35 | SAA keeps about three quarters of its gain with the mean plan's storage |
| V2G + BESS | mean plan, Nb forced to 20 | 20 | 3,600.97 | worse than the mean plan itself (3,341.68) |
| V2G + BESS | SAA24 (3 seeds), Nb forced to 18 | 18 | 3,152.99 / 3,115.13 / 3,144.47 | SAA keeps 76–92% of its gain with the mean plan's storage |

Quantile-day plans (2023 day at the 10th / 25th / 50th irradiance percentile) buy 5–11 / 9–11 / 18–21 units and cost 5,362–5,467 / 4,559–4,682 / 3,510–3,511 in 2022: a dark planning day is not a conservative plan, it is a plan with no storage.

No-BESS arm: monthly plans fail 100–106 of 365 days with fixed profiles except January, November and December (9–14 trucks; December has zero failures at 5,789/day). Nine of the 15 no-BESS MIPs hit the 900 s limit with pool gaps 0.2–3.1%.

Reading: the 7% advantage of SAA over the annual-mean plan reported in wave 7 is an artifact of that baseline. Against the submitted paper's own training-selected monthly profile, SAA is within ±0.3% in both BESS arms. Most of what SAA gains over the annual-mean plan is in the truck profiles and initial storage state, not the storage count.

## Decision under the registered rule

Continue with adaptive columns only for the regime in which stationary storage is absent, capacity-limited, or priced well above 36/day per unit: there the adaptive oracle satisfies both continuation conditions (>= 3% and all failures removed). In the BESS arms the adaptive gain is below 0.1%, and the common-profile SAA gain over a well-chosen deterministic day is below 0.3%. The next experiment is therefore a BESS price and capacity sweep with both oracles, to locate the substitution frontier, before any pricing implementation.

## Addendum: causal-controller check of the baselines (`gate_causal_wave15`, job 585521, 22 cases, 1.12 CPU-h)

Frozen wave-7 controller (holdout_dispatch_v3), 2022, 365 days, monthly and monthly-plus-current-solar forecasts fitted on 2023. Reference under the current-solar forecast (wave 7): V2G+BESS annual-mean plan 3,412.91 (0 failures), SAA24 3,162.41 / 3,163.78 / 3,174.03 (0 failures); Solar+BESS annual-mean 3,569.50 (0), SAA24 2 / 2 / 3 failures.

| Plan | Forecast | Failed days | Mean cost (all days) | Cost on feasible days | Oracle |
|---|---|---|---|---|---|
| V2G+BESS month08 | current solar | 0 | 3,162.04 | 3,162.04 | 3,095.08 |
| V2G+BESS month08 | monthly | 2 | — | 3,140.34 | 3,095.08 |
| Solar+BESS month04 | current solar | 1 | — | 3,204.21 | 3,149.72 |
| Solar+BESS month04 | monthly | 2 | — | 3,198.72 | 3,149.72 |
| V2G+BESS SAA24 Nb=18 (seeds 11/29/47) | current solar | 0/0/0 | 3,238.26 / 3,189.53 / 3,212.21 | same | 3,152.99 / 3,115.13 / 3,144.47 |
| V2G+BESS mean Nb=20 | current solar | 0 | 3,674.80 | same | 3,600.97 |
| Solar+BESS SAA24 Nb=20 (seeds 11/29/47) | current solar | 1/1/1 | — | 3,304.13 / 3,286.61 / 3,287.06 | 3,232.78 / 3,229.21 / 3,228.35 |
| Solar+BESS mean Nb=22 / 23 | current solar | 0 / 0 | 3,345.37 / 3,376.39 | same | 3,267.91 / 3,296.49 |

The month-selected plan reproduces the whole causal saving previously attributed to SAA in the V2G+BESS arm and matches SAA's reliability in the Solar+BESS arm. SAA forced to the mean plan's storage count keeps 70–90% of its causal gain. Full records: `campaigns/gate_causal_wave15/cases/*/days.jsonl` and `status.json`.
