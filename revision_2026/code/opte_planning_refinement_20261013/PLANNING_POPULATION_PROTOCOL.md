# Full-population bounded planning verification

Prespecified12 October2026, before any solve under this protocol. This additive
study covers all270 original COMMON4 bases and all four configurations, exactly
1080 attempts. No outcome selects an input, budget, rerun, or inclusion decision.
The original frozen benchmark, manuscript, and original result files are untouched.

## Fixed inputs and model

The270 cases in `planning_population_inputs.json` comprise task counts20,60,120,
nine solar multipliers1,1.25,1.5,1.75,2,2.5,3,3.5,4, and seeds0–9. Task generator,
source data, parameters, and every regenerated physical input are hash recorded.
The generator uses three task locations, two-hour tasks, salt50000, depot charging,
700kWh capacity,175kWh/block rate,25kWh grid, no loss, full/full truck boundaries,
periodic stationary storage, and the original costs. This is the existing
deterministic finite family; no plugs, stochastic optimization, or parked-only
vehicles are added. Charge-only removes truck discharge arcs. No-BESS fixes its
count to zero. All original real singleton columns remain; here every singleton
has an independently checked path in the grid graph.

## Uniform computation and resource limits

Each configuration receives one cold direct integer solve with Gurobi12.0.3,
one allocated CPU, one solver thread, Seed0, Method−1, Crossover−1,
MIPGap1e−6, MIPGapAbs1e−10, FeasibilityTol/OptimalityTol/IntFeasTol1e−8.
The60-second clock includes graph/seed validation, matrix assembly, environment
and model creation, and optimization. Physical-input reconstruction/hash checking
precedes that clock. Native TimeLimit receives only the remaining time. Final
raw output serialization and primal checks are recorded separately. Native stop
overshoot is retained. No standalone LP is solved. No previous solution, basis,
restricted pool, or incumbent is supplied to the MIP.

Each configuration runs in a fresh process. Its parent uses a120-second process
group watchdog, including imports, preparation, solve, and diagnostics. All errors,
missing incumbents, timeouts and numerical failures remain in the fixed denominator.
The four configurations of a base run serially; the population array has270 base
jobs with throttle28, leaving the four concurrent1000-task MIPs untouched and
keeping these two new studies at no more than32 simultaneous solver processes.
Each base job requests4GB and a12-minute hard Slurm limit. Fresh queue/node state
and immutable submission receipts are saved; no existing job is changed.

The intended optimization allocation is at most1080×60s=18 single-thread CPU
hours, apart from native soft-limit overshoot. The per-worker120s watchdog gives
36 process-wall hours over all workers, including diagnostics; launcher overhead
is additional. The270×12-minute Slurm limits give a54 allocated-core-hour outer
cap if every base reaches its hard limit. Queueing time is not execution time.
For comparison,1080×1800s would allocate540 optimization CPU hours. The earlier
three diagnostic bases are not a random timing sample:10 of12 MIPs completed
within60s, but the other two used692s and1800s. No population runtime or precision
guarantee is inferred from them.

## Evidence and primary analysis

Every worker saves its instance, source/vendor hashes, native status, unrounded
objective and bound, solve/build/replay timings, raw primalNPZ, compressed physical
path and stationary-dispatch replay, and numerical feasibility/integrality checks.
Independent analysis must replay the new incumbent, verify scenario restrictions,
and check finite native bound≤incumbent plus tolerance before using both endpoints.
Native bounds remain solver-reported floating-point evidence, not exact-arithmetic
certificates. Native optimal status does not replace the actual objective–bound gap.

Primary cost intervals use only this uniform60-second run: a valid full-family
native lower bound and an independently replayed new upper bound, with outward
numerical allowance1e−6. Nonnegative cost gives a conservative zero lower bound
if none is available. Missing or rejected upper bounds remain unbounded unless a
validated new restrictive-configuration schedule can be independently replayed in
the flexible configuration. Do not treat rounded original totals as validated new
primal bounds. Original results and the three1800-second diagnostics may appear
only in separately labeled supplementary comparisons.

Use feasible-set nesting only between the identical-cost configurations of the
same physical base: solar≥solar_bess≥v2g and solar≥v2g_fleet≥v2g. Propagate lower
bounds upward and upper bounds downward; any interval inconsistency is a failure
requiring investigation, not clipping away evidence. Cost shares use these cost
intervals and nesting, not differences of independently improved incumbents alone.
For a share R=(A−B)/(A−D), the partial derivatives have signs +,−,+ on A≥B≥D and
A>D. After propagating the nested intervals, endpoint bounds are

    R_low=max(0,L_A−U_B)/(L_A−L_D),
    R_high=(U_A−L_B)/(U_A−min(U_D,L_B)).

Degenerate/unbounded endpoints conservatively allow[0,1]. Strictly positive joint
savings must be certified before treating each ratio as unconditionally defined;
otherwise retain the denominator qualification without dropping that base. For
daily reduction1−B/A, use[max(0,1−U_B/L_A),min(1,1−L_B/U_A)] when costs are positive.
The full-population median lies between the median of the lower endpoints and
the median of the upper endpoints. For270 bases this uses the average of order
statistics135 and136 at each endpoint. Gamma subsets are fixed from input data:
30 cases at gamma≤0.35 and100 cases at gamma>2.

## Prespecified reporting decision and stopping rule

Finish the fixed1080-attempt pass, then report all statuses and median intervals.
There are no outcome-selected extra optimizations in this protocol. A rounded
Table7 headline is resolved only if its entire numerical median interval lies
strictly within one rounding bin: width1 percentage point for the integer96%
BESS share and62% V2G-alone share, and width0.1 percentage point for the19.6%,0.6%,
and9.3% daily-reduction values. A boundary-touching interval remains unresolved.
If the common bin equals the original headline, it is supported to displayed
precision; if different, report the new bin and disclose the change. If unresolved,
report the interval and retain any original point only with its restricted-incumbent
label. Individual native optimality is not required when aggregate endpoints settle
the displayed statistic. No selected three-base evidence enters this primary rule.
