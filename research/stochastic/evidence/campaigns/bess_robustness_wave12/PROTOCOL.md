# Does weather variability increase the reliability value of BESS?

Registered 13 September 2026, before running this experiment. This is a controlled mechanism test on previously used 2022 development weather. It is not a new holdout, a new investment optimization, or an adaptive-bus-charging experiment.

**Hypothesis.** With an identical bus fleet, trip service, complete bus charging/discharging profile, generator limit and solar mean, a given stationary battery capacity removes more expected emergency-energy demand when weather is variable than when it is predictable. The corresponding failure-probability reduction is a secondary outcome. The hypothesis may fail: storage cannot create energy, and extended low-solar periods, power limits or controller errors may limit its value.

## Fixed decisions and information

Use all six existing SAA24 profiles from the validated fair-policy panel: policies 11/14/17 (originally designed without BESS) and 21/24/27 (originally designed with BESS), scenario seeds 11/29/47. Each profile's bus fleet and complete energy schedule remain unchanged across every treatment. Required trip service remains identical. Comparisons are paired within a profile; different source profiles are sensitivity cases, not six independent weather populations.

Before each day, stationary capacity is prescribed at 0, 5, 10, 20 or 30 units. Each unit has the inherited energy capacity 7 and per-slot power 1.75 in the reference energy units. The inherited battery cost is 36 model cost units per day per unit. These are benchmark units and costs, not a site-specific investment quotation. The prior optimizer's choice of 20 units was **not** an imposed upper bound.

For this first mechanism test, every BESS starts empty and must end empty each day. This ensures added capacity does not provide extra free starting energy and nests the physical oracle feasible regions. It differs from the prior endogenous common initial SoC; investment conclusions require a follow-up with the original initial-state decision and an explicit interday operating assumption.

The causal controller observes the current slot's average solar and all past observations; it does not observe later realized solar. It uses the existing validated current-solar forecast update and lexicographically minimizes predicted emergency energy, then operating cost. The complete-day information oracle is reported separately as a physical flexibility benchmark. Bus routes and charging remain fixed. Travel times, traction energy, prices and extra-duty calls remain deterministic.

## Mean-preserving weather control

For each month and time slot, compute the mean solar profile of the finite 2022 development population. Define solar for day d as

`solar(d, lambda) = monthly_mean(d) + lambda * (observed_2022_solar(d) - monthly_mean(d))`.

Use lambda = 0, 0.5 and 1. These convex combinations preserve nonnegative solar and the exact monthly mean at every time slot; the conditional variance scales with lambda squared. Lambda 0 repeats the predictable monthly curve. Lambda 1 reproduces the original daily profiles. All regimes use the same load, days, generator limit, bus profile and battery parameters.

The synthetic population's monthly mean is supplied to the controller in all regimes. This is a controlled known-mean experiment, **not** a forecast learned independently of evaluation data. Source bus policies were trained on 2023; no new policy is fitted to 2022. Do not use these counterfactual results as new 2024/2025 holdout evidence.

## Comparisons and falsification

There are 6 profiles × 5 capacities × 3 variability levels = **90 independent daily-replay cases**, each covering 365 days. The primary statistic within each profile and nonzero capacity n is:

`interaction(n) = [EENS(0,1) - EENS(n,1)] - [EENS(0,0) - EENS(n,0)]`.

EENS is mean daily emergency energy, including every day. A positive interaction supports additional reliability value from variability; a nonpositive value is evidence against that claim for that setting. Report all capacities, including adverse results. Do not select a winning capacity after inspecting the results and present it as preselected. Half variability measures the shape of the response. Repeat the calculation for failure probability and the perfect-information oracle separately. Oracle shortage must be nonincreasing with capacity; this is a validation property, not a required property of the causal heuristic.

Report each seed/source profile, daily failure fraction, mean shortage, maximum shortage, worst-5% mean shortage (empirical CVaR95), and operating/asset costs. Costs on failed days exclude emergency-energy pricing and are not total feasible service costs. Provide paired cost comparisons on jointly feasible dates with the denominator; never hide failed days in a cost mean. Use the existing 2,000 paired circular 14-day block resamples, seed 7291, for descriptive intervals. The finite weather population and synthetic transformations limit population interpretation; zero empirical failures does not prove zero future risk.

## Execution and validation

Daily replay uses byte-identical `horizon` and `day` function bodies extracted from the validated dispatcher. No public third-party solver is imported. Record source hashes, extracted code hash, new execution commit, config/input hashes, source profile hashes and native environment. Recheck selected-route physical feasibility, mandatory coverage, exact solar mean preservation, causal prefix invariance and zero-storage behavior before launch. Verify every saved trajectory independently, journal continuity, status identity, oracle nesting and no future-data use; repeat independent oracle solves on predetermined dates 0/182/364 after collection.

Use default_partition, at most 50 tasks concurrently, 1 CPU and 2 GiB per task, 60-minute wall limit, requeue and USR1 warning 120 seconds early. Exclude reserved-compute-host. Checkpoint and fsync every day; resume only after matching the manifest, input identities and complete journal chain. These are resumable daily LP evaluations, not Gurobi MIP searches. An incomplete journal line is an error requiring a separate diagnosed recovery, never silent truncation.

Run two small cluster smoke cases (no storage and positive storage) and validate before submitting the full array with no dependencies. Record actual allocation and work time, including smoke and retries; 90 CPU-hours is a scheduler ceiling, not expected usage. Preserve all earlier campaigns and EVSP–DR jobs.

## Investment follow-up after this gate

To establish **economic investment value**, use a common validated route pool across deterministic and stochastic planning, reoptimize integer bus choices and BESS count, and allow only the declared causal recourse. Compare annualized total cost versus reliability targets, battery cost/efficiency sensitivity and the same held-out weather. Report the minimum capacity/cost achieving a target failure probability or EENS, with intervals and MIP bounds. A curve from fixed schedules cannot establish the optimal system-wide investment. V2G on/off is a separate matched factorial to test substitution or complementarity. Existing published solar/bus/storage studies already motivate this hypothesis; novelty needs a sharper operational finding.
