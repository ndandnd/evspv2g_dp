# Matched fair-policy results — 2022 development

On identical route pools within each arm, V2G+BESS SAA with the frozen current-solar forecast saves **238.9–250.5 cost units/day** against the annual-mean deterministic policy, with all 365 days feasible for every seed. The minimax expected-cost tie-break reduces observed failures in both BESS arms, but does not uniformly lower causal cost or remove the cost tradeoff.

The completed campaign contains 30 policies and 50 evaluations: annual-mean deterministic, SAA24, minimax24, and minimax24 with expected-cost tie-break, with seeds 11, 29 and 47 for the sampled methods. Fitting uses 2023; evaluation uses 2022 development. All ten policies within each arm share one frozen pool: 313 solar+BESS columns, 1,919 V2G/noBESS columns, or 419 V2G+BESS columns. Pools differ across arms. The [validated results JSON](validated_results.json) contains all seeds, both forecasts, shortages, cost comparisons, uncertainty intervals, and solver certificates.

Failure counts below are out of 365 days. Triples follow seed order **11 / 29 / 47**; the deterministic policy has one fit. A failure means daily emergency energy exceeds `1e-6`.

| Arm | Policy | Monthly forecast | Current-solar forecast |
|---|---|---:|---:|
| Solar+BESS | Annual mean | 0 | 0 |
| Solar+BESS | SAA24 | 2 / 3 / 3 | 2 / 2 / 3 |
| Solar+BESS | Minimax24 | 10 / 12 / 11 | 4 / 8 / 8 |
| Solar+BESS | Minimax24 + tie-break | 3 / 9 / 6 | 3 / 5 / 5 |
| V2G/noBESS | Annual mean | 100 | Equivalent |
| V2G/noBESS | SAA24 | 6 / 8 / 9 | Equivalent |
| V2G/noBESS | Minimax24 | 0 / 0 / 0 | Equivalent |
| V2G/noBESS | Minimax24 + tie-break | 0 / 0 / 0 | Equivalent |
| V2G+BESS | Annual mean | 0 | 0 |
| V2G+BESS | SAA24 | 2 / 1 / 1 | 0 / 0 / 0 |
| V2G+BESS | Minimax24 | 8 / 11 / 9 | 8 / 7 / 9 |
| V2G+BESS | Minimax24 + tie-break | 6 / 6 / 6 | 4 / 4 / 4 |

NoBESS has no intertemporal stationary dispatch, so the two forecast rules are equivalent and only monthly was evaluated. Its oracle failures equal its causal failures. Every BESS policy is feasible under the daily perfect-information oracle; its causal failures therefore arise under the frozen controller and forecast assumptions.

For V2G+BESS with current-solar forecasts, the deterministic baseline costs **3,412.91/day**. Each paired comparison below includes all 365 days:

| SAA24 seed | Mean cost/day | Savings/day | Paired 95% interval for savings |
|---|---:|---:|---:|
| 11 | 3,162.41 | 250.50 | 153.11 to 348.02 |
| 29 | 3,163.78 | 249.13 | 152.77 to 346.64 |
| 47 | 3,174.03 | 238.89 | 144.67 to 331.86 |

Intervals use 2,000 paired circular-block resamples, 14-day blocks, seed 7291. They describe this development-year comparison; empirical zero failures, including bootstrap intervals of zero width, do not establish zero future risk.

The tie-break's causal cost effect is mixed. For V2G+BESS with current-solar forecasts, paired savings versus pure minimax are **−6.66**, **8.87**, and **35.02/day** for seeds 11, 29 and 47, with 95% intervals **[−10.20, −3.46]**, **[0.35, 18.07]**, and **[21.06, 49.41]**. These comparisons use 357, 358 and 356 jointly feasible days, respectively. They exclude failed days and do not price emergency energy. The tie policies' full-year perfect-information oracle mean remains about **6,619.54/day**, while the SAA causal policies above serve every day at 3,162.41–3,174.03/day. Resolving minimax degeneracy therefore does not eliminate the observed cost tradeoff.

Costs for policies with failures must remain conditional on explicitly reported feasible support; the JSON supplies an unconditional `mean_cost` only when all days are feasible and paired savings on jointly feasible days otherwise. Failure and shortage statistics retain all days. Comparing separate feasible-day averages without matching dates can distort the ranking.

The mathematical guarantee concerns sampled, full-day perfect-information training recourse with shared truck profiles, integer BESS count and common cyclic initial state. It does not guarantee causal performance; the causal controller assumes the current slot's average solar is observable. All nine tie-break primary solves have zero reported gap and match the corresponding pure minimax objectives within numerical precision. Stage 2 minimizes sampled mean cost under the stage-1 incumbent plus `1e-5`; its bound applies only to that constrained finite-pool problem. No complete-route integer proof or source-pool bound transfers. The three V2G/noBESS SAA solves retain gaps of **1.45%, 1.72% and 2.41%**, so their incumbent rankings are not rankings of certified SAA optima.

Validation covered **60 native solution vectors, 18,250 daily physical replays, 150 independent oracle checks, and all 30 rounded training policies**. Three rounding-sensitive tie policies were separately cross-checked: rounded commitments remain feasible, preserve matched minimax worst cost within `1.82e-12`, and alter reported mean cost by at most `0.000106/day`. See the [formulation audit](../../diagnostics/FAIR_POLICY_AUDIT.md) and [rounding checks](../../diagnostics/fair_rounded_tie_checks.json). Measured allocated CPU usage was **3.19 hours**; native optimization runtime totaled **2,872.21 seconds**. Each policy had a requested 900-second native solver budget; actual maximum runtime was 900.035 seconds.

The next gate, now submitted, is a **nested 64-scenario comparison** on these identical frozen pools, preserving seeds 11/29/47, 2023 fitting, 2022 development evaluation, and the 900-second solver budget. It will test sensitivity to expanding the sampled training set while reusing the wave-7 deterministic fits. Preparation array **951353**, MIP array **951354** (27 policies) and dependent evaluation array **951692** (45 cases) were submitted on 12 September. The three deterministic baselines are reused. This is not a new-year holdout result.
