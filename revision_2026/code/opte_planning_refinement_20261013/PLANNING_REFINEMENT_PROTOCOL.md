# Supplementary refinement of all unresolved planning MIPs

Frozen 13 October 2026 before any solve under this protocol. This follow-up is
selected by the previous study's stopping status, not prespecified as part of
that original study. It includes **all 187 configurations with TIME_LIMIT status**
in the completed 1,080-configuration, 60-second planning pass. No favorable effect,
particular technology, median position, or gap magnitude selects an attempt.
The original 893 native-optimal configurations are not rerun. In particular, the
eleven numerically tied combined-saving bases receive no tie-driven reruns.

## Frozen inputs and computation

`planning_refinement_inputs.json` identifies every selected base/configuration,
the original result and serialized-instance digests, and the complete original
instance record. It binds the original population input manifest, independent
primary audit, and guarded uniform-primal-repair report. Each worker independently
regenerates its instance with the frozen original builder and requires exact
agreement with the saved record before solving. The model is the same expanded
DP graph plus original real singleton family, with continuous periodic BESS
dispatch, integer truck/seed/BESS counts, and the same four technology controls.
There is no claim of equality with continuous-truck-energy integer schedules.

Each selected configuration gets exactly one new **cold 300-second** MIP, using
the unchanged `planning_population.solve` implementation with only its in-memory
budget constant set to 300 seconds. No baseline source file is modified. The
timer includes graph/seed checks, matrices, solver environment/model creation,
and optimization. Input reconstruction/hash checking precedes the clock; output
serialization and physical diagnostics follow the recorded algorithm stop.
Native soft-time-limit overshoot is recorded. No previous primal, MIP start,
basis, search tree, route pool, or solver state is supplied, and no standalone LP
is solved. A cold 300-second run is a fresh run, not continuation from 60 seconds;
it need not improve either endpoint, which is why analysis intersects bounds.

Use Gurobi 12.0.3 on the AMD EPYC 9654 processor model, one allocated and
bound CPU, Threads=1, Seed=0, Method=-1, Crossover=-1, MIPGap=1e-6,
MIPGapAbs=1e-10, FeasibilityTol=OptimalityTol=IntFeasTol=1e-8. The five numerical
library thread environment variables are all one. Each arm is a fresh process
with a **420-second process-group watchdog**; imports, input construction and
final diagnostics are included in that outer limit. A parent-managed array may
request one CPU and 4 GB per task, eight minutes of scheduler time, and at most
32 simultaneous refinement workers, subject to the shared OPTE resource cap.
The parent checks the fresh queue and handles deployment/submission; this worker
contains no SSH or scheduler submission command and changes no existing job.

The planned solve allowance is 187*300=56,100 single-thread elapsed seconds
(15.5833 hours), apart from native soft-limit overshoot. The process watchdog
allows at most 21.8167 process-wall hours in total, plus launcher overhead; an
eight-minute-per-task scheduler allocation gives a 24.9333 core-hour outer cap.
Queueing time is not execution time. There is no outcome-dependent extension,
replacement, or repeated attempt in this protocol.

## Queue-based mixed-node amendment, 13 October 2026

The original v1 deployment targeted lisbeth, the host of the 60-second population
study. An attempted all-pending retirement was refused by its guard because at
least task 242531_0 had started; no cancellation occurred in that attempt. This
amendment **retains every started original task and its eventual outcome**. Only
original-array tasks confirmed never started and still `PENDING` may be retired
and migrated once. Their selection uses scheduler state alone; no refinement
scientific outcomes are inspected or used to select migration. The parent saves
fresh state checks and confirmed cancellation receipts. The frozen exact index
manifest retains indices **0 and 1** on v1 and migrates **2 through 186** (185
never-started tasks) to v2. Its path is
`results/planning_refinement_deployment_20261013/migration_manifest.json`, SHA-256
`e1ddec584e28a1a06317735db61f76595b9c08fec6845769fc301583c9456fde`.
The receipt records every migrated task as cancelled with zero elapsed time and
zero allocated CPUs; indices 0 and 1 were respectively completed and running
when that receipt was taken. These two sets partition all 187 configurations.
Running or completed tasks are neither cancelled nor rerun by this amendment.

Retained tasks continue under the unchanged v1 snapshot on lisbeth. Migrated
tasks use v2 on **cdses-compute-01.orie.cornell.edu only**, with exact processor
model `AMD EPYC 9654 96-Core Processor`, Gurobi 12.0.3 and one-CPU affinity,
confirmed by hardware probe 242263. V2 manifests identify amendment
`2026-10-13-mixed-node-queue-only`. The original runtime snapshot remains in
`results/planning_refinement_deployment_20261013/code`; the original analyzer
and related local sources are also preserved in
`results/planning_refinement_source_history_20261013/v1`.

All 187 input identities, the formulation, 300-second budget, cold-start policy,
solver settings, watchdog and bound-intersection analysis remain unchanged.
Each index still has one scientific refinement attempt. The final analyzer
requires the exact v1 code hashes with lisbeth or exact v2 hashes with cdses,
and enforces the retained/migrated index manifest. Duplicate attempts are rejected
rather than selected favorably. The mixed-node refinement supplies additional
solution bounds; it supports **no cross-node or cross-study timing comparison**.

## Evidence and supplementary analysis

Save all 187 outcomes, including absent incumbents, solver errors, time limits
and watchdog failures. Every worker stores the original/new input linkage,
source/vendor/environment hashes, native status and unrounded objective/bound,
timings, raw primal NPZ, and full physical profile. Analysis checks every digest,
model/control identity and environment, and independently replays every new
incumbent through the physical transitions and original vendor-master rows.
The same uniform constructive repair used for all original 1,080 incumbents is
applied to each new incumbent: round path weights/BESS count, require exact task
coverage, repair periodic SoC and rates, derive non-simultaneous BESS actions,
and reconstruct uncapped generation. The repaired vector is checked again, with
objective correction recorded. Every transferred restrictive schedule is checked
in the target flexible configuration. Native lower bounds remain floating-point
solver evidence; the repair only establishes the primal side numerically.

For each of all 1,080 configurations combine the original valid native lower
bound and repaired upper bound with any valid new endpoints:

    L = max(valid original lower, valid new lower) - allowance,
    U = min(valid repaired original upper, valid repaired new upper) + allowance.

A missing or rejected new endpoint leaves the original endpoint available; it
does not remove the configuration or invalidate unrelated valid evidence. Keep
source identities for each contributing endpoint. Investigate any inconsistent
intersection rather than clipping it. The original 60-second report, repaired
report, timings and flags stay unchanged and separately accessible. The new
report is explicitly a **supplementary status-selected refinement**, not a new
uniform-300-second population study or a timing comparison with the old run.

Propagate identical-cost technology nesting within each base. Use the same
share/daily-reduction endpoint formulas, all 270 bases, fixed 30/100 gamma subsets,
and even-population median convention as the original analysis. Retain undefined
share-denominator qualifications. Also report the already defined secondary
median over truly positive-saving bases, bounding uncertain membership by zeros
and ones. Apply the three predeclared numerical allowances $1e-6, $1e-4 and $1e-3
uniformly. These sensitivities are not exact-arithmetic enclosures.

Report old and intersected median intervals and their width changes at full
precision, and whether each interval lies strictly inside one rounding bin.
The original display rules remain one percentage point for share headlines and
0.1 percentage point for daily-reduction headlines. Report newly resolved bins
even when they differ from original estimates; retain unresolved intervals. No
additional optimization is authorized here to make a particular headline round.
