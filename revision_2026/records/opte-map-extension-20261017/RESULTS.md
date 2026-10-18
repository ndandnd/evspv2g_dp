# Map extension of Table 4 (tab:locscaling): 160 and 200 locations

Code: `experiments/opte_map_extension_20261017` (PROTOCOL.md). Results: `unicorn:~/opte-map-extension-20261017/results/`; all 8 arms done. `result.json` and `manifest.json` were copied with rsync to `raw/`. `collect_grid.py` and `make_tables.py` are byte-identical copies of the ones in `output/opte-grid-results-20261016/` and were run on `raw/`. Their outputs are `grid_rows.json` and `table8_rows.tex`.

## Rows (Table 4 format)

```
160 & 320 & 1 & 39.4 & 3{,}686 & 1{,}800 & 11.73 & not solved & starting schedule only (57.7) \\
160 & 320 & 2 & 39.5 & 4{,}276 & 1{,}800 & 5.30 & not solved & starting schedule only (58.5) \\
200 & 400 & 1 & 60.5 & 7{,}620 & 1{,}800 & 10.60 & not solved & starting schedule only (58.0) \\
200 & 400 & 2 & 60.4 & 8{,}345 & 1{,}800 & 7.59 & not solved & starting schedule only (57.8) \\
```

In these rows, "not solved" means not solved within 1,800 s. In Table 4 it means not within 3,600 s (see "Protocol differences").

## Per input (measured)

| L / n / sample | arcs | CG phase | CG converged | route MIP | CG bound (= LB*) | U (CG routes) | gap (%) | pool bound (% above CG bound) | pool own gap (%) | direct root | direct at 1,800 s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 160/320/1 | 39,426,390 | 3,686 s | yes | 1,800 s, time_limit | 22,037.67 | 24,964.89 | 11.73 | 22,143.91 (0.48) | 11.30 | not solved | start only, 52,103.95 (57.70) |
| 160/320/2 | 39,513,418 | 4,276 s | yes | 1,800 s, time_limit | 21,647.37 | 22,858.96 | 5.30 | 21,726.31 (0.36) | 4.95 | not solved | start only, 52,103.95 (58.45) |
| 200/400/1 | 60,479,730 | 7,620 s | yes | 1,800 s, time_limit | 27,425.67 | 30,676.94 | 10.60 | 27,490.04 (0.23) | 10.39 | not solved | start only, 65,309.95 (58.01) |
| 200/400/2 | 60,425,577 | 8,345 s | yes | 1,800 s, time_limit | 27,570.74 | 29,836.56 | 7.59 | 27,634.00 (0.23) | 7.38 | not solved | start only, 65,309.95 (57.78) |

- "CG converged" means `cg_priced_out` and `final_pricing_call_empty` are both true (`cg_status` = candidate_priced_out). This took 1,511-2,411 RMP calls, well within the 14,400-s cap.
- Route MIP: 1,870-2,850 integer variables (2,063-3,043 variables in total), 62k-112k nodes, 10 solutions each. It reached the 1,800-s limit in all four runs.
- CG + route MIP total: 5,486 / 6,076 / 9,420 / 10,145 s (91-169 min).
- LB* is the CG bound in all four rows because the direct runs reported no bound (`bound` = null). Table 4 rows at 50-120 locations also use the CG bound, since their direct bound was 0 or null. The gap is computed the same way in practice.
- Direct MIP: there was one incumbent in each run, the one-truck-per-task starting schedule (fleet 320/400), found at 199 / 199 / 302 / 299 s. The runs logged 0 simplex iterations, 0 barrier iterations and no bound. The solver used its whole remaining budget (solve 1,512-1,610 s after 113-173 s of model build) and stopped at 1,804-1,807 s from construction. Peak RSS was 34.5-34.9 GB at 160 locations and 52.9-53.1 GB at 200, against 128/190 GB requested.
- What the bounds show (measured): the restricted MIP's own gap is 4.95-11.30%, so its integer search was far from finished. Its own bound is only 0.23-0.48% above the CG bound. The pool's integer optimum lies somewhere between the pool bound and U, so these runs cannot split the 5.3-11.7% gap into route-restriction loss and unfinished search. This is the same caveat as the M20 paragraph.

## Validation flags (all measured, all pass)

- `instance_sha256` agrees in the result, the manifest and `preflight_local.json` for all 8 arms. The `code_sha256` in each manifest equals the preflight `code_sha256`.
- Environment: AMD EPYC 9654 on every arm. `allocated_cpus` = 1, CPU affinity is a single core, threads = 1, Gurobi 12.0.3. Hosts were samitha-compute-01, portal-compute-04, jjs533-compute-02 and cdses-compute-01.
- CG arms: `incumbent_validated`, `matrix_primal_check.passed`, `validation.passed`, `aggregate.passed` and `original_model_feasible` are all true, with artificial mass 0. `selected_paths.passed` is true (all_selected_columns_witnessed, max residual 0). The replayed objective equals U (aggregate max residual 3.6e-12). The checks pool bound >= CG bound and U >= pool bound hold for all four.
- Direct arms: `incumbent_validated`, `matrix_primal_check.passed` and `validation.passed` are all true (max residual 1.5e-11). The one incumbent event passed both the matrix check and the physical replay.
- Restart: the CG arm for 160/sample 1 was preempted twice (`SLURM_RESTART_COUNT` = 2, job 365215). Both partial attempts were moved to `preempted/` and are not used. The reported run started fresh at 2026-10-18 02:47 UTC and ran to completion (CG 3,686 s, MIP 1,800 s, diagnostics 1,244 s). The other 7 arms started at 2026-10-17 23:33 UTC with no restarts.

## Protocol differences from Table 4

1. Direct MIP limit: 1,800 s here, 3,600 s in Table 4. The "Result at 1,800 s" column reads the same quantity. The "Direct MIP root" column does not: the Table 4 caption defines "not solved" as not within 3,600 s. Inferred, not measured: a 3,600-s limit would very likely not change these rows, because the 120-location Table 4 direct runs also logged 0 barrier iterations at 3,600 s.
2. Total time: CG + route MIP used 91-169 min, while the direct MIP had 30 min. In Table 4 at 40-120 locations the direct MIP had more total time than CG + MIP. That is no longer true here.

## Recommendation

**Mention in one sentence; do not add the rows to Table 4.** CG converged on all four inputs and every validation check passed, so adding the rows would be defensible. It would, however, require five edits for a minor revision, plus a figure:
- Table 4 caption (l. 1203 of `blue_manuscript.tex`): add a clause that the direct MIP had a 1,800-s limit at 160 and 200 locations, or put a dagger on "not solved".
- l. 1186: "CG converges at every size, within 2{,}209 seconds" would become 8,345 s. "within 6\% at 100--120 locations" would need gaps up to 11.7% at 160-200 locations.
- l. 1193: "finished within 57 minutes ... (67 minutes at 120)" would need 169 min at 200. The sentence's claim that the direct MIP had more total time would not hold for the new rows.
- l. 1192: the 3,600-s rerun sentence covers "the 40--120-location instances of Table 4". It would need a note that the new rows were not rerun.
- Fig. breakpoint caption (l. 1245): "all 164 instances of Tables ..." and panel (a). Either regenerate the figure or limit it to at most 120 locations.

A single sentence carries the result without any of these edits.

## Draft sentence

Insert after the sentence that ends "within 6\% at 100--120 locations" (l. 1186):

> On two further sizes, 160 and 200 locations (320 and 400 tasks, 39--60 million arcs, two samples each), CG converged in 3{,}686--8{,}345 seconds and the restricted MIP reached its 1{,}800-second limit with gaps of 5.3--11.7\%, its own bound being within 0.5\% of the CG bound, whereas the direct MIP, run with a 1{,}800-second limit, did not solve its root relaxation and held only its starting schedule (gaps 57.7--58.5\%).

## Files

- `raw/<case>/{cg_pool_mip,direct_mip}/{result,manifest}.json`: the 16 copied files.
- `collect_grid.py` and `make_tables.py`: unchanged copies.
- `grid_rows.json`: collector output.
- `table8_rows.tex`: the four rows above.
