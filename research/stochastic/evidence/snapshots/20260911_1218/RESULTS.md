# Matched-method pool results — 11 September 2026

All 27 MIPs and 27 evaluations completed. Each physical arm used one validated union of all nine source pools: 313 columns (solar+BESS), 1919 (V2G without BESS), 419 (V2G+BESS). Twenty trips, PV scale2, fossil cap0.8, 24 parent training scenarios, seeds11/29/47. Reduced models retain8 weighted real days. Equal MIP ceiling900seconds.

| Arm | SAA failed days | Minimax failed days | Reduced failed days |
|---|---|---|---|
| Solar+BESS | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| V2G without BESS | 6 / 8 / 9 | 0 / 0 / 0 | 6 / 12 / 14 |
| V2G+BESS | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |

Reduced seed29 without BESS still fails one omitted parent training day despite feasibility on all8 retained days. This is a controlled counterexample to feasibility preservation by this reduction, surviving common-pool control. It does not refute all clustering methods.

For solar+BESS, mean costs are3157.85/3144.71/3142.33 SAA, 6626.55/6607.37/6606.30 minimax, 3280.84/3143.71/3206.66 reduced. For V2G+BESS:3094.52/3096.26/3094.81 SAA, 6621.09/6637.33/6662.84 minimax, 3211.81/3085.38/3137.80 reduced. Minimax optimizes a different worst-scenario objective and has no expected-cost tie-break; the high mean is not proof of dominance. No unconditional cost is reported for policies failing days. Reduction has no consistent mean-cost benefit: paired block intervals exclude zero in the harmful direction for seeds11/47 of both BESS arms; seed29 intervals include zero.

Native MIP runtime totals across9 cases: SAA2703.57s, minimax18.00s, reduced2701.33s. Three SAA and three reduced MIPs reached900s; maximum finite-pool gaps2.408% and3.000%; minimax max0.001952%. Reduction did not resolve the difficult no-BESS MIPs at this budget. These are finite-pool bounds and native solve time, not full integer-family certificates or total allocation usage.

[Full distributions, intervals, paired results and hashes](method_results.json). Circular14-day block bootstrap,2000replicates,seed7291; intervals conditional on fixed policies and one observed year. Constant zero-failure bootstrap intervals cannot bound unseen-event risk. 2022 is reused development data independent of2023 fitting, not a fresh scientific holdout. Full-day recourse remains perfect-foresight. Next: causal-dispatch comparison using frozen policies, before another training factorial or RL.

Date/user-scoped Slurm accounting (original research artifact `snapshots/20260911_1218/slurm_accounting.psv`; not included in this export) records1.8175allocatedCPU-hours for union preparation, MIPs and evaluation combined. Some evaluation allocations received2CPUs despite requesting1, so allocation usage is computed from recorded AllocCPUS × elapsed, not assumed from requests.
