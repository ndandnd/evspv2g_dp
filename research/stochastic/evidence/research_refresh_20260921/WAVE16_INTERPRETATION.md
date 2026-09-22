# Wave 16 interpretation: capacity substitution and inherited-profile regret

21 September 2026. Interpretation of the completed, validated capacity screen; no new experiment or solver run was performed for this note. Evidence: `snapshots/capacity_gate_wave16_validation/validation/RESULTS.md` and `validation.json`. Validation covers 24 cases, 8,760 day records, 1,460 Nb=0 reference matches and 7,300 adjacent-capacity day pairs. The recorded allocation is 26 jobs and approximately 0.375 CPU-hours.

**The screen establishes what adding BESS does to four inherited truck profiles. It does not yet isolate the value of weather-adaptive truck charging against the best common charging profile at the new capacity.**

At Nb=20, all three SAA cases have the same reported adaptive annual mean, 3,602.39/day. Their fixed-profile means are 3,605.38, 3,604.12 and 3,677.95. Thus seed 47's 75.56/day gap (2.05%; descriptive interval [49.87, 101.62]) contrasts with only 2.99/day (0.08%) and 1.73/day (0.05%) for seeds 11 and 29. Each comparison has all 365 days feasible. The difference is in the cost of the committed comparator after adding storage, rather than in the reported adaptive objective. The equal reported adaptive annual means at every capacity are consistent with similar attainable energy outcomes, but do not prove identical route-feasible sets, common optimal schedules or identical daywise objectives.

The profiles were selected for a no-BESS system and are retained unchanged as stationary capacity is added. A daywise adaptive LP may improve them both by **retuning an obsolete static schedule** and by **choosing genuinely different schedules for different weather**. Wave 16 combines those effects. The seed-47 outlier makes this confounding consequential; it does not establish which component dominates without a new comparator.

## The missing mathematical comparator

Fix one source policy's exact serialized skeletons, fleet, traction, Nb, generation cap, truck boundary and empty-cyclic BESS boundary. Let E be all feasible continuous truck-energy profiles on those skeletons, using the same physical domain as the adaptive LP. For weather day ω, let Qω(e) be the optimum BESS/generator recourse cost with common truck profile e, including truck throughput cost. Treat minimum emergency energy lexicographically before money, as in the existing gate.

For a fixed finite weather population with weights pω, restrict the cost comparison to zero shortage on every day and define:

- F_old = Σω pω Qω(e_old): inherited profile, the existing fixed comparator.
- F_common = min over a **single e ∈ E shared by every day** of Σω pω Qω(e): best common profile, with full-day BESS/generator recourse per scenario.
- A = Σω pω min over eω ∈ E Qω(eω): daywise adaptive oracle.

Include the same fixed asset cost in all three. Then:

**F_old − A = (F_old − F_common) + (F_common − A).**

Both terms are nonnegative on that same finite population. The first is inherited-profile regret, removable without weather-dependent truck decisions. The second is the remaining perfect-information adaptation value against the best static profile. At Nb=20 the existing fixed profiles already have zero shortage on every 2022 day, so this cost decomposition can be applied cleanly there. Where no common profile can attain the adaptive shortage optimum, report the reliability gap first; do not force it into a monetary decomposition using differing successful-day supports.

This comparator needs an extensive LP, not new columns or route pricing: truck charge/discharge and truck SoC are common across all weather scenarios; BESS/generation/emergency variables are scenario-specific. Keep Nb and initial states fixed. Optimize total weighted shortage first and expected operating cost second. The original profile is an admissible feasible point, and every adaptive scenario uses the same per-truck physical constraints. This supplies direct nesting witnesses and avoids introducing fleet, route, boundary or discretization changes.

## The next narrow diagnostic and its falsifiers

Start with **policy 17 (SAA seed 47), Nb=20**, using the same 365-day 2022 development population. Solve its best-common-profile LP and report the two components of its 75.56/day gap. A seed-29/Nb=20 control is useful only if a second cell is needed; a new capacity factorial is unnecessary to diagnose the outlier.

This use of all 2022 days is a retrospective development mechanism test. A single profile optimized on that population is still nonadaptive within each day, but its performance is in-sample; do not describe it as a training-only deployable policy or fresh validation. For a later policy comparison, fit the common-profile comparator on 2023 only, freeze it, and evaluate it and a causal adaptive controller with identical information. Training-only selection does not guarantee the same finite-sample cost ordering on a different evaluation population.

- **Inherited-profile explanation:** supported to the extent F_old − F_common accounts for the gap. A feasible common profile that approaches 3,602.39/day directly falsifies the claim that the original 2.05% gain requires weather-dependent truck decisions.
- **Residual oracle opportunity:** supported only by a material F_common − A after the common-profile LP is solved and validated. Report its magnitude and the decomposition, rather than selecting a favorable percentage after seeing the result. A positive residual establishes value of full-day truck information on this population; it still does not show an implementable causal controller can capture it.
- **No collapse:** if a tightly solved common-profile LP retains most of the 75.56/day gap, static retuning cannot explain this particular cell. Failure of a heuristic or a time-limited search to find a better profile would not establish that conclusion; preserve the LP bound, residuals and feasible witness.

## Capacity claims that are and are not supported

Across these four inherited profiles and these 365 days, Nb=5,10,20 gives zero fixed-profile failures; all three SAA profiles already reach zero at Nb=2, while the mean profile retains one failure there. Adaptive profiles have zero failures throughout the tested grid. These are empirical reliability statements for the saved design and weather population, not guarantees for unseen weather or other duties.

There is **no universal cost-gap threshold** in the results. Even among these four plans, Nb=20 does not make every gap smaller than 1%: seed 47 remains at 2.05%. Neither does its exception prove that no finite capacity could remove the gap after static retuning. The difference between two nested optima is not generally monotone, so observations at the six sampled capacities do not identify a universal cutoff between them or beyond them. A prospective “capacity eliminates adaptation value” claim must name the common-profile benchmark, policy family, weather population, reliability condition and numerical materiality threshold.

The best supported conclusion is narrower: stationary capacity greatly improves the retained no-BESS profiles and usually narrows their oracle gap, but one profile leaves a substantial residual that must first be separated into static retuning regret and true scenario-adaptation value. No investment optimum or general abandonment rule follows from this screen.
