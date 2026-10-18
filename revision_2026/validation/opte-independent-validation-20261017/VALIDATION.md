# Independent validation of the new benchmark results — 17 October 2026

This folder checks every schedule cost and lower bound behind the new revision results.
It covers Tables 8, 19, 20, 21 and 22, Figure 3, and the 3,600-second runs.
That is 235 inputs and 548 saved runs (283 CG + route-MIP runs, 265 direct-MIP runs).

All checks passed. Every printed row can be rebuilt from independently validated values. The only exception is the hand-corrected 4,000-task entry in Table 20, and the validation confirms that correction.

## What was checked

**Inputs.**
- Each input was rebuilt from its declared specification by the instance generator of the code copy that ran it (`src/rebuild_input.py`, a separate process).
- In all 548 runs, the rebuilt input equals the saved `instance.json`.
- Its SHA256 equals the hash recorded in the run's `result.json` and `manifest.json`.
- The declared specification equals the one in the manifest.
- The hashes of the runtime and vendor code equal those recorded in every manifest.

**Code independence.**
- `src/validate_case.py` imports only numpy, scipy, gurobipy and the original published code under `vendor/` (instance, master, colgen).
- It asserts at exit that none of `arc_flow`, `extension_models`, `column_witness`, `rmp_solver`, `phase_models`, `direct_mip_traced`, `direct_mip_1000` or the runners was loaded. None was, in any run.
- It rebuilds the pricing-graph topology itself from the physical input.
- For all 235 inputs, the node and arc counts (pruned and unpruned) equal the runner's records.
- In a one-off test on one input (`src/ivtest_topology.py`, not part of the validator), the full arc arrays also equal the original builder's.

**Direct-MIP schedules.** For each direct run, the validator checks two saved vectors: the incumbent chosen by the reading rule, and the final vector. The reading rule takes the best incumbent at or before 1,800 seconds, plus 3,600 seconds for the inputs used in the 3,600-second runs. 538 vectors were checked. For each vector, the validator:
- checks integrality and bounds;
- checks flow conservation on the rebuilt graph;
- decomposes the flow into truck routes;
- replays every route against the vendor instance: task times, places and energy; deadhead time and energy; charging places and rate; and the SoC range;
- compares each one-task route with the vendor's single-trip construction;
- checks that every task is covered exactly once;
- checks the block energy balance with solar, and the battery dynamics, capacity and rates;
- recomputes the cost.

**Route-MIP schedules.** For each CG run, the validator checks the saved restricted-MIP vector over the saved route pool (283 runs):
- Every selected route is realized as a path in the rebuilt graph, or as a vendor singleton.
- The route is replayed, and its stored energy profile and cost must equal the replay.
- The master is then checked as above.

The first pass used the runner's saved route witnesses as hints, and checked each of them fully. A second pass ignored the witnesses and found every route by search over the rebuilt graph (`results_nohints/`).
- The second pass has finished for all 235 inputs (228 in the first batch: 276 CG runs, 8,882 routes found by search, plus singletons; 7 large inputs in job 365866).
- Every one of those runs passed, with the same costs and certificates as the first pass.
- The seven large inputs (grid L120 with 480 and 960 tasks, panel map75, the 4,000-task input) finished later in array job 365866 (all tasks COMPLETED, exit 0). Update, 17 October 22:00: all 235 inputs now pass the witness-free second pass.

**Cross-check.**
- For all 821 checked schedules, the original published master (Gurobi backend, solving only over the replayed routes) found a dispatch and battery count costing no more than the reported cost.

**CG lower bounds.**
- Each bound is a Lagrangian bound computed from the saved stopping duals alone. It does not use z_RMP or the route pool.
- The bound is Σα + Σμ·Δ + n·min(0, rc_min) + (U/c_b)·min(0, c_b + v\*). Here rc_min is the minimum reduced cost over the whole route family: an exact DP on the rebuilt graph plus every singleton. v\* is the least dispatch cost of one battery, from a small LP.
- In all 282 runs where CG converged, this certificate is at least the reported bound z_RMP − n·10⁻⁶. The most negative reduced cost was −1.2·10⁻⁸.
- The 4,000-task CG run stopped at its 14,400-second cap. It reports no bound, and the paper uses none.

**Direct lower bounds.**
- Gurobi's ObjBound is solver evidence, and was not recomputed.
- It was checked for consistency: it is never above a validated cost of the same input.
- For the 118 runs reported optimal, the bound is within the 10⁻⁶ MIP gap of the validated final cost.

## Results by table

The "Rows matching the collector" column compares rows rebuilt from validated values with each collector's rows, field by field. It covers costs, bounds, LB\*, gaps and the "starting schedule only" flag. The original table generators were then rerun on the rebuilt rows, and their LaTeX output was compared with the printed rows.

| Table | Inputs | Runs passed | Rows matching the collector | Printed LaTeX rows reproduced |
|---|---:|---:|---:|---|
| Table 8, Table 21 (map × tasks grid) | 64 | 82/82 CG, 64/64 direct | 64/64 | Table 8: 24/24. Table 21: both panels, 6/6 rows each |
| Table 22, Figure 3 (transition) | 108 | 138/138 CG, 138/138 direct | 108/108 | 18/18 |
| Table 19 (tasks) | 40 | 40/40 CG, 40/40 direct | 40/40 | 29/29 lines |
| Table 20 (equal MIP time) | 23 | 23/23 CG, 23/23 direct | 23/23 | 22/23 (see below) |
| 3,600-second runs | 48 | (included above) | 48/48 | — |

**Accuracy of the checks.**
- The largest physical residual was 1.0·10⁻⁸ (direct runs) and 1.6·10⁻¹¹ (route MIP).
- Recomputed costs agree with the reported objectives to within a relative 1.1·10⁻¹⁵.

**The 4,000-task row of Table 20.**
- The generator prints "0.00" for this row; the printed manuscript has "<0.01 (TL)".
- The validated cost is 209,811.5 and the Gurobi bound is 209,806.94, so the gap is 0.0022%.
- The printed "<0.01 (TL)" is therefore correct.

**3,600-second runs.**
- At 35 locations, the direct MIP holds a schedule better than its starting schedule on 11 of 12 inputs.
- From 40 locations it does so on none (0 of 2 in each size).

**Starting schedule.** Wherever the tables say "starting schedule only" or "fallback", the validated vector is the one-truck-per-task schedule of singletons.

## Dependence on Gurobi bounds

LB\* is the larger of the certified CG bound and Gurobi's bound.

**Where LB\* comes from.**
- Tables 8 and 21: the certified CG bound in 35 of 64 rows, Gurobi's in 29 (the smaller maps, where the direct MIP solves or nearly solves the problem).
- Tables 19 and 22: Gurobi's bound in every row.
- Table 20: Gurobi's bound in 19 of 23 rows.

**If only the certified CG bound were used.** The printed gaps would grow by at most:
- 0.67 percentage points in Tables 8/21;
- 0.63 in Table 22;
- 0.43 in Table 19;
- 0.11 in Table 20.

This excludes the unconverged 4,000-task input, where the Gurobi bound is the only bound. Per-row values are in `validation_summary.json` and `cg_bound_certificates.json`.

## Not covered

- **Times.** CG phase, route-MIP time, root time and "optimal at" times are clock records and were not validated.
- **Gurobi bounds.** These were checked only for consistency (see above). Optimality claims rest on them.
- **Superseded runs.** Eight grid inputs had their direct arm rerun with 72 GB of memory. Their original direct runs are not printed and were not validated; the 72 GB reruns were.
- **Stage-1 input rebuild.** This process loads `arc_flow.validate_instance`, because the instance generator calls it as an input check. The validator process does not load it.
- **Graph enumeration order.** The rebuilt graph enumerates arcs in the original order, so that saved vectors can be decoded. The order was written from reading the original builder. A wrong order would show up as failed flow conservation or failed route replays.

## Files

- `src/`:
  - `rebuild_input.py`, `validate_case.py`: the validator.
  - `aggregate.py`: table-level checks.
  - `make_jobs.py`, `worker.sh`: Slurm.
  - `finalize.sh`: pull and aggregate.
  - `ivtest_topology.py`: the one-off topology test.
- `results/<cohort>/<case>.json`: one report per input, with every arm.
- `results_by_arm/<cohort>/<case>__<arm>.json`: the same reports, split per run.
- `results_nohints/`: the witness-free second pass over the CG runs.
- `validation_summary.json`, `cg_bound_certificates.json`, `aggregate_stdout.txt`.
- `slurm/`:
  - `jobs.json`
  - submission receipts (array jobs 364438–364441; 365264–365267 and 365866 for the second pass)
  - `sacct` records
  - the worker script

The Slurm logs and the stage-1 input records are not included in this copy.
