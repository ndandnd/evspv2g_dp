# A small, causal fixed-skeleton energy model

Built locally on 21 September 2026. This implements the next mathematical check
from the independent review, without modifying the campaign or reference code.
It needs Python, NumPy, and SciPy; it does not need Gurobi or a cluster.

```sh
# From the repository root
cd research/stochastic/evidence
python3 adaptive_prototype_20260921/demo.py
python3 -m unittest discover -s adaptive_prototype_20260921 -p 'test_*.py' -v
```

The checked environment was NumPy 1.26.4 and SciPy 1.13.1 (HiGHS through
`scipy.optimize.linprog`). `results.json` contains every action, state, load,
probability, passive spill amount, objective, and feasibility/duality diagnostic
for both examples. The 13 tests pass.

## What is implemented

Routes, truck count, BESS capacity, initial and terminal states, parking windows,
and trip obligations are inputs shared by all scenarios. The optimization chooses
truck charge/discharge, BESS charge/discharge, and generation. Every active control
has the same declared information restriction. An optional signed profile pins
each truck to a supplied charging/discharging plan.

A scenario contains a sequence of observations. At slot `t`, the signal at `t`
arrives **before** controls are selected. The node is the entire observation
history `observations[:t+1]`, not just the latest label; previously separated
histories cannot accidentally merge. Controls for scenarios with the same node
are constrained equal. Shared initial states and deterministic withdrawals then
give shared inherited states automatically. Observations can define several
branching times; the main example uses one reveal at the start of slot 2.

This is a synthetic, idealized signal: at slot 2 it reveals which of the two
weather paths applies. It is not evidence that an observed morning-PV statistic
identifies actual future weather perfectly. A real tree must declare which
measurements or forecasts are available at each decision and must be constructed
without exposing future observations to a controller.

The four comparable information restrictions are:

| Arm | Truck controls | BESS and generator controls |
|---|---|---|
| All-control open-loop | Common across all scenarios | Common across all scenarios |
| Committed trucks, causal dispatch | Best common profile on these scenarios | Common on observed-history nodes |
| Adaptive tree | Common on observed-history nodes | Common on observed-history nodes |
| Perfect information | Full scenario known from slot 0 | Full scenario known from slot 0 |

The all-control open-loop arm is deliberately stringent: it commits generation
too. It is **not** the campaign's existing common-truck-profile SAA with oracle
BESS/generator recourse. The second arm isolates vehicle flexibility with matched
causal information for other assets. Its vehicle profile is optimized on this
tiny scenario set, whereas the later counterexample pins a supplied profile.

## Formulation and physical assumptions

For truck `j`, scenario `w`, and slot `t`, let `c,d` be nonnegative grid-side
charge/discharge, `s` the battery state, and `q[j,t]` the committed traction
withdrawal. The dynamics are

```
s[w,j,t+1] = s[w,j,t] + eta_truck c[w,j,t] - d[w,j,t] - q[j,t].
b[w,t+1]   = b[w,t]   + eta_bess  cb[w,t]   - db[w,t].
```

All capacities, connection masks, rates, initial states, and terminal states are
hard constraints. The examples use lossless batteries, full-to-full trucks, and
cyclic BESS. The code also supports positive charge losses; those are tested.
The generator has an explicit per-slot cap. The balance and shared charger bound
are

```
g[w,t] + sum_j(d[w,j,t]-c[w,j,t]) + db[w,t]-cb[w,t] >= Delta[w,t]
sum_j c[w,j,t] + cb[w,t] <= charger_cap[t].
```

`Delta` is exogenous demand minus available renewable production. As in the
reference energy formulation, excess supply can be discarded without cost. The
reported passive spill is the balance residual, **not an unconstrained
scenario-specific generator or battery action**. Thus if scenarios have different
unobserved loads within a node, common generation must cover each of their balance
inequalities; it cannot silently take a different realization-specific value.
This assumes free renewable curtailment/load dumping. It is conservative relative
to a controller allowed an additional current-load observation; that observation
should instead be added to the tree if actually available. Systems without a free
spill sink require a different balance model and suitable balancing information.

Expected cost is the probability-weighted sum of generation, charging and
discharging throughput, and discharge degradation, plus a common fixed asset cost.
Probabilities appear exactly once. No shortage variable or emergency source is
hidden in the model: an infeasible arm returns a solver status and `None` costs.
No feasible-only mean is substituted for an unconditional result.

With nonnegative generation costs, positive throughput costs, free spill, and
efficiencies in `(0,1]`, simultaneous charging and discharging is unnecessary:
reduce charge by `d/eta` and discharge by `d` (or until charge reaches zero).
State changes are preserved, demand and charger use weakly decrease, and cost
strictly decreases. Apply this at the node to preserve nonanticipativity. The
reported solutions have zero simultaneous flow to numerical tolerance.

Input checks require every declared trip exactly once, no overlapping trips on
one truck, no charging while on a trip, and sufficient traction withdrawal at
each departure. They do not establish spatial feasibility of a newly invented
route. Parking masks and deadhead withdrawals must come from an independently
validated fixed skeleton; this prototype does not choose a spatial route.

## Results and validation

The first example has two trucks, two simultaneous committed trips at slot 1,
a one-unit BESS, and two equally probable net-demand paths. Units and costs are
normalized; these values are not measurements of the research instance.

| Arm | Expected operating cost | Common asset cost | Total |
|---|---:|---:|---:|
| All-control open-loop | 10.1000 | 6.7000 | 16.8000 |
| Committed trucks, causal dispatch | 7.6550 | 6.7000 | 14.3550 |
| Adaptive tree | 7.1000 | 6.7000 | 13.8000 |
| Perfect information | 5.9875 | 6.7000 | 12.6875 |

The feasible sets are nested in precisely that order: every common control is
allowed by a refined information partition, and no physical or cost assumption
changes. Therefore `C_PI <= C_tree <= C_committed <= C_open` follows directly from
feasible-set inclusion. All inequalities are strict in this example.

The tests independently reconstruct the energy balances, battery trajectories,
costs, limits, and boundary conditions from exported actions. They also check:

- one-scenario equivalence of all three primary information modes;
- invariance when one scenario is duplicated and its probability is split;
- equal truck, BESS, and generator actions on the same observed prefix;
- equal inherited states at the reveal, with allowed subsequent divergence;
- no history recombination, no-observation recovery of open-loop, and complete
  slot-0 revelation recovering the perfect-information optimum;
- exactly-once trip coverage and rejection of missing traction/illegal charging;
- objective nesting, the dark-day independent energy lower bound, and LP primal
  versus dual objective reconstruction;
- absent BESS, nonunit efficiency, and explicit infeasibility handling.

The LP dual check validates this extensive formulation. It is **not** a reduced
cost check for a new adaptive column-generation implementation.

## A zero oracle gap does not rule out causal vehicle value

The second example is an exact counterexample to interpreting the campaign's
fixed-profile/adaptive oracle difference as an upper bound on causal improvement.
It holds the same assets, duties, and supplied truck profile in both fixed-profile
arms. Each truck's supplied profile is `[0, 0, 0, 1, 0]`. BESS capacity is three,
starts full, and must end full. The net demands are `[1,2,3,0,-1]` and
`[1,2,-2,-4,2]`, revealed at slot 2. All active controls use the declared information.

| Vehicle restriction | Causal tree dispatch | Perfect-information dispatch |
|---|---:|---:|
| Same supplied fixed truck profile | 6.1550 | 5.2650 |
| Adaptive truck energy | 5.3750 | 5.2650 |
| Value of truck flexibility | **0.7800** | **0.0000** |

Perfect-information BESS dispatch can choose different early discharge decisions
for the two futures. Causal fixed-profile dispatch must retain enough BESS energy
for the high-demand slot in the first future. Adaptive trucks can supply energy
at that slot and replenish later, allowing the common early BESS discharge. The
additional flexibility therefore has causal value even though it has no value
when BESS already knows the whole day.

Writing `F` for a supplied fixed profile and `A` for adaptive energy, the relevant
causal upper envelope is

```
F_causal - A_PI = (F_causal - F_PI) + (F_PI - A_PI).
```

The gate reports only the second term. The first term can be substantial. A
small oracle charging gap is evidence about charging flexibility **under oracle
dispatch**; it does not by itself settle causal policy value. This counterexample
establishes the logical point, not its empirical magnitude in the campaign.

## Why independent unrestricted suffix pricing is still invalid

The executable finite counterexample offers two mutually exclusive one-trip
suffix skeletons, `A` and `B`, with incidences `(1,0)` and `(0,1)`. Their unweighted
energy costs in equally probable classes are `(0,10)` and `(10,0)`, respectively.
Each covered trip has dual reward 2. A valid common-duty column chooses `A` in
both classes or `B` in both; either reduced cost is `0.5*0 + 0.5*10 - 2 = +3`.

Independent suffix minimization chooses `A` in the first class and `B` in the
second. Even allocating half the coverage reward to each class gives `-1-1=-2`.
The negative value belongs to no feasible common-incidence column. Repeating a
full reward in every class causes a separate error: a single common covered trip
with reward 2 contributes `-2`, not `-4` for two classes.

This LP fixes the route skeleton first and retains all energy/history coupling.
It proves neither cheap exact pricing over common skeletons, a `K+1` pricing
runtime, nor an inherited lattice-exactness theorem. Those claims remain separate
research work. Class-dependent route incidence would require different coverage
rows and would be a different model.

## Next integration step

1. Export one already validated selected policy as a small local fixture: trip
   assignments, actual parking/deadhead skeleton, multiplicities, capacities,
   signed truck profiles, BESS boundary energy, and source hashes. Keep the source
   policy and its reconstructed skeleton unchanged across comparisons.
2. Match one deterministic day against `gate_wave15/oracle.py`, both with truck
   profiles pinned and with free truck energy. Audit charge efficiency and
   discharge degradation explicitly: the current gate LP's truck dynamics are
   lossless, whereas its BESS charge coefficient is `1-inst.eta`. Match this
   convention when reproducing existing results before changing physics.
3. Freeze a small, genuinely observable tree from training data, then compare
   pinned profiles, optimized common profiles, and adaptive profiles with the
   **same history constraints on BESS and generation**. Report shortages or
   infeasibility separately. This isolates causal vehicle value from information
   granted to the other assets. Include a matched rolling-horizon controller for
   out-of-sample deployment; an in-sample finite tree is not such an evaluation.
4. Revisit pricing only if the causal fixed-skeleton evidence warrants it. First
   enumerate a tiny family of common skeletons, collect each coverage reward
   once, and compare an exact coupled-state method to enumeration. Establish its
   lattice assumptions and complexity rather than importing the disproved
   independent-suffix argument.

Sources examined locally: `independent_review_20260916/ASSESSMENT.md` (Section 5,
correction/addendum), `RESPONSE_AND_NEXT_STEPS.md`, `reference/pricing_truck.py`,
and `gate_wave15/oracle.py` and `causal.py`. No existing source files were edited.
