# Prespecified LP scaling study

> Public copy. Administrative sentences about project approval and cluster job handling were removed; the technical protocol is unchanged. The SHA-256 of the file as run is listed in `cluster_snapshot_code_v1.manifest.json`.

12 October 2026. Written before the new scaling results. The earlier 14-case comparison remains a separate immutable study.

## Question and outcomes

The question is whether the observed CG advantage in obtaining the LP value persists or grows with task count and location count when the direct formulation is also solved with barrier. An increasing advantage is a hypothesis, not an acceptance criterion. Either method may win. The study evaluates LP algorithms; it does not describe column generation as an integer algorithm or add branch-and-price to the revision.

Primary endpoint: end-to-end time to the correct full implemented-family LP value, with construction and the algorithm's work included and separately recorded post-run validation excluded. Report objective, termination status, model size, CG iteration count, pricing time and memory information alongside elapsed time. Integer performance remains represented by the earlier matched 14-case study.

## Fixed inputs and repetitions

Use the existing DIAG2 random family, with task counts **100, 400 and 1,000**, task locations **4 and 15** (excluding the depot), and historical draws **0 and 1**. This gives 12 fixed inputs. The middle size is part of the historical DIAG2 design, not selected after observing speed. The generator's seed argument is `200 + draw`; preserve all physical/economic settings and serialize/hash each full input.

Each input has three timing repetitions. Each repetition is a paired block in which three methods run sequentially on the same allocated CPU and host, each in a fresh process: **direct dual simplex**, **direct barrier**, and **CG**. Rotate their order over the three repetitions so each method occupies each position once. Keep the solver seed fixed at zero; repetitions measure timing variability, not algorithmic seed sensitivity.

The expected main batch is 36 blocks and 108 LP arms. A small implementation calibration on the already studied 100-task/15-location/draw-zero instance is kept outside the main results. Calibration checks correctness and instrumentation; it does not select away an unfavorable method or change the fixed main inputs.

## Exact family and validation

Both formulations represent all frozen DP paths plus the exact original physically feasible singleton seed profiles. The 175-kWh physical block limit and 50-kWh SoC step imply a 150-kWh maximum DP-grid move. Initial singleton profiles and stationary storage retain the original 175-kWh rate. Preserve full/full truck boundaries, the original periodic BESS block and all shared cost/coupling rows. Do not claim continuous-SoC LP exactness for this nonaligned rate.

CG uses the frozen initialization, pricing and stabilization, but **zero enrichment rounds and no restricted integer solve**. Save the actual stopping LP and duals. A current-dual pricing test must cover both all graph paths and every original real seed; all artificial mass must be zero before accepting a physical LP solution. A time limit, iteration limit, repeated column key, or unchanged objective is not a pricing certificate.

Independently check matched objective values to absolute tolerance `1e-6`, selected-route feasibility, task coverage, original energy/rate/boundary constraints, aggregate BESS and objective reconstruction. Keep solver-tolerance qualifications. Report the CG bound corrected by `n_tasks × 1e-6`; distinguish a mathematical family-equivalence proof from numerical corroboration and from a continuous-energy claim.

## Solver and timing control

The cluster runtime is initially identified as Python 3.12.13, NumPy 1.26.4, SciPy 1.13.1 and Gurobi 12.0.3. Each worker records its actual versions, hostname, CPU model, affinity, source/input hashes and Slurm allocation. These timings are not pooled with the earlier macOS/Gurobi 12.0.1 timings.

Use one solver thread and one allocated CPU per block. Set BLAS/OpenMP thread limits to one. Direct methods explicitly use `Method=1` and `Method=2`; report the barrier/crossover settings and time. Preserve feasibility/optimality tolerances of `1e-8`. Each LP arm receives a **1,800-second build-inclusive allowance**. A bounded external worker deadline catches runaway work; record any overshoot or interruption rather than reporting it as a completed solve. The CG iteration guard is a safety limit, not a stopping proof.

Instance generation, imports and input serialization are outside each arm timer. Direct graph/model construction and LP solution are inside. CG initialization, master construction/solution and pricing are inside. Record any intermediate validation/progress overhead that remains in the CG implementation. Final independent physical replay and scalar pricing are outside the reported algorithm timer, with their own time. No solutions, bases or columns are shared between arms.

The direct model and master solver code are frozen at launch. CG retains the implemented master-rebuild policy; the comparison does not claim to benchmark every possible CG acceleration or warm-start implementation. Source manifests identify exactly which code ran.

## Analysis rules

Show all cases, all three repetitions, failures and censored outcomes. For fully certified solves, report per-case medians and ranges, and paired direct/CG ratios for each direct algorithm separately. A general CG speed advantage requires considering both direct algorithms, not selecting the slower baseline. If only one direct algorithm loses, state that dependence explicitly.

Do not replace a timeout with an exact 1,800-second solution time. Report solved counts and valid one-sided timing information; do not average away unsuccessful cases or compare unequal LP values as speedups. Two task draws per cell are limited replication. Increasing task count changes the actual trip set; these are family-level comparisons, not a nested-trip causal experiment. Do not infer monotonic asymptotic dominance from three task counts.

Compare locations at matched task counts, and sizes within each location setting. Present all outcomes before interpreting a trend. If a stage fails validation, repair implementation transparently and use a new run version; preserve the failed evidence. Do not tune the algorithm on main outcomes and silently reuse its timings.
