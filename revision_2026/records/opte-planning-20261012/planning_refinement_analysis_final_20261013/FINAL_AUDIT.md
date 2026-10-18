# Final planning refinement audit — 13 October 2026

All 187 supplementary refinement outcomes pass the input, source, deployment,
physical-path, original-master, raw-vector and constructive-repair audits. The
new outcomes comprise **106 native `optimal` statuses and 81 `time_limit`
statuses**, with usable native lower bounds and independently repaired incumbents
for every configuration. No missing, rejected or unaccounted logical outcome
remains. No optimization was performed by either analysis script.

This is the predeclared supplementary cold 300-second refinement of **all 187
configurations that reached the original 60-second limit**. It is not a new
uniform 300-second study of all 1,080 configurations. The original uniform study,
all its flags, timings, bounds and repaired incumbents remain unchanged. Each
configuration uses the maximum valid original/new lower bound and the minimum
original/new repaired upper bound, before the common outward allowance and
technology nesting. Historical rounded paper incumbents and the selected
1,800-second diagnostics do not enter these endpoints.

## Scope and execution accounting

- All 270 original bases and all four configurations are retained: 1,080 cost
  intervals, with the original fixed 30-base low-gamma and 100-base high-gamma
  subsets. The refinement selection matches exactly the 187 original time-limit
  identities, serialized inputs and physical model dimensions.
- Final source/host assignment is 95 original-v1 executions on lisbeth and 92
  v2 executions on cdses-compute-01. The exact frozen hashes, verified AMD EPYC
  9654 CPU model, Gurobi 12.0.3, one-affinity-CPU computation and one solver
  thread (Slurm accounting reports `AllocCPUS=2` hardware threads), five
  single-thread environment variables and all solver settings pass.
- The collection reconciles as 2 initial v1 results, 66 completed original v2
  results, 93 first executions returned to v1 after confirmed never-started
  cancellation, and 26 completed recovery results. All 26 retries have scheduler
  state `COMPLETED`; their solver statuses are 18 optimal and 8 time limits.
- There were **213 observed scientific executions** for 187 logical refinement
  configurations: 187 completed attempts plus 26 externally preempted original
  attempts. Interrupted original elapsed time totals **2,199 seconds**. Partial
  interrupted bounds are unused; both attempts remain recorded. Zero-allocation
  queue migrations are scheduling events, not additional scientific executions.
- This audit makes no cross-node, cross-budget or uninterrupted-runtime claim.

The final recovery accounting SHA-256 is
`750cd258f25ee504c6a7370a4a608b16033c88b245838614ab8509436b6695b3`.
The first migration, pending-only return and recovery policy/receipts are all
bound in `refinement_summary.json`. The original 1,080 result digests, all 187
new result digests, their raw evidence inventories and analysis dependency
digests were independently rechecked after the analyzer finished.

The final remote receipt at 2026-10-13 06:02:39 UTC also matches all 187 local
result hashes, reports successful accounting/queue commands and contains no
active planning jobs. Its SHA-256 is
`7753332833546c23fefa43189a05723b31d9a03a1274a90a75b552fd9e23f1fa`;
`remote_completion_binding.json` records the independent check. Scheduler
`AllocCPUS=2` is preserved verbatim for executed allocations, while the worker
manifests record `SLURM_CPUS_PER_TASK=1`, one-CPU affinity and one solver/math
thread. Do not infer one billed logical CPU from the one-thread solve setting.

**This completed author audit supersedes the generic checkpoint/provisional
sentence in the analyzer's readable template.** All 187 attempts have finished.
The recommended publication share statistic below is the explicitly defined
259–270-member true-positive-saving envelope; the conditional all-270 version
remains in the raw report for traceability.

## Numerical validation

The analyzer replays all **179,722 new path transitions**, shared BESS schedules,
generation, task coverage, scenario restrictions and original vendor-master
rows. The same uniform constructive repair is applied to every new incumbent:
integer path/BESS quantities are rounded and checked; periodic BESS states are
projected to capacity and rate limits; charging/discharging are reconstructed
from state increments; uncapped generation is recomputed to satisfy balance.
The uncapped, lossless, periodic assumptions required by this repair are checked
on every input. Every schedule transfer used for technology nesting is validated
in its target configuration.

| Check over the 187 new outcomes | Maximum |
| --- | ---: |
| Raw physical and original-master residual | 8.70705e-9 |
| Raw NPZ/dispatch/integrality consistency residual | 0 |
| Repaired physical residual | 0 |
| Repaired original-master residual | 3.63798e-12 |
| Increase in repaired objective | $1.58143e-6 |
| Native lower bound minus repaired objective | $9.10e-13 |

Native status is preserved rather than interpreted as exact equality: 31 of the
106 new native-optimal outcomes retain an absolute objective-bound gap above
$1e-9. Their largest gap is about $0.0125 (relative gap below 9.878e-7). The 81
time-limit outcomes have largest absolute gap $36.4765625 and largest relative
gap about 1.139%. Every recorded interval is retained.

The separate standard-library checker `verify_planning_refinement_final.py`
passes **49,262 checks**, including a Decimal recomputation of endpoint
intersections, a closed-form partial-order nesting calculation independent of
the analyzer's iterative procedure, ratio endpoints, exact even-population
median indexing, strict rounding cells, all possible positive-membership
population sizes, and expansion under larger numerical allowances. Decimal
arithmetic checks the scalar reporting arithmetic; it does **not** convert
floating-point native MIP bounds into exact certificates.

## Conservative publication intervals

The following endpoints are rounded **outward** to two percentage decimals and
cover all three uniformly applied allowances ($1e-6, $1e-4 and $1e-3). The shares
refer to the median among all truly positive-joint-saving bases, retaining the
11 numerically uncertain memberships as possible members. They are not point
estimates obtained by dropping those cases.

| Statistic | Conservative numerical median interval | Rounding conclusion |
| --- | ---: | --- |
| BESS share of joint savings, positive-saving population | 96.34–96.73% | Neither a unique 96% nor 97% headline is established |
| V2G-alone share of joint savings, positive-saving population | 69.64–75.38% | No unique whole-percent headline; the earlier 62% cell is excluded for this estimand |
| V2G-alone daily cost reduction, all 270 bases | 21.68–21.69% | 21.7% at one decimal |
| Additional V2G daily cost reduction with BESS, gamma <= 0.35, 30 bases | 0.09–0.10% | 0.1% at one decimal |
| Additional V2G daily cost reduction with BESS, gamma > 2, 100 bases | 9.47–9.48% | 9.5% at one decimal |

At the smallest two allowances the V2G-alone share lower endpoint rounds
outward to 69.65%; the displayed **69.64%** covers the $1e-3 sensitivity as well.
All other displayed endpoints and all one-decimal rounding conclusions above
are stable across the three allowances. Rounding decisions use full-precision
endpoints strictly inside the relevant cell, not the displayed outward values.

There are 181 strict lower-bound improvements and 90 strict repaired-upper-bound
improvements before nesting. Across all allowances, 259 bases have numerically
certified positive joint savings and 253 have numerically certified strictly
positive additional V2G savings with BESS. The 11 unresolved joint-saving cases
are retained, giving a possible true-positive population size of 259–270.
The conditional all-270 share calculation is also retained separately in the
machine-readable report. Any later exact-zero proof is a separate analysis and
has not been used to alter this final prespecified numerical report.

## Why the share intervals remain wider

The research-only diagnostic `membership_width_diagnostic.json` fixes the 259
numerically certified-positive bases, without claiming that these are the whole
true-positive population. At $1e-6, their fixed-population BESS-share median lies
in 96.6026525–96.6330027%, a width of 0.0303502 percentage points; their V2G-alone
share median lies in 72.6581035–72.6581037%, a width near 1.01e-7 percentage points.
Both fixed-population diagnostics remain within outward intervals 96.60–96.64%
and 72.65–72.66%, respectively, at all three allowances.

Allowing the 11 uncertain members broadens those envelopes to approximately
0.38694 and 5.72194 percentage points at $1e-6. The difference between these
envelopes is a sensitivity to membership, not an additive causal decomposition
of error. In particular, the remaining broad V2G-share interval is driven mainly
by uncertain membership around a potentially zero denominator; it is not
evidence that the known-positive median still has a large MIP gap. Daily cost
reductions divide by positive baseline cost and have no such membership change.

## Mathematical interpretation

For configuration j, let L_j be the maximum original/new native lower bound and
U_j the minimum independently repaired upper bound. The numerical interval is
[max(0,L_j−delta), U_j+delta]. The four exact-family feasible sets are nested:
solar is more restrictive than either single-flexibility configuration, and both
are more restrictive than V2G+BESS. Lower bounds propagate toward restrictive
configurations; replayed upper bounds propagate toward flexible configurations.
These directions and all nonempty intersections are checked for every base.

For nested optimal costs A >= B >= D and intervals [L_A,U_A], [L_B,U_B],
[L_D,U_D], the saving share (A−B)/(A−D), conditional on A>D, is bounded by
max(0,L_A−U_B)/(L_A−L_D) and
(U_A−L_B)/(U_A−min(U_D,L_B)), using conservative 0/1 conventions at vanishing
denominators. Daily reduction (A−B)/A uses max(0,1−U_B/L_A) and 1−L_B/U_A.
The median is monotone in every observation, so lower and upper medians give
population bounds; an even population uses the mean of its two central order
statistics. For unknown positive-saving membership, padding known lower
endpoints with eleven zeros and known upper endpoints with eleven ones bounds
every subset of the unknown members. The audit checks every admissible subset
size, while preserving the uncertainty rather than asserting exact zero.

These bounds concern the implemented full finite graph-plus-initial-seed family
with its continuous shared BESS dispatch. They do not establish equivalence to
an unrestricted continuous-energy integer vehicle model. All lower-bound claims
retain the native floating-point solver-evidence qualification; the numerical
allowance sensitivities are not exact-arithmetic proofs.

## Bound artifacts

- `refinement_summary.json` SHA-256:
  `6b2317829c4045588980a8206dd4c6650572f1fd4959aa5066ada8cdd0d0ef1a`.
- `independent_integrity.json` binds that summary and the independent checker,
  records all check categories, residuals, execution counts and rounding results.
- `worker_outcomes.csv` preserves every one of the 187 statuses and bounds;
  `new_repaired_profiles.json.gz` preserves all repaired new schedules.
- `membership_width_diagnostic.json` is explicitly a research diagnostic and
  does not replace the publication estimand.
