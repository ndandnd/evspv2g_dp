# Persistent restricted-master CG diagnostic

Protocol fixed before main outcomes. Earlier studies and all frozen sources stay
unchanged. This diagnostic tests the complete persistent-model/basis-reuse
implementation; it does not identify the causal share of model construction,
presolve, simplex iterations, dual selection, or route-pool changes individually.

## Population and controls

- Six existing DIAG2 L15 inputs: n=100,400,1000, draws0,1. Reuse the exact hashed
  generator, physical data, graph-plus-original-singleton family, and serialized
  instance payloads from the LP scaling study. No input is selected by performance.
- Three time repeats per input:18 blocks and54 fresh worker processes. Repeats
  measure timing variability; the two draws are the independent input draws.
- Every block executes cold CG, persistent CG, and direct barrier sequentially
  in the same one-CPU allocation. Three Latin rotations place each variant in
  every position once per input. Record host, CPU model, affinity, versions and
  all code/input hashes. Do not combine these timings with earlier studies.
- Each arm gets1800seconds including model construction/updates and optimization.
  A fresh-process watchdog allows600additional seconds for final diagnostics;
  allow120minutes per block for all three worst-case watchdogs. No imported
  solution, basis, or columns crosses arm/process boundaries.
- One Gurobi12.0.3 thread, seed0, feasibility/optimality tolerances1e-8.
  Barrier uses Method2, crossover default−1, BarConvTol1e-8. Both CG variants
  retain Method−1. Persistent CG explicitly uses the default LPWarmStart1.

## Matched CG algorithm and one implementation change

Both CG variants call the frozen `lp_scaling_models.solve_cg_lp` and vendor CG:
original feasible singleton/artificial initialization, beta0.5 stabilization,
pricing tolerance1e-6, maximum20000iterations, exact same DP pricing, duplicate
handling, no enrichment, and no final MIP. The cold arm uses the unchanged
`rmp_solver.solve_rmp` callback. The persistent arm substitutes only the callback
with `PersistentRMP.solve`.

The persistent model is initialized from the original `_build_lp` coefficients.
Later columns are appended with coverage a, signed energy e, gross positive
charge where that row exists, and cost fixed_cost+eps_pen*sum(abs(e)). BESS rows,
objective, bounds, original physical charging rate, and all existing columns
remain identical. Return vectors are permuted to the original master order for
the unchanged independent aggregate replay. Each column addition restores the
prior VBasis/CBasis and sets new variables nonbasic at their zero lower bound.
The initial model has no supplied basis. Missing bases, mutations of old columns,
nonappend pools, changed instances, and unsupported model extensions fail loudly.

Maintaining the model and basis can change presolve and degenerate dual selection,
which can change generated columns and the number of pricing iterations. Record
these effects rather than assuming the same CG trajectory or claiming a pure
overhead speedup. LPWarmStart1 may suppress presolve when an advanced basis is
present; this behavior is part of the declared implementation change.

## Timing, outcomes and checks

Input reconstruction/imports/initial serialization precede arm timing. Timed work
includes singleton/graph generation, model construction or updates, basis handling,
LP/pricing calls, intermediate aggregate replay and progress/native logging.
Final independent graph/seed pricing, physical replay and serialization are
outside algorithm time and reported separately. Preserve process RSS at stopping,
RMP build/update time, solver runtime, replay/pricing time, iterations, basis
restorations, column counts and the bounded objective trace.

Every outcome is retained, including iteration limits, time limits, nonoptimal
RMPs, uncertified duplicate stops, errors and external watchdogs. Only an actual
priced-out feasible stopping LP with zero artificial mass is accepted. Independently
verify saved primal columns/aggregate data and graph+singleton+periodic-BESS dual
conditions using unchanged `verify_lp_scaling.py`, outside timing. Preserve the
native direct primal/dual checks; supplementary full-family direct certificates,
if needed, remain explicitly separate and never overwrite strict flags.

Main comparisons pair identical case/repeat blocks. Show all54 outcomes and all
time limits. Use finite positive timings for ratios; accepted completed pairs
must have agreeing objectives/certified intervals. Report censors as bounds,
never as completed times or by excluding failed outcomes from the population.
Compare each CG variant with fresh barrier and persistent with fresh cold CG.
Report by n and draw, with repeated timing ranges and no predetermined conclusion.

Before deployment, smoke tests (excluded from main statistics) compare persistent
coefficients exactly with `_build_lp` after append operations, compare fixed-pool
LP objectives with the cold solver, test finite charging-cap rows and rejection
of mutated columns, and independently verify one actual L15 worker outcome.

## Entry points and dependencies

`python run_cg_reuse.py --plan` prints all18 blocks. Run a block with
`--case-name diag2_L15_n100_s0 --repeat 0 --output FRESH_DIR --budget 1800`.
Use `--variant cold`, `reuse`, or `barrier` for a separate preflight.

New runtime files: `persistent_rmp.py`, `run_cg_reuse.py`, this protocol. Frozen
dependencies are exported as `run_cg_reuse.DEPENDENCIES`, with unchanged vendor
manifest. Libraries:Python3.12,NumPy1.26.4,SciPy1.13.1,Gurobi12.0.3. Cluster submission,
license environment, concurrency and priority are coordinated by the parent task.
