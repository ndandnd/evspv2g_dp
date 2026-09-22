# Response to the independent assessment

Read 16 September 2026. This is a response to ASSESSMENT.md, not an alteration of the independent review. No experiments or code changes were launched by this response.

## Direction to adopt

The strongest recommendation is to test the value of adaptive vehicle energy decisions before implementing a new stochastic pricing algorithm. Strengthen deterministic planning baselines, isolate asset-sizing effects, and freeze reserve-controller tuning for the immediate comparison. Keep uncertain additional duties as a subsequent research question. A negative charging-adaptation result on the current fixed-duty instance would not by itself rule out the additional-duty problem.

## Corrections needed before implementing Section 5

1. **Independent suffixes do not preserve common task incidence.** The proposed column has one task-incidence vector shared by weather classes. Independent backward sweeps over the unrestricted route DAG can select different post-observation tasks. The current reference pricing state records time, location, SoC and a flag for having served any trip; it does not encode a common remaining task sequence. In general, the sum of independently minimized suffix costs is a relaxation of minimizing that sum subject to a common suffix duty pattern. Fixing a route skeleton first avoids this particular issue for an energy-only subproblem, but does not prove efficient exact pricing over all common skeletons. Alternatively, allow class-dependent task incidence and use class-specific coverage rows; that is a different adaptive-routing model.

2. **Coverage duals are counted repeatedly in the proposed formula.** With one common coverage row, a column contributes the coverage reward once. Applying the full reward -alpha_i in each of K suffix sweeps subtracts K alpha_i for a task common to every suffix. Any decomposition must allocate the reward consistently, in addition to enforcing the intended common task incidence. Probability-weighting or splitting the reward alone does not fix the incidence problem.

3. **Truck nonanticipativity is not system-wide nonanticipativity.** The proposed class rule makes truck energy profiles implementable at the observation time. Scenario-indexed generator and BESS variables still permit full-day perfect-information dispatch unless constrained by observed history. One can deliberately use that planning approximation and evaluate causally, but must label it accordingly. A fully causal stochastic system model needs appropriate nonanticipativity for those controls too, or an explicitly embedded controller.

4. **Exactness is a proposed theorem, not an established result.** Check the network and lattice assumptions, shared states, branch coupling and admissible route patterns. The unresolved common-incidence coupling prevents treating the independent-sweep argument as a proof of the proposed pricing algorithm. Neither the K+1 runtime claim nor inherited discretization exactness should be a promised paper contribution yet.

## Correct the interpretation of the gate experiments

A day-by-day optimum that changes fleet and BESS capacity mixes investment flexibility with information. It can be reported as a wait-and-see relaxation with matched cost accounting, but cannot isolate the value of intraday charging adaptation. For the primary gate, freeze truck count, BESS count, initial energy, terminal rules, generator limits and task obligations across comparators.

Jensen's inequality does not guarantee that the mean-day optimum purchases fewer batteries than SAA, or guarantee a strictly positive out-of-sample saving. The reported capacity difference is empirical evidence to test through matched-capacity controls.

## Ranked next batch

| Priority | Comparison | What it answers | Required controls |
|---|---|---|---|
| 1 | Fixed truck profiles versus fixed route skeletons with daily perfect-information charging/discharging LP | Is there enough upper-bound value in energy adaptation to justify a causal implementation? | Same assets, tasks, initial/terminal energy, generation caps and physical model; compare shortages as well as cost |
| 2 | Mean-day, training-selected monthly profile, conservative deterministic profile and SAA | Does stochastic training beat credible deterministic alternatives? | Equal search budgets/common admissible pool where appropriate; include matched BESS and fleet variants; select alternatives using training/development data only |
| 3 | Small implementable adaptive-charging policy versus deterministic rolling-horizon control | Can an attainable policy capture the oracle opportunity? | Same forecast information and fixed assets; explicitly timed observations; never reveal future weather in the controller |
| 4 | Exact tiny branching example and reduced-cost verification | Can the proposed pricing formulation be made mathematically correct? | Enumerated feasible policies or an extensive formulation; common-duty checks; dual dot-product checks; single-class recovery |
| 5 | Scale and sites | Are positive findings robust beyond the development instance? | Frozen policy-selection protocol; multiple instances and sites; fresh evaluation data; record solve gaps and budgets |

Start the first two on a small reproducible subset, then expand if the implementations pass physical and optimization checks. Preserve failed days separately; do not turn missing feasible costs into zeros or compare conditional cost averages as unconditional savings. Treat suggested 1%, 2%, and 3% thresholds as provisional practical criteria, not statistical conclusions. Report paired uncertainty intervals and failure severity. Avoid declaring the entire adaptive research direction unpromising from one instance or one generation-cap regime.

## Manuscript issues

The assessment flags weather provenance, a demand-energy unit discrepancy and related-work omissions. Verify each against the original manuscript and actual input files before editing; this response does not independently certify those factual corrections.

## Decision

Adopt the gate experiments and stronger baselines. Treat adaptive-column pricing as a promising formulation to validate, not an already-proved inexpensive extension. Defer RL, branch-and-price and further broad reserve sweeps while these gates are unresolved.
