# Prospective station/time plug-capacity experiment

> Public copy. Administrative sentences about project approval and cluster job handling were removed; the technical protocol is unchanged (missing spaces between numbers and words were restored). The SHA-256 of the file as run is listed in `runtime_release_v1.json`.

Written 13 October 2026 (New York time), before the runs. This is a separate, exploratory extension. It preserves the earlier studies, their decision rules, source snapshots and raw outcomes. Its purpose is to measure how physical connector limits affect CG, direct LP, and integer scheduling. Favorable and unfavorable results receive the same checks and accounting. No manuscript claim depends on obtaining a favorable result.

## Scientific question and reviewer scope

Reviewer comment 4 asks us to state practical scope carefully because plug counts and station-specific capacities were not tested. It does not require this implementation. A completed, validated study could support a short optional addition; it should not expand the revision into a stochastic model or a claim about real charger-network deployment.

For each location and half-hour block, limit the number of trucks actively charging **or** discharging to an integer number of bidirectional plugs. A truck uses one whole plug whenever either action is positive, independent of energy transferred. Idle trucks may disconnect without a switching cost. Stationary BESS is separately connected and does not consume truck plugs. These assumptions retain the shared electrical node and omit distribution-network limits. Throughput divided by a power rating is not an exact plug count.

In a path master, each column carries a station/time occupancy vector; in the direct model, every active charge/discharge arc carries the same coefficient. Pricing includes the corresponding capacity duals. This is still a shortest-path pricing problem with additive arc costs. The side constraints can nevertheless change degeneracy, column count, and integer difficulty; there is no presumption that they improve CG's performance. Full path and arc formulations remain equivalent on the same finite route family. CG followed by an integer restricted master remains a heuristic, not branch-and-price.

## Fixed inputs and interventions

Use three physical settings: 100 tasks / 15 locations / 25 kWh energy step; 100 / 15 / 12.5; and 200 / 30 / 25. Generate two fresh draws per setting using `SeedSequence([20261013,1014,cell_index,draw])`. Each location has at least two task origins and destinations. Reuse the fixed bounded geometry, 48-block day, 700 kWh battery, and 175 kWh maximum energy transfer per block from the earlier study. Trip duration is one hour and trip energy is independent of OD distance, as in this synthetic generator.

Task energies have symmetric support from 75 to 125 kWh at the declared step. Tile complete support cycles and fill the remainder with 100 kWh, giving an exact mean of 100 kWh. Shuffle with the independent namespace `[20261013,1014,cell_index,draw,1]`. The declared grid is the coarsest common lattice of the physical inputs; the earlier uniform-energy exact25kWh coarsening is not applicable by that argument.

Each of the six physical inputs is paired across three all-day plug policies:

| Policy | Plugs at each nondepot location | Plugs at depot |
|---|---:|---:|
| Unlimited control | Unlimited | Unlimited |
| Loose | 2 | ceiling(tasks / 20), hence 5 or 10 |
| Tight | 1 | ceiling(tasks / 40), hence 3 or 5 |

This gives 18 cases. The physical input hash must be identical across the three policies. Capacity levels are fixed before solving, rather than adjusted until one solver wins. Full-model feasibility is not assumed. Depot recharge can be a genuine bottleneck because trucks finish full. Preserve infeasibility, unfinished feasibility restoration, timeouts, numerical failures and resource failures as distinct outcomes. Do not drop difficult draws or replace them with easier ones.

## Algorithms and budgets

Each case has four cold, fresh-process arms: CG LP, direct barrier LP, CG followed by restricted-pool MIP, and direct arc-flow MIP. Every arm gets a total 1,800-second algorithm allowance, including construction. The integer pipeline has a maximum 600-second CG phase within the same 1,800 seconds; unused time transfers to its MIP. Neither integer arm may reuse the separately timed LP arm's pool, basis, bound, graph or solution. Comparisons between the two new LP methods and between the two new integer methods are paired. The new unlimited control includes the new implementation's overhead and is not replaced by a faster old result.

CG uses a genuine two-phase master: minimize artificial task coverage with zero real operating cost, then fix artificials to zero and optimize the physical objective. A restricted Phase I failure is not a full-model infeasibility certificate. All physical singleton seed routes are retained with exact location/time witnesses; artificial columns never enter a physical integer solution. If the generated physical pool is infeasible, retain that result rather than borrowing columns from another arm.

Use Gurobi 12.0.3, an AMD EPYC 9654 CPU, one bound CPU and one solver/math thread, solver seed 0, 64 GiB, and the existing numerical tolerance controls. Direct LP uses barrier with automatic crossover. Direct MIP also uses barrier for its root relaxation (Method=2); the restricted-pool MIP uses the automatic method (Method=-1). Both MIPs target a relative gap of 1e-6. This direct-MIP setting was fixed prospectively before any plug-study run, after the earlier separate MIP study spent its allowance in the root simplex relaxation; all earlier evidence is retained. Each arm has a separate 600-second process watchdog grace for diagnostics; grace is not extra optimization time. Run at most one new paired block concurrently. Rotate the four-arm order over the fixed case order, so methods occupy each position as evenly as 18 blocks permit. No automatic solver-time-limit retry.

There are 72 main solver arms and at most 36 solver CPU-hours, plus separately recorded validation and infrastructure overhead. An excluded small allocated calibration checks both algorithms and the plug rows before release.

## Acceptance and reporting

Save full inputs, source hashes, solver controls, raw primal vectors, column paths and occupancy vectors, relevant duals and solver logs. Independent checks must reconstruct task coverage, physical transitions, battery boundaries, shared energy rows, integrality where required, and every station/time plug count. LP values are compared only at matched full-family numerical quality, with independently checked pricing-based lower bounds that include the capacity-dual constant. Model equivalence is not established merely by two similar objective values.

Required small checks include a binding plug example, an instance where energy/rate would allow two simultaneous trucks but one physical plug forbids them, V2G occupancy, no plug use during idle time or by BESS, equal unlimited-case LP values, two-phase feasibility restoration, direct/path equivalence on an enumerable tiny graph, and relevant budget/failure boundaries. Local and excluded calibration timings never enter the main study.

Report every ratio above one, where direct time / CG time greater than one favors CG; do not impose a twofold threshold. A certified time limit gives a justified interval, not a completed 1,800-second solve. For MIP compare feasible cost, each method's own full-model bound, and a clearly separate common post-hoc global gap. Restricted-pool bounds remain pool-only. A quickly solved restricted MIP with a worse incumbent is not a speed win at equal quality. Keep algorithm-stop and independently validated-workflow times and memory separate.

Characterize the change from unlimited to loose and tight capacities on the *same* physical input: LP objective and runtime, integer cost and gaps, active/binding plug rows, peak and total occupancy, depot versus other locations, capacity shadow prices, CG columns/iterations, pricing and master time, direct construction/solve time, graph/matrix size and memory. Do not treat the three policies as 18 independent physical draws. This is an exploratory mechanism study with six independent physical draws; it does not replace the earlier fixed-panel hypothesis test or justify a general superiority claim.

Reporting decisions should depend on relevance, validation, clarity and the minor-revision scope—not the sign of the outcome. All results remain in the research record even if the paper includes only a concise optional summary.
