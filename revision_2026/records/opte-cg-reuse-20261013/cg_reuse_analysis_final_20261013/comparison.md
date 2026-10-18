# CG persistent-master diagnostic

Fixed three-arm, matched-allocation diagnostic. Strict primary acceptance and post-hoc barrier full-family validation are separate; original native flags/times remain unchanged. Censors and failures are retained. This is a combined persistent-model/basis implementation comparison, not isolated causal attribution to model construction or warm starts.

Planned outcomes:54; present:54; complete blocks:18/18.
Independent replay requested:True. Global checks:True.

Times below are median [minimum, maximum] seconds for the explicitly selected completed population. Censors remain separate and are not entered as completed times.

| Tasks | Variant | Primary accepted /6 | Direct native optimal | Additional supplementary | Time limits | Primary completed times | Supplementary completed times |
|---:|:---|---:|---:|---:|---:|:---|:---|
| 100 | cold | 6/6 | n/a | 0 | 0 | 39.780 [34.293, 41.345] | 39.780 [34.293, 41.345] |
| 100 | reuse | 6/6 | n/a | 0 | 0 | 22.324 [20.449, 22.908] | 22.324 [20.449, 22.908] |
| 100 | barrier | 6/6 | 6 | 0 | 0 | 28.174 [25.012, 33.192] | 28.174 [25.012, 33.192] |
| 400 | cold | 6/6 | n/a | 0 | 0 | 283.870 [234.000, 403.279] | 283.870 [234.000, 403.279] |
| 400 | reuse | 6/6 | n/a | 0 | 0 | 133.401 [110.452, 152.693] | 133.401 [110.452, 152.693] |
| 400 | barrier | 0/6 | 6 | 6 | 0 | — | 39.976 [34.992, 59.265] |
| 1000 | cold | 0/6 | n/a | 0 | 6 | — | — |
| 1000 | reuse | 6/6 | n/a | 0 | 0 | 906.076 [778.693, 1355.546] | 906.076 [778.693, 1355.546] |
| 1000 | barrier | 0/6 | 6 | 6 | 0 | — | 50.195 [43.907, 65.865] |

Peak resident process memory, MiB, median [minimum, maximum] (observed workers /6):

| Tasks | Variant | At algorithm stop | After worker diagnostics |
|---:|:---|:---|:---|
| 100 | cold | 84.00 [84.00, 84.05] (6/6) | 116.95 [116.07, 119.98] (6/6) |
| 100 | reuse | 81.00 [81.00, 81.01] (6/6) | 116.74 [116.66, 116.82] (6/6) |
| 100 | barrier | 395.10 [391.74, 398.19] (6/6) | 395.10 [391.74, 398.19] (6/6) |
| 400 | cold | 105.00 [104.25, 106.28] (6/6) | 155.45 [153.61, 165.99] (6/6) |
| 400 | reuse | 99.01 [99.00, 102.00] (6/6) | 159.27 [155.08, 164.32] (6/6) |
| 400 | barrier | 441.85 [437.02, 443.78] (6/6) | 441.85 [437.02, 443.78] (6/6) |
| 1000 | cold | 186.13 [160.19, 189.64] (6/6) | 186.13 [160.19, 189.64] (6/6) |
| 1000 | reuse | 160.53 [160.51, 163.52] (6/6) | 425.19 [422.29, 425.92] (6/6) |
| 1000 | barrier | 512.26 [507.50, 515.03] (6/6) | 512.26 [507.50, 515.03] (6/6) |

Both memory columns are cumulative per-worker process high-water marks, not Gurobi-only allocations. The stop measurement includes construction, optimization/pricing and intermediate RMP checks, but precedes final full-family validation. The second includes the worker's later diagnostics and evidence generation; separate later replay/analysis processes are excluded. CG may materialize its full graph only for post-stop validation. A budget-exhausted worker may not produce that certificate, so its second measurement does not imply completed validation. The memory table retains all observed outcomes; certificate and censor counts above identify their status. Algorithm-stop memory and timing advantages must not be described as full validation-workflow advantages.


Infrastructure recovery: 2 whole blocks have one registered replacement after external preemption. All original partial executions remain in execution_ledger.csv; completed original arms are not mixed with replacement arms. The54 logical outcomes are distinct from the additional execution attempts.
Execution counts: {"original": {"externally_preempted_without_saved_result": 2, "planned_execution_arm_slots": 54, "saved_result_outcomes": 49, "selected_logical_slots": 48, "unstarted_slots": 3, "workers_started": 51}, "recovery": {"externally_preempted_without_saved_result": 0, "planned_execution_arm_slots": 6, "saved_result_outcomes": 6, "selected_logical_slots": 6, "unstarted_slots": 0, "workers_started": 6}}


Every paired ratio, censor, provenance error, phase statistic and raw stop is in the JSON/CSV outputs. A ratio above one favors its denominator. Repeated timings are not additional independent task draws. Basis reuse can alter presolve and dual/column trajectories, so this measures the complete declared implementation change.
