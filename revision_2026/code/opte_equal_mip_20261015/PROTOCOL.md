# Equal-MIP-time comparison of CG-plus-restricted-MIP and the direct arc-flow MIP — 15 October 2026

Replaces the 1,800-second shared-budget design of the earlier integer follow-ups (manuscript Tables 20–22), after the coauthor meeting on 15 October. The earlier results stay unchanged as separate records.

## Question

For each input, how do the two integer methods compare once each is a MIP with the same time budget? The two methods are:

- **CG + restricted MIP (heuristic).** Column generation runs to pricing convergence, and its time and LP bound are reported. A restricted set-covering MIP over the generated routes then gets 1,800 s.
- **Direct arc-flow MIP (exact).** The arc-flow MIP of Appendix A.1 gets the same 1,800 s, counted from graph construction.

There is no branch-and-price, so the CG arm is a price-and-branch heuristic. Its only full-family lower bound is the CG LP bound.

## Inputs (23)

1. The 12 heterogeneous-energy panel inputs of manuscript Table 19, exactly as built by `opte_lp_hypothesis_20261013/panel_instances.py`. The input hashes are checked against that study's `input_manifest.json`. These inputs come from the panel where CG's LP advantage was measured, so the LP and integer tables share inputs.
2. The 7 scaling inputs (1,000 tasks at 15/25 kWh, 30/50 and 50/50 locations/grid; 4,000 tasks at 15/50).
3. The 4 original 1,000-task inputs (4 or 15 locations, 50 kWh grid, draws 0 and 1).

Inputs 2 and 3 are the exact payloads of `opte_integer_extension_20261014`.

## Arms

**cg_pool_mip**
- Algorithm: the frozen persistent-Gurobi CG of the earlier studies (`phase_models.generate_pool`). Settings: beta 0.5, pricing tolerance 1e-6, enrichment 0, warm-start singleton seeds.
- Iteration and time limits: the iteration cap is raised to 200,000. The safety time cap is 14,400 s; a run that reaches it is reported as unconverged and has no LP bound.
- Lower bound: on convergence, the full-family LP lower bound is z_RMP − n·1e-6, as in Section 6.
- Route pool: every accepted real column plus the original singleton profiles; artificial columns are removed.
- Restricted MIP: a cold MIP (`phase_models.solve_pool_mip`) with 1,800 s counted from the start of its own model construction. CG time is excluded from this budget.
- Pool bound: the MIP's own bound applies to the pool only and is never a full-family bound.

**direct_mip**
- Model: Appendix A.1 on the same pricing graph plus the singleton profiles, with integral flows, profile weights and BESS count.
- Solver settings: barrier root (Method 2), automatic crossover. Threads 1, seed 0. Feasibility, optimality and integrality tolerances 1e-8. MIP gap 1e-6 relative and 1e-10 absolute. SoftMemLimit 36 GB, so a memory stop still returns the incumbent and bound.
- Time limit, counted from graph construction:
  - 3,600 s on the panel, where CG takes minutes.
  - 16,200 s on the scaling and 1,000-task inputs, equal to the CG cap plus the MIP budget.
- What the callback records:
  - every new incumbent with its time, Gurobi work and vector;
  - a bound observation at most every 1 s from MIP and MIPNODE callbacks, plus each MIPSOL bound and the final ObjBound.
- What the callback does not provide:
  - Gurobi raises no callback during barrier or crossover, so observations can be sparse there.
  - The root-LP finish time comes from the "Root relaxation: objective" log line. A "time limit" root line means the root is unfinished.
  - The 7-digit log value is informative only; it is never used as a bound.
- Reading rule at time T (T = 1,800 s for equal MIP time, or the CG arm's `cg_total_readout_seconds` for matched total time):
  - Incumbent: the best incumbent recorded at or before T.
  - Bound: the largest bound observed at or before T. Because the bound only increases, this is valid but can be conservative. The time of that observation is reported with it.
  - If T exceeds the direct budget, the row is labelled "direct truncated", not matched.
- Root LP value: Gurobi's root value belongs to the presolved MIP and can exceed the Appendix A.1 LP. So the LP-equality check is one-sided: flag only a direct root bound below the CG lower bound. The two-sided equality of the unpresolved LPs is already established by the 72-run LP study.
- Validation: the timed record is written to `native_stop.json` before any diagnostics. Every incumbent vector then gets a matrix check and a physical replay outside the timed clock.

**cg_pool_mip, additional rules**
- LP lower bound: z_RMP − n·1e-6 is reported only when the final DP call itself returned no column.
- Time definition: the per-iteration aggregate replay inside CG is part of the frozen CG code and is reported separately (`cg_inloop_validation_seconds`). The matched total time is CG seconds plus MIP-stage seconds, excluding checkpoint I/O.

**Both arms**
- Gurobi 12.0.3 and one bound CPU on cdses-compute-01 (AMD EPYC 9654), the node of all earlier timing tables.
- Slurm allocation: 24 GiB for CG arms and 48 GiB for direct arms. Each arm runs in its own array task with no requeue.
- Concurrency: at most three CG and three direct tasks run at once. Start and end times are saved with sacct after the runs so that node load can be checked.
- Seeds: one seed (0), so differences between methods are descriptive.
- Physical replay and matrix checks of every final incumbent follow the timed stop and are timed separately.

## Reporting

For each input, report the following:
- The pricing-graph size: nodes, arcs, and the number of routes in the pool.
- CG: time to convergence and LP bound. Direct: time at which its root LP finished, or "unfinished", and its root LP value. These two LP values must agree to tolerance (Appendix A.1). Report the largest relative deviation.
- At 1,800 s of MIP time:
  - the CG-pool incumbent and the pool's own bound (pool optimality);
  - the direct incumbent and its branch-and-bound bound.
- Best known solution (BKS): the minimum over all valid incumbents from this study and earlier ones, with provenance.
- Best known bound: the maximum of the valid full-family bounds, namely the CG LP bound and the direct branch-and-bound bound.
- For each method:
  - gap to BKS, 100(U − BKS)/BKS;
  - certified gap, 100(U − LB*)/U.
- When the direct root never finishes, report "root unfinished; one-truck-per-task fallback" instead of a 100% gap.

The LP and integer optima of the two representations are equal (Appendix A.1). The comparison is therefore about time-to-bound and the quality of the integer search, not about bound strength.
