# Plug-limit integer arms under the agreed protocol (17 October 2026)

This folder reruns only the **36 integer arms** of the plug-limit study (reviewer comment 4) under the protocol now used for every other integer table. The 36 LP arms of the original study are unaffected and are not rerun. Their numbers (LP values, LP times, binding rows, plug prices, peak occupancy) come unchanged from `output/opte-plugs-final-20261015/plug_results.json`.

Original study: `experiments/opte_plugs_20261013/PROTOCOL.md` (code and inputs), `output/opte-plugs-final-20261015/` (results, collector). Nothing in those folders is edited.

## What changed, and why

| | Original plug study (13 Oct) | This rerun (agreed protocol) |
|---|---|---|
| cg_pool_mip budget | One 1,800 s clock per arm. CG capped at 600 s inside it; unused CG time went to the MIP. | CG runs to pricing convergence (no route or seed with reduced cost below −1e-6); safety cap 14,400 s; CG time reported separately. Then a cold restricted MIP gets 1,800 s on its own clock, starting before its matrices are built. Checkpoint I/O is outside both clocks. |
| Consequence in the original | The two 200-task tight blocks (14, 17) hit the 600 s cap before convergence, and the MIP had only 1,200 s; in every block the MIP had 1,800 s minus the CG time. | Every MIP gets the same 1,800 s, after a converged CG, as in Tables 20–22 and the grid/map studies. |
| direct_mip | 1,800 s from graph construction, barrier root (Method 2). One trace sample every 30 s. | Same budget, same clock start, same Method 2. New: every incumbent and bound is time-stamped (callback of `opte_grid_scaling_20261016/runtime/direct_mip_traced.py`); the reported value is the best incumbent at or before 1,800 s. |
| Max CG iterations | 20,000 | 200,000 (as the grid study; the time cap is now 14,400 s) |
| Hardware/placement | One four-arm block at a time on one node (cdses-compute-01); 64 GiB per block. | Single-arm jobs, one bound CPU each, EPYC 9654 nodes only (runner guard `--require-cpu-model=9654`, node list as in the grid/map studies), right-sized memory. The original runner's check that the job has exactly 65,536 MiB is dropped, because memory is now right-sized. |
| Lower bound / gaps | Pool bound (restricted pool only) and direct ObjBound reported separately. | LB* = max(z_RMP − n·1e-6 when CG priced out, direct final ObjBound); gap = 100(U − LB*)/U per arm. |

The reason for the change is the same as for Tables 20–22 (`experiments/opte_equal_mip_20261015/PROTOCOL.md`): under the shared budget, the MIP stage of the CG arm received whatever the CG phase left, and the CG phase could be cut short. That mixes CG speed with MIP quality. The agreed protocol separates them.

## What did not change

- **Inputs.** The same 6 physical inputs × 3 plug policies (unlimited; loose: 2 plugs per task location, depot 5 or 10; tight: 1, depot 3 or 5), built by the original `plug_instances.py`. `--preflight` rebuilds all 18 and checks every instance hash, and every capacity entry, against the original `input_manifest.json`, the original plan, block summaries and the manifests/instances of all 72 original arms (`original_reference.json`, written by `build_reference.py`).
- **Plug model.** Byte-identical copies of `plug_problem.py`, `plug_pricing.py`, `plug_master.py`, `plug_solvers.py`, `frozen_snapshot.json` and all frozen modules. Plug rows enter the CG master in `plug_problem.rmp_matrices` (one row per finite station/time cell, coefficient 1 for each route that charges or discharges there; the persistent master appends the same coefficients in `plug_master.append`). Plug duals are read in `plug_master.solve` (`plug_price = −Pi` of the plug rows) and added as a cost to every charge or discharge arc at that cell in `plug_pricing.price_route`; seeds are priced with the same duals (`plug_pricing.reduced_cost`). Plug rows enter the direct model in `plug_problem.direct_matrices` (coefficient 1 on every charge/discharge arc at the cell and on each seed's occupied cells).
- **CG algorithm.** `plug_solvers.generate_pool` is called unchanged: two-phase master (Phase I minimizes task artificials), persistent Gurobi RMP with basis reuse, dual stabilization 0.5, convergence only after pricing at the unstabilized duals finds no route or seed below −1e-6. The integer pool is all real columns (generated routes plus the 100 or 200 original singleton seeds), no artificials.
- **Solver settings.** Gurobi 12.0.3, Threads 1, Seed 0, FeasibilityTol/OptimalityTol/IntFeasTol 1e-8, MIPGap 1e-6, MIPGapAbs 1e-10. Pool MIP Method −1 (`plug_solvers.solve_matrix`, unchanged), direct MIP Method 2.
- **Validation.** After the timed stop: matrix primal check (plug rows are part of the inequality block), then `plug_problem.replay_pool`, which replays each selected route from its witness, recomputes station/time occupancy, compares it with every finite plug capacity, and replays the aggregate master and the objective. For the direct arm, this is done for the reported (≤ 1,800 s) incumbent and the final incumbent; every incumbent gets the matrix check.

## The CG lower bound with plug rows

When CG stops priced out, pricing at the final RMP duals (including the plug duals) found no route and no seed with reduced cost below −1e-6. Every route serves at least one task, so at most n routes are used, and z_RMP − n·1e-6 is a lower bound on the full-family LP with plug rows and hence on the integer optimum. The plug study's stopping test already prices all seeds, so the grid study's separate "final pricing call returned no column" check is not needed. The result also records the exact Lagrangian value z_RMP + n·min(0, min reduced cost).

## Files

- `run_plugs_protocol.py`: runner (`--plan`, `--preflight`, `--task-index K --results DIR`). Plan task 2i is block i cg_pool_mip, task 2i+1 is block i direct_mip.
- `runtime/protocol_arms.py`: the only new solver code (`solve_cg_then_pool`, `solve_direct_mip_traced`). Everything else in `runtime/` is a byte-identical copy.
- `cluster/arm_worker.sh`, `cluster/submit_plugs_protocol.py` (main 36 arms; not yet submitted), `cluster/submit_smoke.py` (smoke, blocks 0 and 2).
- `collect_plugs_protocol.py`: collector; table layout of `plug_table.md` plus CG time, pool-MIP time, LB*, gaps and the best-cost change versus unlimited.
- `preflight_local.json`, `cluster/preflight_cluster.json`: preflight records.

Cluster: `unicorn:~/opte-plugs-protocol-20261017/` (`code/`, `results/`, `logs/`, `preempted/`, `smoke/`).
