# Revision experiments (October 2026)

This folder holds the code, run records and independent validation for the
experiments added in the October 2026 revision of the manuscript: Tables
4-6 and 14-18, Fig. 3, the 160- and 200-location runs and the 3,600-second
runs of Section 8.2, the plug-limit study and its integer rerun, and the
Corollary 1 checks (map below). The code at the repository root is
the first-submission code; every experiment here runs a frozen, hash-checked
copy of it (`runtime/frozen/vendor/` or `vendor/` inside each study).

| Folder | Contents |
|---|---|
| `code/<study>/` | Experiment code as run: runners, input builders, frozen solver code, protocols. `code/cluster_code_hashes/` lists the SHA-256 of the copies that ran on the cluster; they equal the files here, except `opte_equal_mip_20261015/TABLE_SPEC.md`, a table-planning note that is not included. |
| `records/<study>/` | Run records (`result.json`, `manifest.json` per run), collectors, table generators, and the row and text files inserted into the manuscript. `records/INDEX.csv` lists every raw JSON file of the Tables 4, 15-18 and 3,600-s folders with the size and SHA-256 of its original; the original plug study has its own `COPY_INDEX.csv`. |
| `validation/` | Independent validator (`src/`), its report `VALIDATION.md`, per-run outputs and the summary `validation_summary.json`. It covers Tables 4 and 15-18, Fig. 3 and the 3,600-s runs; see "Validation coverage". |

Folder names carry the date of the study. Table numbers in this file are those
of the final manuscript (see "Older numbers" below).

## Where each result comes from (current manuscript numbering)

| Manuscript item | Code | Records (rows) |
|---|---|---|
| Table 4 (`tab:locscaling`), map growth | `code/opte_grid_scaling_20261016` (`runtime/run_grid.py`) | `records/opte-grid-results-20261016` (`table8_rows.tex`) |
| Section 8.2, 160 and 200 locations (sentence after Table 4) | `code/opte_map_extension_20261017` | `records/opte-map-extension-20261017` (`RESULTS.md`, `table8_rows.tex`) |
| Table 5 (`tab:decomp`), restricted-MIP medians and direct bounds over 270 planning bases (Section 8.4, Appendix B.1 "Planning checks") | `code/opte_planning_population_20261012` (60-s direct solves), `code/opte_planning_refinement_20261013` (300-s refinements) | `records/opte-planning-20261012` (`planning_population_analysis_final_20261012/`, `planning_refinement_analysis_final_20261013/`; repair and residuals in `planning_population_numerical_sensitivity_verified_20261012/`) |
| Table 6 (`tab:planningdirect`), targeted planning checks | `code/opte_lp_scaling_20261012` (`planning_direct.py`) | `records/opte-planning-20261012/table9_planning_direct/` |
| Table 14 (`tab:cgreuse`, Appendix C), master reuse | `code/opte_cg_reuse_20261013` | `records/opte-cg-reuse-20261013` (`cg_reuse_analysis_final_20261013/worker_outcomes.csv`) |
| Table 15 (`tab:taskscaling`, Appendix D.1), number of tasks | `code/opte_task_scaling_20261016` (`runtime/run_task_scaling.py`) | `records/opte-task-scaling-results-20261016` (`v9654/main_table_rows.tex`) |
| Table 16 (`tab:equalmip`, Appendix D.2), 23 further instances | `code/opte_equal_mip_20261015` (`runtime/run_equal_mip.py`, `PROTOCOL.md`) | `records/opte-equal-mip-results-20261016` (`appendix_table_rows.tex`) |
| Table 17 (`tab:grid`, Appendix D.3), map x tasks | `code/opte_grid_scaling_20261016` | `records/opte-grid-results-20261016` (`table21_cg_rows.tex`, `table21_direct_rows.tex`) |
| Table 18 (`tab:transition`, Appendix D.4), six samples per cell | `code/opte_transition_20261017` (`runtime/run_transition.py`) | `records/opte-transition-results-20261017` (`transition_rows.tex`) |
| Fig. 3 (`fig:breakpoint`) | as Tables 4, 17, 18 | `records/opte-transition-results-20261017/figure/` |
| 3,600-second runs (Section 8.2) | `code/opte_grid_scaling_20261016`, `code/opte_transition_20261017` | `records/opte-3600-results-20261017` (`rows_3600.json`) |
| Plug limits, LP numbers (Remark on plug limits; response letter) | `code/opte_plugs_20261013` (original plug study, LP arms) | `records/opte-plugs-final-20261015` (`plug_table.md`, `plug_results.json`) |
| Plug limits, integer numbers (Remark on plug limits; response letter): rerun under the benchmark protocol | `code/opte_plugs_protocol_20261017` | `records/opte-plugs-protocol-20261017` (`RESULTS.md`, `summary/`) |
| Corollary 1 divisibility checks (Section 7) | `code/opte_corollary1_check_20261015`, `code/opte_conservative_grid_20261017` | `records/opte-corollary1-check-20261015`, `records/opte-conservative-grid-20261017` |
| CG speed comparison of the original and current code (response letter, comment 1) | first-submission code at the repository root and `code/opte_equal_mip_20261015` | `records/opte-cg-speed-ablation-20261017` (`ABLATION.md`) |
| Not in the final manuscript, kept for completeness: LP times of dual simplex, barrier and CG with a rebuilt master (108 runs); direct MIPs on the four 1,000-task instances of Table 3 (summarized in one sentence in Section 8.2) | `code/opte_lp_scaling_20261012`, `code/opte_direct_mip1000_20261012` | `records/opte-lp-scaling-20261012`, `records/opte-direct-mip1000-20261012` |

Tables 1-3 and 7-13, and Figs. 1, 2 and 4-12, come from the first-submission code and results at the repository root.

**Two plug studies.** The original plug study (`opte_plugs_20261013`, 72 arms)
ran four arms per input: CG LP, direct barrier LP, CG followed by the MIP over
its routes, and the direct MIP, each with 1,800 s. Its LP arms are the source
of the LP numbers. Its integer arms shared one 1,800-s budget between CG
(capped at 600 s) and the MIP; they are superseded by the rerun
(`opte_plugs_protocol_20261017`, 36 integer arms), which uses the benchmark
protocol (CG to pricing convergence, then 1,800 s for each MIP). All integer
numbers in the paper and the letter come from the rerun. The original integer
arms stay in `records/opte-plugs-final-20261015` for completeness.

**Older numbers in file names and notes.** The records were written while the
tables were being renumbered, so their notes and file names use earlier numbers:

- Most notes (including `validation/.../VALIDATION.md`): Table 8 = current
  Table 4, and Tables 19, 20, 21, 22 = current Tables 15, 16, 17, 18.
  Protocols written before the runs may cite still older numbers.
- File names: `table8_*` = Table 4, `table21_*` = Table 17,
  `table9_planning_direct` = Table 6.
- `records/make_small_tables.py` labels its output Table 5 (`tab:lpscaling`,
  the LP-scaling study), Table 6 (`tab:directlarge`, the four 1,000-task
  direct MIPs) and Table 17 (`tab:cgreuse`, now Table 14). The first two are
  not in the final manuscript.

**One hand edit.** In Table 16, the 4,000-task row prints the direct gap as
`<0.01 (TL)`; the generator prints `0.00`. Stored values: cost at 1,800 s
209,811.50, best lower bound 209,806.94, gap 0.0022%, direct status time limit.

**Memory reruns.** Eight direct runs of the grid study (Tables 4 and 17)
stopped at their memory limit and were rerun with 72 GB (`raw_mem72/`, used by
the collector); `mem72_readout_comparison.json` shows that the 1,800-s
readings are identical.

**Text files.** The `*_text.tex` files are the drafts first inserted into the
manuscript. The manuscript text was edited afterwards; the row files are the
numbers printed.

## Conventions

- **Sample numbering.** Sample *k* is the input with draw index *k*-1, i.e.
  case suffix `_draw{k-1}` (Tables 4, 15, 17, 18, the 160/200-location runs
  and the panel inputs of Table 16) or `_s{k-1}` (Table 14 and the other
  inputs of Table 16). Samples differ only in the random seed of the task
  generator.
- **Gap** = 100(U - LB\*)/U. LB\* is the larger of the CG bound z_RMP - n 10^-6
  (only when pricing found no column with reduced cost below -10^-6) and the
  direct MIP's branch-and-bound bound at the end of its run. The bound of the
  MIP over the CG routes applies to its route pool only and is never used.
- **Clocks.** CG phase = `cg_seconds`, until pricing converged, not charged to
  the MIP budget. Route MIP = `mip_seconds`, from the construction of the MIP
  over the generated routes. The direct MIP clock starts before graph
  construction and includes the root LP. The reading at time T is the best
  incumbent with `elapsed_seconds` <= T that passed the in-run matrix check and
  physical replay.
- **Budgets** (from the run manifests):

  | Item | CG cap | MIP over CG routes | Direct MIP run (read at) |
  |---|---|---|---|
  | Tables 4, 17 (grid study) | 14,400 s | 1,800 s | 3,600 s (1,800 s) |
  | Table 15 | 3,600 s (n <= 500), 10,800 s (n > 500) | 1,800 s | 3,600 s, 10,800 s (1,800 s) |
  | Table 16 | 14,400 s | 1,800 s | 3,600 s panel, 16,200 s others (1,800 s) |
  | Table 18 | 14,400 s | 1,800 s | 1,800 s (1,800 s) |
  | 160 and 200 locations (Section 8.2) | 14,400 s | 1,800 s | 1,800 s (1,800 s) |
  | 3,600-s runs | 14,400 s | 3,600 s | 3,600 s (3,600 s) |
  | Plug rerun, integer arms (integer numbers in the paper and letter) | 14,400 s | 1,800 s | 1,800 s (1,800 s) |
  | Original plug study, integer arms (superseded, not cited) | 600 s, inside one 1,800-s budget | rest of the 1,800 s | 1,800 s |

  The 3,600-s runs repeat the MIP over the CG routes for 48 inputs (18 grid
  inputs with 40-120 locations, 30 transition inputs with 30 and 35 locations)
  and the direct MIP for the 30 transition inputs; for the grid inputs they use
  the original 3,600-s direct runs. The LP arms of the original plug study (CG
  LP and direct barrier LP, the source of the LP numbers) had 1,800 s each,
  counted from construction. Table 14 and the two studies not in the final
  manuscript (LP scaling, four 1,000-task direct MIPs) are separate studies
  with 1,800 s per arm, counted from model construction. Tables 5 and 6 use
  the budgets in their protocols (`code/opte_planning_*`,
  `code/opte_lp_scaling_20261012`).

  Each manifest records all three budget arguments; those its arm does not
  use keep the runner's defaults (for example `cg_cap_seconds` 1,200 in
  direct-MIP manifests and `direct_budget_seconds` 3,000 in CG manifests).

## Validation coverage

- **Independent validator** (`validation/`): Tables 4 and 15-18, Fig. 3, the
  3,600-s runs and the 160- and 200-location runs, that is 239 inputs and 556
  saved runs (287 CG + route MIP, 269 direct MIP; the 160/200-location runs are
  in the addendum of `VALIDATION.md`). It rebuilds each input, replays every reported schedule and
  certifies each CG bound from the saved duals; all checks passed. It does not
  check run times, and it does not cover the eight grid direct runs replaced by
  the 72-GB reruns (not printed).
- **In-run checks only:** the plug-limit integer rerun. Every reported
  schedule passed the in-run matrix check and the replay of its routes, with
  zero plug violation, and the input and code hashes match the preflight
  records (`records/opte-plugs-protocol-20261017/RESULTS.md`). The independent
  validator does not model plug limits.
- The other studies (Tables 5, 6 and 14, the original plug study, the
  Corollary 1 checks) carry their own checks in their records.

## Software and hardware

- Python 3.12.13, NumPy 1.26.4, SciPy 1.13.1, gurobipy 12.0.3, as recorded in
  the run manifests. One bound CPU, one Gurobi thread, BLAS/OpenMP threads 1,
  Gurobi seed 0.
- Gurobi parameters of the MIPs: MIPGap 1e-6, MIPGapAbs 1e-10,
  FeasibilityTol, OptimalityTol and IntFeasTol 1e-8. The direct MIP solves its
  root with barrier (Method 2) in Tables 4 and 15-18, the 160/200-location runs
  and both plug studies, and with the automatic method in the four 1,000-task
  direct MIPs; the MIP over the CG routes uses the automatic method. The
  LP-scaling study uses dual simplex (Method 1) and barrier (Method 2) with
  tolerances 1e-8. CG stops when pricing finds no column with reduced cost
  below -10^-6.
- Hardware: AMD EPYC 9654 for all timed cluster runs, except some Table 16
  inputs on AMD EPYC 9555 (both methods of an input on the same node; see
  Appendix D.2). The validator ran on other nodes; its times are not used.
- The Corollary 1 step sweep and the conservative-rounding test ran on a laptop
  (the latter solves its route MIPs with Gurobi 12.0.1); their times are not
  used as timing evidence.

## Regenerating the rows from the stored records

The scripts overwrite their outputs, so work on a copy:

```bash
cp -R revision_2026/records /tmp/records && cd /tmp/records
(cd opte-grid-results-20261016 && python3 collect_grid.py raw raw_mem72 && python3 make_tables.py)            # Tables 4, 17
(cd opte-map-extension-20261017 && python3 collect_grid.py raw && python3 make_tables.py)                    # 160 and 200 locations
(cd opte-transition-results-20261017 && python3 collect_transition.py raw && python3 make_transition_table.py) # Table 18
(cd opte-task-scaling-results-20261016/v9654 && python3 ../collect_task_scaling.py ../raw9654 && python3 ../make_main_table.py) # Table 15
(cd opte-equal-mip-results-20261016 && python3 collect_prelim.py && python3 make_appendix_table.py)          # Table 16 (then the hand edit)
(cd opte-3600-results-20261017 && python3 analyze_3600.py)                                                   # 3,600-s runs
(cd opte-transition-results-20261017 && python3 make_figure.py)                                              # Fig. 3 (needs matplotlib)
python3 make_small_tables.py                                                                                 # Table 14 (and two untabled studies)
(cd opte-corollary1-check-20261015 && python3 summarize_sweep.py)                                            # step sweep table
```

The collectors need only the Python standard library. From this folder the
row files, `sweep_table.md` and the PNG of Fig. 3 regenerate byte for byte,
the JSON row files are equal after parsing (the PDF of Fig. 3 differs only in
its creation date), and `make_small_tables.py` prints the printed rows of
Table 14. For the 160 and 200 locations, `make_tables.py` also writes
`table21_*` files, which are not used.

**Compacted records.** The CG `result.json` and `native_stop.json` files hold
the full CG trace; the 303 originals above 1 MB total about 22 GB. Here each of
them is an extract (original plug study: every raw JSON file above 100 kB, as
listed in its `COPY_INDEX.csv`; `plug_results.json` is kept whole): all scalars
and all lists of at most 400 pretty-printed lines are kept; longer lists are
replaced by `{"_omitted_list": true, "elements": N, ...}`. Each extract stores
the size and SHA-256 of its original under `_compaction`. The extracts were
made with `records/tools/compact_result.py`. The collectors above read only
kept fields. `records/opte-plugs-final-20261015/collect_plugs.py` checks the
hash of every raw file and therefore needs the full originals.

## Running the experiments

The runners of Tables 4 and 15-18 (`run_grid.py`, `run_task_scaling.py`,
`run_equal_mip.py`, `run_transition.py` in `code/<study>/runtime/`) print their
plan with `--plan` and run one arm with `--case-name CASE --arm
{cg_pool_mip,direct_mip} --results DIR`; budgets are set with `--cg-cap`,
`--mip-budget` and `--direct-budget`. They check the frozen code against
`runtime/frozen_manifest.json` before they start and, by default, require
Gurobi 12.0.3 and an AMD EPYC processor (`--require-gurobi`,
`--require-cpu-model`). A Gurobi license is required. Some scripts were
written for the original project layout, in which `experiments/<study>/` is
`code/<study>/` here and `output/<folder>/` is `records/<folder>/`; the path
`~/Downloads/paper-rewrite 2/code` in some scripts and records is the
first-submission code at the repository root.

## Journal computational supplement

The journal's computational supplement contains this folder, identical to the
version in this repository, and adds the saved vectors of the 564 run folders
behind Tables 4 and 15-18, Fig. 3, the 3,600-s runs and the 160/200-location
runs (the 556 validated runs and the 8 grid direct runs replaced by the 72-GB
reruns): 2,095 `*.npz` and 851 `*.json.gz` files, about 126 MB.

- Direct MIP: time-stamped incumbents `incumbent_NNN.npz`, the final vector
  `direct_mip_primal.npz` and the in-run physical replay
  `physical_replay.json.gz`.
- CG and the MIP over its routes: the route-MIP solution
  `restricted_primal.npz`, the CG stopping duals `cg_stopping_primal.npz`, and
  the generated routes `cg_pool_columns.json.gz` and
  `cg_stopping_columns.json.gz`.

The independent validator replayed the vectors of the 556 validated runs. The
supplement's own README maps each vector folder to its records folder here.

## Not included

- In neither this repository nor the supplement: the full CG traces (the
  complete `result.json` and `native_stop.json` files, about 22 GB), and the
  schedule vectors of both plug studies. They
  are kept by the authors. The validator in `validation/` replays the vectors
  of the supplement, so it cannot be rerun from this repository alone; its
  outputs are included.
- Per-run raw files of Tables 5 and 14, of the LP-scaling study and of the
  conservative-rounding test; their summary records are included.
- Slurm logs, accounting and submission scripts of the experiment runs (the
  validator's job list, receipts, accounting and worker script are in
  `validation/opte-independent-validation-20261017/slurm/`); superseded
  attempts (the first mixed-processor task-scaling run, a location-scaling
  pilot that no table uses, and preempted or cancelled runs).
- The script that redrew Fig. 2 with corrected legend labels (plotted values unchanged).
