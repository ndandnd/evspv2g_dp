# EVSP–V2G research refresh — 21 September 2026

## Where we left the research

The September 17–19 gate campaign materially changes the earlier assessment. It tested fixed-skeleton vehicle charging with perfect weather information, stronger deterministic planning days, matched battery counts and selected causal BESS baselines. This refresh audits those artifacts rather than launching that gate again.

| Finding | Evidence | Interpretation |
|---|---|---|
| A good deterministic planning day matches SAA in the main BESS regime | V2G+BESS training-selected August plan: causal cost 3,162.04/day and 0/365 failed days. SAA24 seeds:3,162.41 / 3,163.78 / 3,174.03, also 0 failed days | The earlier roughly 7% saving over the annual-mean plan is not evidence that SAA is necessary here |
| Vehicle energy flexibility matters in the no-BESS oracle comparison | SAA plans save 3.81–4.76% on jointly feasible 2022 days; failed days 6/8/9 become 0 with adaptive charging | Positive development signal on fixed assets and reconstructed skeletons, assuming the full day is known |
| BESS changes the comparison | Under the existing BESS plans, full-information fixed-profile versus adaptive-profile savings are below 0.1% | BESS substitutes for vehicle flexibility under perfect information in these tested plans; this does not prove causal vehicle flexibility has no value |
| Existing evidence is narrow | Main stochastic evidence: one 20-trip, 2-location synthetic instance, solar site and capped generator regime | Need stronger information baselines, multiple regimes/instances and eventually fresh evaluation data before a paper-level claim |

The analysis agent verified 64,970 daily journal records, source identities, 66 reconstructed policy skeleton sets and 468 pinned checks. It corrected the reported MIP termination count (48 optimal, 6 time-limited) and recomputed calendar-block intervals without compressing away failed dates. Those corrected no-BESS cost intervals remain positive. See GATE_AUDIT.md and gate_audit/ for evidence.

## A necessary correction to the earlier stopping rule

A small difference between two perfect-information oracles is not an upper bound on savings relative to a forecast-limited causal baseline. Both costs may increase differently when information is restricted. Therefore we should not abandon causal truck adaptation solely because the BESS oracle gap is small. The fair next comparison gives both controllers the same forecast and observation history, then changes only whether truck energy decisions may adapt. The new executable synthetic counterexample has a zero fixed-profile/adaptive perfect-information gap but a positive causal gap with exactly the same pinned baseline truck profile. This is a mathematical counterexample to the old inference, not an empirical savings estimate. Thirteen semantic tests passed, including information consistency, physics, duplicated scenarios, infeasibility reporting and this counterexample.

## Work advanced today

| Workstream | Deliverable | Scope |
|---|---|---|
| Literature | ../literature_refresh_20260921/REVIEW.md | Updated primary-source comparisons, newly identified causal-PV reference, code/data availability and explicit access limits |
| Experimental audit | GATE_AUDIT.md | Recomputed/checked archived results and corrected interpretation; no changes to prior raw evidence |
| Mathematical prototype | ../adaptive_prototype_20260921/ | Fixed-skeleton LP with nonanticipativity on trucks, BESS and generation; tiny semantic tests and counterexample to unrestricted independent suffix pricing |
| New capacity experiment | ../campaigns/capacity_gate_wave16/PROTOCOL.md | Four original no-BESS plans × six stationary capacities; paired full-information LPs on 2022 development weather |

The requested /deepresearch skill is absent in this installation. The literature agent attempted Google Scholar discovery, reported access failure, and used accessible primary sources. No claim of a complete Scholar or systematic review is made.

## What changed in the literature review

| Reference | What we learned | Use for this project |
|---|---|---|
| Abdelwahed et al., Decision Sciences (2025; online 2024) | Real-time charging with uncertain solar, actual forecast updates, stationary storage and supplied bus availability | Stronger causal comparator than a fixed annual-mean plan; adaptive charging plus PV/BESS alone is not a new contribution |
| Enyam et al. (2026 preprint) | Scenario MPC with fixed EV timetables, but charge-only EVs and explicitly perfect PV foresight | Useful control architecture; not a verified uncertain-PV V2G predecessor |
| Caustur et al. (2026 revision) | Deterministic PV/ESS/V2G economics with supplied duties; verified public data and loader, no released solver found | Data/comparison lead for stationary/mobile substitution and degradation sensitivity |
| Zhuang & Liang (2021) | Primary bibliography confirms a stochastic renewable/B2G energy-management paper; full formulation remains unavailable | High-priority unresolved overlap before any novelty claim about stochastic bus-to-grid operations |

The full [literature refresh](../literature_refresh_20260921/REVIEW.md) links the primary papers, equation evidence, repository snapshots and search log. Nath/Baldua's revised preprint, Yetkin's latest preprint and Ricard's final metadata were also checked. The official Elia historical PV schema offers actuals and day-ahead forecast fields, but its most-recent-forecast field does not establish which intraday forecast was available at a past decision time. A complete intraday forecast-vintage dataset is still unverified.

## New experiment and resource use

Campaign capacity_gate_wave16 uses frozen source policies 10/11/14/17 and Nb 0/1/2/5/10/20. Every comparison retains identical fleet, assigned tasks, reconstructed parking/deadhead skeleton, generator cap and initial/terminal conventions. BESS starts and ends empty. This tests conditional operating value, not optimal investment or a reoptimized fleet.

24 cases × 365 development days = 8,760 paired daily outcomes. Array 691633 follows passed smoke 691628. Maximum 4 single-CPU jobs, 2 GiB each, 20-minute ceiling, default_partition, nice=1000; reserved GPU host excluded. Journals flush daily and verify identities on resume. Source commit caecc0af3568fb63ba8a5e09052abdd4e555b419; manifest 5fa223935ce243f15972230b6239ae0f7cd0051e21e7a3ee33a61c443c3b3add. No MIPs or changes to EVSP–DR were submitted. Launch status is recorded in the campaign launch.json; subsequent validation, when available, supersedes launch state.

## New capacity results — complete and validated

All 24 cases completed (8,760 paired daily outcomes). All 26 scheduler tasks including smoke completed with exit 0:0. Allocated CPU time was **0.375 hours**, with at most four single-CPU jobs active. Validation checked 1,460 zero-storage days against wave15, 7,300 adjacent-capacity day pairs, source identities, journal chains and recomputed summaries.

The following ranges cover the three SAA source profiles; they share the same weather, rather than constituting independent test populations. Both comparators know the full day. The mean-day source is also retained in the complete report.

| Added BESS units | Fixed-profile failed days (of 365) | Adaptive-profile failed days | Paired cost saving from vehicle energy flexibility |
|---:|---:|---:|---:|
| 0 | 6–9 | 0 | 3.81–4.76% (conditional on jointly feasible days) |
| 1 | 0–2 | 0 | 1.71–3.34% (conditional where failures occur) |
| 2 | 0 | 0 | 1.41–3.03% |
| 5 | 0 | 0 | 1.14–2.97% |
| 10 | 0 | 0 | 0.32–2.55% |
| 20 | 0 | 0 | 0.05–2.05% |

Two stationary units eliminate observed failures in all three fixed SAA profiles **under perfect-information BESS dispatch**. This is neither a causal reliability result nor a guarantee for other weather. At 20 units, two profiles retain less than 0.1% flexibility value, but the third retains 2.05%; therefore there is no universal threshold in these results.

An important control remains: these truck profiles were designed without BESS and then held fixed as storage was added. The measured gap can include the benefit of retuning a common truck profile for the changed assets, as well as day-specific adaptation. The next comparison should optimize a common truck profile on the same fixed skeleton/assets using training data, then evaluate it alongside a causal adaptive controller with matched information. Do not call the full gap the value of weather information.

[All cases and calendar-block intervals](../snapshots/capacity_gate_wave16_validation/validation/RESULTS.md) and [machine-readable validation](../snapshots/capacity_gate_wave16_validation/validation/validation.json) retain every profile and capacity. No further V2G batch was submitted automatically after this completed screen.

## Recommended sequence

1. The capacity screen is validated. First diagnose policy 17 at Nb=20 with a single best-common-profile LP on the already-used 2022 population. This retrospective mechanism test separates static retuning from full-information adaptation without claiming out-of-sample performance. Then fit a common-profile control on 2023 and compare it with causal adaptation. See [the precise decomposition and falsifiers](WAVE16_INTERPRETATION.md). Do not interpret conditional costs as unconditional savings.
2. Connect the validated causal fixed-skeleton prototype to small real-instance route skeletons. Compare committed truck profiles plus causal BESS/generation against adaptive truck energy under identical information. Keep fleet and BESS fixed.
3. Use defensible forecast information. A historical realized-current-block mean is an explicit idealization; it is not automatically a forecast available when the block begins. Archived forecast issue times and lead times are needed for a realistic information-value study.
4. If causal gains survive, vary storage constraints/prices, generator limits and duty timing on additional instances/sites, then freeze the protocol before fresh out-of-sample evaluation.
5. Keep additional-duty uncertainty as a separate controlled extension. First-stage fleet/readiness, task revelation, post-revelation reassignment and service guarantees must be explicit. A weak weather-only result would not settle this distinct question.

Retain the current CG+restricted-MIP infrastructure. Neither RL nor full branch-and-price is presently required to answer these experimental questions. The suggested K+1-sweep adaptive pricing algorithm remains unproved for common task incidence; the new prototype is an energy-policy model, not that pricing algorithm.
