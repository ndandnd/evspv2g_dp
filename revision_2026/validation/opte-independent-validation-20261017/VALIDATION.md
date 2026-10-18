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

The cluster copy is in `~/opte-independent-validation-20261017/`, including logs and the stage-1 input records.

## Addendum, 18 October: 160 and 200 locations

Section 8.2 now cites four more inputs from the map extension (`experiments/opte_map_extension_20261017`): 160 and 200 locations (320 and 400 tasks), two samples each. Each input has two saved runs, 8 in all:
- 4 CG + route-MIP runs;
- 4 direct-MIP runs, with an 1,800-second limit.

This addendum checks the saved evidence only. No optimization was rerun.

**All 8 runs passed.** The witness-free second pass also passed for all 4 CG runs. All printed gaps and the manuscript's gap range (l. 1187) are reproduced from validated values.

**How it was run.**
- The validator, the input rebuild and the worker are unchanged. `src/validate_case.py` has the same SHA256 (`e0bdd729…`) as in all 548 earlier runs.
- The only new input is the job list. `src/make_jobs_mapx.py` writes `slurm/jobs_mapx.json`. It uses cohort `grid` and the extension's runtime copy, which is the code that ran (its `grid_instances.py` adds 160 and 200 to `DIAG_L`). It sets one reading time, 1,800 s.
- `src/aggregate_mapx.py` applies the same rules as `aggregate.py`; its functions are copied from it unchanged. It does three things:
  - rebuilds the rows in the collector's schema (`output/opte-map-extension-20261017/grid_rows.json`) from validated values;
  - reruns that folder's `make_tables.py`, which is byte-identical to the grid study's, on the rebuilt rows;
  - diffs the LaTeX output with `table8_rows.tex`.
- It writes its own files. It does not change the summary files of the 548-run validation.

**CG + route-MIP runs.** Routes are replayed against the rebuilt graph, and LB\* is the certified CG bound.

| L / n / sample | Input SHA256 | Nodes / arcs (rebuilt = runner) | Routes replayed (one-task + graph paths) | Max residual | Recomputed cost (= reported) | Certificate (reported bound) | Most negative reduced cost | Gap %, recomputed (printed) |
|---|---|---|---|---:|---:|---:|---:|---:|
| 160 / 320 / 1 | `01a8983b…` | 293,764 / 39,426,390 | 79 (31 + 48) | 0 | 24,964.8875 | 22,037.6750 (22,037.6747) | −1.9·10⁻¹¹ | 11.73 (11.73) |
| 160 / 320 / 2 | `fb534359…` | 294,373 / 39,513,418 | 66 (13 + 53) | 0 | 22,858.9625 | 21,647.3750 (21,647.3747) | −1.4·10⁻¹¹ | 5.30 (5.30) |
| 200 / 400 / 1 | `20c8488b…` | 367,040 / 60,479,730 | 94 (33 + 61) | 0 | 30,676.9375 | 27,425.6750 (27,425.6746) | −1.5·10⁻¹¹ | 10.60 (10.60) |
| 200 / 400 / 2 | `2a716caf…` | 366,728 / 60,425,577 | 88 (26 + 62) | 0 | 29,836.5625 | 27,570.7375 (27,570.7371) | −1.1·10⁻¹¹ | 7.59 (7.59) |

**Direct MIP runs.** The table gives the vector read at 1,800 s; it is also the final vector. The Gurobi bound was null in all four runs.

| L / n / sample | Unpruned states / arcs (rebuilt = runner) | Vector at 1,800 s | Max residual | Recomputed cost (= reported) | Gap %, recomputed (printed) |
|---|---|---|---:|---:|---:|
| 160 / 320 / 1 | 457,562 / 63,213,852 | incumbent 0, found at 199 s: 320 one-task routes | 0 | 52,103.95 | 57.70 (57.7) |
| 160 / 320 / 2 | 457,562 / 63,213,852 | incumbent 0, found at 199 s: 320 one-task routes | 0 | 52,103.95 | 58.45 (58.5) |
| 200 / 400 / 1 | 571,242 / 96,916,448 | incumbent 0, found at 302 s: 400 one-task routes | 0 | 65,309.95 | 58.01 (58.0) |
| 200 / 400 / 2 | 571,242 / 96,916,448 | incumbent 0, found at 299 s: 400 one-task routes | 0 | 65,309.95 | 57.78 (57.8) |

The printed values are those in `table8_rows.tex` of the extension. The pruned node and arc counts of the direct runs equal those of the CG run of the same input.

**Inputs and code.**
- In all 8 runs, the input rebuilt by the extension's generator equals the saved `instance.json`.
- Its SHA256 equals the hash in `result.json` and `manifest.json`, and the manifest's specification equals the declared one.
- No runtime or vendor file differs from the hashes in the manifests.
- No forbidden module was loaded, in either pass.

**Graphs.**
- In all 8 runs, the rebuilt node and arc counts equal the runner's records. For the direct runs, the unpruned counts also match.
- The rebuilt graphs have 39.4–60.5 million arcs; the manuscript rounds this to "39--60 million".
- At 160 locations, the unpruned counts are the same for both samples. The runner records show the same values.

**Route-MIP schedules.**
- All 327 selected routes were replayed: 103 vendor one-task routes and 224 graph paths, with 8,996 transitions.
- Each stored energy profile and cost equals its replay.
- The physical residuals are all 0. Recomputed costs equal the reported ones to within 3.6·10⁻¹² (absolute).
- The original published master over the replayed routes finds an optimal cost equal to the reported cost in all four runs.
- Witness-free pass (`results_nohints/mapx/`): all 224 graph paths were found again by search on the rebuilt graph. The costs and certificates are the same as in the first pass.

**Direct schedules.**
- 8 vectors were checked: the 1,800-second reading and the final vector of each run. Both are the same incumbent, which was the first and only one.
- Every vector is the one-truck-per-task starting schedule: 320 or 400 vendor one-task routes, no graph route, no battery.
- The residuals, including flow conservation, are 0. Recomputed costs equal the reported ones to within 1.5·10⁻¹¹.
- The vendor master over the same routes gives the same cost.

**CG bounds.**
- All four CG runs report pricing convergence (`cg_priced_out` and `final_pricing_call_empty`).
- The certificate uses the exact reduced-cost DP over the full rebuilt graph plus all one-task routes. The most negative reduced cost is between −1.9·10⁻¹¹ and −1.1·10⁻¹¹.
- The battery reduced cost is +36 (= c_b), so the battery term is zero.
- Each certificate is above the reported bound by n·10⁻⁶ (3.2·10⁻⁴ and 4.0·10⁻⁴), to within 10⁻⁸. This is because the reported bound is the final RMP value minus n·10⁻⁶ (checked against `cg_lp.objective` in each `result.json`).

**LB\* and gaps.**
- The direct runs report no Gurobi bound, so LB\* is the certified CG bound in all four rows. These rows do not depend on any Gurobi bound.
- Rows rebuilt from validated values match the collector's rows field by field (4/4). From them, `make_tables.py` reproduces all 4 printed lines exactly.
- Manuscript l. 1187:
  - "gaps of 5.3--11.7%": recomputed as 5.30–11.73%.
  - "holds only its starting schedule": confirmed (see Direct schedules).
  - "39--60 million arcs": the rebuilt counts (39.4–60.5 million).

**Not covered.**
- **Times.** These are clock records and were not validated: the CG phase (3,686–8,345 s, "61--139 minutes" in the manuscript), the route-MIP and direct limits, and the incumbent times.
- **Root relaxation.** That the direct root relaxation was not solved comes from the solver record (`root_lp_solved_seconds` = null). The validator confirms only that no bound was reported and that the only incumbent is the starting schedule.
- **Preempted attempts.** The CG run at 160 locations, sample 1, was preempted twice (job 365215, `SLURM_RESTART_COUNT` = 2). The two partial attempts in `preempted/` were not validated. The validated run is the complete one in `results/`.

**Jobs.**
- Common settings for all jobs:
  - flags `--nodes=1 --ntasks=1 --cpus-per-task=1 --hint=nomultithread --requeue`;
  - command `/usr/bin/time -v worker.sh`, with `JOBS=jobs_mapx.json` (and `NOHINTS=1` for the second pass).
- Memory was first measured on one 160-location input: job 380169, 32 GB requested, peak RSS 3.24 GB, 27 s.
- The rest were then sized from that measurement:
  - first pass: 380192 (8 GB) and 380193 (12 GB); peak RSS 3.19 GB at 160 locations, 5.23–5.79 GB at 200; 47–93 s;
  - witness-free pass: 380194 (12 GB) and 380195 (16 GB); peak RSS 3.24–3.25 GB and 4.93 GB; 10–20 min.
- All jobs COMPLETED with exit 0 and no requeue.
- Job IDs on unicorn have wrapped around, so query `sacct` with `-S 2026-10-18`.
- On the cluster, the unchanged worker wrote the reports to `results/grid/` and `results_nohints/grid/`; the case names do not collide with the 64 grid inputs. The local copies are in `results/mapx/` and `results_nohints/mapx/`.

**Files.**
- Reports:
  - `results/mapx/<case>.json`
  - `results_by_arm/mapx/<case>__{cg1800,direct}.json`
  - `results_nohints/mapx/<case>.json`
- Summaries: `validation_summary_mapx.json`, `cg_bound_certificates_mapx.json`, `aggregate_mapx_stdout.txt`.
- Scripts: `src/make_jobs_mapx.py`, `src/aggregate_mapx.py`.
- Slurm records: `slurm/jobs_mapx.json`, `slurm/submit_mapx_receipt.json`, `slurm/sacct_mapx.txt` (with the peak RSS of each job).
- `aggregate.py` reads every `results/*/*.json`. Rerunning it, or `finalize.sh`, would therefore add these 4 CG arms and 8 direct vectors to its counts. Its table checks would not change.
