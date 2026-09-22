# Common truck-profile experiment — wave 17

Registered 21 September 2026 (America/New_York; cluster timestamps use UTC).

## Question and fixed scope

How much of wave 16's apparent benefit from weather-dependent truck charging is removable by improving a single weather-independent charging plan after adding stationary storage?

Retain each policy's frozen profile-compatible truck skeletons, 15-truck fleet, trip coverage, traction, 20 stationary units, generator cap 0.8, PV scale 2, zero losses/degradation and unlimited shared charging capacity. Truck states start/end full; BESS starts/ends empty. Units are those of the submitted model (one energy unit = 100 kWh). The skeletons were reconstructed from saved profiles; they are not claimed to be original saved routes. No fleet, BESS purchase or task-assignment decisions are optimized here.

## Information and formulation

One set of continuous truck charge/discharge/state decisions is shared by all weather scenarios. Each scenario has its own BESS, generator and emergency-energy decisions with full-day information. Common truck variables enforce their nonanticipativity directly; scenario recourse remains a perfect-information relaxation. Integer route multiplicities and BESS count are fixed inputs, not optimization variables.

First minimize weighted emergency energy; then minimize expected fuel and throughput cost subject to the optimum emergency level. Use the inherited truck plan as a pinned feasible witness. Compare the optimized common profile to the existing daywise adaptive oracle only on the identical 2022 support and physical domain. Require all-day zero shortage before interpreting cost differences as ordinary savings.

For the same finite population, F_old − A = (F_old − F_common) + (F_common − A). The first term is static retuning regret; the second is residual perfect-information adaptation value. A common profile close to A falsifies attributing the full old gap to weather adaptation.

## Four cases, declared before solving

| Case | Source | Fit data | Evaluation | Purpose |
|---|---|---|---|---|
| policy17_nb20_fit2022 | SAA seed 47 | all 365 days, 2022 | same 2022 days | Diagnose the 75.56/day outlier; retrospective development test |
| policy14_nb20_fit2022 | SAA seed 29 | all 365 days, 2022 | same 2022 days | Low-gap control |
| policy17_nb20_fit2023 | SAA seed 47 | all 365 days, 2023 | 2022, independently replayed | Training-only fit with respect to 2022 |
| policy14_nb20_fit2023 | SAA seed 29 | all 365 days, 2023 | 2022, independently replayed | Training-only control |

2022 has already informed research choices, so it is development evaluation, not a fresh untouched test. Cross-year replay is independent of fitting but is not chronological deployment validation. The in-sample nesting guarantee does not transfer to 2023-fit performance on 2022. No scenario sampling or clustering is introduced; these are full-year finite populations.

## Computation and acceptance

Gurobi continuous LP, one thread, barrier method, 600-second ceiling per phase, four phases per case (pinned shortage/cost and common shortage/cost). Maximum two cluster cases concurrently, one CPU and 4 GiB each, one-hour job wall limit. Scaglione with no requeue and exclusion of scaglione-compute-01. This is a small stable LP batch; there is no branch-and-bound search or CG certificate to claim. No dependencies on EVSP–DR jobs.

Preserve exact input/code hashes, execution commit, Slurm IDs, all four native Gurobi logs, statuses, bounds/dual evidence, full primal arrays, residuals and version metadata. Each output directory belongs to one attempt. An interrupted attempt is recorded and a fresh directory is required for a retry; never overwrite an earlier solver log or call a restart a continuation.

Validate exported solutions independently without importing the solver's matrices. Independently replay each frozen profile on 2022 using SciPy/HiGHS. Check every energy/state constraint, shared truck representation, task coverage, source identity, pinned-profile cost against wave 16 and same-population nesting. Report failed days, cost distributions and calendar-block bootstrap intervals (descriptive dependence sensitivity, not independent-day confidence guarantees). Record infeasible-day costs separately from feasible-day comparisons. Stop to resolve validation failure before interpreting an advantage.

## Decision after results

If static retuning explains most of the old gap, carry the better common profile forward as the baseline for matched-information causal control. If a residual remains, quantify it as a full-information opportunity on these fixed assets. Either outcome still requires matched forecast/observation histories to measure achievable causal value. Additional-duty uncertainty remains a separate extension.

## References and provenance

- [Wave 16 interpretation and exact comparator](../evidence/research_refresh_20260921/WAVE16_INTERPRETATION.md).
- [Literature refresh](../evidence/literature_refresh_20260921/REVIEW.md): Najafi et al., Yetkin et al., Nath/Baldua et al. and Abdelwahed et al. are relevant precedents for common decisions, recourse and causal charging. This experiment is a diagnostic comparator, not a novelty claim.
- `inputs/*.json`: frozen weather, skeletons, physical settings and source hashes; original submitted Git reference identified in each input.
