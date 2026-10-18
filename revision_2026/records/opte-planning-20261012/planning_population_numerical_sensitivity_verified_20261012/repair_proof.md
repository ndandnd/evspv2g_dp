# Uniform constructive primal validation and numerical sensitivity

This is a separately labeled post-solve check. It preserves the original
prespecified 1e-6 analysis and all 1,080 cold-solve results. It does not optimize,
rerun, drop or select a configuration. Native lower bounds remain floating-point
solver evidence.

The planning family has lossless storage, uncapped generation and aggregate
charging, identical nonnegative costs, and periodic BESS. For every incumbent,
round its truck-path multiplicities and BESS count to integers. Require exact
task coverage by the rounded multiplicities and independently replay the same
grid-valid physical truck paths. Let u be the saved BESS SoC clipped into
[0,G*Nb], with u[T]=u[0]. Let h=max(abs(diff(u))) and lambda=min(1,rho*Nb/h),
using lambda=1 when h=0. For Nb=0 use the identically zero state. The repaired
state s=lambda*u+(1-lambda)*u[0] is periodic, in capacity, and its increments
obey the rate limit. A tiny outward floating-point guard is used when scaling
is necessary. Set charge=max(diff(s),0) and discharge=max(-diff(s),0). Finally
set generation=max(Delta+truck_net+charge-discharge,0). Uncapped generation makes
this a feasible dispatch; no simultaneous BESS actions remain. Evaluate all
costs, including gross throughput. Independent physical and original-vendor
master-row checks verify the repaired vector. The same vector is replayed in
every permitted more flexible technology configuration before transferring its
upper bound.

Intervals use the new native bound minus an allowance and the repaired feasible
objective plus that allowance. We report the same uniformly applied allowances
1e-6, 1e-4 and 1e-3 dollars for all 1,080 configurations. Technology nesting,
ratio endpoints, denominator checks and exact even-population median rules are
unchanged. No original rounded incumbent or selected 1,800-second result enters
these sensitivities. Changes to sign counts are numerical validation effects,
not new optimization results or revised benchmark timings.

A separate share statistic concerns the population of all bases whose true
joint savings are positive. Every base with a positive lower saving bound must
belong to this population; the remaining bases have unknown membership. If
their joint savings are zero, their share is undefined and they do not belong.
Every defined share lies in [0,1] by technology nesting alone. To bound the
median over every possible membership, append one zero per uncertain member
to the lower endpoints of the certain members, and one one per uncertain
member to their upper endpoints. The median is coordinatewise monotone.
Moreover, adding a zero cannot increase a median of [0,1] values, and adding
a one cannot decrease it; this holds for both the odd median and the mean of
the two central order statistics for even populations. Consequently these
padded medians bound every admissible positive-saving population, including
every possible subset of uncertain members. No uncertain member is silently
discarded, and no strict positivity of a numerical tie is assumed. This is a
secondary estimand, distinct from the conditional all-270-base share analysis.
