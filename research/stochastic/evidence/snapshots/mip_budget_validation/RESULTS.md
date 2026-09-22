# Longer-budget frozen-pool MIP diagnostic — validated

All21 native solutions, source/input identities, physical columns, final vectors, objective/bound checks and rounded fixed-policy LPs pass. The result distinguishes a demonstrated route-pool limitation from remaining search uncertainty.

| Workload and pool | Prior120s cost | Final cost, seeds11 /29 /47 | Final gaps, seeds11 /29 /47 | Native seconds, seeds11 /29 /47 |
|---|---:|---|---|---|
| 20 trips, v2g_fleet, legacy_highs | 6129.375 | 6074.925 / 6056.451 / 6056.451 | 1.620% / 1.343% / 1.294% | 3600.0 / 3600.0 / 3600.0 |
| 20 trips, v2g_fleet, sparse_gurobi | 6064.704 | 6064.704 / 6064.704 / 6064.704 | 1.231% / 1.243% / 1.314% | 3600.0 / 3600.0 / 3600.0 |
| 20 trips, v2g_fleet, persistent_gurobi | 6132.205 | 6075.769 / 6086.881 / 6073.757 | 1.531% / 1.761% / 1.485% | 3600.0 / 3600.0 / 3600.0 |
| 20 trips, v2g_fleet, persistent_cached_warm | 6132.242 | 6132.054 / 6132.054 / 6132.054 | 0.000% / 0.000% / 0.000% | 334.5 / 366.1 / 374.4 |
| 120 trips, v2g, legacy_highs | 15598.644 | 15598.644 / 15598.644 / 15598.644 | 0.000% / 0.000% / 0.000% | 154.2 / 179.6 / 173.6 |
| 120 trips, v2g, sparse_gurobi | 15517.665 | 15517.665 / 15517.665 / 15517.665 | 0.000% / 0.000% / 0.000% | 64.3 / 64.6 / 62.1 |
| 120 trips, v2g, persistent_gurobi | 15573.631 | 15559.975 / 15559.975 / 15559.975 | 0.000% / 0.000% / 0.000% | 141.0 / 138.1 / 141.6 |

**What changed our interpretation:** the20-trip/noBESS warm pool has optimum6132.054 within tolerance in allthree solver seeds, while a different pool has a feasible6056.451 solution. Therefore that warm pool cannot attain the better known solution: additional integer search inside it cannot solve the deficiency. The other three noBESS pools remain time-limited; their exact optima and ranking remain unresolved.

For120-trip/V2G+BESS all three pools solve to tolerance: legacy15598.644, coldGurobi15517.665, persistent15559.975. Their integer-cost differences persist despite equal rootLP objectives; this is a route-pool effect, not solely a short-MIP-budget effect. It is not proof that the best pool attains the full-route integer optimum.

**Next bounded test:** combine the already validated columns within each physical workload and solve that union with a mapped best known feasible incumbent, preserving all trip/physics/scenario data. This tests cheap pool enrichment without new pricing or a branch-and-price tree. Larger unions may take longer to search; compare allthree solver seeds and report source preparation and the previous computation separately.

**Budget and uncertainty:** each case is a new search from its own prior120-second incumbent, with up to3600 additional native seconds, one thread and seeds11/29/47. These are solver seeds, not new weather samples. It is neither a resumed search tree nor a from-scratch speed comparison. Costs are training-model monetary units; no new weather-policy evaluation was run. Twelve searches proved their finite-pool optimum within tolerance; nine reached the time limit. No statistical population intervals are inferred from three solver seeds.

Scoped allocation including both smoke attempts: 9.649CPU-hours. Main native solver time: 34594.21s. Maximum recorded batch memory: 1.004GiB. All21 scheduler tasks completed0:0; first smoke40307 failed in shell before Python, corrected40957 passed. ReservedGPUhost excluded, Scaglione no-requeue, no interrupted main attempts.

**Milestones:** [milestones.csv](milestones.csv) retains all84 requested milestone observations, actual callback/final times, incumbent and bound. We use the first saved callback at or after a requested time, or the final result if no later callback exists; early optimal solves finish before later milestones. These are not exact-time checkpoint claims. Full chronological telemetry remains in each case and [validated_results.json](validated_results.json). [All21 final rows](all_results.csv) and accounting (original research artifact `snapshots/mip_budget_validation/accounting.psv`; not included in this export) are retained.

All original route pools, wave9 code, weather training/holdout data and EVSP–DR were preserved. The independent verification does not upgrade finite-pool bounds to full-route integer proofs.
