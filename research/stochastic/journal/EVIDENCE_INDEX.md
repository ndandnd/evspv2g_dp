# Evidence index

This index accompanies the [chronological journal](RESEARCH_JOURNAL.md). Reports are the project's own summaries; primary papers are linked rather than republished. Relative links below use the public export layout `research/stochastic/evidence/<original research-relative path>`. Native run artifacts named inside older reports are original research-relative references unless explicitly included in that export; a report link alone does not imply that the full raw campaign is published.

The journal was assembled from dated records on 21 September 2026 local time / 22 September UTC. The evidence hierarchy is validated run artifacts and their audit, then dated summaries, then provisional interpretations. Corrections are recorded in later journal entries. A scheduler's completed state alone is not scientific validation.

The [export notes](../evidence/EXPORT_NOTES.md) list included material and intentionally omitted original-artifact references. The [manifest](../evidence/EXPORT_MANIFEST.json) preserves source and exported hashes; the [export verification](../evidence/EXPORT_VERIFICATION.json) records link/hash checks and the 13 passing prototype tests. The [causal fixed-skeleton prototype](../evidence/adaptive_prototype_20260921/README.md) includes its Python source, tests and saved synthetic results.

## Core reading

| Report | What it supplies |
|---|---|
| [Experiment register](../evidence/EXPERIMENT_REGISTER.md) | Dated campaign sequence, original outcomes, numerical repairs, proof scopes and continuation decisions through wave 16. |
| [13 September briefing](../evidence/CURRENT_BRIEFING_20260913.md) | State before the independent review: matched SAA comparison, reserve costs, data provenance and algorithm findings. |
| [Independent assessment](../evidence/independent_review_20260916/ASSESSMENT.md) | Original 16 September recommendations, accepted pricing corrections and 19 September gate interpretation. Read alongside the later audit. |
| [Response](../evidence/independent_review_20260916/RESPONSE_AND_NEXT_STEPS.md) | Common-duty coupling, dual-counting, fixed-assets and system-wide information corrections. |
| [21 September briefing](../evidence/research_refresh_20260921/BRIEFING.md) | Consolidated audited state, prototype scope, completed capacity screen and next decision. |
| [Gate audit](../evidence/research_refresh_20260921/GATE_AUDIT.md) | Independent checks, corrected MIP count and calendar bootstrap, reconstructed-skeleton scope and model limitations. |
| [Wave-16 interpretation](../evidence/research_refresh_20260921/WAVE16_INTERPRETATION.md) | Common-profile regret decomposition and the precise retrospective mechanism test. |
| [21 September literature review](../evidence/literature_refresh_20260921/REVIEW.md) | Equation-level comparisons, versions, inspected repositories, source-access limits and unresolved overlaps. |

## Historical results

These links lead to concise result or validation reports. Their internal references identify the native configuration, source identities, journals, solver records and machine-readable validation; inclusion of raw inputs and outputs must be checked in the export itself.

| Date | Result report | Principal use |
|---|---|---|
| 11 September | [Matched methods](../evidence/snapshots/20260911_1218/RESULTS.md) | Same-pool SAA, minimax and scenario-reduction comparisons. |
| 11 September | [Forecast gate](../evidence/snapshots/20260911_1421/RESULTS.md) | Fixed-profile causal dispatch and forecast sensitivity. |
| 12 September | [Holdout](../evidence/snapshots/holdout_validation/RESULTS.md) | Frozen 2024/2025 evaluation; retain the unmatched deterministic caveat. |
| 12 September | [Fair-policy comparison](../evidence/snapshots/fair_policy_validation/RESULTS.md) | Matched deterministic/SAA and minimax tie-break controls. |
| 12 September | [Nested 64 scenarios](../evidence/snapshots/sample64_validation/RESULTS.md) | Paired sample-size sensitivity and retained solve gaps. |
| 12 September | [Algorithm panel](../evidence/snapshots/algorithm_efficiency_validation/RESULTS.md) | Correctness, speed and integer-pool quality. |
| 12 September | [Longer MIP searches](../evidence/snapshots/mip_budget_validation/RESULTS.md) | Frozen-pool limitation versus search budget. |
| 12 September | [Pool unions](../evidence/snapshots/pool_union_validation/RESULTS.md) | Improvement from existing validated columns, with bound scope. |
| 13 September | [BESS robustness](../evidence/snapshots/bess_robustness_validation/RESULTS.md) | Fixed-mean solar variation, capacity and dispatch controls. |
| 13 September | [Reserve control](../evidence/snapshots/reserve_control_validation/RESULTS.md) | Maximum-reserve cost and shortage outcomes. |
| 13 September | [Bounded reserves](../evidence/snapshots/bounded_reserve_validation/BRIEFING.md) | Cheaper reserve targets and the retained adverse case. |
| 13 September | [Public-code checks](../evidence/public_code_checks/RESULTS.md) | What was actually compiled/tested versus inspected only. |
| 17–19 September | [Gate results](../evidence/snapshots/gate_wave15_validation/RESULTS.md) | Original oracle and baseline tables; later audit corrects narrative counts and interpretation. |
| 21 September | [Capacity validation](../evidence/snapshots/capacity_gate_wave16_validation/validation/RESULTS.md) | All four source profiles and six capacities, with paired intervals and validation checks. |
| 21–22 September | [Common-profile gate](../common_profile_gate/) | Registered next diagnostic; use its actual status and validation before citing results. |

## Primary references

These references support the journal's research context. Method-specific statements follow the inspected versions in the [literature refresh](../evidence/literature_refresh_20260921/REVIEW.md), with the [12 September audit](../evidence/literature_update_20260912/CLOSEST_PAPERS.md) retained for historical context. Bibliographic DOI links are identifiers, not proof that every cited formulation or implementation was reproduced.

1. Najafi, A., Gao, K., Parishwad, O., Tsaousoglou, G., Jin, S., and Yi, W. (2025). **Integrated optimization of charging infrastructure, electric bus scheduling and energy systems.** *Transportation Research Part D: Transport and Environment*, 141, 104664. [DOI: 10.1016/j.trd.2025.104664](https://doi.org/10.1016/j.trd.2025.104664). Closest inspected overlap in integrated common decisions and scenario energy supply. Primary version of record was audited; author solver code was not verified.

2. Nath, R. B., Baldua, M., Vasudeva, V., and Rambha, T. (2025; revised 27 July 2026). **Charge Schedule Optimization and Infrastructure Planning for Solar-Integrated Electric Bus Transit Systems.** arXiv:2504.20790, version 2. [DOI: 10.48550/arXiv.2504.20790](https://doi.org/10.48550/arXiv.2504.20790); [inspected version](https://arxiv.org/abs/2504.20790v2). The revised version lists Nath first; earlier records used Baldua first. Scenario planning with shared capacities and boundary energy; public implementation inspected, not reproduced as an end-to-end comparator.

3. Abdelwahed, A., van den Berg, P. L., Brandt, T., and Ketter, W. (2025; online 2024). **A real-time decision support system to improve operations in electric bus networks.** *Decision Sciences*, 56(2), 193–212. [DOI: 10.1111/deci.12633](https://doi.org/10.1111/deci.12633). Primary full-text comparator for rolling charging, uncertain PV, forecast updates and BESS with supplied duties.

4. Yetkin, M., Augustino, B. R., Lamadrid, A. J., and Snyder, L. V. (2024). **Co-optimizing the smart grid and electric public transit bus system.** *Optimization and Engineering*, 25, 2425–2472. [DOI: 10.1007/s11081-023-09878-w](https://doi.org/10.1007/s11081-023-09878-w); [2026 preprint revision](https://arxiv.org/abs/2012.08087v4). Committed mobility with energy recourse is relevant precedent; two-stage decisions are not automatically sequentially causal.

5. Ricard, L., Desaulniers, G., Lodi, A., and Rousseau, L.-M. (2026). **Chance-constrained battery management for electric bus scheduling.** *European Journal of Operational Research*, online 1 June 2026. [DOI: 10.1016/j.ejor.2026.05.046](https://doi.org/10.1016/j.ejor.2026.05.046); [inspected 2025 preprint](https://arxiv.org/abs/2503.19853v1). Relevant stochastic traction-energy and pricing work. The verified public repository contains benchmark inputs/results rather than solver source; detailed formulation claims refer to the accessible preprint.

6. Enyam, K. B., Koepele, C., Asare, T., Wallington, K., and Lygeros, J. (2026). **Scenario-Based Stochastic MPC for Energy Hubs with EV Fleets Under Persistent Grid Outages.** arXiv:2604.18268, version 1, 20 April. [DOI: 10.48550/arXiv.2604.18268](https://doi.org/10.48550/arXiv.2604.18268). A shared-first-action controller with charging-only EVs and explicitly privileged PV information in the inspected model.

7. Whitaker, J., Redmond, D., Droge, G., and Gunther, J. (2025 journal record; 2024 preprint). **Scheduling Battery-Electric Bus Charging under Stochasticity using a Receding-Horizon Approach.** *IEEE Transactions on Intelligent Transportation Systems*. [DOI: 10.1109/TITS.2025.3601558](https://doi.org/10.1109/TITS.2025.3601558); [inspected preprint](https://arxiv.org/abs/2408.04087). Practical rolling-controller comparator. The journal DOI was verified in the review, while full journal-text equivalence and author code remained unverified.

8. Caustur, L., Hertoghe, P., Ma, T.-Y., and Vandebroek, M. (2025; revised 15 February 2026). **An Integrated Optimization Framework for Smart Charging of Electric Bus Fleets under Dynamic Electricity Prices with On-Site Solar Generation, Energy Storage, and V2G operations.** arXiv:2509.05940, version 2. [DOI: 10.48550/arXiv.2509.05940](https://doi.org/10.48550/arXiv.2509.05940). Deterministic technology comparator; the verified linked repository contains data and a loader, not the reported optimizer.

9. Zhuang, P., and Liang, H. (2021). **Stochastic Energy Management of Electric Bus Charging Stations With Renewable Energy Integration and B2G Capabilities.** *IEEE Transactions on Sustainable Energy*, 12(2), 1206–1216. [DOI: 10.1109/TSTE.2020.3039758](https://doi.org/10.1109/TSTE.2020.3039758). High-priority unresolved overlap: primary citation metadata was confirmed, but accessible full model text and author code were not verified. No classification of its information structure is made.

10. Parmentier, A., Martinelli, R., and Vidal, T. (2021; revised 5 February 2023). **Electric Vehicle Fleets: Scalable Route and Recharge Scheduling through Column Generation.** arXiv:2104.03823, version 2. [DOI: 10.48550/arXiv.2104.03823](https://doi.org/10.48550/arXiv.2104.03823). This identifies the inspected preprint and associated component work; the journal implementation was not reproduced. The project's [public-code checks](../evidence/public_code_checks/RESULTS.md) record the limited tests actually performed.

11. Kleywegt, A. J., Shapiro, A., and Homem-de-Mello, T. (2002). **The Sample Average Approximation Method for Stochastic Discrete Optimization.** *SIAM Journal on Optimization*, 12(2), 479–502. [DOI: 10.1137/S1052623499363220](https://doi.org/10.1137/S1052623499363220). General method background; it does not validate this campaign's finite-sample comparisons.

## Append convention

Append each new journal entry with its actual decision date and question, action, result, limits, next decision and evidence. Record protocol registration, execution completion and scientific validation as distinct events. Preserve source attempts and link the actual protocol, logs, solver output and validation report when published. If an interpretation changes, append the correction and identify the earlier claim; do not quietly replace the research history.
