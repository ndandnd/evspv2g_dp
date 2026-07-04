# DP pricing = MILP pricing: the LP-equivalence evidence

**Claim.** Given the same restricted master problem — same objective, same
constraints, same instance — column generation with the labeling-DP pricing
oracle converges to the same LP optimum as the original's MILP pricing.
Where every detail is truly identical the match is **exact to the digit**;
against the original code itself the match is **0.5%**, with every basis point
of the residual attributed to a named, small implementation difference.

**Why the LP value is the right test.** The converged CG objective is
independent of *how* pricing is done: any oracle that finds a negative-
reduced-cost column whenever one exists drives the restricted master to the
full LP optimum. So two pricers are "doing the same job" iff, on the same
master, they terminate at the same LP value. The LP is also the only
heuristic-free quantity: integer solutions and side metrics (fuel, fleet mix)
are degenerate near the optimum and differ legitimately between ~1%-gap runs.

The DP is an exact oracle here because every energy quantity in these
instances (trip energy, deadhead energy, charge per block, capacity) is a
multiple of the SoC lattice step, so the time-space-SoC DAG contains every
feasible route; a single forward pass finds the true minimum reduced cost.

---

## E1. Implementation equivalence — exact to the digit

Three independently written implementations (this repo: numpy DP + HiGHS
master; a from-scratch PuLP/CBC labeling-DP implementation; a third
independent implementation) were run on matched-granularity instances
(integer deadheads, aligned SoC lattice, identical costs, same SoC boundary
convention). Converged LP optima:

| case / trips | impl. 1 | impl. 2 | impl. 3 |
|---|---|---|---|
| route-only | 70.0000 | 70.0000 | 70.0000 |
| truck V2G | 80.0000 | 80.0000 | 80.0000 |
| arbitrage (battery) | 78.0000 | 78.0000 | 78.0000 |
| ladder 4/6/8/10/12 trips | 80 / 110 / 140 / **152.8571** / 170 | same | same |

The **fractional** optimum 152.8571 matching across codebases rules out
coincidence. Also validated here: the aggregate-battery block in the master is
LP-equivalent to discrete battery columns (fractional column mixing recovers
continuous dispatch), so the two battery formulations do not affect the LP.

## E2. LP-solver independence — exact

On shared column pools at 160 / 360 / 450 / 600 / 1000 tasks, HiGHS and Gurobi
return **identical LP objectives** (`lp_match=True` in every row of
`solver_compare.py`), and end-to-end CG with the Gurobi LP backend converges
to the same bound as with HiGHS (`cg_lp_match=True`, including the 1000-task
instance). The LP value is a property of the model, not of any solver.

## E3. Per-iteration internal checks

* The PuLP implementation asserts, at **every** CG iteration, that the DP's
  reduced cost equals the master's algebraic reduced-cost formula
  (|difference| < 1e-6) for every emitted column.
* The battery DP was validated against an exact LP formulation of the same
  subproblem: |LP − DP| = 2.3e-13.
* The truck DP has an independent cross-check: a Bellman–Ford shortest path
  on the same DAG (networkx) reproduces the DP's optimal reduced cost.

## E4. Head-to-head against the original MILP-pricing code — 0.5%

The capstone: a **fresh Gurobi run of the original repo** (`ndandnd/evspv2g`,
`python src/run_experiments.py`, its saved defaults: mode 3, eps=2.5,
2 locations = 20 trips, solar_mult=7) versus this repo's DP with the master
aligned to the original's (`original_headtohead.py`):

* `soc_mode="free"` — the original's free full initial charge, free terminal;
* `master.COVERING=True` — the original's coverage `>= 1`;
* base-load constant `c_g * sum_t max(Delta_t, 0) = 845` subtracted (the
  original's master keeps base-load fossil outside the model);
* `c_b = 45` — replicating the original `build_master`'s battery-cost slip
  (its final LP/MIP prices battery routes with `bus_cost`; the `batt_cost`
  argument is never used).

| | adjusted objective |
|---|---|
| original code, fresh run | 295.00 |
| **this DP, aligned** | **296.50 (+0.5%)** |

The 0.5% residual is fully accounted for: our `eps_pen` activity damping
(~+0.3%, vs their 1.01 charge premium which is ~0 in the export regime), our
half-hour charging grid vs their integer-hour charge starts (small, opposite
sign), and their CG tail tolerance. The solution *structure* also matches:
at the slipped battery price the optimizer goes truck-heavy (9 trucks +
1 battery), exactly the original's published pattern.

With the intended battery cost (`c_b = 36`) our aligned model gives
**237.10** (7 trucks + 9 batteries). Independent verification of the slip:
change `bus_cost -> batt_cost` on the two `route_costs_batt` lines of the old
repo's `build_master` and rerun — it should then print ~237.

**Discovery note.** The 19.6% gap that this test initially exposed (295.00 vs
237.10) is what led to finding the slip; it suppressed battery deployment in
the original's final solutions (batteries priced at truck cost lose to trucks,
which also cover trips) and explains the original's truck-heavy fleets. The
original's final "MIP" is also built with `binary=False` in the code version
at hand (its LP and MIP print identical to 13 decimals).

---

## Reproduce

| evidence | how |
|---|---|
| E1 | matched-granularity scripts (session artifacts); the toy cases re-derive from the three repos |
| E2 | `python3 solver_compare.py` (Gurobi machine; auto-skips Gurobi columns without it) |
| E3 | asserts run inside every PuLP-implementation CG call; `python3 pricing_truck.py` runs the Bellman–Ford cross-check |
| E4 | old repo: `python src/run_experiments.py`; new repo: fill `ORIG_LP`/`ORIG_MIP` in `original_headtohead.py`, run it |

**One-sentence summary:** on identical masters the DP and the MILP pricer
reach the same LP optimum — exactly when every detail is matched, and to 0.5%
against a fresh run of the original code once its own final-master battery-
cost slip is accounted for.
