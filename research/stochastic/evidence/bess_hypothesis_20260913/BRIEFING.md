# Public-code reuse and the BESS hypothesis

**We have inspected the public code, but have not compiled, reproduced or integrated those solvers.** The completed solver improvements were implemented in our Python code, informed by the EVSP–DR audit. The pool-union experiment was also our implementation; its 2.25% improvement is not a benchmark of Parmentier’s solver.

| Resource | Actual use so far | Next useful use |
|---|---|---|
| [Parmentier–Martinelli–Vidal](https://github.com/axelparmentier/ElectricalVSP-ColumnGeneration) | Read and pinned MIT C++/CPLEX/Boost source; CG, branch-and-price, diving and resource-state routines inspected. No compilation, numerical reproduction or code import. | Reproduce one author example in isolation, then test a specifically mapped pricing bound or stabilization idea. Its charge-only deterministic solver does not directly represent our V2G/weather/BESS coupling. |
| [Léa Ricard’s repository](https://github.com/learicard/evsp-policy-battery) | Inspected benchmark data and reported results; no solver source found in the audited release. We have not run its data through our solver. | Build a separate compatible benchmark adapter if it answers a specific comparison question. |
| [Baldua’s csp-res](https://github.com/transnetlab/csp-res) | Read scenario construction, storage variables and CPLEX Benders annotations; no third-party model executed or imported. | Reproduce a tiny extensive-form versus solver-decomposition example before adapting components. Integer common bus duties and our V2G constraints still need our own formulation. |

The earlier phrase “reusable public code” described availability, not completed reuse. Detailed code audit (original research artifact `code_review_20260912/PUBLIC_CODE_REVIEW.md`; not included in this export).

**The BESS hypothesis is plausible and testable, but needs a precise comparison.** A battery shifts available energy to times when it is needed. It may reduce the extra risk caused by variable solar, provided energy and charging/discharging power are available. Long low-solar spells, limited power, operating rules and forecast mistakes can reduce its benefit. Lower expected cost, lower shortfall risk and an economically justified purchase are three different outcomes.

Existing experiments are encouraging:

| Existing comparison | Observation | What it establishes |
|---|---|---|
| SAA24, 2024 | No BESS: 9–12 failed days out of 366; BESS: 0, across the three scenario seeds. | The fitted BESS systems were more reliable on these dates. Fleets and route pools differ, so this is not the isolated effect of adding BESS. |
| SAA24, 2025 | No BESS: 12–13 failed days out of 365; BESS: 1. About 92% fewer observed failed days. | Same qualification. Zero or near-zero observed failures is not zero future risk. |
| Matched-pool investment, V2G+BESS | Deterministic mean: 18 battery units; SAA24: 20 for every seed. There is no imposed 20-unit cap. | Weather-aware planning bought two more units in this setting. This is a cooptimized system decision, not a general investment theorem. |
| Minimax policies, 2024 | No BESS: 0 failures; BESS: 7–11 under causal dispatch. | A BESS-equipped plan is not automatically a more reliable policy. Full-day foresight training and operational forecasts matter. |

The minimax comparison changes the complete fitted plan; it does not show that adding optional physical storage shrinks feasibility. With identical commitments and the option to leave added capacity unused, the physical feasible set expands. A particular replanned or forecast-driven policy can still perform worse.

Paired descriptive comparisons below use the exact same evaluation dates, 2,000 circular block resamples of 14 days, separately for each year and training seed. They are post-hoc comparisons of existing fitted systems. Three seeds are not three independent weather years.

| Year | SAA seed | No-BESS failures | BESS failures | Failure reduction, percentage points | Paired 95% interval |
|---|---:|---:|---:|---:|---|
| 2024 | 11 | 9 | 0 | 2.46 | 0.82 to 4.10 |
| 2024 | 29 | 12 | 0 | 3.28 | 1.09 to 5.74 |
| 2024 | 47 | 10 | 0 | 2.73 | 1.09 to 4.64 |
| 2025 | 11 | 13 | 1 | 3.29 | 0.82 to 6.30 |
| 2025 | 29 | 13 | 1 | 3.29 | 0.82 to 6.30 |
| 2025 | 47 | 12 | 1 | 3.01 | 0.55 to 6.03 |

Full post-hoc evidence, shortage outcomes, counterexamples and input hashes (original research artifact `bess_hypothesis_20260913/existing_evidence.json`; not included in this export).

**New controlled experiment completed: array 110896, 90 cases and 32,850 daily trajectories, all validated.** Two cluster smoke cases passed independent validation first. Main experiment plus smoke allocation used 3.229 CPU-hours.

The results are **suggestive, not conclusive**: the extra reduction in mean emergency energy under variable solar is positive in all 24 schedule/capacity comparisons, but every paired 95% interval includes zero. These related comparisons do not constitute 24 independent confirmations. The failed-day outcome is mixed, so “more robustness” needs a named metric.

For an illustration, take the fixed schedule originally designed with BESS, seed 11, and add 20 battery units. With predictable solar, mean shortage falls from 0.650 to zero. With variable solar, it falls from 0.761 to 0.021. The additional benefit under variability is 0.090 reference energy units/day, with a descriptive 95% interval of −0.018 to 0.206. Under variable solar, failed days fall from 100 to 10; the same treatment under predictable solar removes all 92 failed days. Shortage severity and failed-day frequency therefore tell different stories.

The clearest next lead is **how the battery is operated**. Added capacity often stops improving causal reliability even though the same physical storage could cover the shortages with complete-day information. This points to a reserve-aware causal controller and initial-state rules before simply buying more capacity. [All controlled results and intervals](../snapshots/bess_robustness_validation/RESULTS.md).

| Ingredient | Fixed or varied |
|---|---|
| Bus schedules | Six existing SAA profiles; each remains identical across its comparisons. |
| BESS | 0, 5, 10, 20 or 30 units; empty at start and end of each day. |
| Solar variability | 0%, 50% or 100% of the observed within-month deviation. Monthly mean energy at every time slot stays exactly the same. |
| Information | Current solar observed, future realized solar hidden; same forecast rule. Full-day oracle reported separately. |
| Evidence set | Synthetic controlled replay based on 2022 development weather, with its population monthly mean supplied equally to all treatments. This is not an independent forecast test or a new holdout. |
| Main outcome | Mean emergency energy prevented by BESS, and whether this prevention is larger with variable solar. |
| Other outcomes | Failed-day probability, worst-5% mean shortage, cost on matched feasible days, uncertainty intervals and actual compute. |

The key calculation is **BESS benefit under variable solar minus BESS benefit under predictable solar**, with the same buses and solar mean. Positive point estimates are reported with their intervals, alongside adverse failed-day results. The complete predeclared [protocol](../campaigns/bess_robustness_wave12/PROTOCOL.md) separates this mechanism test from investment conclusions.

**Then quantify investment:** use the same route pool for deterministic and stochastic planning, reoptimize fleet and battery count, and trace total cost against reliability targets while varying BESS cost and forecast quality. This gives the additional capacity and cost needed to reach a stated reliability level. Include V2G on/off to test when mobile and stationary storage substitute for or complement each other. Preserve independent evaluation after choosing the method.

The publication question should be “when, how much, and under what information does BESS provide extra reliability value?” Existing solar/bus/storage papers already address the broad technology combination; merely asserting that storage helps uncertainty is insufficient. [Closest-paper comparison](../literature_update_20260912/CLOSEST_PAPERS.md).
