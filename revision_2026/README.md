# Revision experiments (October 2026)

This folder holds the code, run records and independent validation for the
solver benchmarks added in the October 2026 revision of the manuscript: Tables
5-7 and 17-21, Fig. 3, the 3,600-second runs, the plug-limit study and the
Corollary 1 checks (map below). The planning studies behind Tables 8 and 9 are
not included (see the end of this file). The code at the repository root is
the first-submission code; every experiment here runs a frozen, hash-checked
copy of it (`runtime/frozen/vendor/` or `vendor/` inside each study).

| Folder | Contents |
|---|---|
| `code/<study>/` | Experiment code as run: runners, input builders, frozen solver code, protocols. `code/cluster_code_hashes/` lists the SHA-256 of the copies that ran on the cluster; they equal the files here, except `opte_equal_mip_20261015/TABLE_SPEC.md`, a table-planning note that is not included. |
| `records/<study>/` | Run records (`result.json`, `manifest.json` per run), collectors, table generators, and the row and text files inserted into the manuscript. `records/INDEX.csv` lists every raw JSON file of the Tables 7, 18-21 and 3,600-s folders with the size and SHA-256 of its original; the plug study has its own `COPY_INDEX.csv`. |
| `validation/` | Independent validator (`src/`), its report `VALIDATION.md`, per-run outputs and the summary `validation_summary.json`. |

Folder names carry the date of the study.

## Where each result comes from (current manuscript numbering)

| Manuscript item | Code | Records (rows) |
|---|---|---|
| Table 5 (`tab:lpscaling`), LP times, 108 runs | `code/opte_lp_scaling_20261012` | `records/opte-lp-scaling-20261012` (`lp_analysis_final_20261012/lp_scaling_workers.csv`; validation in `lp_analysis_final_certificate_20261012/`) |
| Table 6 (`tab:directlarge`), direct MIPs on four 1,000-task inputs | `code/opte_direct_mip1000_20261012` | `records/opte-direct-mip1000-20261012` (`direct_mip1000_analysis_20261012/mip1000_comparison.csv`) |
| Table 7 (`tab:locscaling`), map growth | `code/opte_grid_scaling_20261016` (`runtime/run_grid.py`) | `records/opte-grid-results-20261016` (`table8_rows.tex`) |
| Table 17 (`tab:cgreuse`), master reuse | `code/opte_cg_reuse_20261013` | `records/opte-cg-reuse-20261013` (`cg_reuse_analysis_final_20261013/worker_outcomes.csv`) |
| Table 18 (`tab:taskscaling`), number of tasks | `code/opte_task_scaling_20261016` (`runtime/run_task_scaling.py`) | `records/opte-task-scaling-results-20261016` (`v9654/main_table_rows.tex`) |
| Table 19 (`tab:equalmip`), 23 further inputs | `code/opte_equal_mip_20261015` (`runtime/run_equal_mip.py`, `PROTOCOL.md`) | `records/opte-equal-mip-results-20261016` (`appendix_table_rows.tex`) |
| Table 20 (`tab:grid`), map x tasks | `code/opte_grid_scaling_20261016` | `records/opte-grid-results-20261016` (`table21_cg_rows.tex` and `table21_direct_rows.tex`, printed side by side) |
| Table 21 (`tab:transition`), six samples per cell | `code/opte_transition_20261017` (`runtime/run_transition.py`) | `records/opte-transition-results-20261017` (`transition_rows.tex`) |
| Fig. 3 (`fig:breakpoint`) | as Tables 7, 20, 21 | `records/opte-transition-results-20261017/figure/` |
| 3,600-second runs (Section 8.2) | `code/opte_grid_scaling_20261016`, `code/opte_transition_20261017` | `records/opte-3600-results-20261017` (`rows_3600.json`) |
| Plug limits (Remark `rem:infra` in Section 5; Section 9) | `code/opte_plugs_20261013` | `records/opte-plugs-final-20261015` (`plug_table.md`, `plug_results.json`, `plug_arms.csv`) |
| Corollary 1 divisibility checks (Section 7) | `code/opte_corollary1_check_20261015`, `code/opte_conservative_grid_20261017` | `records/opte-corollary1-check-20261015` (`audit_table.md`, `sweep_table.md`), `records/opte-conservative-grid-20261017` (`tables.md`, `summary.json`) |

**Older numbers in file names and notes.** File names and the notes inside the
records (including `validation/.../VALIDATION.md`) use the numbering of an
earlier draft: old Table 8 = Table 7, old 19 = 18, old 20 = 19, old 21 = 20,
old 22 = 21. Protocols written before the runs may cite still older numbers.
Use the table above.

**One hand edit.** In Table 19, the 4,000-task row prints the direct gap as
`<0.01 (TL)`; the generator prints `0.00`. Stored values: cost at 1,800 s
209,811.50, best lower bound 209,806.94, gap 0.0022%, direct status time limit.

**Memory reruns.** Eight direct runs of Tables 7 and 20 stopped at their
memory limit and were rerun with 72 GB (`raw_mem72/`, used by the collector);
`mem72_readout_comparison.json` shows that the 1,800-s readings are identical.

**Text files.** The `*_text.tex` files are the drafts first inserted into the
manuscript. The manuscript text was edited afterwards; the row files are the
numbers printed.

## Conventions

- **Sample numbering.** Sample *k* is the input with draw index *k*-1, i.e.
  case suffix `_draw{k-1}` (Tables 7, 18, 20, 21 and the panel inputs of Table
  19) or `_s{k-1}` (Tables 5, 6, 17 and the other inputs of Table 19). Samples
  differ only in the random seed of the task generator.
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
  | Tables 7, 20 | 14,400 s | 1,800 s | 3,600 s (1,800 s) |
  | Table 18 | 3,600 s (n <= 500), 10,800 s (n > 500) | 1,800 s | 3,600 s, 10,800 s (1,800 s) |
  | Table 19 | 14,400 s | 1,800 s | 3,600 s panel, 16,200 s others (1,800 s) |
  | Table 21 | 14,400 s | 1,800 s | 1,800 s (1,800 s) |
  | 3,600-s runs | 14,400 s | 3,600 s | 3,600 s (3,600 s) |
  | Plug study, integer arms | 600 s | rest of 1,800 s | 1,800 s |

  The 3,600-s runs repeat the MIP over the CG routes for 48 inputs (18 grid
  inputs with 40-120 locations, 30 transition inputs with 30 and 35 locations)
  and the direct MIP for the 30 transition inputs; for the grid inputs they use
  the original 3,600-s direct runs. Tables 5, 6 and 17 are separate studies
  with 1,800 s per arm, counted from model construction.

## Software and hardware

- Python 3.12.13, NumPy 1.26.4, SciPy 1.13.1, gurobipy 12.0.3, as recorded in
  the run manifests. One bound CPU, one Gurobi thread, BLAS/OpenMP threads 1,
  Gurobi seed 0.
- Gurobi parameters of the MIPs: MIPGap 1e-6, MIPGapAbs 1e-10,
  FeasibilityTol, OptimalityTol and IntFeasTol 1e-8. The direct MIP solves its
  root with barrier (Method 2) in Tables 7 and 18-21 and the plug study, and
  with the automatic method in Table 6; the MIP over the CG routes uses the
  automatic method. Table 5 uses dual simplex (Method 1) and barrier (Method 2)
  with tolerances 1e-8. CG stops when pricing finds no column with reduced
  cost below -10^-6.
- Hardware: AMD EPYC 9654 for all timed cluster runs, except some Table 19
  inputs on AMD EPYC 9555 (both methods of an input on the same node; see
  Appendix D.2). The validator ran on other nodes; its times are not used.
- The Corollary 1 step sweep and the conservative-rounding test ran on a laptop
  (the latter solves its route MIPs with Gurobi 12.0.1); their times are not
  used as timing evidence.

## Regenerating the rows from the stored records

The scripts overwrite their outputs, so work on a copy:

```bash
cp -R revision_2026/records /tmp/records && cd /tmp/records
(cd opte-grid-results-20261016 && python3 collect_grid.py raw raw_mem72 && python3 make_tables.py)            # Tables 7, 20
(cd opte-transition-results-20261017 && python3 collect_transition.py raw && python3 make_transition_table.py) # Table 21
(cd opte-task-scaling-results-20261016/v9654 && python3 ../collect_task_scaling.py ../raw9654 && python3 ../make_main_table.py) # Table 18
(cd opte-equal-mip-results-20261016 && python3 collect_prelim.py && python3 make_appendix_table.py)          # Table 19 (then the hand edit)
(cd opte-3600-results-20261017 && python3 analyze_3600.py)                                                   # 3,600-s runs
(cd opte-transition-results-20261017 && python3 make_figure.py)                                              # Fig. 3 (needs matplotlib)
python3 make_small_tables.py                                                                                 # Tables 5, 6, 17
(cd opte-corollary1-check-20261015 && python3 summarize_sweep.py)                                            # step sweep table
```

The collectors need only the Python standard library. From this folder the
row files, `sweep_table.md` and the PNG of Fig. 3 regenerate byte for byte,
the JSON row files are equal after parsing (the PDF of Fig. 3 differs only in
its creation date), and `make_small_tables.py` prints the printed rows of
Tables 5, 6 and 17.

**Compacted records.** The CG `result.json` and `native_stop.json` files hold
the full CG trace; the 303 originals above 1 MB total about 22 GB. Here each of
them is an extract (plug study: every raw JSON file above 100 kB, as listed in
its `COPY_INDEX.csv`; `plug_results.json` is kept whole): all scalars and all
lists of at most 400 pretty-printed lines are kept; longer lists are replaced
by `{"_omitted_list": true, "elements": N, ...}`. Each extract stores the size
and SHA-256 of its original under `_compaction`. The extracts were made with
`records/tools/compact_result.py`. The collectors above read only kept fields.
`records/opte-plugs-final-20261015/collect_plugs.py` checks the hash of every
raw file and therefore needs the full originals.

## Running the experiments

The runners of Tables 7 and 18-21 (`run_grid.py`, `run_task_scaling.py`,
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

## Not included

- Schedule vectors (`*.npz`), generated route columns and in-run physical
  replays (`*.json.gz`), and the full CG traces (the complete `result.json` and
  `native_stop.json` files). These are provided in the journal's computational
  supplement. The validator in `validation/` replays these vectors, so it
  cannot be rerun from this repository alone; its outputs are included.
- Per-run raw files of the Table 5 and Table 17 studies and of the
  conservative-rounding test; their summary records are included.
- Slurm logs, accounting and submission scripts of the experiment runs (the
  validator's job list, receipts, accounting and worker script are in
  `validation/opte-independent-validation-20261017/slurm/`); superseded
  attempts (the first mixed-processor task-scaling run, a location-scaling
  pilot that no table uses, and preempted or cancelled runs).
- The planning studies behind Table 8 (`tab:decomp`, restricted-MIP medians
  and direct bounds over 270 planning bases) and Table 9
  (`tab:planningdirect`, targeted planning checks), and the script that
  redrew Fig. 2 with corrected legend labels (plotted values unchanged).
  The code snapshot in `code/opte_lp_scaling_20261012/` contains
  `planning_direct.py`, the worker of the Table 9 checks, but no records of
  those runs are included.
