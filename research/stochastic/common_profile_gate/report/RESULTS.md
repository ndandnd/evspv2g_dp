# Common-profile gate: saved-output report

Status: **validated_complete**.

For source policy 17 (seed 47), fitting one common truck profile on 2022 removes **99.23%** of the inherited 75.5612-per-day oracle gap. Static retuning saves 74.9828 per day; the remaining common-profile-to-adaptive gap is **0.5784 per day**.

This result is conditional on the retained assets, reconstructed skeletons and 2022 development population, with full-day BESS/generator foresight. It does not measure attainable causal savings. The 2023-fit rows below are separate frozen-profile evaluations; same-population nesting is not asserted for them.

| Source policy / fit year | Old cost/day | Common cost/day | Adaptive oracle/day | Common − oracle/day | Failed days: old / common / oracle |
|---|---:|---:|---:|---:|---|
| 17 (seed 47) / 2022 | 3,677.9469 | 3,602.9640 | 3,602.3856 | 0.5784 | 0 / 0 / 0 (365 days) |
| 14 (seed 29) / 2022 | 3,604.1166 | 3,602.9640 | 3,602.3856 | 0.5784 | 0 / 0 / 0 (365 days) |
| 17 (seed 47) / 2023 | 3,677.9469 | 3,602.9702 | 3,602.3856 | 0.5846 | 0 / 0 / 0 (365 days) |
| 14 (seed 29) / 2023 | 3,604.1166 | 3,602.9702 | 3,602.3856 | 0.5846 | 0 / 0 / 0 (365 days) |

Overview costs and remaining gaps require every day to be feasible for all three arms; otherwise they are withheld. All costs include the same fixed assets.

A separate [cost-component audit](https://github.com/ndandnd/evspv2g_dp/blob/codex/stochastic-adaptation-gates/research/stochastic/common_profile_gate/report/COST_COMPONENTS.md) of these archived runs finds equal common/oracle fuel costs day by day; their small remaining gap is the model's throughput penalty. Reproduce that accounting with cost_components.py.

Bootstrap intervals are descriptive dependence sensitivity with fixed fitted profiles. They do not include training-fit uncertainty or policy-selection uncertainty. The 7/14/30-day circular block lengths use 1,000 replicates and seed 20260922; year-end wrapping is an approximation, not a seasonal or independent-weather model.

All cases replay 2022 development weather. Fits on 2022 are retrospective same-population mechanism tests; 2023 fits are frozen-profile cross-year comparisons, without a nesting guarantee or chronological deployment claim. BESS/generator recourse has full-day foresight; this is not a causal controller comparison.

Failed days remain in failure statistics. Every cost table uses dates jointly feasible for old, common and adaptive. When any day fails, those costs are conditional and do not establish all-day savings or a monetary nesting decomposition. Zero observed failures never guarantees zero future risk. Wilson intervals below are IID-only binomial benchmarks and are not calibrated for temporal dependence.

Full statistics, support dates, hashes and diagnostic fields are in [stats.json](stats.json). Input cases remain separate; seeds/source plans share weather and are not independent populations.

## policy17_nb20_fit2022

Status: **validated_complete**.

Evidence: [execution](../runs/attempt02/policy17_nb20_fit2022/execution.json); [fit](../runs/attempt02/policy17_nb20_fit2022/fit/result.json); [validation](../runs/attempt02/policy17_nb20_fit2022/validation.json); [status](../runs/attempt02/policy17_nb20_fit2022/replay2022/status.json); [journal](../runs/attempt02/policy17_nb20_fit2022/replay2022/days.jsonl); [identity](../runs/attempt02/policy17_nb20_fit2022/replay2022/identity.json).

retrospective development mechanism test. Cost support: all 365 calendar days.

| Arm | Failures / days | Failure probability | Wilson 95% IID-only benchmark | Mean shortage |
|---|---:|---:|---|---:|
| old | 0 / 365 | 0.000% | [0.000%, 1.041%] | 0.00000000 |
| common | 0 / 365 | 0.000% | [0.000%, 1.041%] | 0.00000000 |
| adaptive | 0 / 365 | 0.000% | [0.000%, 1.041%] | 0.00000000 |

Costs on the same 365 jointly feasible dates (fixed asset cost included):

| Arm | Mean | Median | 5th percentile | 95th percentile |
|---|---:|---:|---:|---:|
| old | 3,677.9469 | 1,745.3157 | 1,564.0398 | 8,932.0785 |
| common | 3,602.9640 | 1,744.5289 | 1,403.2671 | 8,931.4747 |
| adaptive | 3,602.3856 | 1,744.5205 | 1,402.8837 | 8,927.8974 |

| Signed paired cost difference | Mean | Median | 5th percentile | 95th percentile |
|---|---:|---:|---:|---:|
| old minus common | 74.9828 | 0.9934 | 0.4882 | 160.8314 |
| common minus adaptive | 0.5784 | 0.2062 | -0.0000 | 3.3632 |
| old minus adaptive | 75.5612 | 4.1651 | 0.6924 | 161.2807 |

Saved nesting asserted: **true**. same-population nesting decomposition.

Descriptive paired-mean interval sensitivity (full calendar sampled before cost conditioning):

| Circular block length | Old − common | Common − adaptive | Old − adaptive |
|---:|---|---|---|
| 7 days | [55.0991, 93.7998] (1000/1000) | [0.3871, 0.7874] (1000/1000) | [55.8143, 94.1612] (1000/1000) |
| 14 days | [48.3741, 100.6820] (1000/1000) | [0.3489, 0.8564] (1000/1000) | [49.0693, 101.3358] (1000/1000) |
| 30 days | [35.4322, 110.2625] (1000/1000) | [0.2819, 0.9794] (1000/1000) | [36.2523, 110.7067] (1000/1000) |

Failure-probability block intervals and arm cost-mean intervals are retained in stats.json. Parenthesized counts above are bootstrap replicates with nonempty shared cost support.

Native Gurobi fitting phases (floating-point optimality/KKT diagnostics, not exact rational or full-route integer certificates). Residuals use scientific notation. n/a means unavailable; native objective/bound values remain visible even when a reconstructed dual bound is undefined:

| Stage / phase | Native status | Runtime s | Native objective / bound | Max primal residual | KKT stationarity / complementarity / sign | Primal − dual | Log |
|---|---|---:|---:|---:|---|---:|---|
| inherited / shortage | OPTIMAL (2) | 0.590 | 0.00000000 / 0.00000000 | 2.842e-14 | 0.000e+00 / 0.000e+00 / 0.000e+00 | 0.000e+00 | [verified log](../runs/attempt02/policy17_nb20_fit2022/fit/inherited_shortage.log) |
| inherited / cost | OPTIMAL (2) | 1.003 | 2,282.94685475 / 2,282.94685475 | 1.421e-14 | 2.061e-13 / 1.947e-16 / 1.388e-17 | n/a | [verified log](../runs/attempt02/policy17_nb20_fit2022/fit/inherited_cost.log) |
| common / shortage | OPTIMAL (2) | 2.682 | 0.00000000 / 0.00000000 | 6.573e-14 | 0.000e+00 / 0.000e+00 / 0.000e+00 | 0.000e+00 | [verified log](../runs/attempt02/policy17_nb20_fit2022/fit/common_shortage.log) |
| common / cost | OPTIMAL (2) | 16.046 | 2,207.96404824 / 2,207.96404824 | 1.421e-14 | 1.980e-13 / 2.157e-11 / 1.388e-17 | n/a | [verified log](../runs/attempt02/policy17_nb20_fit2022/fit/common_cost.log) |

All 4 native phase-log hashes and the 365-day journal chain verified. Independent replay maximum residuals: old 7.105e-15, common 7.105e-15. Execution elapsed: 44.246 s. Execution commit: `f8f8101557f2ee2983f3cdc6e7369def28338ded`.

## policy14_nb20_fit2022

Status: **validated_complete**.

Evidence: [execution](../runs/attempt02/policy14_nb20_fit2022/execution.json); [fit](../runs/attempt02/policy14_nb20_fit2022/fit/result.json); [validation](../runs/attempt02/policy14_nb20_fit2022/validation.json); [status](../runs/attempt02/policy14_nb20_fit2022/replay2022/status.json); [journal](../runs/attempt02/policy14_nb20_fit2022/replay2022/days.jsonl); [identity](../runs/attempt02/policy14_nb20_fit2022/replay2022/identity.json).

retrospective development mechanism test. Cost support: all 365 calendar days.

| Arm | Failures / days | Failure probability | Wilson 95% IID-only benchmark | Mean shortage |
|---|---:|---:|---|---:|
| old | 0 / 365 | 0.000% | [0.000%, 1.041%] | 0.00000000 |
| common | 0 / 365 | 0.000% | [0.000%, 1.041%] | 0.00000000 |
| adaptive | 0 / 365 | 0.000% | [0.000%, 1.041%] | 0.00000000 |

Costs on the same 365 jointly feasible dates (fixed asset cost included):

| Arm | Mean | Median | 5th percentile | 95th percentile |
|---|---:|---:|---:|---:|
| old | 3,604.1166 | 1,745.4289 | 1,404.2648 | 8,932.2571 |
| common | 3,602.9640 | 1,744.5289 | 1,403.2671 | 8,931.4747 |
| adaptive | 3,602.3856 | 1,744.5205 | 1,402.8837 | 8,927.8974 |

| Signed paired cost difference | Mean | Median | 5th percentile | 95th percentile |
|---|---:|---:|---:|---:|
| old minus common | 1.1525 | 0.8923 | 0.7037 | 1.2055 |
| common minus adaptive | 0.5784 | 0.2062 | -0.0000 | 3.3632 |
| old minus adaptive | 1.7309 | 1.1882 | 0.8875 | 4.2276 |

Saved nesting asserted: **true**. same-population nesting decomposition.

Descriptive paired-mean interval sensitivity (full calendar sampled before cost conditioning):

| Circular block length | Old − common | Common − adaptive | Old − adaptive |
|---:|---|---|---|
| 7 days | [0.9195, 1.5474] (1000/1000) | [0.3872, 0.7873] (1000/1000) | [1.4078, 2.1682] (1000/1000) |
| 14 days | [0.9189, 1.5362] (1000/1000) | [0.3489, 0.8566] (1000/1000) | [1.3816, 2.1868] (1000/1000) |
| 30 days | [0.9027, 1.6040] (1000/1000) | [0.2820, 0.9795] (1000/1000) | [1.3084, 2.2145] (1000/1000) |

Failure-probability block intervals and arm cost-mean intervals are retained in stats.json. Parenthesized counts above are bootstrap replicates with nonempty shared cost support.

Native Gurobi fitting phases (floating-point optimality/KKT diagnostics, not exact rational or full-route integer certificates). Residuals use scientific notation. n/a means unavailable; native objective/bound values remain visible even when a reconstructed dual bound is undefined:

| Stage / phase | Native status | Runtime s | Native objective / bound | Max primal residual | KKT stationarity / complementarity / sign | Primal − dual | Log |
|---|---|---:|---:|---:|---|---:|---|
| inherited / shortage | OPTIMAL (2) | 0.577 | 0.00000000 / 0.00000000 | 2.842e-14 | 0.000e+00 / 0.000e+00 / 0.000e+00 | 0.000e+00 | [verified log](../runs/attempt02/policy14_nb20_fit2022/fit/inherited_shortage.log) |
| inherited / cost | OPTIMAL (2) | 0.847 | 2,209.11655812 / 2,209.11655812 | 1.421e-14 | 2.096e-13 / 1.947e-16 / 1.388e-17 | n/a | [verified log](../runs/attempt02/policy14_nb20_fit2022/fit/inherited_cost.log) |
| common / shortage | OPTIMAL (2) | 2.340 | 0.00000000 / 0.00000000 | 4.263e-14 | 0.000e+00 / 0.000e+00 / 0.000e+00 | 0.000e+00 | [verified log](../runs/attempt02/policy14_nb20_fit2022/fit/common_shortage.log) |
| common / cost | OPTIMAL (2) | 17.354 | 2,207.96404824 / 2,207.96404824 | 1.421e-14 | 1.962e-13 / 5.164e-12 / 1.332e-14 | n/a | [verified log](../runs/attempt02/policy14_nb20_fit2022/fit/common_cost.log) |

All 4 native phase-log hashes and the 365-day journal chain verified. Independent replay maximum residuals: old 7.105e-15, common 7.105e-15. Execution elapsed: 31.725 s. Execution commit: `f8f8101557f2ee2983f3cdc6e7369def28338ded`.

## policy17_nb20_fit2023

Status: **validated_complete**.

Evidence: [execution](../runs/attempt02/policy17_nb20_fit2023/execution.json); [fit](../runs/attempt02/policy17_nb20_fit2023/fit/result.json); [validation](../runs/attempt02/policy17_nb20_fit2023/validation.json); [status](../runs/attempt02/policy17_nb20_fit2023/replay2022/status.json); [journal](../runs/attempt02/policy17_nb20_fit2023/replay2022/days.jsonl); [identity](../runs/attempt02/policy17_nb20_fit2023/replay2022/identity.json).

frozen training-profile evaluation on a different weather population. Cost support: all 365 calendar days.

| Arm | Failures / days | Failure probability | Wilson 95% IID-only benchmark | Mean shortage |
|---|---:|---:|---|---:|
| old | 0 / 365 | 0.000% | [0.000%, 1.041%] | 0.00000000 |
| common | 0 / 365 | 0.000% | [0.000%, 1.041%] | 0.00000000 |
| adaptive | 0 / 365 | 0.000% | [0.000%, 1.041%] | 0.00000000 |

Costs on the same 365 jointly feasible dates (fixed asset cost included):

| Arm | Mean | Median | 5th percentile | 95th percentile |
|---|---:|---:|---:|---:|
| old | 3,677.9469 | 1,745.3157 | 1,564.0398 | 8,932.0785 |
| common | 3,602.9702 | 1,744.5317 | 1,403.2671 | 8,931.5345 |
| adaptive | 3,602.3856 | 1,744.5205 | 1,402.8837 | 8,927.8974 |

| Signed paired cost difference | Mean | Median | 5th percentile | 95th percentile |
|---|---:|---:|---:|---:|
| old minus common | 74.9767 | 1.0916 | 0.4881 | 160.8314 |
| common minus adaptive | 0.5846 | 0.2174 | -0.0000 | 3.4146 |
| old minus adaptive | 75.5612 | 4.1651 | 0.6924 | 161.2807 |

Saved nesting asserted: **false**. signed descriptive contrasts; no cross-population ordering asserted.

Descriptive paired-mean interval sensitivity (full calendar sampled before cost conditioning):

| Circular block length | Old − common | Common − adaptive | Old − adaptive |
|---:|---|---|---|
| 7 days | [55.0896, 93.7999] (1000/1000) | [0.3926, 0.7928] (1000/1000) | [55.8143, 94.1612] (1000/1000) |
| 14 days | [48.3700, 100.6876] (1000/1000) | [0.3572, 0.8632] (1000/1000) | [49.0693, 101.3358] (1000/1000) |
| 30 days | [35.4413, 110.2562] (1000/1000) | [0.2895, 0.9894] (1000/1000) | [36.2523, 110.7067] (1000/1000) |

Failure-probability block intervals and arm cost-mean intervals are retained in stats.json. Parenthesized counts above are bootstrap replicates with nonempty shared cost support.

Native Gurobi fitting phases (floating-point optimality/KKT diagnostics, not exact rational or full-route integer certificates). Residuals use scientific notation. n/a means unavailable; native objective/bound values remain visible even when a reconstructed dual bound is undefined:

| Stage / phase | Native status | Runtime s | Native objective / bound | Max primal residual | KKT stationarity / complementarity / sign | Primal − dual | Log |
|---|---|---:|---:|---:|---|---:|---|
| inherited / shortage | OPTIMAL (2) | 0.569 | 0.00000000 / 0.00000000 | 2.842e-14 | 0.000e+00 / 0.000e+00 / 0.000e+00 | 0.000e+00 | [verified log](../runs/attempt02/policy17_nb20_fit2023/fit/inherited_shortage.log) |
| inherited / cost | OPTIMAL (2) | 0.970 | 2,668.37701649 / 2,668.37701649 | 1.421e-14 | 2.096e-13 / 9.733e-17 / 1.388e-17 | n/a | [verified log](../runs/attempt02/policy17_nb20_fit2023/fit/inherited_cost.log) |
| common / shortage | OPTIMAL (2) | 2.302 | 0.00000000 / 0.00000000 | 4.263e-14 | 0.000e+00 / 0.000e+00 / 0.000e+00 | 0.000e+00 | [verified log](../runs/attempt02/policy17_nb20_fit2023/fit/common_shortage.log) |
| common / cost | OPTIMAL (2) | 15.215 | 2,607.47265838 / 2,607.47265838 | 1.421e-14 | 2.033e-13 / 1.507e-12 / 1.388e-17 | n/a | [verified log](../runs/attempt02/policy17_nb20_fit2023/fit/common_cost.log) |

All 4 native phase-log hashes and the 365-day journal chain verified. Independent replay maximum residuals: old 7.105e-15, common 7.105e-15. Execution elapsed: 28.987 s. Execution commit: `f8f8101557f2ee2983f3cdc6e7369def28338ded`.

## policy14_nb20_fit2023

Status: **validated_complete**.

Evidence: [execution](../runs/attempt02/policy14_nb20_fit2023/execution.json); [fit](../runs/attempt02/policy14_nb20_fit2023/fit/result.json); [validation](../runs/attempt02/policy14_nb20_fit2023/validation.json); [status](../runs/attempt02/policy14_nb20_fit2023/replay2022/status.json); [journal](../runs/attempt02/policy14_nb20_fit2023/replay2022/days.jsonl); [identity](../runs/attempt02/policy14_nb20_fit2023/replay2022/identity.json).

frozen training-profile evaluation on a different weather population. Cost support: all 365 calendar days.

| Arm | Failures / days | Failure probability | Wilson 95% IID-only benchmark | Mean shortage |
|---|---:|---:|---|---:|
| old | 0 / 365 | 0.000% | [0.000%, 1.041%] | 0.00000000 |
| common | 0 / 365 | 0.000% | [0.000%, 1.041%] | 0.00000000 |
| adaptive | 0 / 365 | 0.000% | [0.000%, 1.041%] | 0.00000000 |

Costs on the same 365 jointly feasible dates (fixed asset cost included):

| Arm | Mean | Median | 5th percentile | 95th percentile |
|---|---:|---:|---:|---:|
| old | 3,604.1166 | 1,745.4289 | 1,404.2648 | 8,932.2571 |
| common | 3,602.9702 | 1,744.5317 | 1,403.2671 | 8,931.5345 |
| adaptive | 3,602.3856 | 1,744.5205 | 1,402.8837 | 8,927.8974 |

| Signed paired cost difference | Mean | Median | 5th percentile | 95th percentile |
|---|---:|---:|---:|---:|
| old minus common | 1.1463 | 0.8875 | 0.6976 | 1.2495 |
| common minus adaptive | 0.5846 | 0.2174 | -0.0000 | 3.4146 |
| old minus adaptive | 1.7309 | 1.1882 | 0.8875 | 4.2276 |

Saved nesting asserted: **false**. signed descriptive contrasts; no cross-population ordering asserted.

Descriptive paired-mean interval sensitivity (full calendar sampled before cost conditioning):

| Circular block length | Old − common | Common − adaptive | Old − adaptive |
|---:|---|---|---|
| 7 days | [0.9124, 1.5358] (1000/1000) | [0.3926, 0.7928] (1000/1000) | [1.4078, 2.1682] (1000/1000) |
| 14 days | [0.9098, 1.5327] (1000/1000) | [0.3573, 0.8633] (1000/1000) | [1.3816, 2.1868] (1000/1000) |
| 30 days | [0.8943, 1.6007] (1000/1000) | [0.2895, 0.9894] (1000/1000) | [1.3084, 2.2145] (1000/1000) |

Failure-probability block intervals and arm cost-mean intervals are retained in stats.json. Parenthesized counts above are bootstrap replicates with nonempty shared cost support.

Native Gurobi fitting phases (floating-point optimality/KKT diagnostics, not exact rational or full-route integer certificates). Residuals use scientific notation. n/a means unavailable; native objective/bound values remain visible even when a reconstructed dual bound is undefined:

| Stage / phase | Native status | Runtime s | Native objective / bound | Max primal residual | KKT stationarity / complementarity / sign | Primal − dual | Log |
|---|---|---:|---:|---:|---|---:|---|
| inherited / shortage | OPTIMAL (2) | 0.563 | 0.00000000 / 0.00000000 | 2.842e-14 | 0.000e+00 / 0.000e+00 / 0.000e+00 | 0.000e+00 | [verified log](../runs/attempt02/policy14_nb20_fit2023/fit/inherited_shortage.log) |
| inherited / cost | OPTIMAL (2) | 0.873 | 2,610.68202042 / 2,610.68202042 | 1.421e-14 | 2.096e-13 / 1.947e-16 / 1.388e-17 | n/a | [verified log](../runs/attempt02/policy14_nb20_fit2023/fit/inherited_cost.log) |
| common / shortage | OPTIMAL (2) | 2.495 | 0.00000000 / 0.00000000 | 4.263e-14 | 0.000e+00 / 0.000e+00 / 0.000e+00 | 0.000e+00 | [verified log](../runs/attempt02/policy14_nb20_fit2023/fit/common_shortage.log) |
| common / cost | OPTIMAL (2) | 14.719 | 2,607.47265838 / 2,607.47265838 | 1.421e-14 | 2.033e-13 / 2.005e-12 / 1.388e-17 | n/a | [verified log](../runs/attempt02/policy14_nb20_fit2023/fit/common_cost.log) |

All 4 native phase-log hashes and the 365-day journal chain verified. Independent replay maximum residuals: old 7.105e-15, common 7.105e-15. Execution elapsed: 29.042 s. Execution commit: `f8f8101557f2ee2983f3cdc6e7369def28338ded`.

## Report integrity and scope

The report checks completion, result/validation/replay identity bindings, every daily journal link, every native phase-log hash, saved summary recomputation and unchanged old/adaptive references across fitting years. The independent fit validation is retained; this postprocessor does not reconstruct model matrices or rerun trace physics. Missing artifacts remain incomplete, and inconsistent artifacts are invalid.

A same-population decomposition is an in-sample mechanism result. Cross-year differences are signed descriptive comparisons; neither cost ordering nor uncertainty calibration carries over automatically. Results do not establish optimal asset investment, original-route recovery, causal savings or population reliability.
