# Existing-route pool union — validated results

**Combining existing route pools materially improves the120-trip case. It gives little benefit in the small no-stationary-battery case under the tested budget.** This supports selective pool enrichment while retaining the current CG-plus-MIP framework. It does not establish a need for a full branch-and-price tree.

| Workload | Union columns | Solver seed | Best prior cost | Union cost | Cost reduction | Union MIP gap | Gap to inherited full-route LP bound |
|---|---:|---:|---:|---:|---:|---:|---:|
| 20 trips, V2G/noBESS | 1108 | 11 | 6056.451 | 6056.451 | 0.0000% | 2.5486% | 2.8500% |
| 20 trips, V2G/noBESS | 1108 | 29 | 6056.451 | 6056.451 | 0.0000% | 2.5294% | 2.8500% |
| 20 trips, V2G/noBESS | 1108 | 47 | 6056.451 | 6053.371 | 0.0509% | 2.4711% | 2.8005% |
| 120 trips, V2G+BESS | 771 | 11 | 15517.665 | 15168.683 | 2.2489% | 0.2290% | 0.2718% |
| 120 trips, V2G+BESS | 771 | 29 | 15517.665 | 15169.116 | 2.2461% | 0.2318% | 0.2746% |
| 120 trips, V2G+BESS | 771 | 47 | 15517.665 | 15169.055 | 2.2465% | 0.2315% | 0.2742% |

All six searches used one additional native hour from the same mapped best-known feasible incumbent within each workload. They all reached the time limit with validated solutions. Solver seeds are11/29/47; training weather remains fixed. Costs are model monetary units, not newly evaluated annual operating savings.

**What the large case shows.** Earlier individual pool optima were15598.644,15517.665 and15559.975. The union gives15168.683–15169.116: about2.25% below the best individual-pool optimum, consistently across the three solver seeds. Useful integer routes from different pools complement one another. The inherited full-route LP bound is15127.457467809361, leaving a0.272–0.275% relative incumbent-to-bound gap in the admitted discretized common-profile model. That is a useful global model bound; the separate0.229–0.232% native gap concerns this finite union pool. Neither is proof of exact integer optimality or a guarantee under future weather.

**What the small case shows.** Two seeds retain6056.451, while one improves to6053.371—a0.0509% improvement. The union MIP gaps remain2.471–2.549%, larger than the earlier source-pool gaps; the larger search space is harder. This does not prove that the union optimum is poor. The small warm pool had a demonstrated limitation, but indiscriminately enlarging every pool is not a demonstrated runtime/quality improvement.

**Decision.** Retain the verified pricing/feasibility safeguards and sparse assembly. Keep persistence and bounded warm import optional. Use union or targeted enrichment when the observed integer pool deficit matters, and keep the best feasible incumbent throughout. Stop repeating broad budget/seed sweeps on these two cells. The next scientific question is adaptive bus charging with an explicit observation history and unchanged trip service; formulate a tiny controlled test before a larger campaign. No new experiment was submitted during this validation.

**Validation and accounting.** All source memberships, full signed-energy/cost keys, exact source-matrix embeddings, native vectors, objective/bound checks and rounded fixed-policy LPs pass. Starting vectors are mapped prior incumbents, not fabricated new native solves; union baseline bounds/gaps remain null until its own optimization. The inherited full-route LP bound is preserved with its original pricing/model scope. Original route pools, worker code, training/holdout weather and EVSP–DR are unchanged.

Local preparation, including source hashing/model checks and mapped-policy checks, took 7.551s. Main native searches total 21600.10s. Scoped union-stage allocation including both smoke tasks: 6.021CPU-hours; maximum recorded batch memory 1.779GiB. Previous wave9 and wave10 allocations were2.119 and9.649CPU-hours respectively, excluding earlier source-pool creation and local analysis. This is an additional-computation experiment, not an end-to-end speedup from scratch.

[All six final rows](all_results.csv) · [All24 requested milestone observations](milestones.csv) · [Validated records and full progress](validated_results.json) · Accounting (original research artifact `snapshots/pool_union_validation/accounting.psv`; not included in this export). Milestones use the first saved callback at or after the requested time, or the terminal record, and retain actual times; they are not exact-time checkpoint claims. Native searches are not resumable from these records.
