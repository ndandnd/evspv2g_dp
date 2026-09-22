# BESS robustness under controlled solar variability

All **90 cases / 32,850 daily trajectories** passed independent validation. The extra mean-shortage reduction from BESS under variable rather than predictable solar is positive in **24 of 24** profile/capacity comparisons, negative in **0**, and numerically zero in 0. The descriptive paired 95% interval is wholly positive in 0. These are related sensitivity comparisons on one development population, not independent hypothesis tests.

**Scope:** each bus schedule stays fixed; all treatments preserve exactly the same monthly solar mean. Batteries start and finish empty. The controller observes current-slot average solar, uses the population monthly mean and its frozen current-solar update, and does not see future realizations. These are synthetic 2022 development counterfactuals, not new holdout savings or an optimal investment recommendation.

The primary interaction is `[shortage(0 batteries, variable) − shortage(n, variable)] − [shortage(0 batteries, predictable) − shortage(n, predictable)]`. Positive means variability increased the mean energy-shortage reduction provided by storage. Energy uses the reference model units.

| Source bus policy | Battery units | Extra mean-shortage reduction under variability | Paired 95% interval | Extra failed-day reduction, percentage points |
|---|---:|---:|---|---:|
| 11 | 5 | 0.001753 | 0.000000 to 0.003807 | 0.274 |
| 11 | 10 | 0.001753 | 0.000000 to 0.003807 | 0.274 |
| 11 | 20 | 0.001753 | 0.000000 to 0.003807 | 0.274 |
| 11 | 30 | 0.001753 | 0.000000 to 0.003807 | 0.274 |
| 14 | 5 | 0.016821 | 0.000000 to 0.043836 | 0.000 |
| 14 | 10 | 0.013234 | 0.000000 to 0.031191 | 0.000 |
| 14 | 20 | 0.013234 | 0.000000 to 0.031191 | 0.000 |
| 14 | 30 | 0.013234 | 0.000000 to 0.031191 | 0.000 |
| 17 | 5 | 0.007310 | 0.000000 to 0.017579 | 0.000 |
| 17 | 10 | 0.007147 | 0.000000 to 0.017097 | 0.000 |
| 17 | 20 | 0.007147 | 0.000000 to 0.017097 | 0.000 |
| 17 | 30 | 0.007147 | 0.000000 to 0.017097 | 0.000 |
| 21 | 5 | 0.087193 | -0.018705 to 0.200669 | -0.548 |
| 21 | 10 | 0.091932 | -0.014713 to 0.207110 | -0.274 |
| 21 | 20 | 0.090422 | -0.017915 to 0.205604 | -0.548 |
| 21 | 30 | 0.090422 | -0.017915 to 0.205604 | -0.548 |
| 24 | 5 | 0.088408 | -0.018534 to 0.202300 | -0.548 |
| 24 | 10 | 0.091932 | -0.014713 to 0.207110 | -0.274 |
| 24 | 20 | 0.090422 | -0.017915 to 0.205604 | -0.548 |
| 24 | 30 | 0.090422 | -0.017915 to 0.205604 | -0.548 |
| 27 | 5 | 0.082352 | -0.020660 to 0.191589 | -1.096 |
| 27 | 10 | 0.086594 | -0.018060 to 0.197808 | -0.548 |
| 27 | 20 | 0.086594 | -0.018060 to 0.197808 | -0.548 |
| 27 | 30 | 0.086594 | -0.018060 to 0.197808 | -0.548 |

Policies 11/14/17 were originally optimized without BESS; 21/24/27 with BESS. Within each group, the training scenario seeds are 11/29/47. Their fleets and routes differ across profiles; all comparisons above are paired within the same profile. The six source profiles are sensitivity cases, not six independently observed weather years.

## All treatment outcomes

Failed-day counts include all 365 days. EENS is mean emergency energy. CVaR95 is the empirical worst-5% mean shortage, with fractional mass at the tail boundary. Mean cost is reported only when every day is feasible; otherwise it is left blank. Fixed route and battery costs use the benchmark coefficients. No monetary value was assigned to emergency energy.

| Source | Batteries | Variability | Failed days | EENS | CVaR95 shortage | Oracle EENS | Mean cost, all days feasible |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 11 | 0 | 0.0 | 0 | 0.000000 | 0.000000 | 0.000000 | 4849.731 |
| 11 | 0 | 0.5 | 0 | 0.000000 | 0.000000 | 0.000000 | 4874.962 |
| 11 | 0 | 1.0 | 6 | 0.038068 | 0.761368 | 0.038068 | — |
| 11 | 5 | 0.0 | 0 | 0.000000 | 0.000000 | 0.000000 | 3929.343 |
| 11 | 5 | 0.5 | 0 | 0.000000 | 0.000000 | 0.000000 | 3990.331 |
| 11 | 5 | 1.0 | 5 | 0.036316 | 0.726315 | 0.000000 | — |
| 11 | 10 | 0.0 | 0 | 0.000000 | 0.000000 | 0.000000 | 3275.210 |
| 11 | 10 | 0.5 | 0 | 0.000000 | 0.000000 | 0.000000 | 3352.993 |
| 11 | 10 | 1.0 | 5 | 0.036316 | 0.726315 | 0.000000 | — |
| 11 | 20 | 0.0 | 0 | 0.000000 | 0.000000 | 0.000000 | 3480.879 |
| 11 | 20 | 0.5 | 0 | 0.000000 | 0.000000 | 0.000000 | 3558.903 |
| 11 | 20 | 1.0 | 5 | 0.036316 | 0.726315 | 0.000000 | — |
| 11 | 30 | 0.0 | 0 | 0.000000 | 0.000000 | 0.000000 | 3840.879 |
| 11 | 30 | 0.5 | 0 | 0.000000 | 0.000000 | 0.000000 | 3918.903 |
| 11 | 30 | 1.0 | 5 | 0.036316 | 0.726315 | 0.000000 | — |
| 14 | 0 | 0.0 | 0 | 0.000000 | 0.000000 | 0.000000 | 4841.827 |
| 14 | 0 | 0.5 | 0 | 0.000000 | 0.000000 | 0.000000 | 4873.230 |
| 14 | 0 | 1.0 | 8 | 0.083631 | 1.672629 | 0.083631 | — |
| 14 | 5 | 0.0 | 0 | 0.000000 | 0.000000 | 0.000000 | 3907.191 |
| 14 | 5 | 0.5 | 0 | 0.000000 | 0.000000 | 0.000000 | 3959.812 |
| 14 | 5 | 1.0 | 8 | 0.066810 | 1.336207 | 0.000000 | — |
| 14 | 10 | 0.0 | 0 | 0.000000 | 0.000000 | 0.000000 | 3255.165 |
| 14 | 10 | 0.5 | 0 | 0.000000 | 0.000000 | 0.000000 | 3330.529 |
| 14 | 10 | 1.0 | 8 | 0.070398 | 1.407959 | 0.000000 | — |
| 14 | 20 | 0.0 | 0 | 0.000000 | 0.000000 | 0.000000 | 3480.781 |
| 14 | 20 | 0.5 | 0 | 0.000000 | 0.000000 | 0.000000 | 3554.577 |
| 14 | 20 | 1.0 | 8 | 0.070398 | 1.407959 | 0.000000 | — |
| 14 | 30 | 0.0 | 0 | 0.000000 | 0.000000 | 0.000000 | 3840.781 |
| 14 | 30 | 0.5 | 0 | 0.000000 | 0.000000 | 0.000000 | 3914.577 |
| 14 | 30 | 1.0 | 8 | 0.070398 | 1.407959 | 0.000000 | — |
| 17 | 0 | 0.0 | 0 | 0.000000 | 0.000000 | 0.000000 | 4884.544 |
| 17 | 0 | 0.5 | 0 | 0.000000 | 0.000000 | 0.000000 | 4914.169 |
| 17 | 0 | 1.0 | 9 | 0.054388 | 1.087764 | 0.054388 | — |
| 17 | 5 | 0.0 | 0 | 0.000000 | 0.000000 | 0.000000 | 3987.448 |
| 17 | 5 | 0.5 | 0 | 0.000000 | 0.000000 | 0.000000 | 4045.447 |
| 17 | 5 | 1.0 | 9 | 0.047078 | 0.941562 | 0.000000 | — |
| 17 | 10 | 0.0 | 0 | 0.000000 | 0.000000 | 0.000000 | 3340.912 |
| 17 | 10 | 0.5 | 0 | 0.000000 | 0.000000 | 0.000000 | 3417.778 |
| 17 | 10 | 1.0 | 9 | 0.047241 | 0.944821 | 0.000000 | — |
| 17 | 20 | 0.0 | 0 | 0.000000 | 0.000000 | 0.000000 | 3552.737 |
| 17 | 20 | 0.5 | 0 | 0.000000 | 0.000000 | 0.000000 | 3634.828 |
| 17 | 20 | 1.0 | 9 | 0.047241 | 0.944821 | 0.000000 | — |
| 17 | 30 | 0.0 | 0 | 0.000000 | 0.000000 | 0.000000 | 3912.737 |
| 17 | 30 | 0.5 | 0 | 0.000000 | 0.000000 | 0.000000 | 3994.828 |
| 17 | 30 | 1.0 | 9 | 0.047241 | 0.944821 | 0.000000 | — |
| 21 | 0 | 0.0 | 92 | 0.649879 | 3.788447 | 0.649879 | — |
| 21 | 0 | 0.5 | 98 | 0.676852 | 4.017429 | 0.676852 | — |
| 21 | 0 | 1.0 | 100 | 0.761279 | 4.452961 | 0.761279 | — |
| 21 | 5 | 0.0 | 0 | 0.000000 | 0.000000 | 0.000000 | 5255.593 |
| 21 | 5 | 0.5 | 6 | 0.003248 | 0.064965 | 0.000000 | — |
| 21 | 5 | 1.0 | 10 | 0.024207 | 0.484138 | 0.000000 | — |
| 21 | 10 | 0.0 | 0 | 0.000000 | 0.000000 | 0.000000 | 4311.550 |
| 21 | 10 | 0.5 | 5 | 0.002691 | 0.053814 | 0.000000 | — |
| 21 | 10 | 1.0 | 9 | 0.019468 | 0.389352 | 0.000000 | — |
| 21 | 20 | 0.0 | 0 | 0.000000 | 0.000000 | 0.000000 | 4348.580 |
| 21 | 20 | 0.5 | 5 | 0.002691 | 0.053814 | 0.000000 | — |
| 21 | 20 | 1.0 | 10 | 0.020978 | 0.419553 | 0.000000 | — |
| 21 | 30 | 0.0 | 0 | 0.000000 | 0.000000 | 0.000000 | 4708.580 |
| 21 | 30 | 0.5 | 5 | 0.002691 | 0.053814 | 0.000000 | — |
| 21 | 30 | 1.0 | 10 | 0.020978 | 0.419553 | 0.000000 | — |
| 24 | 0 | 0.0 | 92 | 0.649879 | 3.788447 | 0.649879 | — |
| 24 | 0 | 0.5 | 98 | 0.676852 | 4.017429 | 0.676852 | — |
| 24 | 0 | 1.0 | 100 | 0.761279 | 4.452961 | 0.761279 | — |
| 24 | 5 | 0.0 | 0 | 0.000000 | 0.000000 | 0.000000 | 5255.579 |
| 24 | 5 | 0.5 | 6 | 0.002724 | 0.054481 | 0.000000 | — |
| 24 | 5 | 1.0 | 10 | 0.022991 | 0.459823 | 0.000000 | — |
| 24 | 10 | 0.0 | 0 | 0.000000 | 0.000000 | 0.000000 | 4311.570 |
| 24 | 10 | 0.5 | 4 | 0.001639 | 0.032777 | 0.000000 | — |
| 24 | 10 | 1.0 | 9 | 0.019468 | 0.389352 | 0.000000 | — |
| 24 | 20 | 0.0 | 0 | 0.000000 | 0.000000 | 0.000000 | 4348.600 |
| 24 | 20 | 0.5 | 4 | 0.001639 | 0.032777 | 0.000000 | — |
| 24 | 20 | 1.0 | 10 | 0.020978 | 0.419553 | 0.000000 | — |
| 24 | 30 | 0.0 | 0 | 0.000000 | 0.000000 | 0.000000 | 4708.600 |
| 24 | 30 | 0.5 | 4 | 0.001639 | 0.032777 | 0.000000 | — |
| 24 | 30 | 1.0 | 10 | 0.020978 | 0.419553 | 0.000000 | — |
| 27 | 0 | 0.0 | 92 | 0.649879 | 3.788447 | 0.649879 | — |
| 27 | 0 | 0.5 | 98 | 0.676852 | 4.017429 | 0.676852 | — |
| 27 | 0 | 1.0 | 100 | 0.761279 | 4.452961 | 0.761279 | — |
| 27 | 5 | 0.0 | 0 | 0.000000 | 0.000000 | 0.000000 | 5255.557 |
| 27 | 5 | 0.5 | 4 | 0.001639 | 0.032777 | 0.000000 | — |
| 27 | 5 | 1.0 | 12 | 0.029047 | 0.580944 | 0.000000 | — |
| 27 | 10 | 0.0 | 0 | 0.000000 | 0.000000 | 0.000000 | 4311.549 |
| 27 | 10 | 0.5 | 4 | 0.001639 | 0.032777 | 0.000000 | — |
| 27 | 10 | 1.0 | 10 | 0.024806 | 0.496120 | 0.000000 | — |
| 27 | 20 | 0.0 | 0 | 0.000000 | 0.000000 | 0.000000 | 4348.578 |
| 27 | 20 | 0.5 | 4 | 0.001639 | 0.032777 | 0.000000 | — |
| 27 | 20 | 1.0 | 10 | 0.024806 | 0.496120 | 0.000000 | — |
| 27 | 30 | 0.0 | 0 | 0.000000 | 0.000000 | 0.000000 | 4708.578 |
| 27 | 30 | 0.5 | 4 | 0.001639 | 0.032777 | 0.000000 | — |
| 27 | 30 | 1.0 | 10 | 0.024806 | 0.496120 | 0.000000 | — |

Every reported failure is diagnostic emergency energy required by the modeled supply balance, not a recorded bus service incident. Half variability preserves mean and halves deviations; variance is one quarter. The oracle has full-day information and is a physical benchmark. Its shortage was verified nonincreasing with battery capacity. Causal-policy monotonicity was not imposed.

Intervals use the predeclared 2,000 paired circular 14-day resamples, seed 7291. They are descriptive for the synthetic development population. Zero observed failures and zero-width bootstrap intervals do not imply zero future risk. Cost comparisons involving failed days must retain the jointly feasible support; the full records retain every shortage and cost.

Validation covered source/manifest identity, all journals and trajectories, analytical no-storage shortage, 270 independently formulated LP checks and oracle capacity nesting. Maximum replay residual: 7.99e-15. Recorded main daily solver work: 1.933 hours; Slurm allocation including both smoke tasks: 3.229 CPU-hours. Source policy training and local preparation are earlier/additional costs. No Gurobi MIP or CG optimality certificate is created by this dispatch study.

**Investment remains a separate question.** Reoptimize common fleet/charging commitments, integer storage quantity and the declared initial-state policy on matched route pools; include annualized asset costs and a stated reliability target. Evaluate selected designs on independent weather. This mechanism test does not establish how many batteries should be bought, nor that larger variability always increases the economic marginal value of storage.

[Validated records and all intervals](validated_results.json) · [Protocol](../../campaigns/bess_robustness_wave12/PROTOCOL.md) · [Source code and earlier evidence briefing](../../bess_hypothesis_20260913/BRIEFING.md).
