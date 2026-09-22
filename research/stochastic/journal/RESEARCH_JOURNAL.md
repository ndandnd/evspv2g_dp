# EVSP–V2G stochastic research journal

This journal follows the work from oldest to newest. The entries through 21 September are retrospective summaries assembled on 21 September 2026 local time / 22 September UTC from the dated research record. They are not newly backdated experiments. New results and corrections should be appended below the existing entries, with their evidence and decision date. Earlier interpretations remain part of the story; a later correction takes precedence.

The research asks when uncertain solar supply makes vehicle-to-grid (V2G) flexibility useful alongside a stationary battery energy storage system (BESS), while mandatory vehicle duties remain covered. Sample average approximation (SAA) fits a plan to sampled weather days. A common truck profile fixes charging and discharging before the day; a causal controller uses only information available when acting; a perfect-information oracle knows the entire day. These are different comparisons.

The [evidence index](EVIDENCE_INDEX.md) maps the entries to reports and primary references. Published material lives in the [stochastic research directory](https://github.com/ndandnd/evspv2g_dp/tree/codex/stochastic-adaptation-gates/research/stochastic). Counts of daily evaluations include repeated use of the same weather: they are not counts of independent weather observations.

## 10 September 2026 — Establish a trustworthy stochastic baseline

**Question.** Can the deterministic scheduling method support shared vehicle plans and scenario-dependent energy supply without changing its physical meaning?

**Action.** The first weather-SAA campaign tested deterministic recovery, duplicated scenarios, reduced costs, physical replay and checkpoint recovery. A reconstruction guard exposed numerical path-matching errors; a separate strict reconstruction release repaired the backward matching tolerance while retaining the forward dynamic program and stopping rule. Failed attempts were preserved.

**Result.** The deterministic restricted-master objective matched 3,464.830702354501 and complete deterministic column generation matched 2,212.4949880687827. The initial corrected paths replayed physically, with reconstruction discrepancies reduced to about 10⁻¹³. Campaign execution and scientific validation were tracked separately.

**Limits.** A priced-out linear program certifies the admitted discretized column family. An integer solution over a frozen pool has a different proof scope. At this stage neither stochastic savings nor reliability benefits had been established.

**Next decision.** Complete and authenticate the first campaign, then compare methods on common validated route pools before attributing cost differences to their training objectives.

**Evidence.** [Campaign register: launch and numerical repairs](../evidence/EXPERIMENT_REGISTER.md); [artifact map](EVIDENCE_INDEX.md#historical-results).

## 11 September 2026 — Separate pool effects, scarcity and information

**Question.** Do the first apparent SAA gains survive equal route choices, constrained supply and implementable energy operation?

**Action.** All 160 effective first-wave policies were evaluated. Common pools removed a major comparison confound. Fixed-policy stress tests were followed by a validated two-phase optimizer for capped generation, matched SAA/minimax/reduced-scenario comparisons, and causal BESS/generator controllers. Truck profiles and purchased assets stayed fixed during these controller evaluations.

**Result.** Equalizing pools reduced the median charge-only/no-BESS saving from 1.240% to 0.029%; the two BESS medians remained about 5.6%. Under capped supply, the matched-method no-BESS SAA plans failed on 6/8/9 development days, while minimax failed on none. Scenario reduction lost feasibility on an omitted training day. The first causal BESS controller exposed failures hidden by full-day foresight; monthly forecasts plus a current-solar update reduced V2G+BESS SAA failures to zero in the 2022 development year.

**Limits.** These findings were conditional on the tested controller, supply cap, finite pools and reused development weather. Minimax optimized a different objective; low failure counts did not imply low expected cost. Costs on jointly feasible days excluded failed days and were never unconditional expected costs. Zero violations with uncapped generation supplied little evidence about reliability.

**Next decision.** Freeze the selected evaluation design and test unused years. The weather audit also changed the data description: the saved training series exactly matched a BestMatch query at fixed UTC−7, rather than the claimed homogeneous ERA5 source. Preserve the benchmark's indexing and disclose the observation-timing limitation.

**Evidence.** [Dated campaign record](../evidence/EXPERIMENT_REGISTER.md); [matched-method results](../evidence/snapshots/20260911_1218/RESULTS.md); [forecast results](../evidence/snapshots/20260911_1421/RESULTS.md). Primary method background: [Kleywegt et al.](EVIDENCE_INDEX.md#primary-references).

## 12 September 2026 — Validate the holdout and challenge method claims

**Question.** How much survives fresh weather, a matched deterministic comparator and a larger training sample?

**Action.** The previously frozen 2024/2025 evaluation was validated, followed by separate 2023-trained comparisons on 2022 development weather. Mean-day, SAA, minimax and minimax with expected-cost tie-breaking shared the same admissible pools. A nested 24-to-64-scenario test retained matched seeds and solver budgets.

**Result.** The holdout audit covered 100 cases and 36,550 daily trajectories. V2G+BESS SAA with the current-solar forecast had 0/0/0 failures in 2024 and 1/1/1 in 2025. In the matched development comparison, SAA24 cost 3,162.41–3,174.03 per day versus 3,412.91 for the annual-mean plan, with all days feasible. SAA64 brought small additional savings whose paired intervals all included zero. More scenarios did not uniformly improve causal reliability.

**Limits.** The original holdout deterministic plans used unmatched pools. Once inspected, those years could no longer serve as untouched test data for later choices. The roughly 7% development advantage was an advantage over an annual-mean comparator; the stronger monthly comparator introduced later would change its interpretation. Remaining no-BESS integer gaps also limited rankings.

**Next decision.** Keep SAA24 as a useful benchmark, stop expanding scenarios without a specific question, and strengthen the deterministic baseline. A literature audit found that integrated duties, common charging, BESS sizing and uncertain PV already overlap closely with [Najafi et al. (2025)](https://doi.org/10.1016/j.trd.2025.104664); the contribution must concern a more precise commitment or information question.

**Evidence.** [Holdout validation](../evidence/snapshots/holdout_validation/RESULTS.md); [matched-policy validation](../evidence/snapshots/fair_policy_validation/RESULTS.md); [sample-size validation](../evidence/snapshots/sample64_validation/RESULTS.md); [12 September literature audit](../evidence/literature_update_20260912/CLOSEST_PAPERS.md).

## 12 September 2026 — Improve computation without confusing speed and policy quality

**Question.** Can the existing column-generation plus restricted-MIP method support the next scientific tests, or is a full branch-and-price implementation needed?

**Action.** An isolated candidate consolidated correctness checks and compared sparse assembly, persistent LPs, pricing caches and warm imports. Longer frozen-pool searches and unions of existing validated pools tested whether weak integer results came from search budgets or missing useful columns.

**Result.** The validated panel contained 56 complete column-generation/MIP variants and two separately certified common-profile LP-infeasible cases. Sparse assembly improved column-generation time by 1.115–1.277× with equal integer costs. Persistence was faster in some stages but changed the generated pools and could worsen total time or integer quality. The 120-trip pool union improved the best individual-pool optimum by about 2.25%, reaching a 0.272–0.275% incumbent gap to a separately valid full-family LP bound.

**Limits.** That bound applies to the admitted discretized common-profile model. The union did not establish integer optimality; prior pool-generation work was not free. A faster LP sequence alone did not establish a better end-to-end method.

**Next decision.** Retain the safeguards and sparse assembly, use persistence and pool enrichment selectively, and answer the operational question before undertaking branch-and-price or reinforcement learning.

**Evidence.** [Algorithm validation](../evidence/snapshots/algorithm_efficiency_validation/RESULTS.md); [MIP-budget validation](../evidence/snapshots/mip_budget_validation/RESULTS.md); [pool-union validation](../evidence/snapshots/pool_union_validation/RESULTS.md).

## 13 September 2026 — Separate installed storage from its controller

**Question.** Does uncertain weather increase the benefit of storage, and can a reserve rule improve reliability at an acceptable cost?

**Action.** Controlled BESS experiments held mean solar fixed. Reserve experiments then varied the operating rule while retaining source truck profiles, capacity, forecast and boundary conditions. The data package documented four weather years and the synthetic instances.

**Result.** The 90-case BESS study produced 24 shortage-interaction estimates favoring a larger storage benefit under variable solar, but every 95% interval included zero. Maximum-reserve operation removed the observed failures in the tested reserve configurations at a large cost. With five BESS units and an empty cyclic start, a 50% reserve target matched the maximum rule's observed zero failures at a 15.5–17.4% cost premium, versus 29.1–33.7%. A 25% target cost 7.9–9.0% more and had one failed day in one of six schedules.

**Limits.** These were repeated development-year evaluations of six source schedules, not independent populations or investment solutions. Cost premiums used matched feasible dates. An adverse setting also increased failures, and zero observed failure was not a future guarantee. No vehicle energy adaptation was present.

**Next decision.** Freeze broad reserve tuning and move to vehicle-side flexibility with explicit information timing. A public energy-resource component from Parmentier, Martinelli and Vidal was exercised successfully, but their full solver was neither reproduced nor integrated.

**Evidence.** [13 September briefing](../evidence/CURRENT_BRIEFING_20260913.md); [BESS study](../evidence/snapshots/bess_robustness_validation/RESULTS.md); [reserve study](../evidence/snapshots/reserve_control_validation/RESULTS.md); [bounded-reserve briefing](../evidence/snapshots/bounded_reserve_validation/BRIEFING.md); [public-code checks](../evidence/public_code_checks/RESULTS.md).

## 16–17 September 2026 — Independent review redirects the next gate

**Question.** What would justify a stochastic extension beyond fixed vehicle profiles and an aggregate storage controller?

**Action.** An independent assessment challenged the weak deterministic baseline and the absence of adaptive vehicle decisions. The response accepted a fixed-assets charging gate and stronger deterministic planning days, while correcting the proposed pricing argument. The resulting gate campaign began during 17–19 September; the saved assessment does not assign a more precise launch time to every subexperiment.

**Result.** The agreed first comparison held fleet, BESS, duties, boundaries and generator limits fixed, then relaxed truck energy commitments on a reconstructed feasible skeleton. The original claim that independent class suffixes provide exact common-duty pricing was withdrawn: suffixes can choose different duties, and repeating a coverage dual counts its reward more than once. Common-skeleton energy adaptation and class-dependent duty assignment became separate models.

**Limits.** Corrected model sketches were proposals, not proved pricing algorithms. Making trucks nonanticipative would not automatically make scenario-dependent BESS and generation causal. The review's suggested abandonment threshold based on two perfect-information oracles was provisional and was further corrected on 21 September.

**Next decision.** Run the bounded charging and deterministic-baseline gates before implementing adaptive pricing. Evaluate any deployable controller against an equally informed rolling-horizon baseline; keep additional-duty uncertainty as a distinct question.

**Evidence.** [Independent assessment and dated addenda](../evidence/independent_review_20260916/ASSESSMENT.md); [response and corrections](../evidence/independent_review_20260916/RESPONSE_AND_NEXT_STEPS.md).

## 19 September 2026 — A stronger baseline changes the SAA story

**Question.** Does fixed-profile SAA outperform a credible deterministic planning day, and where is perfect-information truck flexibility valuable?

**Action.** The gate evaluated reconstructed fixed skeletons with adaptive truck charging, monthly and quantile planning days, selected matched-capacity controls and causal BESS baselines. The 19 September addendum recorded the interpretation; the values below use the later 21 September audit where it corrected the original report.

**Result.** A training-selected August V2G+BESS plan cost 3,162.04 per day causally, compared with 3,162.41 / 3,163.78 / 3,174.03 for SAA24, with zero failed days for all four. Thus the earlier roughly 7% gain over the annual-mean plan did not show that SAA was necessary. Without BESS, perfect-information adaptive truck energy saved 3.81–4.76% on jointly feasible days and removed the SAA profiles' 6/8/9 failures. The existing BESS plans had oracle gaps below 0.1%.

**Limits.** Both sides of the oracle comparison knew the full day. The skeletons were reconstructed to be compatible with the retained profiles, rather than recovered original pricing paths. Matched battery counts still allowed other policy choices to change. The original claim that a dark planning day bought no storage was false: audited 10th-percentile plans purchased seven units in Solar+BESS and five in V2G+BESS.

**Next decision.** Test how adding stationary capacity affects the existing no-BESS profiles. Treat small BESS oracle gaps as evidence of substitution under perfect information, while leaving the causal comparison open.

**Evidence.** [19 September addendum](../evidence/independent_review_20260916/ASSESSMENT.md#addendum-19-september-2026-gate-results); [audited gate results and qualifications](../evidence/research_refresh_20260921/GATE_AUDIT.md).

## 21 September 2026 — Audit the gate and narrow the information claim

**Question.** Are the saved gate results sound, and does a small oracle gap rule out useful causal adaptation?

**Action.** The refresh checked 64,970 daily journal records, 66 reconstructed policy skeleton sets and 468 pinned LP witnesses. It recomputed conditional-cost intervals by resampling calendar dates before removing infeasible observations. A fixed-skeleton energy-policy prototype and a refreshed primary-source review tested the proposed next direction.

**Result.** The saved results passed the stated audit; the correct baseline MIP count was 48 optimal and six time-limited. Corrected no-BESS cost intervals remained positive. Thirteen semantic prototype tests passed, including a counterexample with zero fixed/adaptive perfect-information gap but positive causal adaptation value. If F and A denote fixed and adaptive costs, the oracle gives A(causal) ≥ A(perfect information). Therefore F(causal) − A(perfect information), rather than F(perfect information) − A(perfect information), bounds attainable savings from the causal baseline.

**Limits.** The counterexample is a mathematical witness, not a real-instance savings result. The audited gate assumes lossless truck charging, zero degradation cost and no finite shared charging limit; dormant implementation issues prevent extending its conclusions beyond those settings without repair. Historical current-slot averages also idealize what is known at the action time.

**Next decision.** Compare causal truck energy adaptation with an equally informed fixed-profile controller. The literature makes that comparison more demanding: [Abdelwahed et al.](https://doi.org/10.1111/deci.12633) already study rolling charging with uncertain solar and BESS; [Enyam et al.](https://doi.org/10.48550/arXiv.2604.18268) use scenario MPC but assume PV foresight. [Zhuang and Liang](https://doi.org/10.1109/TSTE.2020.3039758) remain a high-priority unresolved formulation overlap. The bounded review does not establish novelty or an exhaustive search.

**Evidence.** [Refresh briefing](../evidence/research_refresh_20260921/BRIEFING.md); [gate audit](../evidence/research_refresh_20260921/GATE_AUDIT.md); [literature refresh](../evidence/literature_refresh_20260921/REVIEW.md); [primary references and access limits](EVIDENCE_INDEX.md#primary-references).

## 21 September 2026 — Capacity helps, but an inherited profile leaves a residual

**Question.** How quickly does added stationary capacity reduce the oracle opportunity in the original no-BESS plans?

**Action.** Wave 16 paired fixed and adaptive perfect-information LPs for four retained profiles and six BESS capacities, using the same fleet, duties, serialized skeleton, generator cap and empty cyclic BESS boundaries. Validation covered all 24 cases and 8,760 day pairs, including 1,460 zero-storage reference matches and 7,300 adjacent-capacity comparisons. Recorded allocation was approximately 0.375 CPU-hours.

**Result.** Two BESS units removed all observed fixed-profile failures for the three SAA plans under perfect-information dispatch. At 20 units, their cost differences were markedly unequal:

| SAA source profile | Fixed cost/day | Adaptive cost/day | Difference/day | Saving |
|---|---:|---:|---:|---:|
| Seed 11 | 3,605.38 | 3,602.39 | 2.99 | 0.08% |
| Seed 29 | 3,604.12 | 3,602.39 | 1.73 | 0.05% |
| Seed 47, policy 17 | 3,677.95 | 3,602.39 | 75.56 | 2.05% |

**Limits.** All 365 days are feasible in these three cells, but the truck profiles were selected for systems without BESS and then retained as storage was added. Their gap includes possible static retuning as well as weather-dependent adaptation. Equal reported adaptive annual means do not prove equal feasible sets or identical daily optima. The screen provides no universal capacity threshold, causal reliability guarantee or optimal investment.

**Next decision.** Solve for one best common truck-energy profile on policy 17's fixed skeleton at 20 units. On the same finite population, decompose inherited-profile cost minus adaptive-oracle cost into inherited-profile regret plus the remaining adaptation value against the best common profile.

**Evidence.** [Wave-16 validation](../evidence/snapshots/capacity_gate_wave16_validation/validation/RESULTS.md); [interpretation and proposed falsifiers](../evidence/research_refresh_20260921/WAVE16_INTERPRETATION.md).

## 21–22 September 2026 — Register the common-profile diagnostic

**Status: protocol registered / preparing; results pending.** This entry was prepared on 22 September UTC, corresponding to 21 September local time. It records the next comparison and does not assert solver completion.

**Question.** How much of policy 17's 75.56-per-day gap at 20 BESS units can be removed by one retuned truck profile shared by every weather day?

**Action.** Prepare a common-profile extensive LP on the exact retained fleet, duties, skeletons, generator cap and boundary conditions. The retrospective 2022 diagnostic separates inherited-profile regret from residual perfect-information adaptation; a 2023-fitted common-profile control is the subsequent training-only comparison. The [registered gate directory](../common_profile_gate/) holds the executable protocol, input identities and eventual run evidence.

**Result.** Pending. No job identifier, numerical outcome, completion state or result hash is inferred from registration. Append the actual execution and validation record when available.

**Limits.** A common profile optimized on the same 2022 population is an in-sample mechanism test. Even a positive residual perfect-information gap would not establish attainable causal savings. Comparisons must retain shortage-first optimization and identical costs and physics; differing successful-day supports cannot be forced into the monetary decomposition.

**Next decision.** Use the validated LP bound and feasible profile witness to measure the two gap components. Then decide whether the remaining question warrants a matched causal controller test. New routing/pricing work depends on that evidence.

**Evidence.** [Mechanism-test specification](../evidence/research_refresh_20260921/WAVE16_INTERPRETATION.md#the-next-narrow-diagnostic-and-its-falsifiers); [gate protocol and run artifacts](../common_profile_gate/).

### Execution record — 22 September 2026 UTC (21 September local)

The four-case protocol and exact inputs were committed and pushed before launch in [d52c2d6](https://github.com/ndandnd/evspv2g_dp/commit/d52c2d6a850e22c24eecbfff0addfff9d7f4a0b0). Initial Slurm array 726949 failed before Python/Gurobi started because of a shell quoting error. All four failure logs and scheduler outcomes are retained in [attempt01](../common_profile_gate/runs/attempt01/). The launcher was corrected, shell syntax checked, and [f8f8101](https://github.com/ndandnd/evspv2g_dp/commit/f8f8101557f2ee2983f3cdc6e7369def28338ded) pushed before retry.

Job 727162 runs the first full policy-17/2022 case in a fresh attempt02 directory. The remaining cases are held for submission until this first case passes the actual cluster solve and independent replay. There is no dependency on EVSP–DR. Resources are at most two single-CPU jobs, 4 GiB each, one-hour wall limit, Scaglione, no requeue and the reserved GPU host excluded. [Launch register](../common_profile_gate/launch.json).

Ten semantic solver tests passed, including native Gurobi/HiGHS agreement. Independent validation reproduced all 730 archived policy-14/policy-17 daily costs within 1.82e-12, with maximum physical residual 7.11e-15; it also checked tamper rejection, interrupted-journal resume and cross-year ordering restrictions. [Validation notes](../common_profile_gate/VALIDATION_NOTES.md).

The Google Doc now includes a separate [Research journal tab](https://docs.google.com/document/d/1UJIr77gwfUqexeJfy7oFLFbHdxWZcHMGYnyVAVAKkVM/edit?tab=t.s4s0ccun8aob), arranged oldest to newest with native editable tables. Existing tabs remain available.

## 21 September local / 22 September UTC — Common-profile diagnostic completed

**Question.** Does policy 17's large remaining oracle gap require weather-adaptive truck charging, or can a single improved charging plan remove it?

**Action.** Ran all four declared fits and independently replayed each frozen profile on all 365 days of 2022 (1,460 new daily comparison records). Corrected execution commit [f8f8101](https://github.com/ndandnd/evspv2g_dp/commit/f8f8101557f2ee2983f3cdc6e7369def28338ded); jobs 727162_0 and 727176_1–3 all completed with exit 0:0. All 16 native Gurobi 12.0.3 LP phases were optimal. No fleet, trip assignment, storage count or route pool was changed.

**Result.** At 20 BESS units, retuning a common profile removes **99.23% of seed 47's old gap**. The 2023-fit controls show the same pattern when evaluated on 2022. All costs below include identical fixed asset charges, and every comparator has zero shortage on all 365 days.

| Source / fit year | Inherited cost/day | Retuned common cost/day | Adaptive oracle/day | Static improvement/day | Remaining gap/day |
|---|---:|---:|---:|---:|---:|
| Seed 47 / 2022 | 3,677.947 | 3,602.964 | 3,602.386 | 74.983 | 0.578 |
| Seed 47 / 2023 | 3,677.947 | 3,602.970 | 3,602.386 | 74.977 | 0.585 |
| Seed 29 / 2022 | 3,604.117 | 3,602.964 | 3,602.386 | 1.153 | 0.578 |
| Seed 29 / 2023 | 3,604.117 | 3,602.970 | 3,602.386 | 1.146 | 0.585 |

The seed-47 in-sample decomposition is 75.561 = 74.983 static retuning + 0.578 residual full-information adaptation. The old 2.05% gap therefore mostly reflected an inherited no-BESS charging plan that had not been retuned after adding storage. This result directly answers wave16's confound; it does not establish that causal adaptation is unnecessary.

**Limits.** 2022 fits are retrospective in-sample mechanism tests. The 2023 fits separate fitting from evaluation, but 2022 was already inspected development data; there is no new untouched test year here. Their differences are signed descriptive comparisons, not a cross-year nesting theorem. BESS and generation still have full-day foresight. All cases retain lossless charging, zero degradation, unlimited shared chargers and fixed reconstructed skeletons. Zero observed shortage is not a future reliability guarantee. Numerical Gurobi bounds, physical replay and statistical interpretation remain separate claims.

**Compute.** Successful runs consumed 142 allocated CPU-seconds; the four pre-solver shell failures consumed another 12, for 0.0428 CPU-hours total. At most two jobs ran concurrently. The [scheduler record](../common_profile_gate/runs/attempt02/accounting.psv) is filtered by job name and submission date as well as IDs, avoiding historical records with reused job numbers. No V2G jobs remain active from this batch.

**Next decision.** Use a retuned common profile as the fixed-profile baseline for causal energy operation. Compare it with adaptive truck charging under identical forecasts and observations, keeping duties and assets fixed. The remaining oracle gap alone cannot answer that causal comparison. Full branch-and-price, RL and another broad capacity sweep are not justified by this diagnostic.

**Evidence.** [Results, distributions and interval sensitivity](../common_profile_gate/report/RESULTS.md); [independent full-result audit](../common_profile_gate/INDEPENDENT_RESULT_AUDIT.json); [all native logs and full solution/replay artifacts](../common_profile_gate/runs/attempt02/); [seed-47 common-cost Gurobi log](../common_profile_gate/runs/attempt02/policy17_nb20_fit2022/fit/common_cost.log); [registered protocol](../common_profile_gate/PROTOCOL.md).

### Additional cost check — 22 September 2026 UTC

Disaggregating the saved actions shows that **the remaining 0.578–0.585/day is entirely the throughput penalty, not fuel savings**, to numerical tolerance. The common and adaptive profiles have equal fuel costs on every 2022 day in all four cases (maximum discrepancy 2.73e-12). Their annual mean fuel cost is 2,200.381307/day. The common plan's throughput charge is 7.582741–7.588923/day, versus 7.004304 for the oracle. The coefficient is 0.025; explicit degradation cost is zero, so this is not a calibrated battery-wear finding.

This post hoc accounting required no new solve. It rechecked 1,460 trace hashes and reconstructed operating costs within 2.01e-11. Seed47's large static improvement mainly reduced fuel: inherited fuel cost 2,274.677874/day falls to 2,200.381307/day. The fair next causal comparison must report fuel, shortage and throughput separately. [Component table, exact quantities and reproduction](../common_profile_gate/report/COST_COMPONENTS.md).
